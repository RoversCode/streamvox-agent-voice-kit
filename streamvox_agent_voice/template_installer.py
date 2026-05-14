"""内置 Skill 模板安装器。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable


# 关键常量：当前仓库只公开一份通用 skill，避免再次分叉 Claude/Codex 专属模板。
DEFAULT_SKILL_NAME = "streamvox-runtime"

# 关键常量：Agent 入口当前只支持 Codex 与 Claude Code，两者都复用同一份 skill 内容。
SUPPORTED_AGENT_TARGETS = ("codex", "claude-code")

# 关键常量：内置模板源固定放在仓库根目录 `skills/`，而不是 Python 包目录。
SKILLS_SOURCE_ROOT = Path(__file__).resolve().parent.parent / "skills"


def builtin_skill_source() -> Path:
    """
    返回内置通用 skill 的资源根目录。

    核心入参:
        本方法无入参。

    预期输出:
        返回仓库根目录 `skills/streamvox-runtime/` 对应的资源目录。

    边界异常:
        内置资源缺失时抛出 RuntimeError，避免 CLI 静默安装出残缺模板。
    """

    source = SKILLS_SOURCE_ROOT / DEFAULT_SKILL_NAME
    if not source.is_dir():
        raise RuntimeError(f"builtin skill template was not found: {DEFAULT_SKILL_NAME}")
    return source


def install_builtin_skill(*, target: str, force: bool = False) -> Path:
    """
    把内置通用 skill 安装到指定 Agent 的默认 skills 目录。

    核心入参:
        target: 目标 Agent，当前只支持 codex 和 claude-code。
        force: 已存在时是否覆盖。

    预期输出:
        返回安装后的 skill 根目录绝对路径。

    边界异常:
        target 不受支持、目标目录已存在且未开启 force 或模板复制失败时抛出异常。
    """

    normalized_target = _normalize_target(target)
    destination = target_skill_install_dir(normalized_target)
    if destination.exists():
        if not force:
            raise FileExistsError(f"skill already exists: {destination}")

        # 强制覆盖时先清理旧模板，业务意图是防止旧文件残留导致新旧规则混合。
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()

    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_resource_tree(source=builtin_skill_source(), destination=destination)
    return destination


def install_builtin_skills(*, target: str | None = None, force: bool = False) -> list[tuple[str, Path]]:
    """
    安装一份或多份内置 skill。

    核心入参:
        target: 目标 Agent；为空时同时安装到 codex 与 claude-code。
        force: 已存在时是否覆盖。

    预期输出:
        返回 `(target, installed_path)` 列表，便于非交互调用方输出最终安装结果。

    边界异常:
        任一目标安装失败时抛出异常；是否覆盖已存在目录由调用方通过 force 明确决定。
    """

    installed: list[tuple[str, Path]] = []
    for target_name in iter_install_targets(target):
        installed.append((target_name, install_builtin_skill(target=target_name, force=force)))
    return installed


def iter_install_targets(target: str | None) -> Iterable[str]:
    """
    解析本次应安装到哪些 Agent 目标。

    核心入参:
        target: 单个目标名称；为空时表示安装全部受支持目标。

    预期输出:
        返回稳定顺序的目标名列表。

    边界异常:
        target 非法时抛出 ValueError。
    """

    if target is None:
        return SUPPORTED_AGENT_TARGETS
    return (_normalize_target(target),)


def target_skill_install_dir(target: str) -> Path:
    """
    计算指定 Agent 的默认 skill 安装目录。

    核心入参:
        target: 已规范化的目标名称。

    预期输出:
        返回 `~/.codex/skills/streamvox-runtime` 或 `~/.claude/skills/streamvox-runtime`。

    边界异常:
        target 非法时抛出 ValueError。
    """

    normalized_target = _normalize_target(target)
    home_dir = Path(os.path.expanduser("~")).resolve()
    if normalized_target == "codex":
        return home_dir / ".codex" / "skills" / DEFAULT_SKILL_NAME
    if normalized_target == "claude-code":
        return home_dir / ".claude" / "skills" / DEFAULT_SKILL_NAME
    raise ValueError(f"unsupported target: {target}")


def _normalize_target(target: str) -> str:
    """
    规范化目标 Agent 名称。

    核心入参:
        target: 调用方传入的目标字符串。

    预期输出:
        返回稳定的小写目标名。

    边界异常:
        目标不在公开集合中时抛出 ValueError。
    """

    normalized_target = target.strip().lower()
    if normalized_target not in SUPPORTED_AGENT_TARGETS:
        raise ValueError(f"unsupported target: {target}")
    return normalized_target


def _copy_resource_tree(*, source: Path, destination: Path) -> None:
    """
    递归复制内置资源目录到本地文件系统。

    核心入参:
        source: 仓库根目录 `skills/` 下的资源目录或文件节点。
        destination: 本地目标路径。

    预期输出:
        复制完成后，目标目录包含与内置模板一致的文件结构。

    边界异常:
        读取资源失败或目标路径不可写时抛出底层异常。
    """

    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)

        # 递归复制目录内容，业务意图是让 skill 可以自然扩展 references、scripts、assets 等子目录。
        for child in source.iterdir():
            _copy_resource_tree(source=child, destination=destination / child.name)
        return

    destination.write_bytes(source.read_bytes())
