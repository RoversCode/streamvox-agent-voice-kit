"""streamvox-say 命令行入口。"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import httpx
import typer

from ..client import VoiceClient
from .json_options import parse_json_object_option


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


def _build_metadata(
    role_name: str | None,
    streamvox_json: str | None,
    streamvox_json_file: str | None,
) -> dict[str, object]:
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

    streamvox_payload = parse_json_object_option(
        raw_value=streamvox_json,
        raw_option_name="--streamvox-json",
        file_path=streamvox_json_file,
        file_option_name="--streamvox-json-file",
    )
    if not streamvox_payload:
        return metadata

    metadata["streamvox"] = streamvox_payload
    return metadata


def _select_high_level_intent(
    info_text: str | None,
    progress_text: str | None,
    urgent_text: str | None,
    done_text: str | None,
) -> tuple[str, str] | None:
    """
    从 CLI 高层策略选项中解析唯一意图。

    核心入参:
        info_text: --info 提供的普通说明文本。
        progress_text: --progress 提供的可覆盖进度文本。
        urgent_text: --urgent 提供的紧急插播文本。
        done_text: --done 提供的完成收尾文本。

    预期输出:
        没有高层选项时返回 None；有且仅有一个高层选项时返回 (intent, text)。

    边界异常:
        同时传入多个高层选项时抛出 typer.BadParameter，避免 CLI 产生含混队列行为。
    """

    # 关键变量：candidates 只收集用户实际选择的高层意图，后续用于互斥校验。
    candidates = [
        ("info", info_text),
        ("progress", progress_text),
        ("urgent", urgent_text),
        ("done", done_text),
    ]

    # 只保留非空文本，业务意图是让空字符串和未提供一样不触发高层策略。
    selected = [(intent, value) for intent, value in candidates if value is not None]
    if not selected:
        return None

    # 高层策略选项必须互斥，因为每个意图都有不同队列控制动作，混用会让最终语义不可解释。
    if len(selected) > 1:
        raise typer.BadParameter("only one of --info/--progress/--urgent/--done can be used")

    intent, value = selected[0]
    if value is None or not value.strip():
        raise typer.BadParameter(f"--{intent} text must not be empty")
    return intent, value


def _ensure_raw_controls_are_not_mixed_with_policy(
    *,
    text: str | None,
    event: str,
    action: str,
    interrupt_text: str | None,
    stop: bool,
    interrupt_current: bool,
) -> None:
    """
    校验高层策略入口没有混用底层控制参数。

    核心入参:
        text/event/action/interrupt_text/stop/interrupt_current: CLI 原始协议参数。

    预期输出:
        参数组合清晰时无返回值。

    边界异常:
        高层策略和底层控制入口混用时抛出 typer.BadParameter，避免 Agent 误以为底层参数仍会生效。
    """

    # 高层策略文本由 --info/--progress/--urgent/--done 承载，位置参数再传文本会产生双文本歧义。
    if text is not None:
        raise typer.BadParameter("TEXT argument cannot be used together with --info/--progress/--urgent/--done")

    # 高层策略已经固定 event/action，业务意图是阻止调用方绕过策略层直接改底层动作。
    if event != "progress" or action != "enqueue":
        raise typer.BadParameter("--event/--action cannot be combined with high-level policy options")

    # stop 和 interrupt 是独立控制入口，不能和高层播报意图混用。
    if stop or interrupt_text is not None or interrupt_current:
        raise typer.BadParameter("--stop/--interrupt/--interrupt-current cannot be combined with high-level policy options")


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
    event: str = typer.Option("progress", "--event", help="Event type: started/progress/done/error/interrupt/stop."),
    action: str = typer.Option(
        "enqueue", # 默认入队
        "--action",
        help="Queue action: enqueue/interrupt/stop/replace_pending/clear_pending_then_enqueue.",
    ),
    interrupt_text: Optional[str] = typer.Option(None, "--interrupt", help="Interrupt current speech and say this text."),
    stop: bool = typer.Option(False, "--stop", help="Stop current speech without shutting down Runtime."),
    info_text: Optional[str] = typer.Option(None, "--info", help="Speak normal information using the high-level policy."),
    progress_text: Optional[str] = typer.Option(
        None,
        "--progress",
        help="Speak progress using replace_pending high-level policy.",
    ),
    urgent_text: Optional[str] = typer.Option(None, "--urgent", help="Speak urgent text using interrupt policy."),
    done_text: Optional[str] = typer.Option(None, "--done", help="Speak done text using finalization policy."),
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
    streamvox_json_file: Optional[str] = typer.Option(
        None,
        "--streamvox-json-file",
        help="Path to a JSON object file forwarded to metadata.streamvox for model-specific stream kwargs.",
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
        text/event/action/interrupt_text/stop/info_text/progress_text/urgent_text/done_text/wait/role_name/streamvox_json/interrupt_current/host/port/timeout: CLI 事件参数。

    预期输出:
        stdout 输出 Runtime 响应 JSON；默认投递后快速返回。

    边界异常:
        文本缺失、Runtime 不可达或协议非法时命令非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    metadata = _build_metadata(role_name, streamvox_json, streamvox_json_file)
    high_level_intent = _select_high_level_intent(info_text, progress_text, urgent_text, done_text)

    # 高层策略入口优先处理，并拒绝混用底层控制参数，业务意图是给 Agent 一个稳定、少分支的调用面。
    if high_level_intent is not None:
        _ensure_raw_controls_are_not_mixed_with_policy(
            text=text,
            event=event,
            action=action,
            interrupt_text=interrupt_text,
            stop=stop,
            interrupt_current=interrupt_current,
        )
        intent, policy_text = high_level_intent
        _print_json(
            _run_client_request(
                getattr(client, intent)(
                    policy_text,
                    wait=wait,
                    metadata=metadata or None,
                )
            )
        )
        return

    # stop 是纯控制指令，不需要文本，也不应该被 event 参数干扰。
    if stop:
        _print_json(_run_client_request(client.stop()))
        return

    # --interrupt "文本" 是显式控制入口，固定使用 VoiceClient.interrupt，不依赖 event 标签推导控制行为。
    if interrupt_text is not None:
        _print_json(
            _run_client_request(
                client.interrupt(
                    interrupt_text,
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
                    text or "",
                    event=event,
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
        _run_client_request(
            client.say(
                text,
                event=event,
                action="interrupt" if interrupt_current else action, # 默认action是enqueue
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
