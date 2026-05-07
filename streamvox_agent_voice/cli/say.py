"""streamvox-say 命令行入口。"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer

from ..client import VoiceClient


app = typer.Typer(help="Send speech events to the local StreamVox Runtime.", invoke_without_command=True)


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


def _build_metadata(role_name: str | None, streamvox_json: str | None) -> dict[str, object]:
    """
    组装事件级 metadata。

    核心入参:
        role_name: 单次事件覆盖的角色名。
        streamvox_json: 模型私有参数 JSON 字符串。

    预期输出:
        返回可直接送入 VoiceClient.say 的 metadata 字典。

    边界异常:
        JSON 非法或不是对象时抛出 typer.BadParameter。
    """

    metadata: dict[str, object] = {}
    if role_name is not None:
        metadata["role_name"] = role_name

    if streamvox_json is None:
        return metadata

    try:
        payload = json.loads(streamvox_json)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"--streamvox-json must be valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise typer.BadParameter("--streamvox-json must decode to a JSON object")

    metadata["streamvox"] = payload
    return metadata


@app.callback()
def send(
    text: Optional[str] = typer.Argument(None, help="Text to speak."),
    event: str = typer.Option("progress", "--event", help="Event type: started/progress/done/error/interrupt/stop."),
    priority: str = typer.Option("normal", "--priority", help="Queue priority: low/normal/high."),
    action: str = typer.Option(
        "enqueue",
        "--action",
        help="Queue action: enqueue/interrupt/stop/replace_pending/clear_pending_then_enqueue.",
    ),
    interrupt_text: Optional[str] = typer.Option(None, "--interrupt", help="Interrupt current speech and say this text."),
    stop: bool = typer.Option(False, "--stop", help="Stop current speech without shutting down Runtime."),
    wait: bool = typer.Option(False, "--wait", help="Wait until this event is completed."),
    role_name: Optional[str] = typer.Option(
        None,
        "--role-name",
        help="Override the Runtime default role for this event.",
    ),
    streamvox_json: Optional[str] = typer.Option(
        None,
        "--streamvox-json",
        help="JSON object forwarded to metadata.streamvox for model-specific stream kwargs.",
    ),
    interrupt_current: bool = typer.Option(
        False,
        "--interrupt-current",
        help="Explicitly stop current speech and clear pending queue before saying TEXT.",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(10.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    向 Runtime 发送语音事件。

    核心入参:
        text/event/priority/action/interrupt_text/stop/wait/role_name/streamvox_json/interrupt_current/host/port/timeout: CLI 事件参数。

    预期输出:
        stdout 输出 Runtime 响应 JSON；默认投递后快速返回。

    边界异常:
        文本缺失、Runtime 不可达或协议非法时命令非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    metadata = _build_metadata(role_name, streamvox_json)

    # stop 是纯控制指令，不需要文本，也不应该被 event 参数干扰。
    if stop:
        _print_json(asyncio.run(client.stop()))
        return

    # --interrupt "文本" 是显式控制入口，固定使用 VoiceClient.interrupt，不依赖 event 标签推导控制行为。
    if interrupt_text is not None:
        _print_json(
            asyncio.run(
                client.say(
                    interrupt_text,
                    event="interrupt",
                    priority="high",
                    action="interrupt",
                    interrupt=True,
                    wait=wait,
                    metadata=metadata or None,
                )
            )
        )
        return

    # action=stop 是协议级控制入口，不需要文本，便于脚本通过 /events 统一发送控制事件。
    if action == "stop":
        _print_json(
            asyncio.run(
                client.say(
                    text or "",
                    event=event,
                    priority=priority,
                    action="stop",
                    wait=wait,
                    metadata=metadata or None,
                )
            )
        )
        return

    # 普通播报必须提供文本；Typer Optional 参数允许 --stop 无文本，因此这里手动校验。
    if text is None:
        raise typer.BadParameter("text is required unless --stop or --interrupt is used")

    _print_json(
        asyncio.run(
            client.say(
                text,
                event=event,
                priority=priority,
                action="interrupt" if interrupt_current else action,
                interrupt=interrupt_current,
                wait=wait,
                metadata=metadata or None,
            )
        )
    )


def main() -> None:
    """
    Typer console script 入口。

    核心入参:
        命令行参数由 Typer 解析。

    预期输出:
        执行 send callback。

    边界异常:
        Typer 负责把参数错误转换为 CLI 错误提示。
    """

    app()


if __name__ == "__main__":
    main()
