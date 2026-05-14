"""Windows 控制台 UTF-8 输出兼容辅助。"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import Any


def ensure_utf8_stdio_for_windows() -> None:
    """
    在 Windows 上尽力把标准输出与错误输出切换到 UTF-8。

    核心入参:
        无。

    预期输出:
        Windows 终端中后续 `print` / `typer.echo` / `stderr.write` 尽量统一按 UTF-8 输出，
        降低中文 Markdown、风格标签和特殊符号被本地代码页打坏的概率。

    边界异常:
        非 Windows 平台直接跳过；运行环境不支持 `reconfigure()`、标准流被替换或重定向时也不抛异常。
    """

    if os.name != "nt":
        return

    # 这里优先使用 Python 3 的 `TextIOWrapper.reconfigure(...)`，
    # 业务意图是只修正当前 CLI 进程自己的标准流编码，不去改全局系统代码页。
    _reconfigure_text_stream(sys.stdout)
    _reconfigure_text_stream(sys.stderr)


def _reconfigure_text_stream(stream: Any) -> None:
    """
    尝试把单个文本流切换成 UTF-8。

    核心入参:
        stream: 可能是 `sys.stdout` 或 `sys.stderr` 的文本流对象。

    预期输出:
        支持 `reconfigure(...)` 时把编码切为 UTF-8，并使用 `replace` 兜底异常字符。

    边界异常:
        流对象缺少 `reconfigure`、已关闭或宿主环境禁止重配时忽略异常。
    """

    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return

    with contextlib.suppress(Exception):
        reconfigure(encoding="utf-8", errors="replace")
