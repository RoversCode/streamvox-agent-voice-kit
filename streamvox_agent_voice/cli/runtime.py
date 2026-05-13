"""streamvox-runtime 命令行入口。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import httpx
import typer
import uvicorn

from ..client import VoiceClient
from ..runtime import (
    RuntimeConfig,
    create_app,
    detect_system_hardware,
    recommend_model_profiles,
)
from .json_options import parse_json_object_option
from .runtime_probe import (
    DEFAULT_REALTIME_SELFTEST_TEXT,
    build_benchmark_summary,
    build_streaming_selftest_summary,
    run_runtime_benchmark,
    run_runtime_realtime_selftest,
)
from .runtime_supervisor import RuntimeShutdownGuard, is_runtime_child_process, run_supervised_start


app = typer.Typer(help="Manage the local StreamVox Agent Voice Runtime.")
models_app = typer.Typer(help="List supported StreamVox model profiles.")
roles_app = typer.Typer(help="Manage cached prompt roles in the local Runtime.")
app.add_typer(models_app, name="models")
app.add_typer(roles_app, name="roles")


def _base_url(host: str, port: int) -> str:
    """
    根据 host/port 构造 Runtime 地址。

    核心入参:
        host: Runtime HTTP host。
        port: Runtime HTTP port。

    预期输出:
        返回 http://host:port。

    边界异常:
        不校验 host 是否可连接。
    """

    return f"http://{host}:{port}"


def _print_json(payload: dict[str, object]) -> None:
    """
    以稳定 JSON 形式输出 CLI 结果。

    核心入参:
        payload: 需要输出的字典。

    预期输出:
        stdout 输出 UTF-8 JSON。

    边界异常:
        不可 JSON 序列化时由 json.dumps 抛出异常。
    """

    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_json_object(raw: str | None, *, option_name: str) -> dict[str, Any]:
    """
    解析 CLI 传入的 JSON 对象字符串。

    核心入参:
        raw: JSON 字符串，可为空。
        option_name: 当前选项名，用于错误提示。

    预期输出:
        成功时返回字典；为空时返回空字典。

    边界异常:
        JSON 非法或不是对象时抛出 typer.BadParameter。
    """

    if raw is None:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"{option_name} must be valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise typer.BadParameter(f"{option_name} must decode to a JSON object")
    return payload


def _parse_audio_data_source(audio_data_json: str | None, audio_data_file: str | None) -> list[float] | None:
    """
    解析 CLI 里的内存音频输入。

    核心入参:
        audio_data_json: 直接传入的 JSON 数组字符串。
        audio_data_file: 存放 JSON 数组的本地文件路径。

    预期输出:
        成功时返回一维浮点采样数组；未提供时返回 None。

    边界异常:
        同时提供两个来源、文件读取失败、JSON 非法或数组元素非数值时抛出 typer.BadParameter。
    """

    if audio_data_json is None and audio_data_file is None:
        return None
    if audio_data_json is not None and audio_data_file is not None:
        raise typer.BadParameter("use either --audio-data-json or --audio-data-file, not both")

    if audio_data_file is not None:
        try:
            raw = Path(audio_data_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise typer.BadParameter(f"--audio-data-file cannot be read: {exc}") from exc
        option_name = "--audio-data-file"
    else:
        raw = audio_data_json
        option_name = "--audio-data-json"

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"{option_name} must contain valid JSON: {exc}") from exc

    if not isinstance(payload, list) or not payload:
        raise typer.BadParameter(f"{option_name} must decode to a non-empty JSON array")

    normalized_audio_data: list[float] = []
    for sample in payload:
        if isinstance(sample, bool) or not isinstance(sample, (int, float)):
            raise typer.BadParameter(f"{option_name} must contain only numbers")
        normalized_audio_data.append(float(sample))
    return normalized_audio_data


def _run_client_request(coroutine: object) -> dict[str, object]:
    """
    执行一次 Runtime HTTP 请求，并把服务端错误转换成可读 CLI 输出。

    核心入参:
        coroutine: `VoiceClient` 返回的协程对象。
    预期输出:
        成功时返回 Runtime 的 JSON 响应。
    边界异常:
        Runtime 返回非 2xx 时，输出服务端 `detail` 并以非零状态退出。
    """

    try:
        return asyncio.run(coroutine)  # type: ignore[arg-type]
    except httpx.HTTPStatusError as exc:
        # 这里优先把服务端 detail 打出来，方便人类和 Agent 都能基于明确原因做恢复。
        typer.echo(_format_http_status_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    except httpx.HTTPError as exc:
        typer.echo(_format_transport_error(exc), err=True)
        raise typer.Exit(code=1) from exc


def _format_http_status_error(exc: httpx.HTTPStatusError) -> str:
    """
    把 HTTPStatusError 格式化为更适合 CLI 的错误文本。

    核心入参:
        exc: `httpx` 抛出的 HTTP 状态异常。
    预期输出:
        返回包含状态码与服务端 detail 的短文本。
    边界异常:
        响应体不是 JSON 时回退到纯文本或原始异常消息。
    """

    detail = ""
    try:
        payload = exc.response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        raw_detail = payload.get("detail")
        if isinstance(raw_detail, str):
            detail = raw_detail.strip()

    if not detail:
        detail = exc.response.text.strip() or str(exc)
    return f"Runtime request failed ({exc.response.status_code}): {detail}"


def _format_transport_error(exc: httpx.HTTPError) -> str:
    """
    鎶?HTTP 杩炴帴绫婚敊璇敹鏁涗负鍙鐨?CLI 鎻愮ず銆?
    鏍稿績鍏ュ弬:
        exc: `httpx` 鎶涘嚭鐨勭綉缁溿€佽秴鏃舵垨杩炴帴绫诲紓甯搞€?
    棰勬湡杈撳嚭:
        杩斿洖涓€鏉＄煭閿欒锛屾彁绀?Runtime 鍦板潃銆佽姹傜被鍨嬫垨鍙兘鐨勮繛鎺ラ棶棰樸€?
    杈圭晫寮傚父:
        涓嶄緷璧栧紓甯镐竴瀹氬甫鏈?request/url锛岀己澶辨椂鍥為€€鍒板師濮嬫秷鎭€?
    """

    request = getattr(exc, "request", None)
    url = getattr(request, "url", None)
    if url is not None:
        return f"Runtime request failed: {exc.__class__.__name__} while contacting {url}"
    return f"Runtime request failed: {exc}"


def _model_recommendation_message(status: str) -> str:
    """
    把模型推荐状态映射成面向人类的极简运行结论。

    核心入参:
        status: `recommend_model_profiles()` 返回的推荐状态。

    预期输出:
        返回带有 `✅/❌` 的中文结论文案。

    边界异常:
        未知状态统一降级为保守提示，避免误报为可流畅运行。
    """

    messages = {
        "recommended": "✅当前硬件满足推荐配置，可流畅运行该模型",
        "supported": "❌当前硬件达到最低要求但未达推荐配置，谨慎选择",
        "cpu_fallback": "❌当前硬件缺少合适 GPU，仅建议谨慎尝试",
        "unknown": "❌当前硬件信息不足，无法确认是否可流畅运行，谨慎选择",
        "insufficient": "❌硬件不满足推荐配置，谨慎选择",
    }
    return messages.get(status, "❌当前硬件信息不足，无法确认是否可流畅运行，谨慎选择")


def _format_model_recommendation_line(model_name: str, status: str) -> str:
    """
    生成 `models list` 的单行输出。

    核心入参:
        model_name: 模型名。
        status: 当前机器上的推荐状态。

    预期输出:
        返回 `模型名 [结论]` 形式的纯文本。

    边界异常:
        不抛异常。
    """

    return f"{model_name} [{_model_recommendation_message(status)}]"


@app.command()
def start(
    model: str = typer.Option(
        RuntimeConfig.model,
        "--model",
        help="StreamVox model name or local bundle path.",
    ),
    device: str = typer.Option("auto", "--device", help="StreamVox device: auto/cpu/gpu/gpu:<index>."),
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    license_key: Optional[str] = typer.Option(None, "--license-key", help="StreamVox online license key."),
    license_path: Optional[str] = typer.Option(None, "--license-path", help="StreamVox offline license path."),
    verify_model_sha256: bool = typer.Option(False, "--verify-model-sha256", help="Verify model bundle sha256."),
    default_role_name: Optional[str] = typer.Option(
        None,
        "--default-role-name",
        help="Default role name inherited by events that do not explicitly override role_name.",
    ),
    streamvox_json: Optional[str] = typer.Option(
        None,
        "--streamvox-json",
        help="JSON object used as fixed TTSEngine.stream kwargs for the current Runtime session.",
    ),
    streamvox_json_file: Optional[str] = typer.Option(
        None,
        "--streamvox-json-file",
        help="Path to a JSON object file used as fixed TTSEngine.stream kwargs for the current Runtime session.",
    ),
    audio_backend: str = typer.Option(
        "speaker",
        "--output",
        "--audio-backend",
        help="Streaming output sink: speaker/null/wav. sounddevice is kept as a compatibility alias.",
    ),
    output_dir: str = typer.Option(
        "streamvox_outputs",
        "--output-dir",
        help="Directory used by file output sinks such as wav.",
    ),
) -> None:
    """
    启动常驻 StreamVox Runtime。

    核心入参:
        model/device/host/port/license/default_role_name/streamvox_json/audio_backend/output_dir: Runtime 启动参数。

    预期输出:
        当前进程启动 uvicorn 服务并保持运行，直到收到 stop/shutdown。

    边界异常:
        模型加载、端口占用、音频后端不可用会导致命令非零退出。
    """

    # 默认由父进程做 supervisor，真正的 Runtime 子进程通过内部环境变量进入本分支下方。
    if not is_runtime_child_process():
        exit_code = run_supervised_start(
            model=model,
            device=device,
            host=host,
            port=port,
            license_key=license_key,
            license_path=license_path,
            verify_model_sha256=verify_model_sha256,
            default_role_name=default_role_name,
            streamvox_json=streamvox_json,
            streamvox_json_file=streamvox_json_file,
            audio_backend=audio_backend,
            output_dir=output_dir,
        )
        if exit_code < 0:
            exit_code = 128 + abs(exit_code)
        raise typer.Exit(code=exit_code)

    explicit_stream_kwargs = parse_json_object_option(
        raw_value=streamvox_json,
        raw_option_name="--streamvox-json",
        file_path=streamvox_json_file,
        file_option_name="--streamvox-json-file",
    )
    stream_kwargs = explicit_stream_kwargs or RuntimeConfig.builtin_stream_kwargs_for_model(model)

    config = RuntimeConfig(
        model=model,
        device=device,
        host=host,
        port=port,
        license_key=license_key,
        license_path=license_path,
        verify_model_sha256=verify_model_sha256,
        default_role_name=default_role_name,
        stream_kwargs=stream_kwargs or None,
        audio_backend=audio_backend,
        output_dir=Path(output_dir),
    )
    runtime_app = create_app(config)
    uvicorn_config = uvicorn.Config(runtime_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(uvicorn_config)

    # 把 server 注入 app.state，/shutdown 接口可以优雅设置 should_exit，而不是强杀进程。
    runtime_app.state.server = server
    shutdown_guard = RuntimeShutdownGuard(runtime_app, server)
    shutdown_guard.install()

    try:
        asyncio.run(server.serve()) # 创建了一个事件循环，开始跑
    except KeyboardInterrupt as exc:
        shutdown_guard.shutdown_for_exception()
        raise typer.Exit(code=130) from exc
    except Exception:
        shutdown_guard.shutdown_for_exception()
        raise
    finally:
        shutdown_guard.restore()


@app.command()
def selftest(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(60.0, "--timeout", help="HTTP request timeout seconds."),
    role_name: Optional[str] = typer.Option(
        None,
        "--role-name",
        help="Optional persisted role name used by the realtime selftest.",
    ),
    text: str = typer.Option(
        DEFAULT_REALTIME_SELFTEST_TEXT,
        "--text",
        help="Long text used to inspect chunk continuity during realtime selftest.",
    ),
) -> None:
    # [旧注释已废弃]: 原 docstring 因编码异常出现乱码，已按当前实现语义重写。
    """
    执行只关注流式连续性的 Runtime 自检。

    核心入参:
        host/port/timeout: Runtime 服务地址与 HTTP 请求超时。
        role_name: 可选的持久化角色名；为空时由 Runtime 自己按默认角色、demo_role 顺序回退。
        text: 用于触发多个 chunk 的长文本，便于检测流式生成是否会中途断裂。

    预期输出:
        stdout 输出一份 JSON 自检报告，包含 chunk 时序、首个断裂点和是否适合实时语音播报的结论。

    边界异常:
        Runtime 不可达、角色不可用、底层 stream 失败或探针执行异常时，CLI 会以非零状态退出并打印可读错误。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    selftest_report = _run_client_request(
        run_runtime_realtime_selftest(
            client,
            text=text,
            role_name=role_name,
        )
    )
    _print_json(build_streaming_selftest_summary(selftest_report))


@app.command()
def benchmark(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(120.0, "--timeout", help="HTTP request timeout seconds."),
    role_name: Optional[str] = typer.Option(
        None,
        "--role-name",
        help="Optional persisted role name used by the benchmark speech requests.",
    ),
    text: str = typer.Option(
        "您好，我正在整理答案，请稍等片刻。",
        "--text",
        help="Benchmark text used to measure end-to-end completion latency.",
    ),
    iterations: int = typer.Option(
        1,
        "--iterations",
        min=1,
        max=10,
        help="How many completed speech runs to measure. Larger values are slower and more audible.",
    ),
    json_summary_only: bool = typer.Option(
        False,
        "--json-summary-only",
        help="Only print the compact machine-friendly benchmark summary JSON.",
    ),
) -> None:
    """
    执行面向 Agent 播报场景的轻量基准测试，用于评估当前 Runtime 是否适合实时语音反馈。

    核心入参:
        host/port/timeout: Runtime 服务地址与请求超时配置。
        role_name: 可选的持久化角色名，用于让基准请求复用指定角色配置。
        text: 基准测试时实际发送给 Runtime 的播报文本。
        iterations: 重复测量次数，用于降低单次抖动对结果的影响。
        json_summary_only: 是否只输出适合机器读取的紧凑摘要 JSON。

    预期输出:
        stdout 输出完整基准报告，或在启用 `--json-summary-only` 时输出压缩后的摘要结果；
        报告中通常包含请求往返耗时、播报完成耗时、估算音频时长以及实时性判断。

    边界异常:
        这是启发式体验基准，不等价于底层声学性能压测；
        当 Runtime 不可达、请求失败或基准执行异常时，命令会以非零状态退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    benchmark_report = _run_client_request(
        run_runtime_benchmark(
            client,
            text=text,
            role_name=role_name,
            iterations=iterations,
        )
    )
    if json_summary_only:
        _print_json(build_benchmark_summary(benchmark_report))
        return
    _print_json(benchmark_report)


@app.command()
def stop(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(5.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    停止 Runtime 进程。

    核心入参:
        host/port/timeout: Runtime 地址和请求超时。

    预期输出:
        stdout 输出 shutdown 响应 JSON。

    边界异常:
        Runtime 不可达时 httpx 异常会使 CLI 非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    _print_json(_run_client_request(client.shutdown()))


@models_app.command("list")
def models_list() -> None:
    """
    列出所有内置模型在当前硬件上的极简运行结论。

    核心入参:
        本命令无入参。

    预期输出:
        stdout 每行输出一个模型及其是否适合当前硬件的结论。

    边界异常:
        不抛业务异常。
    """

    hardware = detect_system_hardware()
    recommendations = recommend_model_profiles(hardware)
    for recommendation in recommendations:
        typer.echo(_format_model_recommendation_line(recommendation.profile.name, recommendation.status))


@roles_app.command("list")
def roles_list(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(5.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    列出当前模型缓存中的角色。

    核心入参:
        host/port/timeout: Runtime 地址和请求超时。

    预期输出:
        stdout 输出角色列表和当前默认角色。

    边界异常:
        Runtime 不可达时 httpx 异常会使 CLI 非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    _print_json(_run_client_request(client.list_roles()))


@roles_app.command("register")
def roles_register(
    role_name: str = typer.Argument(..., help="Role name to register in the current model cache."),
    audio_path: Optional[str] = typer.Option(
        None,
        "--audio-path",
        help="Reference audio path on the Runtime host. This is an advanced same-machine option.",
    ),
    audio_file: Optional[str] = typer.Option(
        None,
        "--audio",
        "--audio-file",
        help=(
            "Local reference audio file path. This is the recommended role registration input on Linux and Windows; "
            "omit --prompt-text to let Runtime auto-transcribe internally."
        ),
    ),
    audio_data_json: Optional[str] = typer.Option(
        None,
        "--audio-data-json",
        help="JSON array of float samples for in-memory role registration.",
    ),
    audio_data_file: Optional[str] = typer.Option(
        None,
        "--audio-data-file",
        help="Path to a JSON file containing a float sample array for in-memory role registration.",
    ),
    sample_rate: Optional[int] = typer.Option(
        None,
        "--sample-rate",
        help="Required when using in-memory audio registration.",
    ),
    prompt_text: Optional[str] = typer.Option(
        None,
        "--prompt-text",
        help="Optional reference transcript override. Omit to let Runtime auto-transcribe the reference audio internally.",
    ),
    set_default: bool = typer.Option(False, "--set-default", help="Set the registered role as the Runtime default role."),
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    注册一个持久化 Prompt 角色。

    核心入参:
        role_name/audio_path/audio_file/audio_data_json/audio_data_file/sample_rate/prompt_text/set_default/host/port/timeout: 角色注册参数。

    预期输出:
        stdout 输出 created 响应。

    边界异常:
        参数非法或 Runtime 不可达时命令非零退出。
    """

    audio_data_value = _parse_audio_data_source(audio_data_json, audio_data_file)
    audio_source_count = sum(
        source is not None
        for source in (
            audio_path,
            audio_file,
            audio_data_value,
        )
    )
    if audio_source_count != 1:
        raise typer.BadParameter(
            "exactly one of --audio/--audio-file, --audio-path or --audio-data-json/--audio-data-file must be provided"
        )
    if audio_data_value is None and sample_rate is not None:
        raise typer.BadParameter("--sample-rate is only valid with --audio-data-json or --audio-data-file")

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    if audio_file is not None:
        _print_json(
            _run_client_request(
                client.register_role_upload(
                    role_name=role_name,
                    audio_file=audio_file,
                    prompt_text=prompt_text,
                    set_default=set_default,
                )
            )
        )
        return

    _print_json(
        _run_client_request(
            client.register_role(
                role_name=role_name,
                audio_path=audio_path,
                audio_data=audio_data_value,
                sample_rate=sample_rate,
                prompt_text=prompt_text,
                set_default=set_default,
            )
        )
    )


@roles_app.command("delete")
def roles_delete(
    role_names: list[str] = typer.Argument(..., help="One or more cached role names to delete."),
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(10.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    删除一个或多个缓存角色。

    核心入参:
        role_names/host/port/timeout: 删除目标和 Runtime 地址。

    预期输出:
        stdout 输出 deleted 响应。

    边界异常:
        Runtime 不可达时命令非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    payload: str | list[str]
    if len(role_names) == 1:
        payload = role_names[0]
    else:
        payload = role_names
    _print_json(_run_client_request(client.delete_roles(payload)))


@roles_app.command("set-default")
def roles_set_default(
    role_name: str = typer.Argument(..., help="Existing cached role name to set as Runtime default."),
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(10.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    切换 Runtime 默认角色。

    核心入参:
        role_name/host/port/timeout: 默认角色更新参数。

    预期输出:
        stdout 输出 updated 响应。

    边界异常:
        角色不存在或 Runtime 不可达时命令非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    _print_json(_run_client_request(client.set_default_role(role_name)))


@roles_app.command("clear-default")
def roles_clear_default(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(10.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    清空 Runtime 默认角色。

    核心入参:
        host/port/timeout: Runtime 地址和请求超时。

    预期输出:
        stdout 输出 updated 响应，默认角色变为 null。

    边界异常:
        Runtime 不可达时命令非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    _print_json(_run_client_request(client.set_default_role(None)))


def main() -> None:
    """
    Typer console script 入口。

    核心入参:
        命令行参数由 Typer 解析。

    预期输出:
        分发到 start/selftest/benchmark/stop/models/roles 等子命令。

    边界异常:
        Typer 负责把参数错误转换为 CLI 错误提示。
    """

    app()


if __name__ == "__main__":
    main()
