"""角色参考音频资产处理工具。"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import AsyncIterator, Iterator, Sequence

import librosa
import numpy as np
import soundfile as sf
from fastapi import UploadFile


# 关键常量：当前产品边界把角色参考音频限制在 30 秒内，避免大体积资产拖慢上传、ASR 和 Prompt 构建。
DEFAULT_MAX_REFERENCE_SECONDS = 30.0


def ensure_audio_path_within_duration_limit(audio_path: str, *, max_seconds: float) -> float:
    """
    校验本地音频文件时长不超过上限。

    核心入参:
        audio_path: 本地音频路径。
        max_seconds: 允许的最大时长。

    预期输出:
        返回检测到的音频时长，单位秒。

    边界异常:
        文件不存在、无法解析音频时长或超出时长上限时抛出异常。
    """

    duration_seconds = _probe_audio_path_duration_seconds(audio_path)
    _ensure_duration_within_limit(duration_seconds, max_seconds=max_seconds)
    return duration_seconds


def ensure_audio_data_within_duration_limit(
    audio_data: Sequence[float],
    *,
    sample_rate: int,
    max_seconds: float,
) -> float:
    """
    校验内存音频数组时长不超过上限。

    核心入参:
        audio_data: 一维采样数组。
        sample_rate: 采样率。
        max_seconds: 允许的最大时长。

    预期输出:
        返回音频时长，单位秒。

    边界异常:
        采样率非法、数组为空或超出时长上限时抛出 ValueError。
    """

    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")

    total_samples = len(audio_data)
    if total_samples <= 0:
        raise ValueError("audio_data must be a non-empty sequence of numbers")

    duration_seconds = total_samples / sample_rate
    _ensure_duration_within_limit(duration_seconds, max_seconds=max_seconds)
    return duration_seconds


@contextmanager
def temporary_wave_file_from_audio_data(
    audio_data: Sequence[float],
    *,
    sample_rate: int,
) -> Iterator[str]:
    """
    把内存音频数组暂存成临时 wav 文件。

    核心入参:
        audio_data: 一维采样数组。
        sample_rate: 采样率。

    预期输出:
        yield 一个临时 wav 路径，供 ASR 或其他仅接受文件路径的组件消费。

    边界异常:
        写文件失败时向上抛出 OSError 或 soundfile 异常。
    """

    with TemporaryDirectory(prefix="streamvox_role_audio_") as temp_dir_name:
        temp_path = Path(temp_dir_name) / "reference.wav"

        # 这里统一转成 float32 wav，保证临时文件兼容 StreamVox 角色 ASR 链路。
        normalized_audio = np.asarray(list(audio_data), dtype=np.float32)
        sf.write(temp_path, normalized_audio, sample_rate)
        yield str(temp_path)


@asynccontextmanager
async def temporary_upload_file(upload: UploadFile) -> AsyncIterator[str]:
    """
    把 multipart 上传文件落到临时路径。

    核心入参:
        upload: FastAPI `UploadFile` 对象。

    预期输出:
        yield 一个可供 Runtime 与 ASR 读取的本地临时文件路径。

    边界异常:
        文件写入失败时向上抛出 OSError。
    """

    suffix = Path(upload.filename or "").suffix or ".wav"
    with TemporaryDirectory(prefix="streamvox_role_upload_") as temp_dir_name:
        temp_path = Path(temp_dir_name) / f"reference{suffix}"
        with temp_path.open("wb") as temp_file:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                temp_file.write(chunk)

        try:
            yield str(temp_path)
        finally:
            await upload.close()


def _probe_audio_path_duration_seconds(audio_path: str) -> float:
    """
    探测本地音频文件时长。

    核心入参:
        audio_path: 本地音频路径。

    预期输出:
        返回秒级时长。

    边界异常:
        文件不存在或无法解析时抛出异常。
    """

    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"audio file does not exist: {audio_path}")

    # 优先使用 soundfile 元数据，避免不必要地解码整段音频。
    try:
        info = sf.info(path)
        if info.duration and float(info.duration) > 0:
            return float(info.duration)
    except RuntimeError:
        pass

    # 对 soundfile 不擅长的格式回退到 librosa 的时长探测逻辑。
    try:
        duration_seconds = float(librosa.get_duration(path=str(path)))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"failed to inspect audio duration for {audio_path}") from exc

    if duration_seconds <= 0:
        raise ValueError(f"audio duration must be greater than 0 seconds: {audio_path}")
    return duration_seconds


def _ensure_duration_within_limit(duration_seconds: float, *, max_seconds: float) -> None:
    """
    统一执行角色参考音频时长上限校验。

    核心入参:
        duration_seconds: 当前音频时长。
        max_seconds: 允许的最大时长。

    预期输出:
        合法时无返回值。

    边界异常:
        超过时长上限时抛出 ValueError。
    """

    if duration_seconds > max_seconds:
        raise ValueError(f"reference audio must be at most {int(max_seconds)} seconds long")
