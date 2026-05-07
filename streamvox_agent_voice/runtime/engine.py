"""StreamVox TTSEngine 封装。"""

from __future__ import annotations

from threading import Event
from typing import Any

import numpy as np

from ..asr import RolePromptTranscriber, default_role_prompt_transcriber
from ..events import VoiceEvent
from .audio_player import AudioSink
from .audio_assets import (
    DEFAULT_MAX_REFERENCE_SECONDS,
    ensure_audio_data_within_duration_limit,
    ensure_audio_path_within_duration_limit,
    temporary_wave_file_from_audio_data,
)
from .config import RuntimeConfig
from .model_registry import resolve_model_profile


class StreamVoxSpeaker:
    """
    常驻 StreamVox 引擎和音频播放的组合封装。

    核心入参:
        config: Runtime 启动配置。
        audio_sink: 音频播放后端。
        engine: 测试注入的伪 TTSEngine；生产环境为空时按配置创建真实引擎。

    预期输出:
        initialize 预热模型，speak 将事件文本转换为流式音频并播放。

    边界异常:
        模型加载、授权、推理、播放设备异常都会向上抛出，由队列层记录为 failed。
    """

    def __init__(
        self,
        config: RuntimeConfig,
        audio_sink: AudioSink,
        engine: Any | None = None,
        prompt_transcriber: RolePromptTranscriber | None = None,
    ) -> None:
        # 关键变量：config 持有模型、设备和默认角色等 Runtime 会话配置。
        self.config = config

        # 关键变量：audio_sink 是唯一负责系统音频输出的对象，便于测试替换。
        self.audio_sink = audio_sink

        # 关键变量：engine 允许测试注入 fake，避免单元测试加载真实大模型。
        self.engine = engine

        # 关键变量：prompt_transcriber 只在缺少 prompt_text 时介入，避免角色工作流强依赖手工转写。
        self.prompt_transcriber = prompt_transcriber or default_role_prompt_transcriber

        # 关键变量：initialized 用于 status 暴露 Runtime 是否已完成模型预热。
        self.initialized = engine is not None

    def initialize(self) -> None:
        """
        初始化并预热 StreamVox TTSEngine 与内部角色 ASR。

        核心入参:
            本方法不接收额外参数，使用构造时的 RuntimeConfig。

        预期输出:
            self.engine 指向可用 TTSEngine。

        边界异常:
            StreamVox SDK 未安装、模型加载失败或授权错误会向上传递。
        """

        # 测试注入 fake engine 时不重复初始化，避免覆盖测试桩。
        if self.engine is not None:
            if self.config.default_role_name is not None:
                self.set_default_role_name(self.config.default_role_name)
            self._preload_prompt_transcriber()
            self.initialized = True
            return

        # 延迟导入 streamvox，保证仅使用 client/CLI 帮助信息时不强制加载原生 TTS 运行时。
        from streamvox import TTSEngine

        self.engine = TTSEngine(
            model=self.config.model,
            license_key=self.config.license_key,
            license_path=self.config.license_path,
            device=self.config.device,
            verify_model_sha256=self.config.verify_model_sha256,
        )

        # 启动即指定默认角色时，应在 Runtime 预热阶段就验证它是否真实存在于当前模型缓存中。
        if self.config.default_role_name is not None:
            self.set_default_role_name(self.config.default_role_name)

        # 角色注册缺省 prompt_text 会依赖内部 ASR，因此把它放到 Runtime 初始化阶段一并预热。
        self._preload_prompt_transcriber()
        self.initialized = True

    def speak(self, event: VoiceEvent, stop_event: Event) -> None:
        """
        合成并播放一条语音事件。

        核心入参:
            event: 已校验的语音事件。
            stop_event: Runtime 控制层传入的中断信号。

        预期输出:
            文本被 StreamVox 流式合成并交给 audio_sink 播放。

        边界异常:
            engine 未初始化、stream 失败或播放失败时抛出 RuntimeError 或底层异常。
        """

        if not event.text.strip():
            return

        if self.engine is None:
            raise RuntimeError("StreamVox engine is not initialized")

        # 关键变量：kwargs 只在包装层补默认模型参数，不改变 Agent 原始文本。
        kwargs = self._stream_kwargs(event)
        chunks = self.engine.stream(text=event.text, **kwargs)
        self.audio_sink.play_chunks(chunks, self.sample_rate, stop_event)

    def validate_event_request(self, event: VoiceEvent) -> None:
        """
        在事件入队前校验当前 Runtime 是否接受该播报请求。

        核心入参:
            event: 已通过公开协议校验的语音事件。

        预期输出:
            合法请求无返回值；非法请求抛出 ValueError。

        边界异常:
            当前主要校验角色覆盖是否存在，以及 Runtime 自己维护的少量会话语义约束。
        """

        # 这里直接复用 stream kwargs 构造逻辑，确保“预校验”和“真正播报”走同一套参数分支。
        self._stream_kwargs(event)

    def register_role(
        self,
        *,
        role_name: str,
        prompt_text: str | None,
        audio_path: str | None = None,
        audio_data: list[float] | None = None,
        sample_rate: int | None = None,
        persist: bool = True,
        make_prompt_kwargs: dict[str, Any] | None = None,
    ) -> str:
        """
        注册一个可复用的 Prompt 角色资产。

        核心入参:
            role_name: 角色名，后续 Runtime 默认角色或事件级 role_name 都依赖它。
            audio_path: 单参考音频路径。
            audio_data: 内存中的单参考音频数组。
            sample_rate: 内存音频采样率。
            prompt_text: 与参考音频严格对齐的参考文本；缺失时由 Runtime 自动 ASR。
            persist: Runtime 资产工作流目前要求必须落盘缓存。
            make_prompt_kwargs: 透传给 TTSEngine.make_prompt 的模型私有参数。

        预期输出:
            成功时返回 role_name 本身，表示该角色已写入当前模型的角色缓存。

        边界异常:
            未初始化引擎、SDK 缺少 make_prompt、role_name 非法或 persist=False 时抛出异常。
        """

        if not isinstance(role_name, str) or not role_name.strip():
            raise ValueError("role_name must be a non-empty string")

        # Runtime 资产工作流的目标是“后续可查询、可切换、可删除”，因此当前强制要求持久化。
        if not persist:
            raise ValueError("runtime role registration only supports persist=true")

        profile = resolve_model_profile(self.config.model)
        max_reference_seconds = self._max_role_reference_seconds(profile)

        if profile is not None:
            if not profile.prompt.persist_role:
                raise ValueError(f"model {profile.name} does not support persisted role registration")

            # 已知模型优先走注册表约束，尽早把多参考、内存音频和 sample_rate 错误拦在 Runtime 边界。
            profile.validate_role_registration_request(
                audio_path=audio_path,
                audio_data=audio_data,
                prompt_text=prompt_text,
                sample_rate=sample_rate,
            )
        else:
            # 未知模型保持保守策略：只开放当前 Runtime 已明确支持的单参考工作流。
            if (audio_path is None) == (audio_data is None):
                raise ValueError("exactly one of audio_path or audio_data must be provided")
            if audio_path is not None and (not isinstance(audio_path, str) or not audio_path.strip()):
                raise ValueError("audio_path must be a non-empty string")
            if audio_data is not None and sample_rate is None:
                raise ValueError("sample_rate is required when audio_data is provided")
            if prompt_text is not None and (not isinstance(prompt_text, str) or not prompt_text.strip()):
                raise ValueError("prompt_text must be a non-empty string")

        # 这里统一执行 30 秒上限校验，避免大音频拖慢上传、ASR 和 Prompt 构建。
        self._validate_role_reference_audio(
            audio_path=audio_path,
            audio_data=audio_data,
            sample_rate=sample_rate,
            max_reference_seconds=max_reference_seconds,
        )

        # Prompt 文本缺失时，Runtime 会自动转写参考音频，减少预设音色资产制作的手工步骤。
        resolved_prompt_text = self._resolve_role_prompt_text(
            prompt_text=prompt_text,
            audio_path=audio_path,
            audio_data=audio_data,
            sample_rate=sample_rate,
        )

        engine = self._require_engine()
        make_prompt = getattr(engine, "make_prompt", None)
        if not callable(make_prompt):
            raise RuntimeError("StreamVox engine does not support make_prompt")

        kwargs = dict(make_prompt_kwargs or {})
        if audio_path is not None:
            kwargs["audio_path"] = audio_path
        else:
            # 统一在 Runtime 边界把 JSON 数组转成 float32 numpy，贴合 StreamVox SDK 的 make_prompt 约定。
            kwargs["audio_data"] = np.asarray(audio_data, dtype=np.float32)
            kwargs["sample_rate"] = sample_rate

        make_prompt(
            role_name=role_name,
            prompt_text=resolved_prompt_text,
            persist=True,
            **kwargs,
        )
        return role_name

    def list_roles(self) -> list[str]:
        """
        列出当前模型下所有已缓存角色。

        核心入参:
            本方法无入参。

        预期输出:
            返回按 SDK 规则排序后的角色名列表。

        边界异常:
            引擎未初始化或缺少 list_roles 能力时抛出异常。
        """

        engine = self._require_engine()
        list_roles = getattr(engine, "list_roles", None)
        if not callable(list_roles):
            raise RuntimeError("StreamVox engine does not support list_roles")
        roles = list_roles()
        return [role for role in roles if isinstance(role, str)]

    def delete_roles(self, role_names: str | list[str]) -> list[str]:
        """
        删除当前模型缓存中的角色资产。

        核心入参:
            role_names: 单个角色名，或角色名列表。

        预期输出:
            返回实际删除成功的角色名列表。

        边界异常:
            引擎未初始化、SDK 缺少 del_roles 或输入类型错误时抛出异常。
        """

        engine = self._require_engine()
        del_roles = getattr(engine, "del_roles", None)
        if not callable(del_roles):
            raise RuntimeError("StreamVox engine does not support del_roles")

        deleted_roles = del_roles(role_names)

        # 如果当前默认角色被删除，必须同步清空会话态，避免后续事件继续引用失效角色。
        if self.config.default_role_name and self.config.default_role_name in deleted_roles:
            self.config.default_role_name = None
        return [role for role in deleted_roles if isinstance(role, str)]

    def set_default_role_name(self, role_name: str | None) -> str | None:
        """
        更新 Runtime 会话级默认角色。

        核心入参:
            role_name: 新的默认角色名；传 None 表示清空默认角色。

        预期输出:
            返回当前最终生效的默认角色名，清空时返回 None。

        边界异常:
            role_name 非法或角色不存在时抛出异常。
        """

        # 允许显式清空默认角色，便于把 Runtime 会话切回“无默认角色”状态。
        if role_name is None:
            self.config.default_role_name = None
            return None

        if not isinstance(role_name, str) or not role_name.strip():
            raise ValueError("role_name must be a non-empty string or null")

        normalized_role_name = role_name.strip()
        profile = resolve_model_profile(self.config.model)
        if profile is not None and not profile.prompt.default_role_supported:
            raise ValueError(f"model {profile.name} does not support default role selection")

        # 默认角色必须指向当前模型缓存里真实存在的角色，避免把错误延迟到真正播报时才暴露。
        available_roles = set(self.list_roles())
        if normalized_role_name not in available_roles:
            raise ValueError(f"role does not exist for current model: {normalized_role_name}")

        self.config.default_role_name = normalized_role_name
        return normalized_role_name

    def shutdown(self) -> None:
        """
        关闭常驻 StreamVox 引擎。

        核心入参:
            本方法没有入参。

        预期输出:
            底层模型资源被释放。

        边界异常:
            engine.shutdown 自身异常会向上传递，便于调用方记录。
        """

        if self.engine is None:
            return
        shutdown = getattr(self.engine, "shutdown", None)
        if callable(shutdown):
            shutdown()
        self.initialized = False

    @property
    def sample_rate(self) -> int:
        """
        返回当前 StreamVox runtime 采样率。

        核心入参:
            本属性不接收参数。

        预期输出:
            返回 engine.runtime.sample_rate，缺失时回退到 24000。

        边界异常:
            本属性不抛异常，避免 status 或 fake engine 场景失败。
        """

        runtime = getattr(self.engine, "runtime", None)
        return int(getattr(runtime, "sample_rate", 24000))

    def _stream_kwargs(self, event: VoiceEvent) -> dict[str, Any]:
        """
        构造传给 TTSEngine.stream 的模型参数。

        核心入参:
            event: 当前语音事件，可通过 metadata 传入少量模型参数。

        预期输出:
            返回安全的 stream kwargs。

        边界异常:
            Runtime 只在这里处理会话级角色语义与少量模型特例；大多数模型私有参数保持透传，交给 StreamVox SDK 自行过滤或校验。
        """

        # 所有模型都可以使用性能日志开关；第一版默认关闭，减少 Agent 播报噪声。
        metadata = event.metadata

        # 关键变量：streamvox_metadata 是模型私有参数透传入口，优先级高于旧的平铺 metadata 字段。
        streamvox_metadata = self._streamvox_metadata(metadata)
        passthrough = dict(streamvox_metadata)
        explicit_role_override = "role_name" in metadata or "role_name" in streamvox_metadata
        kwargs: dict[str, Any] = {
            "track_performance": bool(
                passthrough.pop("track_performance", metadata.get("track_performance", False))
            )
        }

        # 角色名是会话级能力的第一步：默认继承 Runtime 配置，事件可显式覆盖。
        role_name = passthrough.pop("role_name", metadata.get("role_name", self.config.default_role_name))
        if role_name:
            normalized_role_name = str(role_name).strip()
            if not normalized_role_name:
                raise ValueError("role_name must be a non-empty string")
            if explicit_role_override:
                self._validate_existing_role_name(normalized_role_name)
            kwargs["role_name"] = normalized_role_name

        # language 继续保留旧入口，兼容 Qwen3 和其他已知多语言模型的常见调用方式。
        if "language" in passthrough:
            kwargs["language"] = passthrough.pop("language")
        elif "language" in metadata:
            kwargs["language"] = metadata["language"]

        # 只有已知是 VoxCPM2 的模型，才在缺省时补一个 mode=text。
        # 这里不再维护会话级默认 control_text；该能力应由单次推理显式决定是否传入。
        profile = resolve_model_profile(self.config.model)
        if profile is not None and profile.name == "voxcpm2-gguf":
            mode = passthrough.pop("mode", metadata.get("mode", "text"))
            kwargs["mode"] = str(mode)

        # 最后再把剩余模型私有参数直接透传到底层 SDK，避免公共协议被所有模型细节污染。
        kwargs.update(passthrough)

        # 这里只保留 Runtime 自己必须维护的少量语义校验，其余模型私有参数交给 SDK。
        if profile is not None:
            profile.validate_stream_request(stream_kwargs=kwargs)
        return kwargs

    def _streamvox_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        提取模型私有参数透传对象。

        核心入参:
            metadata: 事件级公开 metadata。

        预期输出:
            返回 `metadata.streamvox` 对象；缺失或类型不对时返回空字典。

        边界异常:
            本方法不抛异常，协议合法性由 VoiceEvent 校验层负责。
        """

        value = metadata.get("streamvox", {})
        if isinstance(value, dict):
            return value
        return {}

    def _validate_existing_role_name(self, role_name: str) -> None:
        """
        校验事件级覆盖角色是否真实存在于当前模型缓存。

        核心入参:
            role_name: 调用方显式传入的角色名。

        预期输出:
            角色存在时无返回值；不存在时抛出 ValueError。

        边界异常:
            引擎未初始化或不支持 list_roles 时，会沿用已有异常语义向上抛出。
        """

        available_roles = set(self.list_roles())
        if role_name not in available_roles:
            raise ValueError(f"role does not exist for current model: {role_name}")

    def _max_role_reference_seconds(self, profile: Any | None) -> float:
        """
        返回当前角色注册公开允许的最大参考音频时长。

        核心入参:
            profile: 当前模型注册表项；未知模型时可为空。

        预期输出:
            已知模型优先使用注册表里的时长上限，否则回退默认 30 秒。

        边界异常:
            不抛异常。
        """

        if profile is not None and profile.prompt.max_reference_seconds is not None:
            return float(profile.prompt.max_reference_seconds)
        return DEFAULT_MAX_REFERENCE_SECONDS

    def _validate_role_reference_audio(
        self,
        *,
        audio_path: str | None,
        audio_data: list[float] | None,
        sample_rate: int | None,
        max_reference_seconds: float,
    ) -> None:
        """
        校验角色参考音频来源与时长边界。

        核心入参:
            audio_path: 文件路径型参考音频。
            audio_data: 内存音频数组。
            sample_rate: 内存音频采样率。
            max_reference_seconds: 最大允许时长。

        预期输出:
            合法时无返回值。

        边界异常:
            音频来源缺失、类型错误或超过时长上限时抛出 ValueError。
        """

        if (audio_path is None) == (audio_data is None):
            raise ValueError("exactly one of audio_path or audio_data must be provided")

        if audio_path is not None:
            if not isinstance(audio_path, str) or not audio_path.strip():
                raise ValueError("audio_path must be a non-empty string")
            ensure_audio_path_within_duration_limit(audio_path, max_seconds=max_reference_seconds)
            return

        if audio_data is None or sample_rate is None:
            raise ValueError("sample_rate is required when audio_data is provided")
        ensure_audio_data_within_duration_limit(
            audio_data,
            sample_rate=sample_rate,
            max_seconds=max_reference_seconds,
        )

    def _resolve_role_prompt_text(
        self,
        *,
        prompt_text: str | None,
        audio_path: str | None,
        audio_data: list[float] | None,
        sample_rate: int | None,
    ) -> str:
        """
        解析角色注册最终要使用的 `prompt_text`。

        核心入参:
            prompt_text: 调用方显式提供的参考文本。
            audio_path: 文件路径型参考音频。
            audio_data: 内存音频数组。
            sample_rate: 内存音频采样率。

        预期输出:
            优先返回显式提供的参考文本；缺失时走内部自动 ASR。

        边界异常:
            音频来源缺失、ASR 不可用或转写结果为空时抛出异常。
        """

        if prompt_text is not None:
            normalized_prompt_text = prompt_text.strip()
            if not normalized_prompt_text:
                raise ValueError("prompt_text must be a non-empty string")
            return normalized_prompt_text

        if audio_path is not None:
            return self._transcribe_role_reference_audio(audio_path)

        if audio_data is None or sample_rate is None:
            raise ValueError("prompt_text is required when no reference audio is available for ASR")

        with temporary_wave_file_from_audio_data(audio_data, sample_rate=sample_rate) as temporary_audio_path:
            return self._transcribe_role_reference_audio(temporary_audio_path)

    def _transcribe_role_reference_audio(self, audio_path: str) -> str:
        """
        使用内置 ASR 把参考音频转成 `prompt_text`。

        核心入参:
            audio_path: 本地可访问的音频路径。

        预期输出:
            返回非空参考文本。

        边界异常:
            转写器缺失接口、转写失败或结果为空时抛出 RuntimeError。
        """

        transcribe = getattr(self.prompt_transcriber, "transcribe_path", None)
        if not callable(transcribe):
            raise RuntimeError("prompt_transcriber does not support transcribe_path")

        prompt_text = str(transcribe(audio_path)).strip()
        if not prompt_text:
            raise RuntimeError("automatic ASR produced an empty prompt_text")
        return prompt_text

    def _preload_prompt_transcriber(self) -> None:
        """
        显式加载并预热内部角色参考音频转写器。

        核心入参:
            无。

        预期输出:
            支持 `load()` 的转写器会在 Runtime 初始化阶段完成预热。

        边界异常:
            转写器 `load()` 失败时沿用底层异常，让 Runtime 启动直接失败。
        """

        load = getattr(self.prompt_transcriber, "load", None)
        if callable(load):
            load()

    def _require_engine(self) -> Any:
        """
        返回已初始化的 StreamVox 引擎实例。

        核心入参:
            本方法无入参。

        预期输出:
            返回可直接调用 SDK 方法的 engine 对象。

        边界异常:
            engine 未初始化时抛出 RuntimeError。
        """

        if self.engine is None:
            raise RuntimeError("StreamVox engine is not initialized")
        return self.engine
