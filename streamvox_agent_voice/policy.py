"""高层语音策略 API 的意图映射。"""

from __future__ import annotations

from dataclasses import dataclass


# 关键常量：高层意图名称是 Agent 日常应该接触的小集合，避免调用方直接操纵底层 action。
HIGH_LEVEL_POLICY_NAMES = frozenset({"info", "progress", "warning", "urgent", "done"})


@dataclass(frozen=True, slots=True)
class VoicePolicy:
    """
    高层语音意图到 Runtime 底层事件协议的确定性映射。

    核心入参:
        event: Runtime 语义事件标签，用于日志、状态和未来 UI 展示。
        action: Runtime 显式队列控制动作，决定当前播报是否入队、替换、清队或打断。
        interrupt: 兼容旧协议的显式打断布尔值，urgent 需要同时置位以确保旧调用链一致。

    预期输出:
        VoiceClient 可直接把本对象字段传给 VoiceEvent，形成稳定 HTTP payload。

    边界异常:
        本数据类不主动校验字段；字段来源由模块内固定映射保证。
    """

    event: str
    action: str
    interrupt: bool = False

    def to_event_kwargs(self) -> dict[str, str | bool]:
        """
        转换为 VoiceClient.say 可直接使用的事件字段。

        核心入参:
            本方法不接收额外参数，直接读取当前策略字段。

        预期输出:
            返回 event/action/interrupt 三个底层协议字段。

        边界异常:
            不抛异常；调用方仍会通过 VoiceEvent.validate 做最终协议校验。
        """

        return {
            "event": self.event,
            "action": self.action,
            "interrupt": self.interrupt,
        }


# 关键常量：默认策略映射只在这里维护，避免 CLI 和 Python Client 各自复制一份规则后漂移。
DEFAULT_VOICE_POLICIES: dict[str, VoicePolicy] = {
    # 普通信息只做顺序入队，业务意图是保留说明性播报的完整顺序。
    "info": VoicePolicy(event="progress", action="enqueue"),

    # 进度播报允许覆盖尚未播放的旧 progress，业务意图是避免用户听到过期过程。
    "progress": VoicePolicy(event="progress", action="replace_pending"),

    # warning 用于提醒用户关注新的风险或注意点，业务意图是清理过期进度后优先播报提醒，但不强制打断当前播放。
    "warning": VoicePolicy(event="warning", action="clear_pending_then_enqueue"),

    # 紧急播报必须立即打断，业务意图是让错误或风险信息不要滞后于普通队列。
    "urgent": VoicePolicy(event="error", action="interrupt", interrupt=True),

    # 完成播报清理旧待播内容再收尾，业务意图是让最终结果优先于过期进度。
    "done": VoicePolicy(event="done", action="clear_pending_then_enqueue"),
}


def resolve_voice_policy(name: str) -> VoicePolicy:
    """
    根据高层意图名称解析默认语音策略。

    核心入参:
        name: 高层意图名称，当前支持 info/progress/warning/urgent/done。

    预期输出:
        返回对应 VoicePolicy，供 Client 或 CLI 组装底层事件。

    边界异常:
        name 不在公开集合中时抛出 ValueError，避免未知意图被静默降级成普通播报。
    """

    # 策略名称必须先规范化，业务意图是让 CLI 或 SDK 传入的大小写差异不影响固定映射。
    normalized_name = name.strip().lower()
    if normalized_name not in DEFAULT_VOICE_POLICIES:
        raise ValueError(f"unsupported high-level voice policy: {name}")
    return DEFAULT_VOICE_POLICIES[normalized_name]
