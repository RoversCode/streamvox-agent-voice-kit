"""语音事件队列与中断控制。"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from threading import Event
from typing import Any

from ..events import VoiceEvent
from .engine import StreamVoxSpeaker


@dataclass(slots=True)
class QueueResult:
    """
    单条队列事件的处理结果。

    核心入参:
        status: accepted/completed/skipped/failed/stopped 等处理状态。
        event_id: Runtime 内部事件 id。
        detail: 可读细节，常用于错误或跳过原因。

    预期输出:
        to_payload 返回可安全序列化给 HTTP 客户端的字典。

    边界异常:
        本数据类不主动抛出异常。
    """

    status: str
    event_id: str
    detail: str = ""

    def to_payload(self) -> dict[str, str]:
        """
        转换为 HTTP 响应字典。

        核心入参:
            本方法无入参。

        预期输出:
            返回 status/event_id/detail。

        边界异常:
            不抛异常。
        """

        return {"status": self.status, "event_id": self.event_id, "detail": self.detail}


@dataclass(slots=True)
class QueueItem:
    """
    队列内部事件项。

    核心入参:
        event: 已校验的 VoiceEvent。
        future: 等待方用于获取处理结果的 asyncio.Future。

    预期输出:
        被 Runtime worker 消费并完成 future。

    边界异常:
        本类不主动抛出异常。
    """

    event: VoiceEvent
    future: asyncio.Future[QueueResult]
    queued_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class VoiceEventQueue:
    """
    Runtime 内部语音事件队列。

    核心入参:
        speaker: 负责合成和播放的 StreamVoxSpeaker。

    预期输出:
        start 后后台 worker 按 FIFO 消费事件；interrupt/stop 可中断当前播放。

    边界异常:
        speaker.speak 抛出的异常会写入 QueueResult(status="failed")，不会杀死 worker。
    """

    def __init__(self, speaker: StreamVoxSpeaker) -> None:
        # 关键变量：speaker 是队列唯一的业务消费者，便于测试用 fake speaker 替换。
        self.speaker = speaker

        # 关键变量：pending 使用 deque 支持 FIFO 和显式 interrupt 插队。
        self._pending: deque[QueueItem] = deque()

        # 关键变量：condition 负责唤醒后台 worker，避免忙等轮询浪费 CPU。
        self._condition = asyncio.Condition()

        # 关键变量：stop_event 会传入播放线程，stop/interrupt 通过它尽快停止当前流。
        self._stop_event = Event()

        # 关键变量：current 记录当前处理项，status 接口和 stop 逻辑都依赖它。
        self._current: QueueItem | None = None

        # 关键变量：worker_task 是后台消费任务，Runtime 生命周期结束时需要取消。
        self._worker_task: asyncio.Task[None] | None = None

        # 关键变量：closed 防止 shutdown 后继续接收事件。
        self._closed = False

    async def start(self) -> None:
        """
        启动后台队列 worker。

        核心入参:
            本方法无入参。

        预期输出:
            创建一个 asyncio 后台任务消费队列。

        边界异常:
            重复调用不会创建多个 worker。
        """

        if self._worker_task is not None:
            return
        self._worker_task = asyncio.create_task(self._run(), name="streamvox-voice-queue")

    async def enqueue(self, event: VoiceEvent) -> QueueItem:
        """
        将事件放入队列。

        核心入参:
            event: 已校验的 VoiceEvent。

        预期输出:
            返回 QueueItem，调用方可等待 item.future。

        边界异常:
            队列已关闭时抛出 RuntimeError。
        """

        if self._closed:
            raise RuntimeError("voice queue is closed")

        loop = asyncio.get_running_loop()
        item = QueueItem(event=event, future=loop.create_future())

        # 并发情况下，谁先拿到锁先进去，其他并发协程会在这里等待
        async with self._condition:
            # action 是控制语义；旧 interrupt=true 继续兼容为 interrupt action。
            action = self._effective_action(event)
            if action == "interrupt":
                self._stop_event.set()
                self._drop_all_pending("interrupted")
                self._pending.appendleft(item)
            elif action == "stop":
                self._stop_event.set()
                self._drop_all_pending("stopped")
                self._complete(item, QueueResult(status="stopped", event_id=item.event.id, detail="stop action requested"))
            elif action == "replace_pending":
                self._drop_pending_by_intent(event.intent, "replaced")
                self._pending.append(item)
            elif action == "clear_pending_then_enqueue":
                self._drop_all_pending("cleared")
                self._pending.append(item)
            else:  # action是enqueue， 入队。 
                self._pending.append(item)
            self._condition.notify()

        return item

    async def stop_current(self) -> QueueResult:
        """
        停止当前播放并清空普通等待队列。

        核心入参:
            本方法无入参。

        预期输出:
            返回控制事件结果；当前播放的 future 会在 worker 真正停止后完成。

        边界异常:
            队列为空时仍返回 stopped，保持 stop 幂等。
        """

        async with self._condition:
            self._stop_event.set()
            self._drop_all_pending("stopped")
            self._condition.notify()
        return QueueResult(status="stopped", event_id="stop", detail="current playback stop requested")

    async def shutdown(self) -> None:
        """
        关闭队列 worker 并停止当前播放。

        核心入参:
            本方法无入参。

        预期输出:
            后台任务被取消，等待队列被标记 skipped。

        边界异常:
            取消 worker 产生的 CancelledError 会被内部吞掉，保证 FastAPI shutdown 稳定。
        """

        self._closed = True
        self._stop_event.set()
        self._drop_all_pending("runtime shutdown")

        if self._worker_task is None:
            return

        self._worker_task.cancel() # 取消任务
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        self._worker_task = None

    def status(self) -> dict[str, Any]:
        """
        返回队列当前状态。

        核心入参:
            本方法无入参。

        预期输出:
            返回 pending/current/closed 字段。

        边界异常:
            不抛异常。
        """

        return {
            "closed": self._closed,
            "pending": len(self._pending), # 等待说话的队列
            "current": self._current.event.to_payload() if self._current is not None else None,
            "current_event_id": self._current.event.id if self._current is not None else None,  # event id
        }

    async def _run(self) -> None:
        """
        后台消费循环。

        核心入参:
            本方法无入参。

        预期输出:
            持续消费队列直到任务被取消。

        边界异常:
            单条事件失败会被捕获并写入 future，worker 继续处理下一条。
        """

        while True:
            # 1. 锁内等待并获取任务，等待并取出下一条队列事件。
            async with self._condition:
                while not self._pending:
                    # 外部执行 task.cancel() 时，会在此处抛出 CancelledError 并直接退出
                    await self._condition.wait()  # TODO: 队列里没数据，这里会释放锁
                item = self._pending.popleft()
            await self._process_item(item)  # 消费

    async def _process_item(self, item: QueueItem) -> None:
        """
        处理单条队列事件。

        核心入参:
            item: 待处理队列项。

        预期输出:
            事件被播放或标记完成，item.future 被设置结果。

        边界异常:
            speaker.speak 抛出的异常会转换为 failed 结果。
        """

        self._current = item  # 当前正在处理的数据
        self._stop_event.clear()

        try:
            # stop action 进入队列时不播报，只执行停止控制并返回。
            if self._effective_action(item.event) == "stop":
                self._stop_event.set()
                self._complete(item, QueueResult(status="stopped", event_id=item.event.id))
                return

            await asyncio.to_thread(self.speaker.speak, item.event, self._stop_event)

            # 如果播放过程中被 stop/interrupt 置位，业务结果应该表达为 stopped 而不是 completed。
            if self._stop_event.is_set():
                self._complete(item, QueueResult(status="stopped", event_id=item.event.id))
                return

            self._complete(item, QueueResult(status="completed", event_id=item.event.id))
        except Exception as exc:  # noqa: BLE001
            self._complete(item, QueueResult(status="failed", event_id=item.event.id, detail=str(exc)))
        finally:
            self._current = None
            self._stop_event.clear()

    def _complete(self, item: QueueItem, result: QueueResult) -> None:
        if not item.future.done():
            item.future.set_result(result) # 任务做好了，设置结果

    def _drop_all_pending(self, detail: str) -> None:
        """
        清理队列里全部等待事件。
        """

        while self._pending:
            item = self._pending.popleft()
            self._complete(item, QueueResult(status="skipped", event_id=item.event.id, detail=detail))

    def _drop_pending_by_intent(self, intent: str, detail: str) -> None:
        """
        清理等待队列中同语义类型的事件。
        比如 Agent 先说“正在检索代码”，紧接着又产生“已经定位到 queue 实现”，
        再下一秒是“正在验证调用链”。这几条如果全播，用户听到的是过时过程；
        更合理的是当前正在播的保留，尚未播出的旧 progress 全丢掉，只播最新状态。

        核心入参:
            intent: 需要被替换的语义标签。
            detail: 写入 QueueResult 的跳过原因。
        """

        kept: deque[QueueItem] = deque()
        while self._pending:
            item = self._pending.popleft()
            if item.event.intent == intent:  # agent语义级别，而不是action，相同语义剔除，播报最新的
                self._complete(item, QueueResult(status="skipped", event_id=item.event.id, detail=detail))
                continue
            kept.append(item)
        self._pending = kept

    def _effective_action(self, event: VoiceEvent) -> str:
        """
        返回兼容旧协议后的有效控制 action。

        核心入参:
            event: 当前语音事件。

        预期输出:
            返回 action 字符串；interrupt=true 会兼容映射为 interrupt。

        边界异常:
            不抛异常；事件合法性由 VoiceEvent.validate 负责。
        """

        if event.interrupt and event.action == "enqueue":
            return "interrupt"
        return event.action
