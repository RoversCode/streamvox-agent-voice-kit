"""给内置 SenseVoice ONNX 代码使用的轻量日志对象。"""

from __future__ import annotations

import logging


# SenseVoice 内置实现内部通过 `logger.info(...)` 输出状态。这里提供同名对象，保持
# 推理模块的日志调用稳定。
logger = logging.getLogger("streamvox_web.vendor")
