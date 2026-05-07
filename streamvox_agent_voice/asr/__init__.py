"""内置角色参考音频 ASR 能力。"""

from .service import RolePromptTranscriber, SenseVoiceASRService, default_role_prompt_transcriber

__all__ = [
    "RolePromptTranscriber",
    "SenseVoiceASRService",
    "default_role_prompt_transcriber",
]
