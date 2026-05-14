"""streamvox-agent 命令行入口。"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from ..template_installer import (
    DEFAULT_SKILL_NAME,
    SUPPORTED_AGENT_TARGETS,
    install_builtin_skill,
    iter_install_targets,
    target_skill_install_dir,
)
from ..windows_command_installer import install_windows_commands, is_directory_in_process_path
from .console_encoding import ensure_utf8_stdio_for_windows


app = typer.Typer(help="Install the built-in StreamVox runtime skill for Codex or Claude Code.", no_args_is_help=True)


@app.callback()
def agent_root() -> None:
    """
    `streamvox-agent` 根命令。

    核心入参:
        子命令参数由 Typer 解析。

    预期输出:
        不直接执行业务逻辑，只保留子命令命名空间。

    边界异常:
        不抛异常。
    """

    # 保留空回调，业务意图是强制 `init` 作为显式子命令存在，而不是被 Typer 自动扁平化成根命令。
    return


@app.command("init")
def init(
    target: str | None = typer.Option(
        None,
        "--target",
        help="Target agent: codex or claude-code. Omit to install into both default home skill directories.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing installed skill without prompting in the selected default home skill directory.",
    ),
) -> None:
    """
    安装唯一的通用 StreamVox skill。

    核心入参:
        target: 目标 Agent；为空时同时安装到 Codex 与 Claude Code 的默认目录。
        force: 已存在时是否强制覆盖。

    预期输出:
        成功时输出每个目标的已安装 skill 路径。

    边界异常:
        target 不受支持、已有 skill 未允许覆盖或复制失败时命令非零退出。
    """

    try:
        installed_results: list[tuple[str, Path, str]] = []
        skipped_results: list[tuple[str, Path]] = []

        # 逐个目标处理，业务意图是让交互式覆盖确认只影响当前目标，而不是让整批安装一起失败。
        for target_name in iter_install_targets(target):
            destination = target_skill_install_dir(target_name)
            destination_exists = destination.exists()
            should_force_install = force

            # 已存在且未显式强制覆盖时，先询问用户是否覆盖；选择否时跳过当前目标并继续后续目标。
            if destination_exists and not force:
                if not _confirm_overwrite(target=target_name, destination=destination):
                    skipped_results.append((target_name, destination))
                    continue
                should_force_install = True

            installed_path = install_builtin_skill(target=target_name, force=should_force_install)
            install_status = "overwritten" if destination_exists else "installed"
            installed_results.append((target_name, installed_path, install_status))
    except (FileExistsError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    # 逐个输出目标与路径，业务意图是让人类和脚本都能直接看到每个目标是安装、覆盖还是跳过。
    for installed_target, installed_path, install_status in installed_results:
        typer.echo(f"{install_status} {DEFAULT_SKILL_NAME} for {installed_target}: {installed_path}")
        typer.echo(f"skill entry: {installed_path / 'SKILL.md'}")
    for skipped_target, skipped_path in skipped_results:
        typer.echo(f"skipped existing {DEFAULT_SKILL_NAME} for {skipped_target}: {skipped_path}")
    typer.echo(f"supported targets: {', '.join(SUPPORTED_AGENT_TARGETS)}")


@app.command("install-windows-commands")
def install_windows_commands_command(
    bin_dir: Path | None = typer.Option(
        None,
        "--bin-dir",
        help="Directory used to place global Windows .cmd launchers. Omit to auto-select a user directory that is already in PATH when possible.",
    ),
    add_to_path: bool = typer.Option(
        True,
        "--add-to-path/--no-add-to-path",
        help="Add the launcher directory into the current user's PATH so new terminals can call streamvox-* directly.",
    ),
) -> None:
    """
    在 Windows 上安装可跨终端直接调用的全局命令入口。

    核心入参:
        bin_dir: `.cmd` 启动器的安装目录。
        add_to_path: 是否把安装目录加入当前用户 PATH。

    预期输出:
        成功时输出安装目录、已生成的命令文件以及 PATH 是否被更新。

    边界异常:
        非 Windows 平台、用户目录不可写或 PATH 更新失败时命令非零退出。
    """

    try:
        resolved_bin_dir, created_files, path_updated = install_windows_commands(
            bin_dir=bin_dir,
            add_to_path=add_to_path,
        )
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"installed Windows launchers into: {resolved_bin_dir}")
    for created_file in created_files:
        typer.echo(f"launcher: {created_file}")
    if is_directory_in_process_path(resolved_bin_dir):
        typer.echo("current terminal can already resolve streamvox-runtime / streamvox-say directly.")
        return
    if add_to_path:
        if path_updated:
            typer.echo("user PATH updated. Open a new terminal to use streamvox-runtime / streamvox-say directly.")
        else:
            typer.echo("launcher directory is already present in user PATH.")
    else:
        typer.echo("user PATH was not modified. Use the generated .cmd files directly, or re-run with --add-to-path.")


def _confirm_overwrite(*, target: str, destination: Path) -> bool:
    """
    在交互式终端中确认是否覆盖已存在的 skill 安装。

    核心入参:
        target: 当前正在处理的 Agent 目标名称。
        destination: 已存在的 skill 安装目录。

    预期输出:
        用户确认覆盖时返回 True；选择跳过时返回 False。

    边界异常:
        非交互环境下无法安全提问时抛出 RuntimeError，引导用户改用 --force。
    """

    # 非交互终端无法可靠读取确认输入，业务意图是避免命令挂起或把 EOF 误判成默认答案。
    if not sys.stdin.isatty():
        raise RuntimeError(
            f"skill already exists: {destination}. Re-run with --force to overwrite, or run in an interactive terminal to confirm."
        )

    return typer.confirm(
        f"{target} skill already exists at {destination}. Overwrite it?",
        default=False,
    )


def main() -> None:
    """
    Typer console script 入口。

    核心入参:
        命令行参数由 Typer 解析。

    预期输出:
        执行 streamvox-agent 的子命令。

    边界异常:
        Typer 负责把参数错误转换为 CLI 错误提示。
    """

    ensure_utf8_stdio_for_windows()
    app()


if __name__ == "__main__":
    main()
