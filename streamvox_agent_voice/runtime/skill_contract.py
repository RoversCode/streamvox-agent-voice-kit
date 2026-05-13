"""Runtime 面向基础 Skill 的稳定协商载荷。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..policy import HIGH_LEVEL_POLICY_NAMES
from .config import RuntimeConfig
from .model_registry import resolve_model_profile


# 关键常量：skill-facing 协议版本单独维护，避免未来 `/skill/describe` 扩展时和普通 Runtime 版本混淆。
SKILL_CONTRACT_VERSION = "v1"

# 关键常量：当前 Runtime CLI 版本与 FastAPI app 版本保持一致，skill 只读这个稳定版本号。
RUNTIME_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class ModelCapabilitiesPayload:
    """
    描述当前模型对基础 Skill 最关键的事实能力。

    核心入参:
        supports_default_role: 是否支持 Runtime 默认音色。
        supports_roles: 是否支持持久化 role 使用。
        supports_sub_language_style_control: 是否支持副语言或风格控制增强。
        style_expression_mode: 当前模型表达风格的方式。
        supported_modes: 当前模型对宿主有意义的模式集合。

    预期输出:
        `to_payload()` 返回稳定 JSON 字典。

    边界异常:
        不抛异常。
    """

    supports_default_role: bool
    supports_roles: bool
    supports_sub_language_style_control: bool
    style_expression_mode: str
    supported_modes: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """
        转换为公开 JSON。

        核心入参:
            本方法无入参。

        预期输出:
            返回模型能力字典。

        边界异常:
            不抛异常。
        """

        return {
            "supports_default_role": self.supports_default_role,
            "supports_roles": self.supports_roles,
            "supports_sub_language_style_control": self.supports_sub_language_style_control,
            "style_expression_mode": self.style_expression_mode,
            "supported_modes": list(self.supported_modes),
        }


@dataclass(frozen=True, slots=True)
class RolesCapabilitiesPayload:
    """
    描述 Runtime 对 role 资产公开的高层能力。

    核心入参:
        list: 是否支持列出角色。
        read_default: 是否支持读取默认角色。
        set_default: 是否支持切换默认角色。
        register: 是否支持注册角色。
        delete: 是否支持删除角色。

    预期输出:
        `to_payload()` 返回稳定 JSON。

    边界异常:
        不抛异常。
    """

    list: bool
    read_default: bool
    set_default: bool
    register: bool
    delete: bool

    def to_payload(self) -> dict[str, bool]:
        """
        转换为公开 JSON。

        核心入参:
            本方法无入参。

        预期输出:
            返回角色能力字典。

        边界异常:
            不抛异常。
        """

        return {
            "list": self.list,
            "read_default": self.read_default,
            "set_default": self.set_default,
            "register": self.register,
            "delete": self.delete,
        }


def build_skill_fingerprint(*, model_name: str, default_role_name: str | None) -> str:
    """
    构造基础 Skill 用的最小指纹。

    核心入参:
        model_name: 当前加载模型标识。
        default_role_name: 当前默认音色名，可为空。

    预期输出:
        返回一个稳定 sha256 十六进制字符串。

    边界异常:
        不抛异常；缺失默认角色时会以空字符串参与指纹计算。
    """

    fingerprint_source = f"{model_name}\0{default_role_name or ''}".encode("utf-8")
    return hashlib.sha256(fingerprint_source).hexdigest()


def build_skill_describe_payload(
    config: RuntimeConfig,
    *,
    available_role_names: list[str],
) -> dict[str, Any]:
    """
    构造 `/skill/describe` 返回的稳定聚合载荷。

    核心入参:
        config: 当前 Runtime 配置。
        available_role_names: 当前模型缓存中的全部角色名。

    预期输出:
        返回基础 Skill 初始化所需的完整事实快照。

    边界异常:
        未注册模型时会返回降级能力摘要，但不会抛异常。
    """

    model_name = config.model
    default_role_name = config.default_role_name
    fingerprint = build_skill_fingerprint(model_name=model_name, default_role_name=default_role_name)

    return {
        "fingerprint": fingerprint,
        "runtime": {
            "version": RUNTIME_VERSION,
            "skill_contract_version": SKILL_CONTRACT_VERSION,
            "public_commands": _build_runtime_public_commands(),
            "stream_kwargs": dict(config.stream_kwargs or {}),
        },
        "model": {
            "name": model_name,
            "capabilities": build_model_capabilities(config).to_payload(),
        },
        "roles": {
            "default_role_name": default_role_name,
            "available_role_names": sorted(available_role_names),
            "capabilities": build_roles_capabilities(config).to_payload(),
        },
    }


def build_skill_fingerprint_payload(config: RuntimeConfig) -> dict[str, str]:
    """
    构造 `/skill/fingerprint` 返回的最小 JSON。

    核心入参:
        config: 当前 Runtime 配置。

    预期输出:
        返回只包含 `fingerprint` 的字典。

    边界异常:
        不抛异常。
    """

    return {
        "fingerprint": build_skill_fingerprint(
            model_name=config.model,
            default_role_name=config.default_role_name,
        )
    }


def build_model_capabilities(config: RuntimeConfig) -> ModelCapabilitiesPayload:
    """
    构造面向基础 Skill 的模型能力摘要。

    核心入参:
        config: 当前 Runtime 配置。

    预期输出:
        返回当前模型的关键事实能力。

    边界异常:
        未知模型时返回保守降级能力，而不是抛异常。
    """

    profile = resolve_model_profile(config.model)
    if profile is None:
        return ModelCapabilitiesPayload(
            supports_default_role=bool(config.default_role_name),
            supports_roles=False,
            supports_sub_language_style_control=False,
            style_expression_mode="unknown",
            supported_modes=(),
        )

    supports_sub_language_style_control = profile.name in {"s2-pro-4b-gguf", "voxcpm2-gguf"}
    style_expression_mode = "text_only"
    supported_modes: tuple[str, ...] = ()

    if profile.name.startswith("qwen3-tts-clone"):
        style_expression_mode = "text_only"
    elif profile.name == "s2-pro-4b-gguf":
        style_expression_mode = "freeform_style_description"
    elif profile.name == "voxcpm2-gguf":
        style_expression_mode = "limited_style_language"
        supported_modes = ("2",)

    return ModelCapabilitiesPayload(
        supports_default_role=profile.prompt.default_role_supported,
        supports_roles=profile.prompt.persist_role,
        supports_sub_language_style_control=supports_sub_language_style_control,
        style_expression_mode=style_expression_mode,
        supported_modes=supported_modes,
    )


def build_roles_capabilities(config: RuntimeConfig) -> RolesCapabilitiesPayload:
    """
    构造面向基础 Skill 的 role 能力摘要。

    核心入参:
        config: 当前 Runtime 配置。

    预期输出:
        返回角色系统高层能力字典。

    边界异常:
        未知模型时返回保守降级能力，而不是抛异常。
    """

    profile = resolve_model_profile(config.model)
    if profile is None:
        return RolesCapabilitiesPayload(
            list=True,
            read_default=True,
            set_default=False,
            register=False,
            delete=False,
        )

    return RolesCapabilitiesPayload(
        list=True,
        read_default=True,
        set_default=profile.prompt.default_role_supported,
        register=profile.prompt.persist_role,
        delete=profile.prompt.persist_role,
    )


def _build_runtime_public_commands() -> dict[str, Any]:
    """
    构造 Runtime 对基础 Skill 公开的高层命令面。

    核心入参:
        本方法无入参。

    预期输出:
        返回 describe/fingerprint/say 三类命令的能力摘要。

    边界异常:
        不抛异常。
    """

    return {
        "describe": {
            "supported": True,
            "command": "streamvox-runtime describe --json",
        },
        "fingerprint": {
            "supported": True,
            "command": "streamvox-runtime fingerprint",
        },
        "say": {
            "supported": True,
            "command": "streamvox-say",
            "supported_intents": sorted(HIGH_LEVEL_POLICY_NAMES),
            "supports_role_name": True,
            "supports_streamvox_json": True,
            "supports_wait": True,
        },
    }
