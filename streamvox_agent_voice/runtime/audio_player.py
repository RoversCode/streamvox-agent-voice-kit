"""音频播放后端。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Iterable, Protocol
from uuid import uuid4

import numpy as np


class AudioSink(Protocol):
    """
    音频输出后端协议。

    核心入参:
        chunks: StreamVox 生成的音频分片。
        sample_rate: 当前模型采样率。
        stop_event: Runtime 用于中断播放的线程事件。

    预期输出:
        播放后端消费全部分片，或在 stop_event 置位后尽快停止。

    边界异常:
        具体后端负责抛出设备不可用、格式不支持等异常。
    """

    def play_chunks(self, chunks: Iterable[object], sample_rate: int, stop_event: Event) -> None:
        ...


class NullAudioSink:
    """
    测试和无声环境使用的空播放后端。

    核心入参:
        chunks: 任意可迭代音频分片。
        sample_rate: 当前模型采样率。
        stop_event: 中断信号。

    预期输出:
        只消费分片，不向系统音频设备写入。

    边界异常:
        分片迭代器自身抛出的异常会向上传递，便于测试 Runtime 错误路径。
    """

    def __init__(self) -> None:
        # 关键变量：played_chunks 供测试断言 Runtime 是否真的消费了流式音频。
        self.played_chunks = 0

    def play_chunks(self, chunks: Iterable[object], sample_rate: int, stop_event: Event) -> None:
        """
        消费音频分片但不播放。

        核心入参:
            chunks: StreamVox 音频分片。
            sample_rate: 当前模型采样率，空后端不使用。
            stop_event: 中断信号。

        预期输出:
            更新 played_chunks 计数。

        边界异常:
            stop_event 置位时提前返回，不抛异常。
        """

        for _chunk in chunks:
            # 中断信号优先级高于继续消费，避免 stop/interrupt 后测试还被长流阻塞。
            if stop_event.is_set():
                return
            self.played_chunks += 1


class SoundDeviceAudioSink:
    """
    基于 sounddevice 的实时音频播放后端。

    核心入参:
        dtype: 写入 sounddevice 的样本格式，默认 float32。

    预期输出:
        把 StreamVox 的 numpy.float32 分片写入默认系统播放设备。

    边界异常:
        sounddevice 未安装、系统无默认输出设备、采样率不支持时抛出 RuntimeError 或底层异常。
    """

    def __init__(self, dtype: str = "float32") -> None:
        # 关键变量：dtype 固定为 StreamVox 文档中的 float32 音频形态。
        self.dtype = dtype

    def play_chunks(self, chunks: Iterable[object], sample_rate: int, stop_event: Event) -> None:
        """
        实时播放 StreamVox 音频分片。

        核心入参:
            chunks: StreamVox 生成的音频分片。
            sample_rate: engine.runtime.sample_rate。
            stop_event: Runtime 中断信号。

        预期输出:
            音频被写入默认输出设备；中断时尽快停止。

        边界异常:
            sounddevice import 失败时抛出 RuntimeError，底层设备异常会继续向上传递。
        """

        # 延迟导入 sounddevice，保证测试环境和无声后端不需要安装或初始化音频设备。
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice is required for real-time playback") from exc

        # 使用 OutputStream 持续写入 chunk，避免每个 chunk 重新打开设备导致爆音和延迟。
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype=self.dtype) as stream:
            for chunk in chunks:
                # stop/interrupt 置位后立即停止写设备，业务上优先响应 Agent 新事件。
                if stop_event.is_set():
                    return

                audio = self._coerce_chunk(chunk)
                if audio.size == 0:
                    continue
                stream.write(audio)

    def _coerce_chunk(self, chunk: object) -> np.ndarray:
        """
        把 StreamVox chunk 归一化为 sounddevice 可写入的二维数组。

        核心入参:
            chunk: numpy 数组、bytes 或可转换为 numpy 数组的对象。

        预期输出:
            返回 shape 为 [samples, channels] 的 float32 数组。

        边界异常:
            无法转换的对象会由 numpy 抛出异常。
        """

        # StreamVox 文档声明 chunk 是 numpy.float32；bytes 分支用于兼容签名标注或未来实现差异。
        if isinstance(chunk, bytes):
            audio = np.frombuffer(chunk, dtype=np.float32)
        else:
            audio = np.asarray(chunk, dtype=np.float32)

        # sounddevice 写入单声道时需要二维数组，统一在边界处补齐 channel 维度。
        if audio.ndim == 1:
            return audio.reshape(-1, 1)
        return audio


class WavAudioSink:
    """
    把每次语音请求保存为 wav 文件的输出后端。

    核心入参:
        output_dir: wav 文件保存目录。

    预期输出:
        每次 play_chunks 调用生成一个 wav 文件，文件名包含 UTC 时间和随机后缀。

    边界异常:
        soundfile 未安装、目录不可写或音频数据无法写入时抛出底层异常。
    """

    def __init__(self, output_dir: Path | str) -> None:
        # 关键变量：output_dir 是文件型 sink 的唯一落盘根目录。
        self.output_dir = Path(output_dir)

        # 关键变量：written_files 供测试和未来 status 扩展观察最近输出。
        self.written_files: list[Path] = []

    def play_chunks(self, chunks: Iterable[object], sample_rate: int, stop_event: Event) -> None:
        """
        消费 StreamVox 分片并保存成 wav。

        核心入参:
            chunks: StreamVox 生成的音频分片。
            sample_rate: 当前模型采样率。
            stop_event: Runtime 中断信号。

        预期输出:
            正常消费到至少一个 chunk 时写出 wav 文件；中断时只保存已收到的分片。

        边界异常:
            soundfile 写入失败会向上传递。
        """

        # 延迟导入 soundfile，保证非 wav sink 启动不被文件输出依赖影响。
        import soundfile as sf

        audios: list[np.ndarray] = []
        was_cancelled = False
        for chunk in chunks:
            # 中断时停止继续消费 generator，符合 chunk 边界取消语义。
            if stop_event.is_set():
                was_cancelled = True
                break

            audio = self._coerce_chunk(chunk)
            if audio.size == 0:
                continue
            audios.append(audio.reshape(-1))

        # 中断时不写半截 wav；没有收到任何音频时不创建空 wav，避免误导调试。
        if was_cancelled or not audios:
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._next_output_path()
        sf.write(output_path, np.concatenate(audios, axis=0), sample_rate)
        self.written_files.append(output_path)

    def _coerce_chunk(self, chunk: object) -> np.ndarray:
        """
        把 StreamVox chunk 归一化为一维 float32 音频。

        核心入参:
            chunk: numpy 数组、bytes 或可转换为 numpy 数组的对象。

        预期输出:
            返回一维 float32 数组。

        边界异常:
            无法转换的对象由 numpy 抛出异常。
        """

        if isinstance(chunk, bytes):
            return np.frombuffer(chunk, dtype=np.float32)
        return np.asarray(chunk, dtype=np.float32).reshape(-1)

    def _next_output_path(self) -> Path:
        """
        生成下一个 wav 输出文件路径。

        核心入参:
            本方法无入参。

        预期输出:
            返回不会主动覆盖已有文件的时间戳文件名。

        边界异常:
            不检查文件系统竞争；极端并发下 uuid 后缀避免常规冲突。
        """

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return self.output_dir / f"streamvox-{timestamp}-{uuid4().hex[:8]}.wav"


def build_audio_sink(name: str, output_dir: Path | str = "streamvox_outputs") -> AudioSink:
    """
    根据配置创建流式输出后端。

    核心入参:
        name: 后端名称，支持 speaker/sounddevice/null/wav。
        output_dir: wav 等文件型输出 sink 的目录。

    预期输出:
        返回 AudioSink 实例。

    边界异常:
        未知后端名抛出 ValueError。
    """

    if name in {"speaker", "sounddevice"}:
        return SoundDeviceAudioSink()
    if name == "null":
        return NullAudioSink()
    if name == "wav":
        return WavAudioSink(output_dir)
    raise ValueError(f"unsupported audio backend: {name}")
