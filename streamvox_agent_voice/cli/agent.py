"""streamvox-agent 命令行入口。"""

from __future__ import annotations

import typer

from ..template_installer import (
    DEFAULT_SKILL_NAME,
    SUPPORTED_AGENT_TARGETS,
    install_builtin_skills,
)


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
    force: bool = typer.Option(False, "--force", help="Overwrite an existing installed skill in the selected default home skill directory."),
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
        installed_results = install_builtin_skills(target=target, force=force)
    except (FileExistsError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    # 逐个输出目标与路径，业务意图是让人类和脚本都能直接看到默认安装落点。
    for installed_target, installed_path in installed_results:
        typer.echo(f"installed {DEFAULT_SKILL_NAME} for {installed_target}: {installed_path}")
        typer.echo(f"skill entry: {installed_path / 'SKILL.md'}")
    typer.echo(f"supported targets: {', '.join(SUPPORTED_AGENT_TARGETS)}")


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

    app()


if __name__ == "__main__":
    main()
