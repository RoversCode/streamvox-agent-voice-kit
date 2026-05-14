"""Windows 全局命令入口安装器。"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import sys
from typing import Iterable


# 关键常量：优先复用用户目录下已经在 PATH 里的 bin 目录；只有找不到时才退回专用目录。
DEFAULT_WINDOWS_FALLBACK_BIN_DIR = Path.home() / ".streamvox" / "bin"
DEFAULT_WINDOWS_BIN_DIR = DEFAULT_WINDOWS_FALLBACK_BIN_DIR

# 关键常量：这里只暴露用户真正需要跨终端直接调用的两个命令，以及辅助安装命令本身。
WINDOWS_COMMAND_SPECS = (
    ("streamvox-runtime.cmd", "streamvox_agent_voice.cli.runtime"),
    ("streamvox-say.cmd", "streamvox_agent_voice.cli.say"),
    ("streamvox-agent.cmd", "streamvox_agent_voice.cli.agent"),
)


def install_windows_commands(
    *,
    bin_dir: str | Path | None = None,
    add_to_path: bool = True,
) -> tuple[Path, tuple[Path, ...], bool]:
    """
    在 Windows 用户目录下安装可跨终端直接调用的命令入口。

    核心入参:
        bin_dir: 目标安装目录；为空时使用默认用户目录。
        add_to_path: 是否同步把安装目录加入当前用户 PATH。

    预期输出:
        返回 `(resolved_bin_dir, created_files, path_updated)`，供 CLI 输出最终结果。

    边界异常:
        非 Windows 平台、当前 Python 解释器不存在或写入 PATH 失败时抛出 RuntimeError。
    """

    _ensure_windows_platform()

    # 关键变量：resolved_bin_dir 是本次命令入口安装的唯一落点，便于后续 PATH 更新与结果展示保持一致。
    resolved_bin_dir = Path(bin_dir) if bin_dir is not None else resolve_default_windows_bin_dir()
    resolved_bin_dir = resolved_bin_dir.expanduser().resolve()
    resolved_bin_dir.mkdir(parents=True, exist_ok=True)

    python_executable = Path(sys.executable).resolve()
    if not python_executable.is_file():
        raise RuntimeError(f"python executable does not exist: {python_executable}")

    created_files: list[Path] = []
    for command_name, module_name in WINDOWS_COMMAND_SPECS:
        command_path = resolved_bin_dir / command_name
        _write_windows_command_shim(
            command_path=command_path,
            python_executable=python_executable,
            module_name=module_name,
        )
        created_files.append(command_path)

    path_updated = False
    # 如果当前终端已经能解析这个目录，就不要再去写用户 PATH；这样安装命令执行完后即可立即使用。
    if add_to_path and not is_directory_in_process_path(resolved_bin_dir):
        path_updated = ensure_directory_in_user_path(resolved_bin_dir)

    return resolved_bin_dir, tuple(created_files), path_updated


def iter_windows_command_specs() -> Iterable[tuple[str, str]]:
    """
    返回全部 Windows 命令入口定义。

    核心入参:
        无。

    预期输出:
        以稳定顺序返回 `(command_file_name, module_name)` 元组，供 CLI 与测试复用。

    边界异常:
        不抛异常。
    """

    return WINDOWS_COMMAND_SPECS


def resolve_default_windows_bin_dir() -> Path:
    """
    解析 Windows 全局命令入口的默认安装目录。

    核心入参:
        无。

    预期输出:
        优先返回当前终端已经在 PATH 里的用户级 bin 目录，例如 `~\\.local\\bin`；
        如果没有可复用目录，再回退到专用目录 `~\\.streamvox\\bin`。

    边界异常:
        非 Windows 平台抛出 RuntimeError。
    """

    _ensure_windows_platform()

    home_dir = Path.home().resolve()
    preferred_candidates = (
        home_dir / ".local" / "bin",
        home_dir / "bin",
        home_dir / ".streamvox" / "bin",
    )
    current_process_entries = {
        os.path.normcase(str(path))
        for path in iter_process_path_directories()
    }

    # 优先命中我们明确知道“适合放用户级脚本”的几个目录。
    for candidate in preferred_candidates:
        normalized_candidate = os.path.normcase(str(candidate.resolve()))
        if normalized_candidate in current_process_entries:
            return candidate

    # 如果 PATH 里存在其他位于 home 下的目录，也优先复用它，避免依赖重新打开终端才生效。
    for candidate in iter_process_path_directories():
        with contextlib.suppress(Exception):
            resolved_candidate = candidate.resolve()
            resolved_candidate.relative_to(home_dir)
            return resolved_candidate

    return DEFAULT_WINDOWS_FALLBACK_BIN_DIR


def iter_process_path_directories() -> Iterable[Path]:
    """
    迭代当前进程 PATH 中声明的目录。

    核心入参:
        无。

    预期输出:
        返回去重后的 PATH 目录列表，供默认安装目录选择和即时可用性判断复用。

    边界异常:
        忽略 PATH 中的空段和无法规范化的异常条目。
    """

    seen: set[str] = set()
    for raw_entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = raw_entry.strip()
        if not entry:
            continue
        with contextlib.suppress(Exception):
            normalized = Path(entry).expanduser().resolve()
            normalized_key = os.path.normcase(str(normalized))
            if normalized_key in seen:
                continue
            seen.add(normalized_key)
            yield normalized


def is_directory_in_process_path(directory: Path) -> bool:
    """
    判断指定目录是否已经存在于当前进程 PATH 中。

    核心入参:
        directory: 待检查目录。

    预期输出:
        已存在返回 True；不存在返回 False。

    边界异常:
        不抛异常。
    """

    normalized_directory = os.path.normcase(str(directory.expanduser().resolve()))
    return any(
        os.path.normcase(str(path)) == normalized_directory
        for path in iter_process_path_directories()
    )


def ensure_directory_in_user_path(directory: Path) -> bool:
    """
    确保指定目录存在于当前用户级 PATH 中。

    核心入参:
        directory: 需要加入 PATH 的目录。

    预期输出:
        新增成功时返回 True；目录本来就在 PATH 中时返回 False。

    边界异常:
        非 Windows 或注册表读写失败时抛出 RuntimeError。
    """

    _ensure_windows_platform()

    try:
        import winreg
    except ImportError as exc:
        raise RuntimeError("winreg is not available on this Python build") from exc

    normalized_directory = str(directory.resolve())
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        "Environment",
        0,
        winreg.KEY_READ | winreg.KEY_WRITE,
    ) as environment_key:
        current_value, value_type = _read_user_path_value(environment_key)
        current_entries = [
            entry.strip()
            for entry in current_value.split(";")
            if entry.strip()
        ]

        # 统一用不区分大小写的绝对路径比较，避免同一路径因为大小写或结尾斜杠不同被重复写入。
        normalized_existing_entries = {
            os.path.normcase(str(Path(entry).expanduser()))
            for entry in current_entries
        }
        if os.path.normcase(normalized_directory) in normalized_existing_entries:
            return False

        updated_entries = current_entries + [normalized_directory]
        updated_value = ";".join(updated_entries)
        winreg.SetValueEx(environment_key, "Path", 0, value_type, updated_value)
    return True


def _read_user_path_value(environment_key: object) -> tuple[str, int]:
    """
    从用户环境变量注册表键读取 PATH 及其原始类型。

    核心入参:
        environment_key: 已打开的 `HKCU\\Environment` 注册表键。

    预期输出:
        返回 `(path_value, value_type)`；PATH 不存在时返回空字符串和可扩展字符串类型。

    边界异常:
        注册表读取异常时沿用底层异常，让上层统一转成 RuntimeError。
    """

    import winreg

    try:
        value, value_type = winreg.QueryValueEx(environment_key, "Path")
    except FileNotFoundError:
        return "", winreg.REG_EXPAND_SZ
    return str(value), value_type


def _write_windows_command_shim(
    *,
    command_path: Path,
    python_executable: Path,
    module_name: str,
) -> None:
    """
    生成一个委托到当前 Python 解释器的 `.cmd` 启动器。

    核心入参:
        command_path: `.cmd` 文件输出路径。
        python_executable: 当前运行安装命令的 Python 解释器路径。
        module_name: 实际要执行的模块名。

    预期输出:
        写出可在任意终端通过命令名直接调用的 Windows 批处理脚本。

    边界异常:
        目标目录不可写时抛出底层文件系统异常。
    """

    # 用当前解释器做唯一真值来源，业务意图是让所有全局命令都复用这一套已经装好依赖的环境，
    # 而不是再要求用户先激活虚拟环境或依赖项目目录恰好在 PATH 中。
    shim_text = (
        "@echo off\r\n"
        "setlocal\r\n"
        f"\"{python_executable}\" -m {module_name} %*\r\n"
    )
    command_path.write_text(shim_text, encoding="utf-8")


def _ensure_windows_platform() -> None:
    """
    确保当前逻辑只在 Windows 平台执行。

    核心入参:
        无。

    预期输出:
        Windows 平台静默通过。

    边界异常:
        非 Windows 平台抛出 RuntimeError。
    """

    if os.name != "nt":
        raise RuntimeError("windows command installation is only available on Windows")
