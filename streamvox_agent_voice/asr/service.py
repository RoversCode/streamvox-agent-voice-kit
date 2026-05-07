"""角色参考音频自动转写服务。"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Any, Protocol

import numpy as np


# 关键常量：Role 自动 ASR 默认使用独立缓存目录，避免把大型权重写进 site-packages。
_DEFAULT_MODEL_DIR = Path.home() / ".cache" / "streamvox-agent-voice-kit" / "sensevoice_onnx"
_SENSEVOICE_MODEL_ID = "ChengHee/sensevoice-onnx"
_REQUIRED_MODEL_FILES = (
    "Inference-Config.json",
    "Prompt-Embd.npy",
    "SenseVoice-CTC.int4.onnx",
    "SenseVoice-Encoder.int4.onnx",
    "Tokenizer.bpe.model",
)


class RolePromptTranscriber(Protocol):
    """
    定义角色参考音频转写器协议。

    核心入参:
        audio_path: 本地可访问的参考音频路径。

    预期输出:
        返回可直接传给 `TTSEngine.make_prompt(...)` 的参考文本。

    边界异常:
        转写失败时实现方应抛出 RuntimeError，便于 Runtime 把问题暴露给调用方。
    """

    def transcribe_path(self, audio_path: str) -> str:
        """转写一条本地参考音频。"""

    def load(self) -> None:
        """显式加载并预热转写引擎。"""


class SenseVoiceASRService:
    """
    基于 SenseVoice ONNX 的懒加载转写服务。

    核心入参:
        model_dir: 可选的权重目录；为空时优先读取环境变量，再回退到用户缓存目录。
        provider: 可选的 ONNX Runtime provider；为空时读取环境变量。

    预期输出:
        在第一次真正需要转写时初始化 ASR 引擎，并返回普通文本。

    边界异常:
        依赖缺失、权重缺失、下载失败或转写为空时抛出 RuntimeError。
    """

    def __init__(self, *, model_dir: str | Path | None = None, provider: str | None = None) -> None:
        # 关键变量：_engine 只在首次真实转写时构建，避免 Runtime 启动就拉起 ASR。
        self._engine: Any | None = None

        # 关键变量：_lock 保护懒加载过程，避免并发角色注册时重复初始化大模型。
        self._lock = threading.RLock()

        # 关键变量：外部显式传入的配置优先级最高，便于测试和部署环境覆盖。
        self._model_dir_override = Path(model_dir) if model_dir is not None else None
        self._provider_override = provider

    @property
    def model_dir(self) -> Path:
        """
        解析当前 ASR 权重目录。

        核心入参:
            无。

        预期输出:
            优先返回构造参数指定目录，其次读取 `STREAMVOX_ASR_MODEL_DIR`，最后回退默认缓存目录。

        边界异常:
            不抛异常。
        """

        if self._model_dir_override is not None:
            return self._model_dir_override

        env_model_dir = os.getenv("STREAMVOX_ASR_MODEL_DIR")
        if env_model_dir:
            return Path(env_model_dir)
        return _DEFAULT_MODEL_DIR

    def load(self) -> None:
        """
        显式预热 ASR 引擎。

        核心入参:
            无。

        预期输出:
            成功时 `_engine` 进入可用状态。

        边界异常:
            与 `_ensure_engine()` 保持一致。
        """

        self._ensure_engine()

    def transcribe_path(self, audio_path: str) -> str:
        """
        转写本地参考音频。

        核心入参:
            audio_path: 本地音频路径。

        预期输出:
            返回清理后的普通文本，可直接作为 `prompt_text`。

        边界异常:
            引擎初始化失败、识别失败或结果为空时抛出 RuntimeError。
        """

        engine = self._ensure_engine()
        result = engine.transcribe(audio_path, chunk_size=40, itn=True, overlap=2, duration=None)
        text = str(getattr(result, "text", "")).strip()
        if not text:
            raise RuntimeError("automatic ASR produced an empty prompt_text")
        return text

    def _provider(self) -> str:
        """
        解析当前 ONNX Runtime provider。

        核心入参:
            无。

        预期输出:
            返回 `cpu`、`cuda`、`dml` 等 provider 字符串。

        边界异常:
            不抛异常；空值会回退到 `cpu`。
        """

        value = self._provider_override or os.getenv("STREAMVOX_ASR_PROVIDER", "cpu")
        normalized = str(value).strip().lower()
        return normalized or "cpu"

    def _ensure_engine(self) -> Any:
        """
        懒加载并返回底层 SenseVoice 推理引擎。

        核心入参:
            无。

        预期输出:
            返回已初始化的 `SenseVoiceInference`。

        边界异常:
            依赖缺失、权重缺失或下载失败时抛出 RuntimeError。
        """

        with self._lock:
            if self._engine is not None:
                return self._engine

            self._download_model_if_needed()
            ASREngineConfig, SenseVoiceInference = self._load_vendor_types()
            config = ASREngineConfig(
                model_dir=str(self.model_dir),
                onnx_provider=self._provider(),
                pad_to=30,
                hotwords=None,
                precision="int4",
                top_k=8,
            )
            engine = SenseVoiceInference(config)
            self._warmup_engine(engine)
            self._engine = engine
            return self._engine

    def _load_vendor_types(self) -> tuple[type[Any], type[Any]]:
        """
        延迟导入内置 SenseVoice 推理实现。

        核心入参:
            无。

        预期输出:
            返回 `ASREngineConfig` 和 `SenseVoiceInference` 两个类型。

        边界异常:
            `sentencepiece`、`onnxruntime` 等依赖未安装时抛出 RuntimeError。
        """

        try:
            from ..vendor.sensevoice_onnx.inference import ASREngineConfig, SenseVoiceInference
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "failed to import the built-in SenseVoice ASR runtime; "
                "please ensure sentencepiece and onnxruntime are installed"
            ) from exc

        return ASREngineConfig, SenseVoiceInference

    def _warmup_engine(self, engine: Any) -> None:
        """
        用 1 秒静音完成一次热身推理。

        核心入参:
            engine: 已初始化但尚未热身的 SenseVoice 推理引擎。

        预期输出:
            首次真实转写前完成算子和图缓存预热。

        边界异常:
            热身失败时沿用底层异常。
        """

        dummy_audio = np.zeros(16000, dtype=np.float32)
        engine.recognize(dummy_audio, chunk_size=40, overlap=2, itn=True)

    def _download_model_if_needed(self) -> None:
        """
        缺失权重时自动下载 SenseVoice ONNX 模型。

        核心入参:
            无。

        预期输出:
            成功时 `self.model_dir` 下具备全部必需文件。

        边界异常:
            modelscope 未安装、网络失败或下载后文件仍缺失时抛出 RuntimeError。
        """

        model_dir = self.model_dir
        if self._is_model_ready(model_dir):
            return

        try:
            from modelscope import snapshot_download
        except ImportError as exc:
            missing = ", ".join(self._missing_model_files(model_dir))
            raise RuntimeError(
                "SenseVoice ASR weights are missing and modelscope is not installed. "
                f"Missing files: {missing}"
            ) from exc

        model_dir.mkdir(parents=True, exist_ok=True)
        try:
            snapshot_download(_SENSEVOICE_MODEL_ID, local_dir=str(model_dir))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"failed to download SenseVoice weights from ModelScope model {_SENSEVOICE_MODEL_ID}"
            ) from exc

        self._normalize_download_layout(model_dir)
        missing = self._missing_model_files(model_dir)
        if missing:
            raise RuntimeError(
                "SenseVoice weights download finished but required files are still missing: "
                + ", ".join(missing)
            )

    def _normalize_download_layout(self, search_root: Path) -> None:
        """
        统一 ModelScope 下载后的目录布局。

        核心入参:
            search_root: 下载目录根路径。

        预期输出:
            必需文件最终直接落在 `self.model_dir` 下。

        边界异常:
            不抛异常；找不到可识别布局时直接返回。
        """

        source_dir = self._find_downloaded_model_dir(search_root)
        target_dir = self.model_dir
        if source_dir is None or source_dir == target_dir:
            return

        target_dir.mkdir(parents=True, exist_ok=True)
        for file_name in _REQUIRED_MODEL_FILES:
            source_file = source_dir / file_name
            target_file = target_dir / file_name
            if source_file.exists() and source_file != target_file:
                shutil.copy2(source_file, target_file)

    def _find_downloaded_model_dir(self, search_root: Path) -> Path | None:
        """
        在下载目录中定位真实模型文件所在层级。

        核心入参:
            search_root: 下载目录根路径。

        预期输出:
            成功时返回包含全部必需文件的目录。

        边界异常:
            不抛异常；找不到时返回 None。
        """

        if self._is_model_ready(search_root):
            return search_root

        for marker in search_root.rglob(_REQUIRED_MODEL_FILES[0]):
            candidate = marker.parent
            if self._is_model_ready(candidate):
                return candidate
        return None

    def _is_model_ready(self, model_dir: Path) -> bool:
        """
        判断指定目录是否已经具备全部必需权重文件。

        核心入参:
            model_dir: 目标目录。

        预期输出:
            文件齐全时返回 True。

        边界异常:
            不抛异常。
        """

        return not self._missing_model_files(model_dir)

    def _missing_model_files(self, model_dir: Path) -> list[str]:
        """
        计算当前目录缺失的权重文件。

        核心入参:
            model_dir: 目标目录。

        预期输出:
            返回缺失文件名列表。

        边界异常:
            不抛异常。
        """

        return [file_name for file_name in _REQUIRED_MODEL_FILES if not (model_dir / file_name).exists()]


default_role_prompt_transcriber = SenseVoiceASRService()
