"""StreamVox Agent Voice Kit workflow event demo."""

from __future__ import annotations

import asyncio

from streamvox_agent_voice import VoiceClient


async def main() -> None:
    """
    演示 Agent 工作流如何发送语音事件。

    核心入参:
        本示例无命令行参数，默认连接本地 Runtime。

    预期输出:
        Runtime 依次播报 started/progress/done；异常时播报 error。

    边界异常:
        Runtime 未启动时 httpx 会抛出连接异常。
    """

    # 关键变量：VoiceClient 只负责投递事件，不加载模型，也不直接处理音频。
    voice = VoiceClient()

    try:
        await voice.say("我开始处理这个工作流。", event="started")
        await voice.say("我正在读取文件。", event="progress")
        await voice.say("我正在整理结果。", event="progress")
        await voice.done("处理完成，我找到了三个重点。", wait=True)
    except Exception:
        # 出错时使用高优先级 error 事件，保证用户能及时听到失败状态。
        await voice.error("工作流执行失败，需要检查终端日志。", wait=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
