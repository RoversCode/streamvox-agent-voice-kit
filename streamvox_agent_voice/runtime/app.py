"""FastAPI Runtime 应用。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile

from ..cli.runtime_probe import DEFAULT_REALTIME_SELFTEST_TEXT, build_streaming_selftest_report
from ..events import VoiceEvent, VoiceEventError
from .audio_player import AudioSink, build_audio_sink
from .audio_assets import temporary_upload_file
from .config import RuntimeConfig
from .engine import StreamVoxSpeaker
from .model_registry import build_capability_snapshot
from .queue import VoiceEventQueue
from .role_payloads import (
    parse_default_role_payload,
    parse_role_delete_payload,
    parse_role_registration_payload,
    parse_role_upload_form,
)


def create_app(
    config: RuntimeConfig,
    *,
    speaker: StreamVoxSpeaker | None = None,
    audio_sink: AudioSink | None = None,
) -> FastAPI:
    """
    创建 StreamVox Runtime FastAPI 应用。

    核心入参:
        config: Runtime 启动配置。
        speaker: 测试可注入的 StreamVoxSpeaker。
        audio_sink: 测试可注入的播放后端。

    预期输出:
        返回已绑定健康检查、状态、事件、停止和关闭接口的 FastAPI 应用。

    边界异常:
        真实启动时模型初始化失败会在 startup 阶段抛出，uvicorn 会终止服务。
    """

    sink = audio_sink or build_audio_sink(config.audio_backend, config.output_dir)
    runtime_speaker = speaker or StreamVoxSpeaker(config=config, audio_sink=sink)
    queue = VoiceEventQueue(runtime_speaker)

    def _current_capabilities() -> dict[str, Any]:
        """
        构造当前 Runtime 会话的最新能力快照。

        核心入参:
            无。

        预期输出:
            返回反映当前默认角色等会话态变化的能力字典。

        边界异常:
            不抛异常；未知模型时仍返回降级快照。
        """

        return build_capability_snapshot(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        FastAPI 生命周期管理器。

        核心入参:
            app: 当前 FastAPI 应用。

        预期输出:
            启动时预热模型并启动队列，关闭时停止队列并释放模型。

        边界异常:
            模型加载失败会阻止 Runtime 启动；shutdown 异常会进入 uvicorn 日志。
        """
        # 当前已经存在的 asyncio 事件循环里，把一个普通同步函数 runtime_speaker.initialize，扔到线程池里的某个工作线程执行
        await asyncio.to_thread(runtime_speaker.initialize)
        await asyncio.to_thread(
            runtime_speaker.ensure_demo_role,
            set_as_default=config.default_role_name is None,
        )
        await queue.start()
        try:
            yield
        finally:
            await queue.shutdown()
            await asyncio.to_thread(runtime_speaker.shutdown)

    # lifespan -> TTSEngine初始化
    app = FastAPI(title="StreamVox Agent Voice Runtime", version="0.1.0", lifespan=lifespan)

    # 把运行时对象挂到 app.state，避免全局变量导致测试之间互相污染。
    app.state.config = config
    app.state.speaker = runtime_speaker
    app.state.voice_queue = queue

    @app.get("/health")
    async def health() -> dict[str, str]:
        """
        健康检查接口。

        核心入参:
            无。

        预期输出:
            返回 ok，供脚本判断 HTTP 服务是否可达。

        边界异常:
            不抛业务异常。
        """

        return {"status": "ok"}

    @app.get("/status")
    async def status() -> dict[str, Any]:
        """
        Runtime 状态接口。

        核心入参:
            无。

        预期输出:
            返回模型、设备、采样率、初始化状态和队列状态。

        边界异常:
            不抛业务异常。
        """

        return {
            "status": "running",
            "model": config.model,
            "device": config.device,
            "sample_rate": runtime_speaker.sample_rate,
            "initialized": runtime_speaker.initialized,
            "default_role_name": config.default_role_name,
            "output": config.audio_backend,
            "output_dir": str(config.output_dir),
            "capabilities": _current_capabilities(),
            "queue": queue.status(),
        }

    @app.get("/capabilities")
    async def capabilities() -> dict[str, Any]:
        """
        返回当前 Runtime 会话的模型能力快照。

        核心入参:
            无。

        预期输出:
            返回当前模型已解析出的能力摘要，以及会话级默认角色等状态。

        边界异常:
            不抛业务异常；未知模型时返回降级快照。
        """

        return _current_capabilities()

    @app.get("/roles")
    async def roles() -> dict[str, Any]:
        """
        列出当前模型缓存中的全部角色。

        核心入参:
            无。

        预期输出:
            返回当前模型、默认角色和角色列表。

        边界异常:
            引擎未初始化时返回 503。
        """

        try:
            roles = await asyncio.to_thread(runtime_speaker.list_roles)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {
            "model": config.model,
            "default_role_name": config.default_role_name,
            "roles": roles,
        }

    @app.post("/selftest/realtime")
    async def realtime_selftest(payload: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
        """
        执行只关注流式连续性的实时语音自检。

        核心入参:
            payload: 可选 `text` 与 `role_name`；未传 `text` 时使用内置长文本，未传 `role_name` 时按默认角色、demo_role 顺序回退。

        预期输出:
            返回 chunk 时序、首个断裂点和是否适合实时语音播报的结论。

        边界异常:
            载荷非法返回 400，引擎不可用或探针失败返回 503。
        """

        if payload is None:
            payload = {}

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="selftest payload must be a JSON object")

        raw_text = payload.get("text", DEFAULT_REALTIME_SELFTEST_TEXT)
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise HTTPException(status_code=400, detail="text must be a non-empty string")

        raw_role_name = payload.get("role_name")
        if raw_role_name is not None and not isinstance(raw_role_name, str):
            raise HTTPException(status_code=400, detail="role_name must be a string when provided")

        try:
            measurement = await asyncio.to_thread(
                runtime_speaker.probe_realtime_stream,
                text=raw_text.strip(),
                role_name=raw_role_name.strip() if isinstance(raw_role_name, str) and raw_role_name.strip() else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return build_streaming_selftest_report(measurement)

    @app.post("/roles")
    async def register_role(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """
        注册一个可复用的 Prompt 角色资产。

        核心入参:
            payload: 角色名、参考音频路径、参考文本和模型私有 make_prompt 参数。

        预期输出:
            成功时返回 created、角色名和当前默认角色。

        边界异常:
            载荷非法返回 400，引擎不可用返回 503。
        """

        try:
            request = parse_role_registration_payload(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            role_name = await asyncio.to_thread(
                runtime_speaker.register_role,
                role_name=request["role_name"],
                audio_path=request["audio_path"],
                audio_data=request["audio_data"],
                sample_rate=request["sample_rate"],
                prompt_text=request["prompt_text"],
                persist=request["persist"],
                make_prompt_kwargs=request["streamvox"],
            )
            if request["set_default"]:
                await asyncio.to_thread(runtime_speaker.set_default_role_name, role_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {
            "status": "created",
            "role_name": role_name,
            "default_role_name": config.default_role_name,
            "model": config.model,
        }

    @app.post("/roles/upload")
    async def register_role_upload(
        role_name: str = Form(...),
        audio_file: UploadFile = File(...),
        prompt_text: str | None = Form(None),
        persist: str = Form("true"),
        set_default: str = Form("false"),
        streamvox_json: str | None = Form(None),
    ) -> dict[str, Any]:
        """
        通过 multipart 上传文件注册一个可复用角色资产。

        核心入参:
            role_name/audio_file/prompt_text/persist/set_default/streamvox_json: 表单形式的角色注册参数。

        预期输出:
            成功时返回 created、角色名和当前默认角色。

        边界异常:
            表单非法返回 400，引擎不可用返回 503。
        """

        try:
            request = parse_role_upload_form(
                role_name=role_name,
                prompt_text=prompt_text,
                persist=persist,
                set_default=set_default,
                streamvox_json=streamvox_json,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            async with temporary_upload_file(audio_file) as temporary_audio_path:
                created_role_name = await asyncio.to_thread(
                    runtime_speaker.register_role,
                    role_name=request["role_name"],
                    audio_path=temporary_audio_path,
                    audio_data=None,
                    sample_rate=None,
                    prompt_text=request["prompt_text"],
                    persist=request["persist"],
                    make_prompt_kwargs=request["streamvox"],
                )
            if request["set_default"]:
                await asyncio.to_thread(runtime_speaker.set_default_role_name, created_role_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {
            "status": "created",
            "role_name": created_role_name,
            "default_role_name": config.default_role_name,
            "model": config.model,
        }

    @app.post("/roles/delete")
    async def delete_roles(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """
        删除一个或多个当前模型缓存中的角色。

        核心入参:
            payload: 角色名或角色名列表。

        预期输出:
            返回实际删除成功的角色列表，以及删除后的默认角色状态。

        边界异常:
            载荷非法返回 400，引擎不可用返回 503。
        """

        try:
            role_names = parse_role_delete_payload(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            deleted_roles = await asyncio.to_thread(runtime_speaker.delete_roles, role_names)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {
            "status": "deleted",
            "deleted_roles": deleted_roles,
            "default_role_name": config.default_role_name,
            "model": config.model,
        }

    @app.post("/session/default-role")
    async def set_default_role(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """
        更新 Runtime 会话级默认角色。

        核心入参:
            payload: `role_name` 或 null。

        预期输出:
            返回 updated 和当前默认角色。

        边界异常:
            载荷非法或角色不存在返回 400，引擎不可用返回 503。
        """

        try:
            role_name = parse_default_role_payload(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            current_role_name = await asyncio.to_thread(runtime_speaker.set_default_role_name, role_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {
            "status": "updated",
            "default_role_name": current_role_name,
            "model": config.model,
        }

    @app.post("/events")
    async def events(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """
        接收 Agent 语音事件。

        核心入参:
            payload: 公开事件协议 JSON。

        预期输出:
            wait=False 时返回 accepted；wait=True 时返回 completed/failed/stopped 等最终结果。

        边界异常:
            协议非法返回 400，队列关闭返回 503。
        """

        try:
            event = VoiceEvent.from_mapping(payload)
        except VoiceEventError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            # 验证参数是否合法
            await asyncio.to_thread(runtime_speaker.validate_event_request, event)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        try:
            # 入轨
            item = await queue.enqueue(event)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        if not event.wait:
            return {"status": "accepted", "event_id": event.id}

        result = await item.future
        return result.to_payload()

    @app.post("/stop")
    async def stop() -> dict[str, Any]:
        """
        停止当前播报。

        核心入参:
            无。

        预期输出:
            返回 stopped，Runtime 进程保持运行。

        边界异常:
            不抛业务异常。
        """

        result = await queue.stop_current()
        return result.to_payload()

    @app.post("/shutdown")
    async def shutdown_runtime(request: Request) -> dict[str, str]:
        """
        请求 Runtime 进程退出。

        核心入参:
            request: FastAPI 请求对象，用于访问 uvicorn server 状态。

        预期输出:
            返回 shutting_down，随后 uvicorn 退出。

        边界异常:
            如果不是 uvicorn 环境，接口仍返回成功但只完成队列关闭。
        """

        await queue.shutdown()
        await asyncio.to_thread(runtime_speaker.shutdown)

        # CLI 启动时会把 uvicorn.Server 注入 app.state；测试环境没有时保持幂等返回。
        server = getattr(request.app.state, "server", None)
        if server is not None and hasattr(server, "should_exit"):
            server.should_exit = True
        return {"status": "shutting_down"}

    return app
