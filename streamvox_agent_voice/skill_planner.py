"""基础 Skill 的最小播报规划器。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .skill_catalog import builtin_style_ids, resolve_style_template
from .skill_models import SessionSnapshot, SpeakPlan, StyleTemplate, VoiceProfile


# 关键常量：这些任务语境是第一版默认允许发声的高价值节点。
_SPEAKABLE_CONTEXT_KINDS = frozenset(
    {
        "long_task_started",
        "phase_changed",
        "risk_detected",
        "blocking_failure",
        "task_finished",
    }
)


def should_speak_for_context(profile: VoiceProfile, context: dict[str, Any]) -> bool:
    """
    根据基础规则判断当前任务语境是否应该播报。

    核心入参:
        profile: 当前用户配置。
        context: 宿主整理出的任务语境字典，通常至少包含 `kind`。

    预期输出:
        返回是否应进入 SpeakPlan 生成阶段。

    边界异常:
        上层传入无效 profile 时会抛出 ValueError。
    """

    profile.validate(known_style_ids=builtin_style_ids())
    if not profile.voice_enabled:
        return False

    kind = str(context.get("kind", "")).strip().lower()
    if not kind:
        return False
    if context.get("fine_grained_step", False):
        return False
    return kind in _SPEAKABLE_CONTEXT_KINDS


def resolve_model_style_expression(style: StyleTemplate, model_name: str) -> dict[str, Any]:
    """
    解析当前 style 在指定模型下的表达预设。

    核心入参:
        style: 当前激活的 StyleTemplate。
        model_name: 当前 Runtime 模型标识。

    预期输出:
        返回该模型下的表达预设；未命中时回退到 `default` 或空字典。

    边界异常:
        不抛异常；未知模型统一回退为空预设，避免宿主侧因此失去风格文案能力。
    """

    if model_name in style.model_presets:
        return deepcopy(style.model_presets[model_name])

    if model_name.startswith("qwen3-tts-clone"):
        return deepcopy(style.model_presets.get("qwen3-family", {}))
    if model_name.startswith("s2-pro"):
        return deepcopy(style.model_presets.get("s2-pro-family", {}))
    if model_name.startswith("voxcpm2"):
        return deepcopy(style.model_presets.get("voxcpm2-family", {}))
    return deepcopy(style.model_presets.get("default", {}))


def build_speak_plan(
    profile: VoiceProfile,
    session_snapshot: SessionSnapshot,
    *,
    intent: str,
    neutral_semantics: dict[str, Any],
    should_speak: bool = True,
    requested_role_name: str | None = None,
) -> SpeakPlan:
    """
    按基础 Skill 的固定规则生成一次播报计划。

    核心入参:
        profile: 当前用户配置。
        session_snapshot: 最近一次 Runtime 同步快照。
        intent: 高层播报意图。
        neutral_semantics: 中性语义骨架。
        should_speak: 调用方外层是否已经判定应播报。
        requested_role_name: 调用方想显式覆盖的角色名。

    预期输出:
        返回一个已完成文本渲染和模型参数适配的 SpeakPlan。

    边界异常:
        profile/session_snapshot 非法时抛出 ValueError；style 不存在时抛出 KeyError。
    """

    profile.validate(known_style_ids=builtin_style_ids())
    session_snapshot.validate()

    style = resolve_style_template(profile.active_style_id)
    resolved_role_name = _resolve_role_override(profile, requested_role_name, session_snapshot)
    rendered_text = _render_style_text(style, profile, neutral_semantics)
    streamvox = _build_streamvox_payload(
        style,
        profile,
        session_snapshot,
        resolved_role_name=resolved_role_name,
    )

    plan = SpeakPlan(
        should_speak=should_speak and profile.voice_enabled,
        intent=intent,
        neutral_semantics=dict(neutral_semantics),
        rendered_text=rendered_text,
        role_name=resolved_role_name,
        streamvox=streamvox,
        style_id=style.style_id,
    )
    plan.validate()
    return plan


def _resolve_role_override(
    profile: VoiceProfile,
    requested_role_name: str | None,
    session_snapshot: SessionSnapshot,
) -> str | None:
    """
    解析本次播报是否需要显式覆盖 Runtime 默认音色。

    核心入参:
        profile: 当前用户配置。
        requested_role_name: 调用方显式传入的角色名。
        session_snapshot: 最近一次 Runtime 快照。

    预期输出:
        默认返回 None，表示继续使用 Runtime 默认音色；只有明确允许且角色存在时才返回显式角色名。

    边界异常:
        角色不存在时抛出 ValueError。
    """

    if requested_role_name is None or not profile.allow_role_override:
        return None

    normalized_role_name = requested_role_name.strip()
    if not normalized_role_name:
        raise ValueError("requested_role_name must be a non-empty string when provided")
    if normalized_role_name not in session_snapshot.available_role_names:
        raise ValueError(f"requested role is not available in current session snapshot: {normalized_role_name}")
    return normalized_role_name


def _build_streamvox_payload(
    style: StyleTemplate,
    profile: VoiceProfile,
    session_snapshot: SessionSnapshot,
    *,
    resolved_role_name: str | None,
) -> dict[str, Any]:
    """
    根据模型能力与当前风格生成最终 `streamvox` 参数。

    核心入参:
        style: 当前风格模板。
        profile: 当前用户配置。
        session_snapshot: Runtime 快照。
        resolved_role_name: 事件级角色覆盖结果。

    预期输出:
        返回可安全传给 Runtime 的模型私有参数字典。

    边界异常:
        当前实现只做能力感知降级，不抛异常；无法安全表达时返回空字典。
    """

    if not profile.allow_model_style_params:
        return {}

    model_expression = resolve_model_style_expression(style, session_snapshot.model_name)
    raw_streamvox = model_expression.get("streamvox", {})
    if not isinstance(raw_streamvox, dict):
        return {}

    # 对 qwen3 这类不支持副语言风格控制的模型，风格只体现在文本里，因此直接返回空参数。
    if session_snapshot.model_name.startswith("qwen3-tts-clone"):
        return {}

    if session_snapshot.model_name == "voxcpm2-gguf":
        # VoxCPM2 在这里统一走 mode=2；若没有默认角色且也没有事件级覆盖，则不能强塞该模式。
        effective_role_name = resolved_role_name or session_snapshot.default_role_name
        if effective_role_name is None:
            return {}
        return dict(raw_streamvox)

    # S2-Pro 当前不通过 Runtime 公开稳定私有参数口径，风格描述仅保留在模板层供宿主使用。
    if session_snapshot.model_name.startswith("s2-pro"):
        return {}

    return dict(raw_streamvox)


def _render_style_text(style: StyleTemplate, profile: VoiceProfile, neutral_semantics: dict[str, Any]) -> str:
    """
    把中性语义骨架渲染为风格化播报文本。

    核心入参:
        style: 当前风格模板。
        profile: 当前用户配置。
        neutral_semantics: 中性语义骨架。

    预期输出:
        返回一句以当前风格表达的播报文本。

    边界异常:
        缺失常见语义字段时会自动回退到 `summary`，避免风格层把主任务阻塞。
    """

    base_message = _neutral_summary(neutral_semantics)
    user_address = profile.user_address.strip() or style.default_user_address
    self_reference = profile.self_reference.strip() or style.default_self_reference

    style_id = style.style_id
    if style_id == "professional_assistant":
        return f"{base_message}"
    if style_id == "earnest_gentle":
        return f"{user_address}，{self_reference}已经把这一步处理好了，现在正在继续推进。{base_message}"
    if style_id == "strict_teacher":
        return f"{user_address}，注意：{base_message}"
    if style_id == "laid_back_expert":
        return f"{base_message}，剩下的我继续收尾。"
    if style_id == "ancient_swordsman":
        return f"{user_address}，此间脉络{self_reference}已探明大半。{base_message}"
    if style_id == "seductive_diva":
        return f"{user_address}，别急嘛，{self_reference}已经替你把这一段理顺了。{base_message}"
    if style_id == "green_tea_girl":
        return f"{user_address}，{self_reference}已经很认真地把这一步做好啦。{base_message}"
    if style_id == "hotheaded_bro":
        return f"{base_message}，这活我还在接着啃。"
    if style_id == "extreme_chuunibyou":
        return f"{user_address}，此刻的命运回路已被{self_reference}逐步拆解。{base_message}"
    return base_message


def _neutral_summary(neutral_semantics: dict[str, Any]) -> str:
    """
    把宿主传入的中性语义骨架压成一句基础摘要。

    核心入参:
        neutral_semantics: 宿主整理后的事实语义。

    预期输出:
        返回一句中性、结果优先的中文摘要。

    边界异常:
        常见字段都缺失时回退到 `summary` 或通用占位句，保证风格层仍能工作。
    """

    completed = str(neutral_semantics.get("completed", "")).strip()
    current_action = str(neutral_semantics.get("current_action", "")).strip()
    risk = str(neutral_semantics.get("risk", "")).strip()
    summary = str(neutral_semantics.get("summary", "")).strip()

    if completed and current_action:
        return f"{completed}已经完成，现在正在{current_action}。"
    if risk:
        return f"我发现了一个需要注意的风险：{risk}。"
    if summary:
        return summary if summary.endswith(("。", "！", "？")) else f"{summary}。"
    if completed:
        return f"{completed}已经完成。"
    if current_action:
        return f"我正在{current_action}。"
    return "我正在继续处理当前任务。"
