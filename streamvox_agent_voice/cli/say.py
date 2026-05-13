"""streamvox-say 命令行入口。"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import httpx
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


def _build_metadata(role_name: str | None) -> dict[str, object]:
    """
    组装事件级 metadata。

    核心入参:
        role_name: 单次事件覆盖的角色名。

    预期输出:
        返回可直接送入 VoiceClient.say 的 metadata 字典。

    边界异常:
        不抛业务异常。
    """

    metadata: dict[str, object] = {}
    if role_name is not None:
        metadata["role_name"] = role_name
    return metadata


def _resolve_text_value(argument_text: str | None, option_text: str | None) -> str | None:
    """
    解析位置参数 TEXT 与 `--text` 的最终文本。

    核心入参:
        argument_text: 位置参数里的文本。
        option_text: `--text` 显式传入的文本。

    预期输出:
        只提供一个来源时返回该文本；都未提供时返回 None。

    边界异常:
        两个来源同时提供时抛出 typer.BadParameter。
    """

    if argument_text is not None and option_text is not None:
        raise typer.BadParameter("TEXT argument cannot be used together with --text")
    return option_text if option_text is not None else argument_text


def _run_client_request(coroutine: object) -> dict[str, object]:
    """
    执行一次 Runtime HTTP 请求，并把服务端错误转换成可读 CLI 输出。

    核心入参:
        coroutine: `VoiceClient` 返回的协程对象。
    预期输出:
        成功时返回 Runtime 的 JSON 响应。
    边界异常:
        Runtime 返回非 2xx 时，输出服务端 `detail` 并以非零状态退出。
    """

    try:
        return asyncio.run(coroutine)  # type: ignore[arg-type]
    except httpx.HTTPStatusError as exc:
        # 这里优先透传 Runtime 的 detail，避免 Agent 只能看到不带上下文的通用 HTTPStatusError。
        typer.echo(_format_http_status_error(exc), err=True)
        raise typer.Exit(code=1) from exc


def _format_http_status_error(exc: httpx.HTTPStatusError) -> str:
    """
    把 HTTPStatusError 格式化为更适合 CLI 的错误文本。

    核心入参:
        exc: `httpx` 抛出的 HTTP 状态异常。
    预期输出:
        返回包含状态码与服务端 detail 的短文本。
    边界异常:
        响应体不是 JSON 时回退到纯文本或原始异常消息。
    """

    detail = ""
    try:
        payload = exc.response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        raw_detail = payload.get("detail")
        if isinstance(raw_detail, str):
            detail = raw_detail.strip()

    if not detail:
        detail = exc.response.text.strip() or str(exc)
    return f"Runtime request failed ({exc.response.status_code}): {detail}"


@app.callback()
def send(
    text: Optional[str] = typer.Argument(None, help="Text to speak."),
    text_option: Optional[str] = typer.Option(None, "--text", help="Text to speak. Preferred by host skills."),
    intent: str = typer.Option(
        "progress",
        "--intent",
        help="Intent type: info/progress/warning/urgent/done.",
    ),
    action: str = typer.Option(
        "enqueue", # 默认入队
        "--action",
        help="Queue action: enqueue/interrupt/stop/replace_pending/clear_pending_then_enqueue.",
    ),
    stop: bool = typer.Option(False, "--stop", help="Stop current speech without shutting down Runtime."),
    wait: bool = typer.Option(False, "--wait", help="Wait until this event is completed."),
    role_name: Optional[str] = typer.Option(
        None,
        "--role-name",
        help="Override the Runtime default role for this event.",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(10.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    向 Runtime 发送语音事件。

    核心入参:
        text/text_option/intent/action/stop/wait/role_name/host/port/timeout: CLI 事件参数。

    预期输出:
        stdout 输出 Runtime 响应 JSON；默认投递后快速返回。

    边界异常:
        文本缺失、Runtime 不可达或协议非法时命令非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    metadata = _build_metadata(role_name)
    resolved_text = _resolve_text_value(text, text_option)
    normalized_intent = intent.strip().lower()
    if normalized_intent not in {"info", "progress", "warning", "urgent", "done"}:
        raise typer.BadParameter(f"unsupported --intent value: {intent}")

    # stop 是纯控制指令，不需要文本，也不应该被意图参数干扰。
    if stop:
        _print_json(_run_client_request(client.stop()))
        return

    # 只传intent时走高层策略映射，业务意图是让 Agent 不必自己推导队列控制动作。
    if action == "enqueue":
        if resolved_text is None:
            raise typer.BadParameter("text is required unless --stop is used")
        _print_json(
            _run_client_request(
                client.speak_intent(
                    normalized_intent,
                    resolved_text,
                    wait=wait,
                    metadata=metadata or None,
                )
            )
        )
        return

    # action=stop 是协议级控制入口，不需要文本，便于脚本通过 /events 统一发送控制事件。
    if action == "stop":
        _print_json(
            _run_client_request(
                client.say(
                    resolved_text or "",
                    intent=normalized_intent,
                    action="stop",
                    wait=wait,
                    metadata=metadata or None,
                )
            )
        )
        return

    # 普通播报必须提供文本；Typer Optional 参数允许 --stop 无文本，因此这里手动校验。
    if resolved_text is None:
        raise typer.BadParameter("text is required unless --stop is used")

    _print_json(
        _run_client_request(
            client.say(
                resolved_text,
                intent=normalized_intent,
                action=action,
                interrupt=action == "interrupt",
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
