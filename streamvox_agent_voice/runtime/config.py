"""Runtime 配置对象。"""

from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from pathlib import Path


@dataclass(slots=True)
class RuntimeConfig:
    """
    StreamVox Runtime 的启动配置。

    核心入参:
        model: StreamVox 模型名或本地 bundle 路径。
        device: 设备选择，透传给 TTSEngine。
        host: Runtime HTTP 监听地址。
        port: Runtime HTTP 监听端口。
        license_key: 在线授权 key，可为空。
        license_path: 离线授权路径，可为空。
        verify_model_sha256: 是否校验模型文件 sha256。
        default_role_name: Runtime 启动后默认继承的角色名，可为空。
        audio_backend: 流式输出后端，第一版支持 speaker/null，兼容 sounddevice 旧别名。
        output_dir: 文件型输出 sink 的目录，例如 wav。

    预期输出:
        配置对象只承载启动参数，不直接启动 Runtime。

    边界异常:
        本类不做复杂校验，CLI 和 Runtime 入口负责处理不可用后端或端口。
    """

    model: str = "voxcpm2-gguf"
    device: str = "auto"
    host: str = "127.0.0.1"
    port: int = 8765
    license_key: str | None = None
    license_path: str | None = None
    verify_model_sha256: bool = False
    default_role_name: str | None = None
    audio_backend: str = "speaker"
    output_dir: Path = Path("streamvox_outputs")

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        """
        从环境变量构造 Runtime 配置。

        核心入参:
            本方法不接收参数，读取 STREAMVOX_* 环境变量。

        预期输出:
            返回 RuntimeConfig，供 CLI 或测试覆盖默认值。

        边界异常:
            STREAMVOX_AGENT_VOICE_PORT 不是整数时会抛出 ValueError。
        """

        # 环境变量只作为默认值来源，CLI 显式参数仍然应该优先覆盖它们。
        return cls(
            model=getenv("STREAMVOX_AGENT_VOICE_MODEL", cls.model),
            device=getenv("STREAMVOX_AGENT_VOICE_DEVICE", cls.device),
            host=getenv("STREAMVOX_AGENT_VOICE_HOST", cls.host),
            port=int(getenv("STREAMVOX_AGENT_VOICE_PORT", str(cls.port))),
            license_key=getenv("STREAMVOX_LICENSE_KEY"),
            license_path=getenv("STREAMVOX_LICENSE_PATH"),
            verify_model_sha256=getenv("STREAMVOX_VERIFY_MODEL_SHA256", "0") == "1",
            default_role_name=getenv("STREAMVOX_AGENT_VOICE_DEFAULT_ROLE_NAME"),
            audio_backend=getenv("STREAMVOX_AGENT_VOICE_OUTPUT", getenv("STREAMVOX_AGENT_VOICE_AUDIO_BACKEND", cls.audio_backend)),
            output_dir=Path(getenv("STREAMVOX_AGENT_VOICE_OUTPUT_DIR", str(cls.output_dir))),
        )

    @property
    def base_url(self) -> str:
        """
        返回当前 Runtime 的 HTTP 根地址。

        核心入参:
            本属性不接收参数。

        预期输出:
            返回形如 http://127.0.0.1:8765 的 URL。

        边界异常:
            不校验 host/port 是否真实可监听。
        """

        return f"http://{self.host}:{self.port}"
