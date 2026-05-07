"""StreamVox 模型注册表与能力快照。"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import RuntimeConfig


# 关键常量：统一使用二进制容量换算，避免 GiB 与 GB 混淆导致阈值判断偏差。
_BYTES_PER_GIB = 1024**3
_MIB_PER_GIB = 1024


@dataclass(frozen=True, slots=True)
class ModelHardwareProfile:
    """
    描述模型对硬件资源的基本要求。

    核心入参:
        min_vram_gb: 最低显存需求，未知时可为空。
        recommended_vram_gb: 推荐显存需求，未知时可为空。
        min_ram_gb: 最低内存需求，未知时可为空。

    预期输出:
        to_payload 返回可直接序列化的硬件能力字典。

    边界异常:
        本数据类不做数值合法性校验；文档和注册表维护负责保证数据可信。
    """

    min_vram_gb: int | None
    recommended_vram_gb: int | None
    min_ram_gb: int | None

    def to_payload(self) -> dict[str, int | None]:
        """
        转换为公开 JSON 字典。

        核心入参:
            本方法无入参。

        预期输出:
            返回最低显存、推荐显存和最低内存。

        边界异常:
            不抛异常。
        """

        return {
            "min_vram_gb": self.min_vram_gb,
            "recommended_vram_gb": self.recommended_vram_gb,
            "min_ram_gb": self.min_ram_gb,
        }


@dataclass(frozen=True, slots=True)
class ModelPromptProfile:
    """
    描述模型在 Prompt / Role 资产上的能力边界。

    核心入参:
        single_reference: 是否支持单参考 Prompt。
        multi_reference: 底层 StreamVox SDK 是否支持多参考 Prompt。
        role_registration_multi_reference: 当前 Agent Voice Runtime 是否公开多参考角色注册。
        persist_role: 是否支持本地缓存角色资产。
        memory_audio: 是否支持通过内存音频数组创建 Prompt。
        sample_rate_required_with_memory_audio: 使用内存音频时是否必须显式提供采样率。
        reference_text_required: 构建 Prompt 时是否要求提供参考文本。
        auto_prompt_text_from_asr: 缺失参考文本时，Runtime 是否可以内部自动 ASR。
        binary_upload: Runtime 是否公开二进制/文件上传角色注册入口。
        max_reference_seconds: Runtime 公开允许的单条参考音频最长时长。
        cache_scope: 角色缓存粒度，当前 StreamVox 按模型隔离。
        default_role_supported: 当前模型是否允许 Runtime 持有默认角色概念。

    预期输出:
        to_payload 返回 Prompt 能力字典。

    边界异常:
        不抛异常。
    """

    single_reference: bool
    multi_reference: bool
    role_registration_multi_reference: bool
    persist_role: bool
    memory_audio: bool
    sample_rate_required_with_memory_audio: bool
    reference_text_required: bool
    auto_prompt_text_from_asr: bool
    binary_upload: bool
    max_reference_seconds: int | None
    cache_scope: str
    default_role_supported: bool

    def to_payload(self) -> dict[str, Any]:
        """
        转换为公开 JSON 字典。

        核心入参:
            本方法无入参。

        预期输出:
            返回 Prompt / Role 能力摘要。

        边界异常:
            不抛异常。
        """

        return {
            "single_reference": self.single_reference,
            "multi_reference": self.multi_reference,
            "role_registration_multi_reference": self.role_registration_multi_reference,
            "persist_role": self.persist_role,
            "memory_audio": self.memory_audio,
            "sample_rate_required_with_memory_audio": self.sample_rate_required_with_memory_audio,
            "reference_text_required": self.reference_text_required,
            "auto_prompt_text_from_asr": self.auto_prompt_text_from_asr,
            "binary_upload": self.binary_upload,
            "max_reference_seconds": self.max_reference_seconds,
            "cache_scope": self.cache_scope,
            "default_role_supported": self.default_role_supported,
        }

    def validate_registration_request(
        self,
        *,
        model_name: str,
        audio_path: str | None,
        audio_data: list[float] | None,
        prompt_text: str | None,
        sample_rate: int | None,
    ) -> None:
        """
        校验当前模型下的角色注册请求是否满足 Prompt 能力约束。

        核心入参:
            model_name: 当前 StreamVox 模型名，仅用于错误提示。
            audio_path: 文件路径型参考音频。
            audio_data: 内存中的单参考音频数组。
            prompt_text: 参考音频对应文本。
            sample_rate: 内存音频采样率。

        预期输出:
            合法请求无返回值；非法请求抛出 ValueError。

        边界异常:
            本方法只校验 Agent Voice Runtime 已公开承诺支持的约束，不校验底层模型私有参数。
        """

        # 角色注册必须明确选择一种音频来源，避免同时传文件和内存音频导致语义冲突。
        if (audio_path is None) == (audio_data is None):
            raise ValueError("exactly one of audio_path or audio_data must be provided")

        if audio_path is not None:
            if not isinstance(audio_path, str):
                if self.multi_reference and not self.role_registration_multi_reference:
                    raise ValueError("runtime only supports single-reference role registration")
                raise ValueError("audio_path must be a non-empty string")
            if not audio_path.strip():
                raise ValueError("audio_path must be a non-empty string")
            if not self.single_reference:
                raise ValueError(f"model {model_name} does not support single-reference role registration")
            if sample_rate is not None:
                raise ValueError("sample_rate is only valid when audio_data is provided")
        else:
            # 从这里开始表示当前走的是内存音频注册链路。
            if not self.memory_audio:
                raise ValueError(f"model {model_name} does not support in-memory audio role registration")

            if self.sample_rate_required_with_memory_audio and sample_rate is None:
                raise ValueError("sample_rate is required when audio_data is provided")

        if prompt_text is not None and (not isinstance(prompt_text, str) or not prompt_text.strip()):
            raise ValueError("prompt_text must be a non-empty string")

        if prompt_text is None and self.reference_text_required and not self.auto_prompt_text_from_asr:
            raise ValueError(f"model {model_name} requires prompt_text for role registration")


@dataclass(frozen=True, slots=True)
class ModelControlProfile:
    """
    描述模型支持的控制能力。

    核心入参:
        language: 是否公开支持语言参数。
        control_text: 是否公开支持 control_text。
        modes: 是否存在显式 mode 概念；没有时为空元组。
        sampling: 公开支持的采样参数名称。
        stream_flag: 是否公开支持 `stream`。
        icl: 是否公开支持 `icl`。
        max_length: 是否公开支持长文本分段上限。
        min_length: 是否公开支持短段合并下限。
        remove_meaningless_chars: 是否公开支持无意义字符清理开关。
        speaker_tags: 是否支持多 speaker 标签。
        inline_tags: 是否支持正文内联控制标签。

    预期输出:
        to_payload 返回控制能力字典。

    边界异常:
        不抛异常。
    """

    language: bool
    control_text: bool
    modes: tuple[str, ...]
    sampling: tuple[str, ...]
    stream_flag: bool
    icl: bool
    max_length: bool
    min_length: bool
    remove_meaningless_chars: bool
    speaker_tags: bool
    inline_tags: bool

    def to_payload(self) -> dict[str, Any]:
        """
        转换为公开 JSON 字典。

        核心入参:
            本方法无入参。

        预期输出:
            返回适合 CLI / HTTP 状态接口展示的能力摘要。

        边界异常:
            不抛异常。
        """

        return {
            "language": self.language,
            "control_text": self.control_text,
            "modes": list(self.modes),
            "sampling": list(self.sampling),
            "stream": self.stream_flag,
            "icl": self.icl,
            "max_length": self.max_length,
            "min_length": self.min_length,
            "remove_meaningless_chars": self.remove_meaningless_chars,
            "speaker_tags": self.speaker_tags,
            "inline_tags": self.inline_tags,
        }

    def validate_stream_request(self, *, model_name: str, stream_kwargs: dict[str, Any]) -> None:
        """
        校验当前模型下的流式推理参数。

        核心入参:
            model_name: 当前模型名，用于生成可读错误提示。
            stream_kwargs: 即将透传给 `TTSEngine.stream(...)` 的参数字典。

        预期输出:
            参数合法时无返回值；非法时抛出 ValueError。

        边界异常:
            当前只校验 Runtime 自己必须维护的少量语义约束；其余模型私有参数默认交给 StreamVox SDK 自行过滤或校验。
        """

        # VoxCPM2 的 ref / continuation 系模式必须显式持有角色资产，否则底层推理语义不完整。
        if model_name == "voxcpm2-gguf":
            mode = stream_kwargs.get("mode")
            resolved_mode = _normalize_mode_name(model_name, mode if mode is not None else "text")
            if resolved_mode in {"ref", "continuation", "ref_continuation"}:
                role_name = stream_kwargs.get("role_name")
                if not isinstance(role_name, str) or not role_name.strip():
                    raise ValueError(f"mode {resolved_mode} requires a persisted role_name")


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """
    描述一个 StreamVox 模型在 Agent Voice Runtime 中公开支持的能力。

    核心入参:
        name: StreamVox 模型名。
        family: 模型家族名称。
        summary: 简短定位说明。
        sample_rate: 模型默认采样率。
        hardware: 基本硬件资源要求。
        prompt: Prompt / Role 能力描述。
        controls: 控制参数能力描述。

    预期输出:
        to_payload 返回可公开给 CLI、HTTP 和文档使用的模型能力字典。

    边界异常:
        本数据类不负责推理参数校验，运行时逻辑应结合当前事件自行处理。
    """

    name: str
    family: str
    summary: str
    sample_rate: int
    hardware: ModelHardwareProfile
    prompt: ModelPromptProfile
    controls: ModelControlProfile

    def to_payload(self) -> dict[str, Any]:
        """
        转换为公开 JSON 字典。

        核心入参:
            本方法无入参。

        预期输出:
            返回完整模型能力摘要。

        边界异常:
            不抛异常。
        """

        return {
            "model": self.name,
            "family": self.family,
            "summary": self.summary,
            "sample_rate": self.sample_rate,
            "hardware": self.hardware.to_payload(),
            "prompt": self.prompt.to_payload(),
            "controls": self.controls.to_payload(),
        }

    def validate_role_registration_request(
        self,
        *,
        audio_path: str | None,
        audio_data: list[float] | None,
        prompt_text: str | None,
        sample_rate: int | None,
    ) -> None:
        """
        校验当前模型下的 Prompt 角色注册请求。

        核心入参:
            audio_path: 文件路径型参考音频。
            audio_data: 内存中的音频数组。
            prompt_text: 参考音频对应文本。
            sample_rate: 内存音频采样率。

        预期输出:
            合法请求无返回值；非法请求抛出 ValueError。

        边界异常:
            只校验 Runtime 已公开承诺支持的角色管理能力，不校验底层 SDK 私有参数。
        """

        self.prompt.validate_registration_request(
            model_name=self.name,
            audio_path=audio_path,
            audio_data=audio_data,
            prompt_text=prompt_text,
            sample_rate=sample_rate,
        )

    def validate_stream_request(self, *, stream_kwargs: dict[str, Any]) -> None:
        """
        校验当前模型下的流式推理请求。

        核心入参:
            stream_kwargs: 即将透传给 `TTSEngine.stream(...)` 的参数。

        预期输出:
            参数合法时无返回值；非法时抛出 ValueError。

        边界异常:
            只校验当前注册表已经公开承诺支持的关键参数，其余未知参数暂时保持透传。
        """

        self.controls.validate_stream_request(model_name=self.name, stream_kwargs=stream_kwargs)


@dataclass(frozen=True, slots=True)
class DetectedGpuInfo:
    """
    描述本机检测到的一张 GPU。

    核心入参:
        index: GPU 序号。
        name: GPU 名称。
        total_vram_mib: 总显存，单位 MiB；未知时为空。

    预期输出:
        to_payload 返回可直接用于 CLI / 文档输出的字典。

    边界异常:
        本数据类不做额外校验，探测逻辑负责保证字段可信。
    """

    index: int
    name: str
    total_vram_mib: int | None

    def to_payload(self) -> dict[str, Any]:
        """
        转换为公开 JSON 字典。

        核心入参:
            本方法无入参。

        预期输出:
            返回 GPU 基本信息和显存容量。

        边界异常:
            不抛异常。
        """

        return {
            "index": self.index,
            "name": self.name,
            "total_vram_mib": self.total_vram_mib,
            "total_vram_gib": _mib_to_gib(self.total_vram_mib),
        }


@dataclass(frozen=True, slots=True)
class SystemHardwareSnapshot:
    """
    描述当前机器的硬件快照。

    核心入参:
        cpu_count: 可见 CPU 核心数。
        total_ram_bytes: 系统总内存，单位字节；未知时为空。
        gpus: 检测到的 GPU 列表。
        detection_warnings: 探测阶段产生的告警信息。

    预期输出:
        to_payload 返回面向 CLI / 文档的硬件摘要。

    边界异常:
        本数据类不抛异常，调用方应根据空值自行决定是否降级。
    """

    cpu_count: int | None
    total_ram_bytes: int | None
    gpus: tuple[DetectedGpuInfo, ...]
    detection_warnings: tuple[str, ...] = ()

    @property
    def total_ram_gib(self) -> float | None:
        """
        以 GiB 返回系统总内存。

        核心入参:
            本属性不接收参数。

        预期输出:
            成功时返回一位小数的 GiB 值，未知时返回 None。

        边界异常:
            不抛异常。
        """

        return _bytes_to_gib(self.total_ram_bytes)

    @property
    def max_vram_mib(self) -> int | None:
        """
        返回当前机器上可见 GPU 的最大显存。

        核心入参:
            本属性不接收参数。

        预期输出:
            至少有一张 GPU 时返回最大显存 MiB；否则返回 None。

        边界异常:
            不抛异常。
        """

        candidates = [gpu.total_vram_mib for gpu in self.gpus if gpu.total_vram_mib is not None]
        if not candidates:
            return None
        return max(candidates)

    @property
    def max_vram_gib(self) -> float | None:
        """
        以 GiB 返回可见 GPU 的最大显存。

        核心入参:
            本属性不接收参数。

        预期输出:
            至少有一张 GPU 时返回一位小数的 GiB 值；否则返回 None。

        边界异常:
            不抛异常。
        """

        return _mib_to_gib(self.max_vram_mib)

    def best_gpu(self, *, minimum_vram_mib: int | None = None) -> DetectedGpuInfo | None:
        """
        返回满足显存要求且显存最大的 GPU。

        核心入参:
            minimum_vram_mib: 最低显存要求；为空时只返回当前机器上显存最大的 GPU。

        预期输出:
            返回一张满足条件的 GPU；没有满足条件的 GPU 时返回 None。

        边界异常:
            不抛异常。
        """

        candidates = [
            gpu
            for gpu in self.gpus
            if gpu.total_vram_mib is not None and (minimum_vram_mib is None or gpu.total_vram_mib >= minimum_vram_mib)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda gpu: gpu.total_vram_mib or 0)

    def to_payload(self) -> dict[str, Any]:
        """
        转换为公开 JSON 字典。

        核心入参:
            本方法无入参。

        预期输出:
            返回 CPU、内存、GPU 和探测告警信息。

        边界异常:
            不抛异常。
        """

        return {
            "cpu_count": self.cpu_count,
            "total_ram_bytes": self.total_ram_bytes,
            "total_ram_gib": self.total_ram_gib,
            "gpu_count": len(self.gpus),
            "max_vram_mib": self.max_vram_mib,
            "max_vram_gib": self.max_vram_gib,
            "gpus": [gpu.to_payload() for gpu in self.gpus],
            "detection_warnings": list(self.detection_warnings),
        }


@dataclass(frozen=True, slots=True)
class ModelRecommendation:
    """
    描述一个模型在当前机器上的推荐结果。

    核心入参:
        profile: 被评估的模型注册表项。
        status: 推荐状态，例如 recommended/supported/cpu_fallback/insufficient。
        recommended_device: 推荐启动设备，例如 gpu:0 或 cpu。
        reasons: 形成当前结论的原因说明。

    预期输出:
        to_payload 返回适合 CLI 输出的推荐条目。

    边界异常:
        不抛异常。
    """

    profile: ModelProfile
    status: str
    recommended_device: str | None
    reasons: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """
        转换为公开 JSON 字典。

        核心入参:
            本方法无入参。

        预期输出:
            返回模型摘要、推荐状态和推荐设备。

        边界异常:
            不抛异常。
        """

        return {
            **self.profile.to_payload(),
            "status": self.status,
            "recommended_device": self.recommended_device,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class ModelDoctorReport:
    """
    描述单个模型在当前机器上的诊断结果。

    核心入参:
        requested_model: 用户请求检查的模型名或路径。
        profile: 解析出的模型注册表项；未知模型时为空。
        hardware: 当前机器硬件快照。
        status: 诊断状态。
        recommended_device: 推荐设备。
        reasons: 诊断说明。

    预期输出:
        to_payload 返回完整诊断结果。

    边界异常:
        不抛异常。
    """

    requested_model: str
    profile: ModelProfile | None
    hardware: SystemHardwareSnapshot
    status: str
    recommended_device: str | None
    reasons: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """
        转换为公开 JSON 字典。

        核心入参:
            本方法无入参。

        预期输出:
            返回请求模型、解析结果、硬件快照与诊断说明。

        边界异常:
            不抛异常。
        """

        return {
            "requested_model": self.requested_model,
            "resolved_model": self.profile.name if self.profile is not None else None,
            "profile_found": self.profile is not None,
            "status": self.status,
            "recommended_device": self.recommended_device,
            "reasons": list(self.reasons),
            "hardware": self.hardware.to_payload(),
            "model_profile": self.profile.to_payload() if self.profile is not None else None,
        }


# 关键常量：注册表只表达当前 Agent Voice Runtime 已经理解并公开支持的模型能力。
_MODEL_PROFILES: dict[str, ModelProfile] = {
    "qwen3-tts-clone-0.6b-gguf": ModelProfile(
        name="qwen3-tts-clone-0.6b-gguf",
        family="Qwen3 TTS Clone",
        summary="极致低延迟、低资源占用的单参考音色克隆模型。",
        sample_rate=24000,
        hardware=ModelHardwareProfile(min_vram_gb=2, recommended_vram_gb=3, min_ram_gb=3),
        prompt=ModelPromptProfile(
            single_reference=True,
            multi_reference=False,
            role_registration_multi_reference=False,
            persist_role=True,
            memory_audio=True,
            sample_rate_required_with_memory_audio=True,
            reference_text_required=True,
            auto_prompt_text_from_asr=True,
            binary_upload=True,
            max_reference_seconds=30,
            cache_scope="model",
            default_role_supported=True,
        ),
        controls=ModelControlProfile(
            language=True,
            control_text=False,
            modes=(),
            sampling=(),
            stream_flag=True,
            icl=True,
            max_length=True,
            min_length=True,
            remove_meaningless_chars=True,
            speaker_tags=False,
            inline_tags=False,
        ),
    ),
    "qwen3-tts-clone-1.7b-gguf": ModelProfile(
        name="qwen3-tts-clone-1.7b-gguf",
        family="Qwen3 TTS Clone",
        summary="速度与自然度更均衡的单参考音色克隆模型。",
        sample_rate=24000,
        hardware=ModelHardwareProfile(min_vram_gb=3, recommended_vram_gb=4, min_ram_gb=4),
        prompt=ModelPromptProfile(
            single_reference=True,
            multi_reference=False,
            role_registration_multi_reference=False,
            persist_role=True,
            memory_audio=True,
            sample_rate_required_with_memory_audio=True,
            reference_text_required=True,
            auto_prompt_text_from_asr=True,
            binary_upload=True,
            max_reference_seconds=30,
            cache_scope="model",
            default_role_supported=True,
        ),
        controls=ModelControlProfile(
            language=True,
            control_text=False,
            modes=(),
            sampling=(),
            stream_flag=True,
            icl=True,
            max_length=True,
            min_length=True,
            remove_meaningless_chars=True,
            speaker_tags=False,
            inline_tags=False,
        ),
    ),
    "s2-pro-4b-gguf": ModelProfile(
        name="s2-pro-4b-gguf",
        family="S2-Pro",
        summary="面向高保真演播、多说话人与复杂表达控制的模型。",
        sample_rate=44100,
        hardware=ModelHardwareProfile(min_vram_gb=7, recommended_vram_gb=8, min_ram_gb=6),
        prompt=ModelPromptProfile(
            single_reference=True,
            multi_reference=True,
            role_registration_multi_reference=False,
            persist_role=True,
            memory_audio=True,
            sample_rate_required_with_memory_audio=True,
            reference_text_required=True,
            auto_prompt_text_from_asr=True,
            binary_upload=True,
            max_reference_seconds=30,
            cache_scope="model",
            default_role_supported=True,
        ),
        controls=ModelControlProfile(
            language=False,
            control_text=False,
            modes=(),
            sampling=("temperature", "top_p", "top_k"),
            stream_flag=False,
            icl=False,
            max_length=True,
            min_length=True,
            remove_meaningless_chars=True,
            speaker_tags=True,
            inline_tags=True,
        ),
    ),
    "voxcpm2-gguf": ModelProfile(
        name="voxcpm2-gguf",
        family="VoxCPM2",
        summary="兼顾音色设计、克隆与续写的多模式流式模型。",
        sample_rate=48000,
        hardware=ModelHardwareProfile(min_vram_gb=6, recommended_vram_gb=8, min_ram_gb=4),
        prompt=ModelPromptProfile(
            single_reference=True,
            multi_reference=False,
            role_registration_multi_reference=False,
            persist_role=True,
            memory_audio=True,
            sample_rate_required_with_memory_audio=True,
            reference_text_required=True,
            auto_prompt_text_from_asr=True,
            binary_upload=True,
            max_reference_seconds=30,
            cache_scope="model",
            default_role_supported=True,
        ),
        controls=ModelControlProfile(
            language=False,
            control_text=True,
            modes=("text", "ref", "continuation", "ref_continuation"),
            sampling=(),
            stream_flag=False,
            icl=False,
            max_length=False,
            min_length=False,
            remove_meaningless_chars=False,
            speaker_tags=False,
            inline_tags=True,
        ),
    ),
}


def list_model_profiles() -> list[ModelProfile]:
    """
    返回当前内置模型注册表。

    核心入参:
        本方法无入参。

    预期输出:
        返回按模型名排序的 ModelProfile 列表。

    边界异常:
        不抛异常。
    """

    return [_MODEL_PROFILES[name] for name in sorted(_MODEL_PROFILES)]


def resolve_model_profile(model: str) -> ModelProfile | None:
    """
    根据模型名或本地 bundle 路径解析已知模型能力。

    核心入参:
        model: StreamVox 模型名，或本地模型 bundle 路径。

    预期输出:
        已知模型返回对应 ModelProfile，未知模型返回 None。

    边界异常:
        manifest 不存在、内容损坏或字段缺失时不抛异常，只回退到更宽松的名称匹配。
    """

    # 先处理最直接的模型名输入，避免路径探测带来多余 I/O。
    if model in _MODEL_PROFILES:
        return _MODEL_PROFILES[model]

    # 再尝试把输入当作本地 bundle 路径解析 manifest，兼容生产环境传本地模型目录。
    manifest_model = _load_manifest_model(model)
    if manifest_model in _MODEL_PROFILES:
        return _MODEL_PROFILES[manifest_model]

    # 最后允许以路径名回退匹配，覆盖 ./models/voxcpm2-gguf 这类常见目录结构。
    candidate_name = Path(model).name
    if candidate_name in _MODEL_PROFILES:
        return _MODEL_PROFILES[candidate_name]

    return None


def build_capability_snapshot(config: RuntimeConfig) -> dict[str, Any]:
    """
    构造当前 Runtime 会话的能力快照。

    核心入参:
        config: 当前 Runtime 配置。

    预期输出:
        返回包含请求模型、已解析模型、能力摘要和当前默认角色状态的字典。

    边界异常:
        未注册模型不会抛异常，而是返回 profile_found=False 的降级结果。
    """

    profile = resolve_model_profile(config.model)
    controls = profile.controls.to_payload() if profile is not None else None
    return {
        "requested_model": config.model,
        "resolved_model": profile.name if profile is not None else None,
        "profile_found": profile is not None,
        "family": profile.family if profile is not None else None,
        "summary": profile.summary if profile is not None else None,
        "sample_rate": profile.sample_rate if profile is not None else None,
        "hardware": profile.hardware.to_payload() if profile is not None else None,
        "prompt": profile.prompt.to_payload() if profile is not None else None,
        "controls": controls,
        # 关键字段：session 用来表达当前 Runtime 会话级默认能力，而不是静态模型文档。
        "session": {
            "default_role_name": config.default_role_name,
            "output": config.audio_backend,
        },
    }


def detect_system_hardware(
    *,
    command_runner: Callable[[list[str]], tuple[int, str, str]] | None = None,
    cpu_count: int | None = None,
    total_ram_bytes: int | None = None,
) -> SystemHardwareSnapshot:
    """
    检测当前机器的基础硬件信息。

    核心入参:
        command_runner: 可注入的命令执行器，主要用于测试替换 nvidia-smi。
        cpu_count: 可注入的 CPU 数，测试时可覆盖真实值。
        total_ram_bytes: 可注入的总内存字节数，测试时可覆盖真实值。

    预期输出:
        返回 CPU、内存、GPU 和探测告警组成的硬件快照。

    边界异常:
        本函数不因探测失败抛异常，而是把问题折叠进 detection_warnings。
    """

    warnings: list[str] = []
    resolved_cpu_count = cpu_count if cpu_count is not None else os.cpu_count()
    resolved_total_ram_bytes = total_ram_bytes if total_ram_bytes is not None else _detect_total_ram_bytes()
    if resolved_total_ram_bytes is None:
        warnings.append("无法自动检测系统总内存，后续 RAM 校验将退化为未知。")

    resolved_command_runner = command_runner or _run_command
    gpus, gpu_warnings = _detect_nvidia_gpus(command_runner=resolved_command_runner)
    warnings.extend(gpu_warnings)
    return SystemHardwareSnapshot(
        cpu_count=resolved_cpu_count,
        total_ram_bytes=resolved_total_ram_bytes,
        gpus=tuple(gpus),
        detection_warnings=tuple(warnings),
    )


def recommend_model_profiles(hardware: SystemHardwareSnapshot | None = None) -> list[ModelRecommendation]:
    """
    根据当前机器硬件给出模型推荐列表。

    核心入参:
        hardware: 可选的硬件快照；为空时自动探测本机硬件。

    预期输出:
        返回按可运行性和资源稳妥程度排序的模型推荐列表。

    边界异常:
        本函数不抛探测异常；探测问题会体现在 recommendations 的 reasons 中。
    """

    resolved_hardware = hardware or detect_system_hardware()
    recommendations = [_assess_model_support(profile, resolved_hardware) for profile in list_model_profiles()]
    return sorted(recommendations, key=_recommendation_sort_key)


def build_model_doctor_report(model: str, hardware: SystemHardwareSnapshot | None = None) -> ModelDoctorReport:
    """
    诊断单个模型在当前机器上的可运行条件。

    核心入参:
        model: 模型名或本地 bundle 路径。
        hardware: 可选硬件快照；为空时自动探测本机。

    预期输出:
        返回单模型诊断报告，包含推荐设备和风险说明。

    边界异常:
        未知模型不会抛异常，而是返回 profile_found=False 的诊断结果。
    """

    resolved_hardware = hardware or detect_system_hardware()
    profile = resolve_model_profile(model)
    if profile is None:
        return ModelDoctorReport(
            requested_model=model,
            profile=None,
            hardware=resolved_hardware,
            status="unknown_model",
            recommended_device=None,
            reasons=(
                "当前模型未在内置模型注册表中声明，无法给出可靠的硬件建议。",
                "如这是自定义 bundle，请先补充 manifest.model 并为该模型添加 ModelProfile。",
            ),
        )

    recommendation = _assess_model_support(profile, resolved_hardware)
    return ModelDoctorReport(
        requested_model=model,
        profile=profile,
        hardware=resolved_hardware,
        status=recommendation.status,
        recommended_device=recommendation.recommended_device,
        reasons=recommendation.reasons,
    )


def _assess_model_support(profile: ModelProfile, hardware: SystemHardwareSnapshot) -> ModelRecommendation:
    """
    评估单个模型在当前机器上的硬件适配情况。

    核心入参:
        profile: 目标模型注册表项。
        hardware: 当前机器硬件快照。

    预期输出:
        返回模型推荐结果，包含状态、推荐设备和原因列表。

    边界异常:
        不抛异常；信息不足时返回 unknown 或 cpu_fallback 等保守结果。
    """

    reasons: list[str] = []
    minimum_ram_bytes = _gib_to_bytes(profile.hardware.min_ram_gb)
    minimum_vram_mib = _gib_to_mib(profile.hardware.min_vram_gb)
    recommended_vram_mib = _gib_to_mib(profile.hardware.recommended_vram_gb)

    # 先评估系统内存，避免显存符合但总内存明显不够时仍给出过于乐观的建议。
    if minimum_ram_bytes is not None:
        if hardware.total_ram_bytes is None:
            reasons.append(f"未检测到系统总内存，无法确认是否满足至少 {profile.hardware.min_ram_gb} GiB 的内存要求。")
        elif hardware.total_ram_bytes >= minimum_ram_bytes:
            reasons.append(
                f"系统内存约 {hardware.total_ram_gib:.1f} GiB，满足模型至少 {profile.hardware.min_ram_gb} GiB 的内存要求。"
            )
        else:
            reasons.append(
                f"系统内存约 {hardware.total_ram_gib:.1f} GiB，低于模型至少 {profile.hardware.min_ram_gb} GiB 的内存要求。"
            )
            return ModelRecommendation(
                profile=profile,
                status="insufficient",
                recommended_device=None,
                reasons=tuple(reasons),
            )

    # 其次评估 GPU 显存；这是本项目当前做出实时播报推荐时最重要的硬件维度。
    gpu_for_recommended = hardware.best_gpu(minimum_vram_mib=recommended_vram_mib)
    if gpu_for_recommended is not None and recommended_vram_mib is not None:
        reasons.append(
            f"检测到 GPU {gpu_for_recommended.index}（{gpu_for_recommended.name}）显存约 "
            f"{_mib_to_gib(gpu_for_recommended.total_vram_mib):.1f} GiB，满足推荐显存 {profile.hardware.recommended_vram_gb} GiB。"
        )
        return ModelRecommendation(
            profile=profile,
            status="recommended",
            recommended_device=f"gpu:{gpu_for_recommended.index}",
            reasons=tuple(reasons),
        )

    gpu_for_minimum = hardware.best_gpu(minimum_vram_mib=minimum_vram_mib)
    if gpu_for_minimum is not None and minimum_vram_mib is not None:
        reasons.append(
            f"检测到 GPU {gpu_for_minimum.index}（{gpu_for_minimum.name}）显存约 "
            f"{_mib_to_gib(gpu_for_minimum.total_vram_mib):.1f} GiB，达到最低显存 {profile.hardware.min_vram_gb} GiB，"
            "但还没有达到推荐显存。"
        )
        return ModelRecommendation(
            profile=profile,
            status="supported",
            recommended_device=f"gpu:{gpu_for_minimum.index}",
            reasons=tuple(reasons),
        )

    # 当 GPU 条件不满足时，仍保留 CPU 回退结论，但明确标注这不保证实时性。
    if hardware.gpus:
        reasons.append(
            f"当前可见 GPU 最大显存约 {hardware.max_vram_gib:.1f} GiB，尚未达到模型最低显存 "
            f"{profile.hardware.min_vram_gb} GiB。"
        )
    else:
        reasons.append("未检测到 NVIDIA GPU，无法给出 GPU 启动建议。")

    if minimum_ram_bytes is not None and hardware.total_ram_bytes is not None and hardware.total_ram_bytes >= minimum_ram_bytes:
        reasons.append("系统内存满足最低要求；如果必须启动，可以显式使用 --device cpu，但实时性和吞吐都可能较差。")
        return ModelRecommendation(
            profile=profile,
            status="cpu_fallback",
            recommended_device="cpu",
            reasons=tuple(reasons),
        )

    if minimum_ram_bytes is not None and hardware.total_ram_bytes is None:
        reasons.append("由于系统内存未知，当前只能给出保守的手工确认结论。")
        return ModelRecommendation(
            profile=profile,
            status="unknown",
            recommended_device=None,
            reasons=tuple(reasons),
        )

    return ModelRecommendation(
        profile=profile,
        status="insufficient",
        recommended_device=None,
        reasons=tuple(reasons),
    )


def _recommendation_sort_key(recommendation: ModelRecommendation) -> tuple[int, int, str]:
    """
    为模型推荐结果生成排序键。

    核心入参:
        recommendation: 单个模型推荐结果。

    预期输出:
        返回一个三元组，用于按可运行性优先、再按资源更稳妥的顺序排序。

    边界异常:
        不抛异常。
    """

    status_rank = {
        "recommended": 4,
        "supported": 3,
        "cpu_fallback": 2,
        "unknown": 1,
        "insufficient": 0,
    }
    hardware_rank = recommendation.profile.hardware.recommended_vram_gb or recommendation.profile.hardware.min_vram_gb or 0
    return (-status_rank.get(recommendation.status, -1), hardware_rank, recommendation.profile.name)


def _detect_total_ram_bytes() -> int | None:
    """
    探测系统总内存。

    核心入参:
        本方法无入参。

    预期输出:
        成功时返回总内存字节数；失败时返回 None。

    边界异常:
        不抛异常。
    """

    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        phys_pages = int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, TypeError, ValueError):
        page_size = 0
        phys_pages = 0

    if page_size > 0 and phys_pages > 0:
        return page_size * phys_pages

    # sysconf 不可用时再退回 /proc/meminfo，兼容更多最小环境。
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if not line.startswith("MemTotal:"):
                continue
            fields = line.split()
            if len(fields) >= 2:
                return int(fields[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def _detect_nvidia_gpus(
    *,
    command_runner: Callable[[list[str]], tuple[int, str, str]],
) -> tuple[list[DetectedGpuInfo], list[str]]:
    """
    通过 nvidia-smi 探测 NVIDIA GPU。

    核心入参:
        command_runner: 命令执行器，返回退出码、stdout 和 stderr。

    预期输出:
        返回 GPU 列表和告警列表。

    边界异常:
        不抛异常；解析失败时返回空列表并附带告警。
    """

    exit_code, stdout, stderr = command_runner(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    if exit_code != 0:
        message = stderr.strip()
        if message:
            return [], [f"GPU 探测跳过：nvidia-smi 不可用或执行失败（{message}）。"]
        return [], []

    gpus: list[DetectedGpuInfo] = []
    warnings: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split(",", 2)]
        if len(fields) != 3:
            warnings.append(f"GPU 探测返回了无法解析的行：{line}")
            continue
        try:
            gpu_index = int(fields[0])
            total_vram_mib = int(float(fields[2]))
        except ValueError:
            warnings.append(f"GPU 探测返回了非法显存数值：{line}")
            continue
        gpus.append(
            DetectedGpuInfo(
                index=gpu_index,
                name=fields[1],
                total_vram_mib=total_vram_mib,
            )
        )
    return gpus, warnings


def _run_command(argv: list[str]) -> tuple[int, str, str]:
    """
    执行一个本地命令并返回退出码与文本输出。

    核心入参:
        argv: 命令及参数数组。

    预期输出:
        返回 exit_code、stdout、stderr。

    边界异常:
        命令不存在或无法执行时不抛异常，而是返回 127 和错误信息。
    """

    try:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True)
    except OSError as exc:
        return 127, "", str(exc)
    return completed.returncode, completed.stdout, completed.stderr


def _normalize_mode_name(model_name: str, raw_mode: object) -> str:
    """
    把模型 mode 统一规范化成注册表使用的标准名称。

    核心入参:
        model_name: 当前模型名。
        raw_mode: 调用方传入的原始 mode 值。

    预期输出:
        返回标准化后的 mode 名称，例如 `text` 或 `continuation`。

    边界异常:
        未命中的值会原样转成小写字符串返回，由上层决定是否接受。
    """

    normalized = str(raw_mode).strip().lower()
    if model_name == "voxcpm2-gguf":
        aliases = {
            "0": "text",
            "1": "ref",
            "2": "continuation",
            "3": "ref_continuation",
        }
        return aliases.get(normalized, normalized)
    return normalized


def _validate_sampling_parameter(param_name: str, value: object) -> None:
    """
    校验公开采样参数的基础类型和值域。

    核心入参:
        param_name: 参数名，当前支持 `temperature`、`top_p`、`top_k`。
        value: 调用方传入的参数值。

    预期输出:
        合法时无返回值；非法时抛出 ValueError。

    边界异常:
        本函数只做基础合法性约束，不对不同模型的更细经验区间做二次收紧。
    """

    if isinstance(value, bool):
        raise ValueError(f"{param_name} must not be a boolean")

    if param_name == "top_k":
        if not isinstance(value, int) or value <= 0:
            raise ValueError("top_k must be a positive integer")
        return

    if not isinstance(value, (int, float)):
        raise ValueError(f"{param_name} must be a positive number")

    numeric_value = float(value)
    if param_name == "temperature":
        if numeric_value <= 0:
            raise ValueError("temperature must be greater than 0")
        return

    if param_name == "top_p" and not (0 < numeric_value <= 1):
        raise ValueError("top_p must be in the range (0, 1]")


def _validate_boolean_parameter(param_name: str, value: object) -> None:
    """
    校验公开布尔参数。

    核心入参:
        param_name: 参数名。
        value: 待校验值。

    预期输出:
        合法时无返回值。

    边界异常:
        不是布尔值时抛出 ValueError。
    """

    if not isinstance(value, bool):
        raise ValueError(f"{param_name} must be a boolean")


def _validate_positive_integer_parameter(param_name: str, value: object) -> None:
    """
    校验公开正整数参数。

    核心入参:
        param_name: 参数名。
        value: 待校验值。

    预期输出:
        合法时无返回值。

    边界异常:
        不是正整数时抛出 ValueError。
    """

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{param_name} must be a positive integer")


def _bytes_to_gib(value: int | None) -> float | None:
    """
    把字节数转换成一位小数的 GiB。

    核心入参:
        value: 字节数。

    预期输出:
        返回 GiB 浮点数；为空时返回 None。

    边界异常:
        不抛异常。
    """

    if value is None:
        return None
    return round(value / _BYTES_PER_GIB, 1)


def _mib_to_gib(value: int | None) -> float | None:
    """
    把 MiB 转换成一位小数的 GiB。

    核心入参:
        value: MiB 数值。

    预期输出:
        返回 GiB 浮点数；为空时返回 None。

    边界异常:
        不抛异常。
    """

    if value is None:
        return None
    return round(value / _MIB_PER_GIB, 1)


def _gib_to_bytes(value: int | None) -> int | None:
    """
    把 GiB 整数阈值转换成字节数。

    核心入参:
        value: GiB 阈值。

    预期输出:
        返回字节数；为空时返回 None。

    边界异常:
        不抛异常。
    """

    if value is None:
        return None
    return value * _BYTES_PER_GIB


def _gib_to_mib(value: int | None) -> int | None:
    """
    把 GiB 整数阈值转换成 MiB。

    核心入参:
        value: GiB 阈值。

    预期输出:
        返回 MiB 数值；为空时返回 None。

    边界异常:
        不抛异常。
    """

    if value is None:
        return None
    return value * _MIB_PER_GIB


def _load_manifest_model(model: str) -> str | None:
    """
    从本地 bundle 目录的 manifest.json 中读取模型名。

    核心入参:
        model: 可能是本地 bundle 路径的字符串。

    预期输出:
        成功时返回 manifest 中的 model 字段；失败时返回 None。

    边界异常:
        文件不存在、JSON 非法或字段类型不对时都吞掉异常并返回 None。
    """

    manifest_path = Path(model) / "manifest.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None

    model_name = data.get("model")
    if isinstance(model_name, str):
        return model_name
    return None
