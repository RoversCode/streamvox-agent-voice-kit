"""streamvox-runtime CLI 通用工具函数。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import typer


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


def _parse_json_object(raw: str | None, *, option_name: str) -> dict[str, Any]:
    """
    解析 CLI 传入的 JSON 对象字符串。

    核心入参:
        raw: JSON 字符串，可为空。
        option_name: 当前选项名，用于错误提示。

    预期输出:
        成功时返回字典；为空时返回空字典。

    边界异常:
        JSON 非法或不是对象时抛出 typer.BadParameter。
    """

    if raw is None:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"{option_name} must be valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise typer.BadParameter(f"{option_name} must decode to a JSON object")
    return payload


def _parse_audio_data_source(audio_data_json: str | None, audio_data_file: str | None) -> list[float] | None:
    """
    解析 CLI 里的内存音频输入。

    核心入参:
        audio_data_json: 直接传入的 JSON 数组字符串。
        audio_data_file: 存放 JSON 数组的本地文件路径。

    预期输出:
        成功时返回一维浮点采样数组；未提供时返回 None。

    边界异常:
        同时提供两个来源、文件读取失败、JSON 非法或数组元素非数值时抛出 typer.BadParameter。
    """

    if audio_data_json is None and audio_data_file is None:
        return None
    if audio_data_json is not None and audio_data_file is not None:
        raise typer.BadParameter("use either --audio-data-json or --audio-data-file, not both")

    # 这里先统一把音频数据来源收敛为一段 JSON 文本，避免后续校验逻辑分散在两个分支里。
    if audio_data_file is not None:
        try:
            raw = Path(audio_data_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise typer.BadParameter(f"--audio-data-file cannot be read: {exc}") from exc
        option_name = "--audio-data-file"
    else:
        raw = audio_data_json
        option_name = "--audio-data-json"

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"{option_name} must contain valid JSON: {exc}") from exc

    if not isinstance(payload, list) or not payload:
        raise typer.BadParameter(f"{option_name} must decode to a non-empty JSON array")

    # 这里把外部传入的数值统一转成 float，保证后续注册角色接口拿到的是稳定的一维浮点数组。
    normalized_audio_data: list[float] = []
    for sample in payload:
        if isinstance(sample, bool) or not isinstance(sample, (int, float)):
            raise typer.BadParameter(f"{option_name} must contain only numbers")
        normalized_audio_data.append(float(sample))
    return normalized_audio_data


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
        # 这里优先把服务端 detail 打出来，方便人类和 Agent 都能基于明确原因做恢复。
        typer.echo(_format_http_status_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    except httpx.HTTPError as exc:
        typer.echo(_format_transport_error(exc), err=True)
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

    # 这里优先尝试抽取服务端 detail，避免 CLI 直接暴露一大段底层异常对象。
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


def _format_transport_error(exc: httpx.HTTPError) -> str:
    """
    把 HTTP 传输层异常格式化为适合 CLI 展示的短文本。

    核心入参:
        exc: `httpx` 抛出的网络、超时或连接类异常。

    预期输出:
        返回一条短错误，提示 Runtime 地址、请求类型或可能的连接问题。

    边界异常:
        不依赖异常一定带有 request/url；缺失时回退到原始异常消息。
    """

    request = getattr(exc, "request", None)
    url = getattr(request, "url", None)
    if url is not None:
        return f"Runtime request failed: {exc.__class__.__name__} while contacting {url}"
    return f"Runtime request failed: {exc}"


def _model_recommendation_message(status: str) -> str:
    """
    把模型推荐状态映射成面向人类的极简运行结论。

    核心入参:
        status: `recommend_model_profiles()` 返回的推荐状态。

    预期输出:
        返回带有 `✅/❌` 的中文结论文案。

    边界异常:
        未知状态统一降级为保守提示，避免误报为可流畅运行。
    """

    # 这里统一集中模型推荐文案，避免命令层和其他输出路径各自维护一份映射表后发生漂移。
    messages = {
        "recommended": "✅当前硬件满足推荐配置，可流畅运行该模型",
        "supported": "❌当前硬件达到最低要求但未达推荐配置，谨慎选择",
        "cpu_fallback": "❌当前硬件缺少合适 GPU，仅建议谨慎尝试",
        "unknown": "❌当前硬件信息不足，无法确认是否可流畅运行，谨慎选择",
        "insufficient": "❌硬件不满足推荐配置，谨慎选择",
    }
    return messages.get(status, "❌当前硬件信息不足，无法确认是否可流畅运行，谨慎选择")


def _format_model_recommendation_line(model_name: str, status: str) -> str:
    """
    生成 `models list` 的单行输出。

    核心入参:
        model_name: 模型名。
        status: 当前机器上的推荐状态。

    预期输出:
        返回 `模型名 [结论]` 形式的纯文本。

    边界异常:
        不抛异常。
    """

    return f"{model_name} [{_model_recommendation_message(status)}]"
