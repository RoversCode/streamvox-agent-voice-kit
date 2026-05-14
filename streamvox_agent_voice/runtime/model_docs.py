"""Runtime 模型能力文档加载器。"""

from __future__ import annotations

from pathlib import Path

from .model_registry import resolve_model_profile

# 关键常量：统一从仓库根目录下的 docs/models 读取面向 AI 的模型能力说明文档。
_MODEL_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "models"

# 关键常量：运行时模型名与能力说明文档文件名不完全同名，因此使用显式映射避免猜测。
_MODEL_DOC_FILENAMES: dict[str, str] = {
    "qwen3-tts-clone-0.6b-gguf": "qwen3-tts-clone.md",
    "qwen3-tts-clone-1.7b-gguf": "qwen3-tts-clone.md",
    "s2-pro-4b-gguf": "s2-pro.md",
    "voxcpm2-gguf": "voxcpm2.md",
}


def load_model_capabilities_markdown(model: str) -> str:
    """
    读取当前 Runtime 模型对应的能力说明 Markdown 原文。

    核心入参:
        model: Runtime 当前运行的模型名，或可被注册表解析的本地 bundle 路径。

    预期输出:
        命中文档时返回 Markdown 原文；未命中文档或文件缺失时返回空字符串。

    边界异常:
        本方法不对未知模型、文档缺失或文件读取失败抛异常，统一降级为空字符串。
    """

    # 这里先通过现有模型注册表把路径或别名解析成标准模型名，避免路由层自己猜模型归属。
    profile = resolve_model_profile(model)
    if profile is None:
        return ""

    # 这里使用显式映射而不是字符串拼接，避免模型命名与文档命名未来再次漂移。
    filename = _MODEL_DOC_FILENAMES.get(profile.name)
    if filename is None:
        return ""

    doc_path = _MODEL_DOCS_DIR / filename
    if not doc_path.is_file():
        return ""

    try:
        return doc_path.read_text(encoding="utf-8")
    except OSError:
        return ""
