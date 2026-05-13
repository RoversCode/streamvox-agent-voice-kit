"""基础 Skill 公开类型。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .policy import HIGH_LEVEL_POLICY_NAMES


# 关键常量：第一版只公开三档人格张力，避免宿主侧写出无法解释的自由值。
PERSONA_INTENSITIES = frozenset({"subtle", "standard", "high"})

# 关键常量：播报频率只保留三档，便于宿主把它稳定映射成自己的节流策略。
SPEAK_FREQUENCIES = frozenset({"conservative", "standard", "active"})


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """
    描述宿主 Skill 当前生效的用户配置。

    核心入参:
        active_style_id: 当前全局唯一激活的内置风格标识。
        user_address: 当前对用户的默认称呼。
        self_reference: 当前自称。
        persona_intensity: 风格强度档位。
        voice_enabled: 当前是否允许播报。
        speak_frequency: 播报频率偏好。
        allow_role_override: 是否允许 Skill 在必要时覆盖 Runtime 默认音色。
        allow_model_style_params: 是否允许 Skill 输出模型风格参数。

    预期输出:
        `to_payload()` 返回可直接持久化到宿主 Skill 目录的稳定 JSON 字典。

    边界异常:
        `validate()` 会在风格档位或风格 id 非法时抛出 ValueError。
    """

    active_style_id: str
    user_address: str
    self_reference: str
    persona_intensity: str = "standard"
    voice_enabled: bool = True
    speak_frequency: str = "standard"
    allow_role_override: bool = True
    allow_model_style_params: bool = True

    def validate(self, *, known_style_ids: set[str] | None = None) -> None:
        """
        校验当前 VoiceProfile 是否满足基础 Skill 第一版约束。

        核心入参:
            known_style_ids: 可选的内置 style id 集合；传入后会进一步校验 `active_style_id` 是否属于内置模板。

        预期输出:
            合法时无返回值。

        边界异常:
            关键字段为空、档位不受支持或 style 不存在时抛出 ValueError。
        """

        if not isinstance(self.active_style_id, str) or not self.active_style_id.strip():
            raise ValueError("active_style_id must be a non-empty string")
        if known_style_ids is not None and self.active_style_id not in known_style_ids:
            raise ValueError(f"unsupported active_style_id: {self.active_style_id}")
        if not isinstance(self.user_address, str) or not self.user_address.strip():
            raise ValueError("user_address must be a non-empty string")
        if not isinstance(self.self_reference, str) or not self.self_reference.strip():
            raise ValueError("self_reference must be a non-empty string")
        if self.persona_intensity not in PERSONA_INTENSITIES:
            raise ValueError(f"unsupported persona_intensity: {self.persona_intensity}")
        if self.speak_frequency not in SPEAK_FREQUENCIES:
            raise ValueError(f"unsupported speak_frequency: {self.speak_frequency}")

    def to_payload(self) -> dict[str, Any]:
        """
        转换为稳定公开 JSON。

        核心入参:
            本方法无入参。

        预期输出:
            返回可供宿主 Skill 持久化的字典。

        边界异常:
            不抛异常。
        """

        return {
            "active_style_id": self.active_style_id,
            "user_address": self.user_address,
            "self_reference": self.self_reference,
            "persona_intensity": self.persona_intensity,
            "voice_enabled": self.voice_enabled,
            "speak_frequency": self.speak_frequency,
            "allow_role_override": self.allow_role_override,
            "allow_model_style_params": self.allow_model_style_params,
        }


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """
    描述宿主最近一次从 Runtime 同步下来的事实状态。

    核心入参:
        fingerprint: 当前 Runtime 指纹。
        model_name: 当前加载的模型标识。
        default_role_name: 当前 Runtime 默认音色。
        available_role_names: 当前模型下全部已注册音色名。
        model_capabilities: `streamvox-runtime describe --json` 返回的模型能力摘要。

    预期输出:
        `to_payload()` 返回宿主可缓存的稳定字典。

    边界异常:
        `validate()` 会在关键字段缺失时抛出 ValueError。
    """

    fingerprint: str
    model_name: str
    default_role_name: str | None
    available_role_names: tuple[str, ...] = ()
    model_capabilities: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """
        校验当前 SessionSnapshot 的关键字段。

        核心入参:
            本方法无额外入参。

        预期输出:
            合法时无返回值。

        边界异常:
            指纹或模型名为空时抛出 ValueError。
        """

        if not isinstance(self.fingerprint, str) or not self.fingerprint.strip():
            raise ValueError("fingerprint must be a non-empty string")
        if not isinstance(self.model_name, str) or not self.model_name.strip():
            raise ValueError("model_name must be a non-empty string")

    def to_payload(self) -> dict[str, Any]:
        """
        转换为稳定公开 JSON。

        核心入参:
            本方法无入参。

        预期输出:
            返回宿主可直接缓存的会话事实状态。

        边界异常:
            不抛异常。
        """

        return {
            "fingerprint": self.fingerprint,
            "model_name": self.model_name,
            "default_role_name": self.default_role_name,
            "available_role_names": list(self.available_role_names),
            "model_capabilities": dict(self.model_capabilities),
        }


@dataclass(frozen=True, slots=True)
class StyleTemplate:
    """
    描述一个基础 Skill 内置风格模板。

    核心入参:
        style_id: 稳定 style 标识。
        display_name: 面向用户的展示名。
        default_user_address: 默认称呼。
        default_self_reference: 默认自称。
        text_style: 文案口吻规则。
        abstract_style_traits: 抽象风格特征，供不同模型适配。
        model_presets: 按模型分流的表达预设。

    预期输出:
        `to_payload()` 返回可直接暴露给宿主 Skill 的模板字典。

    边界异常:
        本数据类不主动做复杂校验；JSON 资产解析阶段负责保证字段完整。
    """

    style_id: str
    display_name: str
    default_user_address: str
    default_self_reference: str
    text_style: dict[str, Any]
    abstract_style_traits: dict[str, Any]
    model_presets: dict[str, dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        """
        转换为稳定公开 JSON。

        核心入参:
            本方法无入参。

        预期输出:
            返回完整风格模板字典。

        边界异常:
            不抛异常。
        """

        return {
            "style_id": self.style_id,
            "display_name": self.display_name,
            "default_user_address": self.default_user_address,
            "default_self_reference": self.default_self_reference,
            "text_style": dict(self.text_style),
            "abstract_style_traits": dict(self.abstract_style_traits),
            "model_presets": {model_name: deepcopy(preset) for model_name, preset in self.model_presets.items()},
        }


@dataclass(frozen=True, slots=True)
class SpeakPlan:
    """
    描述基础 Skill 规划好的一次播报。

    核心入参:
        should_speak: 当前是否应当真正触发播报。
        intent: 高层语音意图。
        neutral_semantics: 中性语义骨架。
        rendered_text: 渲染后的风格化播报文本。
        role_name: 可选的事件级音色覆盖。
        streamvox: 最终传给 Runtime 的模型私有参数。
        style_id: 当前生效的 style 标识。

    预期输出:
        `to_payload()` 返回宿主可直接转成 CLI 调用参数的字典。

    边界异常:
        `validate()` 会在 should_speak=True 但 intent/text 非法时抛出 ValueError。
    """

    should_speak: bool
    intent: str
    neutral_semantics: dict[str, Any]
    rendered_text: str
    role_name: str | None
    streamvox: dict[str, Any]
    style_id: str

    def validate(self) -> None:
        """
        校验当前 SpeakPlan。

        核心入参:
            本方法无入参。

        预期输出:
            合法时无返回值。

        边界异常:
            高层 intent 非法、需要播报但文本为空时抛出 ValueError。
        """

        if self.intent not in HIGH_LEVEL_POLICY_NAMES:
            raise ValueError(f"unsupported intent: {self.intent}")
        if self.should_speak and (not isinstance(self.rendered_text, str) or not self.rendered_text.strip()):
            raise ValueError("rendered_text must be a non-empty string when should_speak is true")
        if self.role_name is not None and (not isinstance(self.role_name, str) or not self.role_name.strip()):
            raise ValueError("role_name must be a non-empty string when provided")

    def to_payload(self) -> dict[str, Any]:
        """
        转换为稳定公开 JSON。

        核心入参:
            本方法无入参。

        预期输出:
            返回宿主可直接消费的播报计划字典。

        边界异常:
            不抛异常。
        """

        return {
            "should_speak": self.should_speak,
            "intent": self.intent,
            "neutral_semantics": dict(self.neutral_semantics),
            "rendered_text": self.rendered_text,
            "role_name": self.role_name,
            "streamvox": dict(self.streamvox),
            "style_id": self.style_id,
        }
