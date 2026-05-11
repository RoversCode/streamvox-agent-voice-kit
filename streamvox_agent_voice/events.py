"""语音事件协议与校验逻辑。"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4


# 关键常量：公开事件类型必须保持小集合，避免 Agent 随意发明事件导致 Runtime 行为不可预测。
EVENT_TYPES = frozenset({"started", "progress", "warning", "done", "error", "interrupt", "stop"})

# 关键常量：优先级只影响队列处理，不直接泄漏到底层 TTS 引擎。
PRIORITIES = frozenset({"low", "normal", "high"})

# 关键常量：action 是显式控制语义，不能从 event 语义标签隐式推导。
ACTIONS = frozenset({"enqueue", "interrupt", "stop", "replace_pending", "clear_pending_then_enqueue"})


class VoiceEventError(ValueError):
    """
    表示语音事件不符合公开协议。

    核心入参:
        message: 可读错误说明，通常会返回给 CLI 或 HTTP 调用方。

    预期输出:
        异常对象本身不产生业务输出；调用方负责捕获并转换为退出码或 HTTP 状态码。

    边界异常:
        本类不额外包装原始异常，保证错误信息直接可读。
    """


@dataclass(slots=True)
class VoiceEvent:
    """
    Agent 发送给 StreamVox Runtime 的最小语音事件。

    核心入参:
        event: 事件类型，限定为 started/progress/warning/done/error/interrupt/stop。
        text: 需要播报的文本；stop 事件允许为空。
        priority: 队列优先级，限定为 low/normal/high。
        action: 队列控制策略，默认 enqueue。
        interrupt: 是否打断当前播报并清理普通等待队列。
        wait: 发送方是否等待该事件完成。
        metadata: 给未来扩展保留的轻量附加信息。

    预期输出:
        通过 from_mapping 或 validate 构造后，得到可安全进入 Runtime 队列的事件对象。

    边界异常:
        event/priority/text 类型不合法时抛出 VoiceEventError。
    """

    event: str = "progress"
    text: str = ""
    priority: str = "normal"  # TODO: 目前没有相关优先级设计，这里先占位
    action: str = "enqueue"
    interrupt: bool = False
    wait: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex) # 随机id
    created_at: float = field(default_factory=time)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "VoiceEvent":
        """
        从 HTTP JSON 字典构造语音事件。

        核心入参:
            payload: 客户端提交的 JSON 对象。

        预期输出:
            返回已完成协议校验的 VoiceEvent。

        边界异常:
            payload 不是字典，或关键字段类型和值不合法时抛出 VoiceEventError。
        """

        # 先确认最外层形态，避免后续字段读取把非对象输入误当成空事件处理。
        if not isinstance(payload, dict):
            raise VoiceEventError("event payload must be a JSON object")

        # 关键变量：metadata 只允许对象，便于后续安全承载模型参数或 trace 信息。
        metadata = payload.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise VoiceEventError("metadata must be an object")

        # 关键字段：metadata.streamvox 预留给模型私有参数透传，必须保持对象形态。
        streamvox_metadata = metadata.get("streamvox")
        if streamvox_metadata is not None and not isinstance(streamvox_metadata, dict):
            raise VoiceEventError("metadata.streamvox must be an object")

        # 关键字段：role_name 走公开协议时要求是字符串，避免 Runtime 收到不可序列化引用。
        role_name = metadata.get("role_name")
        if role_name is not None:
            if not isinstance(role_name, str):
                raise VoiceEventError("metadata.role_name must be a string")
            if not role_name.strip():
                raise VoiceEventError("metadata.role_name must not be empty")

        event = cls(
            event=str(payload.get("event", "progress")),
            text=str(payload.get("text", "")),
            priority=str(payload.get("priority", "normal")),
            action=str(payload.get("action", "enqueue")),
            interrupt=bool(payload.get("interrupt", False)),
            wait=bool(payload.get("wait", False)),
            metadata=metadata,
        )
        event.validate()
        return event

    def validate(self) -> None:
        """
        校验当前事件是否符合公开协议。

        核心入参:
            本方法不接收额外参数，直接检查当前对象字段。

        预期输出:
            合法事件无返回值；非法事件抛出 VoiceEventError。

        边界异常:
            stop 事件允许 text 为空，其余事件必须提供非空文本。
        """

        # 事件类型必须收敛，避免 Runtime 对未知事件做出错误队列决策。
        if self.event not in EVENT_TYPES:
            raise VoiceEventError(f"unsupported event type: {self.event}")

        # 优先级必须收敛，避免未来扩展队列策略时出现不可比较的优先级。
        if self.priority not in PRIORITIES:
            raise VoiceEventError(f"unsupported priority: {self.priority}")

        # action 是控制行为的唯一扩展点，必须显式收敛，不能让任意字符串进入队列策略。
        if self.action not in ACTIONS:
            raise VoiceEventError(f"unsupported action: {self.action}")

        # stop 事件是控制指令，不需要播报文本；其他事件没有文本就没有语音价值。
        if self.event != "stop" and self.action != "stop" and not self.text.strip():
            raise VoiceEventError("text is required unless event is stop")

    def to_payload(self) -> dict[str, Any]:
        """
        转换成公开 HTTP 事件 JSON。

        核心入参:
            本方法不接收额外参数。

        预期输出:
            返回只包含公开协议字段的字典，不包含 Runtime 内部 id 和时间戳。

        边界异常:
            本方法假设对象已通过 validate；不会重复抛出校验异常。
        """

        return {
            "event": self.event,
            "text": self.text,
            "priority": self.priority,
            "action": self.action,
            "interrupt": self.interrupt,
            "wait": self.wait,
            "metadata": self.metadata,
        }
