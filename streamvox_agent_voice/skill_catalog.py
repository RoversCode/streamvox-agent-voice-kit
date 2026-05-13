"""基础 Skill 内置风格库加载器。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .skill_models import StyleTemplate


# 关键常量：风格库固定跟仓库里的技能模板资产保持同源，避免 Python 侧与宿主 Skill 侧出现双份定义。
_STYLE_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "skills" / "streamvox-runtime" / "assets" / "style-catalog.json"
)


def builtin_style_catalog_path() -> Path:
    """
    返回内置 style catalog 资产路径。

    核心入参:
        本方法无入参。

    预期输出:
        返回 `skills/streamvox-runtime/assets/style-catalog.json` 的绝对路径。

    边界异常:
        资产缺失时抛出 RuntimeError，避免宿主安装了技能却拿不到风格库。
    """

    if not _STYLE_CATALOG_PATH.is_file():
        raise RuntimeError(f"builtin style catalog was not found: {_STYLE_CATALOG_PATH}")
    return _STYLE_CATALOG_PATH


@lru_cache(maxsize=1)
def load_builtin_style_catalog() -> dict[str, StyleTemplate]:
    """
    读取并解析内置风格库。

    核心入参:
        本方法无入参。

    预期输出:
        返回按 `style_id` 建索引的 StyleTemplate 字典。

    边界异常:
        JSON 非法、字段缺失或 style_id 冲突时抛出 ValueError。
    """

    raw_payload = json.loads(builtin_style_catalog_path().read_text(encoding="utf-8"))
    if not isinstance(raw_payload, list) or not raw_payload:
        raise ValueError("style catalog must be a non-empty JSON array")

    catalog: dict[str, StyleTemplate] = {}
    for item in raw_payload:
        if not isinstance(item, dict):
            raise ValueError("each style catalog item must be an object")

        template = StyleTemplate(
            style_id=_required_string(item.get("style_id"), field_name="style_id"),
            display_name=_required_string(item.get("display_name"), field_name="display_name"),
            default_user_address=_required_string(item.get("default_user_address"), field_name="default_user_address"),
            default_self_reference=_required_string(
                item.get("default_self_reference"),
                field_name="default_self_reference",
            ),
            text_style=_required_object(item.get("text_style"), field_name="text_style"),
            abstract_style_traits=_required_object(
                item.get("abstract_style_traits"),
                field_name="abstract_style_traits",
            ),
            model_presets=_required_object(item.get("model_presets"), field_name="model_presets"),
        )
        if template.style_id in catalog:
            raise ValueError(f"duplicate style_id found in catalog: {template.style_id}")
        catalog[template.style_id] = template
    return catalog


def list_builtin_styles() -> list[StyleTemplate]:
    """
    返回全部内置 style 模板。

    核心入参:
        本方法无入参。

    预期输出:
        返回按 `style_id` 排序的 StyleTemplate 列表。

    边界异常:
        风格库损坏时抛出解析异常。
    """

    catalog = load_builtin_style_catalog()
    return [catalog[style_id] for style_id in sorted(catalog)]


def resolve_style_template(style_id: str) -> StyleTemplate:
    """
    根据 style_id 解析内置模板。

    核心入参:
        style_id: 内置风格标识。

    预期输出:
        返回对应 StyleTemplate。

    边界异常:
        style_id 不存在时抛出 KeyError。
    """

    catalog = load_builtin_style_catalog()
    if style_id not in catalog:
        raise KeyError(f"unknown style_id: {style_id}")
    return catalog[style_id]


def builtin_style_ids() -> set[str]:
    """
    返回全部合法 style_id。

    核心入参:
        本方法无入参。

    预期输出:
        返回一个稳定 set，便于 `VoiceProfile.validate()` 复用。

    边界异常:
        风格库损坏时抛出解析异常。
    """

    return set(load_builtin_style_catalog())


def _required_string(value: object, *, field_name: str) -> str:
    """
    解析必填非空字符串字段。

    核心入参:
        value: 原始值。
        field_name: 字段名。

    预期输出:
        返回去掉首尾空白后的字符串。

    边界异常:
        类型错误或为空时抛出 ValueError。
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _required_object(value: object, *, field_name: str) -> dict[str, object]:
    """
    解析必填 JSON 对象字段。

    核心入参:
        value: 原始值。
        field_name: 字段名。

    预期输出:
        返回原对象。

    边界异常:
        不是对象时抛出 ValueError。
    """

    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value
