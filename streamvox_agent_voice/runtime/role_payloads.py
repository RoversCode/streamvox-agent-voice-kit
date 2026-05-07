"""Prompt 角色资产相关的请求载荷校验。"""

from __future__ import annotations

import json
from typing import Any


def parse_role_registration_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    解析并校验 JSON 角色注册请求。

    核心入参:
        payload: HTTP JSON 请求体。

    预期输出:
        返回 role_name、audio_path/audio_data、sample_rate、prompt_text、persist、set_default 和 streamvox 字段。

    边界异常:
        字段缺失、类型错误或音频来源冲突时抛出 ValueError。
    """

    role_name = _parse_required_string(payload.get("role_name"), field_name="role_name")
    audio_path_raw = payload.get("audio_path")
    audio_data_raw = payload.get("audio_data")
    prompt_text = _parse_optional_string(payload.get("prompt_text"), field_name="prompt_text")
    sample_rate = _parse_optional_sample_rate(payload.get("sample_rate"))

    # 角色注册必须明确选择文件音频或内存音频其中一种，避免请求语义含糊。
    has_audio_path = audio_path_raw is not None
    has_audio_data = audio_data_raw is not None
    if has_audio_path == has_audio_data:
        raise ValueError("exactly one of audio_path or audio_data must be provided")

    audio_path: str | None = None
    audio_data: list[float] | None = None

    if has_audio_path:
        audio_path = _parse_required_string(audio_path_raw, field_name="audio_path")
        if sample_rate is not None:
            raise ValueError("sample_rate is only valid when audio_data is provided")
    else:
        audio_data = _parse_audio_data(audio_data_raw)
        if sample_rate is None:
            raise ValueError("sample_rate is required when audio_data is provided")

    persist = _parse_required_boolean(payload.get("persist", True), field_name="persist")
    set_default = _parse_required_boolean(payload.get("set_default", False), field_name="set_default")
    streamvox = _parse_optional_object(payload.get("streamvox"), field_name="streamvox")

    return {
        "role_name": role_name,
        "audio_path": audio_path,
        "audio_data": audio_data,
        "sample_rate": sample_rate,
        "prompt_text": prompt_text,
        "persist": persist,
        "set_default": set_default,
        "streamvox": streamvox,
    }


def parse_role_upload_form(
    *,
    role_name: Any,
    prompt_text: Any,
    persist: Any,
    set_default: Any,
    streamvox_json: Any,
) -> dict[str, Any]:
    """
    解析并校验 multipart 角色注册表单。

    核心入参:
        role_name: 表单里的角色名。
        prompt_text: 可选参考文本；缺失时由 Runtime 触发自动 ASR。
        persist: 表单里的持久化标记。
        set_default: 表单里的默认角色切换标记。
        streamvox_json: 模型私有 `make_prompt` 参数 JSON 字符串。

    预期输出:
        返回标准化后的注册参数字典。

    边界异常:
        表单字段非法时抛出 ValueError。
    """

    return {
        "role_name": _parse_required_string(role_name, field_name="role_name"),
        "prompt_text": _parse_optional_string(prompt_text, field_name="prompt_text"),
        "persist": _parse_form_boolean(persist, field_name="persist"),
        "set_default": _parse_form_boolean(set_default, field_name="set_default"),
        "streamvox": _parse_optional_json_object_string(streamvox_json, field_name="streamvox_json"),
    }


def parse_role_delete_payload(payload: dict[str, Any]) -> str | list[str]:
    """
    解析并校验角色删除请求。

    核心入参:
        payload: HTTP JSON 请求体。

    预期输出:
        返回单个角色名，或角色名列表。

    边界异常:
        字段缺失、类型错误或空字符串时抛出 ValueError。
    """

    return _parse_string_or_string_list(payload.get("role_names"), field_name="role_names")


def parse_default_role_payload(payload: dict[str, Any]) -> str | None:
    """
    解析并校验默认角色切换请求。

    核心入参:
        payload: HTTP JSON 请求体。

    预期输出:
        返回新的默认角色名；显式传 null 时返回 None，表示清空默认角色。

    边界异常:
        role_name 字段类型错误时抛出 ValueError。
    """

    role_name = payload.get("role_name")
    if role_name is None:
        return None
    return _parse_required_string(role_name, field_name="role_name")


def _parse_required_string(value: Any, *, field_name: str) -> str:
    """
    解析必填字符串字段。

    核心入参:
        value: 任意输入值。
        field_name: 当前字段名。

    预期输出:
        返回去除首尾空白后的非空字符串。

    边界异常:
        为空或类型错误时抛出 ValueError。
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _parse_optional_string(value: Any, *, field_name: str) -> str | None:
    """
    解析可选字符串字段。

    核心入参:
        value: 任意输入值。
        field_name: 当前字段名。

    预期输出:
        缺失时返回 None，存在时返回去空白后的字符串。

    边界异常:
        类型错误或空字符串时抛出 ValueError。
    """

    if value is None:
        return None
    return _parse_required_string(value, field_name=field_name)


def _parse_required_boolean(value: Any, *, field_name: str) -> bool:
    """
    解析 JSON 布尔字段。

    核心入参:
        value: 任意输入值。
        field_name: 当前字段名。

    预期输出:
        返回布尔值。

    边界异常:
        类型错误时抛出 ValueError。
    """

    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _parse_form_boolean(value: Any, *, field_name: str) -> bool:
    """
    解析 multipart 表单里的布尔字段。

    核心入参:
        value: 表单字符串、布尔值或空值。
        field_name: 当前字段名。

    预期输出:
        返回布尔值。

    边界异常:
        无法识别时抛出 ValueError。
    """

    if isinstance(value, bool):
        return value
    if value is None:
        raise ValueError(f"{field_name} must be provided")
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a boolean or boolean-like string")

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{field_name} must be a boolean or boolean-like string")


def _parse_optional_object(value: Any, *, field_name: str) -> dict[str, Any]:
    """
    解析可选 JSON 对象字段。

    核心入参:
        value: 任意输入值。
        field_name: 当前字段名。

    预期输出:
        缺失时返回空字典，存在时返回对象本身。

    边界异常:
        类型错误时抛出 ValueError。
    """

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _parse_optional_json_object_string(value: Any, *, field_name: str) -> dict[str, Any]:
    """
    解析表单里的可选 JSON 对象字符串。

    核心入参:
        value: 字符串形式的 JSON，或空值。
        field_name: 当前字段名。

    预期输出:
        返回字典；缺失时返回空字典。

    边界异常:
        JSON 非法或不是对象时抛出 ValueError。
    """

    if value is None:
        return {}
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a JSON object string")

    normalized = value.strip()
    if not normalized:
        return {}

    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must contain valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{field_name} must decode to a JSON object")
    return payload


def _parse_string_or_string_list(value: Any, *, field_name: str) -> str | list[str]:
    """
    解析单字符串或字符串列表字段。

    核心入参:
        value: 任意 JSON 值。
        field_name: 当前字段名，用于错误提示。

    预期输出:
        返回清理后的字符串，或字符串列表。

    边界异常:
        值缺失、类型错误、列表为空或包含空字符串时抛出 ValueError。
    """

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be empty")
        return normalized

    if isinstance(value, list):
        if not value:
            raise ValueError(f"{field_name} list must not be empty")

        normalized_list: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"each {field_name} item must be a non-empty string")
            normalized_list.append(item.strip())
        return normalized_list

    raise ValueError(f"{field_name} must be a string or list[str]")


def _parse_audio_data(value: Any) -> list[float]:
    """
    解析 JSON 里的内存音频数组。

    核心入参:
        value: 任意 JSON 值。

    预期输出:
        返回一维浮点采样数组。

    边界异常:
        不是数组、数组为空或包含非数值元素时抛出 ValueError。
    """

    if not isinstance(value, list) or not value:
        raise ValueError("audio_data must be a non-empty array of numbers")

    normalized_audio_data: list[float] = []
    for sample in value:
        if isinstance(sample, bool) or not isinstance(sample, (int, float)):
            raise ValueError("audio_data must contain only numbers")
        normalized_audio_data.append(float(sample))
    return normalized_audio_data


def _parse_optional_sample_rate(value: Any) -> int | None:
    """
    解析可选采样率字段。

    核心入参:
        value: 任意 JSON 值。

    预期输出:
        合法时返回正整数采样率；缺失时返回 None。

    边界异常:
        类型错误或值不为正整数时抛出 ValueError。
    """

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("sample_rate must be a positive integer")
    return value
