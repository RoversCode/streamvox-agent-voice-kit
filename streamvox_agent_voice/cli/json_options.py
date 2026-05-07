"""CLI JSON 选项解析工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer


def parse_json_object_option(
    *,
    raw_value: str | None,
    raw_option_name: str,
    file_path: str | None,
    file_option_name: str,
) -> dict[str, Any]:
    """
    解析一组“内联 JSON / JSON 文件”互斥选项。

    核心入参:
        raw_value: 直接从命令行传入的 JSON 字符串。
        raw_option_name: 内联 JSON 选项名，用于错误提示。
        file_path: 指向 JSON 文件的路径。
        file_option_name: 文件选项名，用于错误提示。
    预期输出:
        返回解析成功后的 JSON 对象；两者都未提供时返回空字典。
    边界异常:
        同时传入两个来源、文件不可读、JSON 非法或结果不是对象时抛出 `typer.BadParameter`。
    """

    # 这里强制两个入口互斥，避免同一轮调用里出现“内联 JSON”和“文件 JSON”谁覆盖谁的不透明行为。
    if raw_value is not None and file_path is not None:
        raise typer.BadParameter(f"use either {raw_option_name} or {file_option_name}, not both")

    if file_path is not None:
        raw_payload = _read_json_text(file_path=file_path, option_name=file_option_name)
        source_name = file_option_name
    else:
        raw_payload = raw_value
        source_name = raw_option_name

    if raw_payload is None:
        return {}

    return _parse_json_object(raw_payload, option_name=source_name)


def _read_json_text(*, file_path: str, option_name: str) -> str:
    """
    读取 JSON 文件文本。

    核心入参:
        file_path: JSON 文件路径。
        option_name: 当前选项名，用于错误提示。
    预期输出:
        返回 UTF-8 文本内容。
    边界异常:
        文件不存在、不可读或读取失败时抛出 `typer.BadParameter`。
    """

    try:
        return Path(file_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise typer.BadParameter(f"{option_name} cannot be read: {exc}") from exc


def _parse_json_object(raw_payload: str, *, option_name: str) -> dict[str, Any]:
    """
    把文本解析为 JSON 对象。

    核心入参:
        raw_payload: 待解析的 JSON 文本。
        option_name: 当前选项名，用于错误提示。
    预期输出:
        返回解析后的对象字典。
    边界异常:
        JSON 非法或解析结果不是对象时抛出 `typer.BadParameter`。
    """

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"{option_name} must be valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise typer.BadParameter(f"{option_name} must decode to a JSON object")
    return payload
