"""StreamVox Agent Voice Kit Runtime 子包。"""

from .app import create_app
from .config import RuntimeConfig
from .model_registry import (
    build_capability_snapshot,
    build_model_doctor_report,
    detect_system_hardware,
    list_model_profiles,
    recommend_model_profiles,
    resolve_model_profile,
)
from .skill_contract import (
    RUNTIME_VERSION,
    SKILL_CONTRACT_VERSION,
    build_model_capabilities,
    build_roles_capabilities,
    build_skill_describe_payload,
    build_skill_fingerprint,
    build_skill_fingerprint_payload,
)

__all__ = [
    "RuntimeConfig",
    "RUNTIME_VERSION",
    "SKILL_CONTRACT_VERSION",
    "build_capability_snapshot",
    "build_model_capabilities",
    "build_model_doctor_report",
    "build_roles_capabilities",
    "build_skill_describe_payload",
    "build_skill_fingerprint",
    "build_skill_fingerprint_payload",
    "create_app",
    "detect_system_hardware",
    "list_model_profiles",
    "recommend_model_profiles",
    "resolve_model_profile",
]
