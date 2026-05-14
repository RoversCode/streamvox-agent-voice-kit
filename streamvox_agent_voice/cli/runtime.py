"""streamvox-runtime 命令行入口。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
import uvicorn

from ..client import VoiceClient
from ..runtime import (
    RuntimeConfig,
    create_app,
    detect_system_hardware,
    recommend_model_profiles,
)
from .json_options import parse_json_object_option
from .console_encoding import ensure_utf8_stdio_for_windows
from .runtime_probe import (
    DEFAULT_REALTIME_SELFTEST_TEXT,
    build_benchmark_summary,
    build_streaming_selftest_summary,
    run_runtime_benchmark,
    run_runtime_realtime_selftest,
)
from .runtime_cli_utils import (
    _base_url,
    _format_model_recommendation_line,
    _parse_audio_data_source,
    _print_json,
    _run_client_request,
)
from .runtime_supervisor import RuntimeShutdownGuard, is_runtime_child_process, run_supervised_start


app = typer.Typer(help="Manage the local StreamVox Agent Voice Runtime.")
models_app = typer.Typer(help="List supported StreamVox model profiles.")
roles_app = typer.Typer(help="Manage cached prompt roles in the local Runtime.")
app.add_typer(models_app, name="models")
app.add_typer(roles_app, name="roles")


@app.command()
def start(
    model: str = typer.Option(
        RuntimeConfig.model,
        "--model",
        help="StreamVox model name or local bundle path.",
    ),
    device: str = typer.Option("auto", "--device", help="StreamVox device: auto/cpu/gpu/gpu:<index>."),
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    license_key: Optional[str] = typer.Option(None, "--license-key", help="StreamVox online license key."),
    license_path: Optional[str] = typer.Option(None, "--license-path", help="StreamVox offline license path."),
    verify_model_sha256: bool = typer.Option(False, "--verify-model-sha256", help="Verify model bundle sha256."),
    default_role_name: Optional[str] = typer.Option(
        None,
        "--default-role-name",
        help="Default role name inherited by events that do not explicitly override role_name.",
    ),
    streamvox_json: Optional[str] = typer.Option(
        None,
        "--streamvox-json",
        help="JSON object used as fixed TTSEngine.stream kwargs for the current Runtime session.",
    ),
    streamvox_json_file: Optional[str] = typer.Option(
        None,
        "--streamvox-json-file",
        help="Path to a JSON object file used as fixed TTSEngine.stream kwargs for the current Runtime session.",
    ),
    audio_backend: str = typer.Option(
        "speaker",
        "--output",
        "--audio-backend",
        help="Streaming output sink: speaker/null/wav. sounddevice is kept as a compatibility alias.",
    ),
    output_dir: str = typer.Option(
        "streamvox_outputs",
        "--output-dir",
        help="Directory used by file output sinks such as wav.",
    ),
) -> None:
    """
    启动常驻 StreamVox Runtime。

    核心入参:
        model/device/host/port/license/default_role_name/streamvox_json/audio_backend/output_dir: Runtime 启动参数。

    预期输出:
        当前进程启动 uvicorn 服务并保持运行，直到收到 stop/shutdown。

    边界异常:
        模型加载、端口占用、音频后端不可用会导致命令非零退出。
    """

    # 默认由父进程做 supervisor，真正的 Runtime 子进程通过内部环境变量进入本分支下方。
    if not is_runtime_child_process():
        exit_code = run_supervised_start(
            model=model,
            device=device,
            host=host,
            port=port,
            license_key=license_key,
            license_path=license_path,
            verify_model_sha256=verify_model_sha256,
            default_role_name=default_role_name,
            streamvox_json=streamvox_json,
            streamvox_json_file=streamvox_json_file,
            audio_backend=audio_backend,
            output_dir=output_dir,
        )
        if exit_code < 0:
            exit_code = 128 + abs(exit_code)
        raise typer.Exit(code=exit_code)

    explicit_stream_kwargs = parse_json_object_option(
        raw_value=streamvox_json,
        raw_option_name="--streamvox-json",
        file_path=streamvox_json_file,
        file_option_name="--streamvox-json-file",
    )
    stream_kwargs = explicit_stream_kwargs or RuntimeConfig.builtin_stream_kwargs_for_model(model)

    config = RuntimeConfig(
        model=model,
        device=device,
        host=host,
        port=port,
        license_key=license_key,
        license_path=license_path,
        verify_model_sha256=verify_model_sha256,
        default_role_name=default_role_name,
        stream_kwargs=stream_kwargs or None,
        audio_backend=audio_backend,
        output_dir=Path(output_dir),
    )
    runtime_app = create_app(config)
    uvicorn_config = uvicorn.Config(runtime_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(uvicorn_config)

    # 把 server 注入 app.state，/shutdown 接口可以优雅设置 should_exit，而不是强杀进程。
    runtime_app.state.server = server
    shutdown_guard = RuntimeShutdownGuard(runtime_app, server)
    shutdown_guard.install()

    try:
        asyncio.run(server.serve()) # 创建了一个事件循环，开始跑
    except KeyboardInterrupt as exc:
        shutdown_guard.shutdown_for_exception()
        raise typer.Exit(code=130) from exc
    except Exception:
        shutdown_guard.shutdown_for_exception()
        raise
    finally:
        shutdown_guard.restore()


@app.command()
def selftest(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(60.0, "--timeout", help="HTTP request timeout seconds."),
    role_name: Optional[str] = typer.Option(
        None,
        "--role-name",
        help="Optional persisted role name used by the realtime selftest.",
    ),
    text: str = typer.Option(
        DEFAULT_REALTIME_SELFTEST_TEXT,
        "--text",
        help="Long text used to inspect chunk continuity during realtime selftest.",
    ),
) -> None:
    # [旧注释已废弃]: 原 docstring 因编码异常出现乱码，已按当前实现语义重写。
    """
    执行只关注流式连续性的 Runtime 自检。

    核心入参:
        host/port/timeout: Runtime 服务地址与 HTTP 请求超时。
        role_name: 可选的持久化角色名；为空时由 Runtime 自己按默认角色、demo_role 顺序回退。
        text: 用于触发多个 chunk 的长文本，便于检测流式生成是否会中途断裂。

    预期输出:
        stdout 输出一份 JSON 自检报告，包含 chunk 时序、首个断裂点和是否适合实时语音播报的结论。

    边界异常:
        Runtime 不可达、角色不可用、底层 stream 失败或探针执行异常时，CLI 会以非零状态退出并打印可读错误。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    selftest_report = _run_client_request(
        run_runtime_realtime_selftest(
            client,
            text=text,
            role_name=role_name,
        )
    )
    _print_json(build_streaming_selftest_summary(selftest_report))


@app.command()
def benchmark(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(120.0, "--timeout", help="HTTP request timeout seconds."),
    role_name: Optional[str] = typer.Option(
        None,
        "--role-name",
        help="Optional persisted role name used by the benchmark speech requests.",
    ),
    text: str = typer.Option(
        "您好，我正在整理答案，请稍等片刻。",
        "--text",
        help="Benchmark text used to measure end-to-end completion latency.",
    ),
    iterations: int = typer.Option(
        1,
        "--iterations",
        min=1,
        max=10,
        help="How many completed speech runs to measure. Larger values are slower and more audible.",
    ),
    json_summary_only: bool = typer.Option(
        False,
        "--json-summary-only",
        help="Only print the compact machine-friendly benchmark summary JSON.",
    ),
) -> None:
    """
    执行面向 Agent 播报场景的轻量基准测试，用于评估当前 Runtime 是否适合实时语音反馈。

    核心入参:
        host/port/timeout: Runtime 服务地址与请求超时配置。
        role_name: 可选的持久化角色名，用于让基准请求复用指定角色配置。
        text: 基准测试时实际发送给 Runtime 的播报文本。
        iterations: 重复测量次数，用于降低单次抖动对结果的影响。
        json_summary_only: 是否只输出适合机器读取的紧凑摘要 JSON。

    预期输出:
        stdout 输出完整基准报告，或在启用 `--json-summary-only` 时输出压缩后的摘要结果；
        报告中通常包含请求往返耗时、播报完成耗时、估算音频时长以及实时性判断。

    边界异常:
        这是启发式体验基准，不等价于底层声学性能压测；
        当 Runtime 不可达、请求失败或基准执行异常时，命令会以非零状态退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    benchmark_report = _run_client_request(
        run_runtime_benchmark(
            client,
            text=text,
            role_name=role_name,
            iterations=iterations,
        )
    )
    if json_summary_only:
        _print_json(build_benchmark_summary(benchmark_report))
        return
    _print_json(benchmark_report)


@app.command()
def stop(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(5.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    停止 Runtime 进程。

    核心入参:
        host/port/timeout: Runtime 地址和请求超时。

    预期输出:
        stdout 输出 shutdown 响应 JSON。

    边界异常:
        Runtime 不可达时 httpx 异常会使 CLI 非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    _print_json(_run_client_request(client.shutdown()))


@app.command()
def status(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(5.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    查询 Runtime 当前状态。

    核心入参:
        host/port/timeout: Runtime 地址和请求超时。

    预期输出:
        stdout 输出 Runtime 的状态 JSON，包括模型、设备、采样率和队列信息。

    边界异常:
        Runtime 不可达时 httpx 异常会使 CLI 非零退出。
    """

    # 这里复用统一客户端与错误处理路径，确保状态命令和其他 CLI 子命令的输出格式完全一致。
    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    _print_json(_run_client_request(client.status()))


@app.command()
def capabilities(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(5.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    查询当前 Runtime 模型对应的能力说明文档。

    核心入参:
        host/port/timeout: Runtime 地址和请求超时。

    预期输出:
        stdout 直接输出 Markdown 原文，不附带任何 JSON 包装。

    边界异常:
        Runtime 不可达时 httpx 异常会使 CLI 非零退出。
    """

    # 这里直接输出文档原文，保证 CLI 和 HTTP 接口都遵守“只返回文档”的同一契约。
    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    typer.echo(asyncio.run(client.capabilities()), nl=False)


@models_app.command("list")
def models_list() -> None:
    """
    列出所有内置模型在当前硬件上的极简运行结论。

    核心入参:
        本命令无入参。

    预期输出:
        stdout 每行输出一个模型及其是否适合当前硬件的结论。

    边界异常:
        不抛业务异常。
    """

    hardware = detect_system_hardware()
    recommendations = recommend_model_profiles(hardware)
    for recommendation in recommendations:
        typer.echo(_format_model_recommendation_line(recommendation.profile.name, recommendation.status))


@roles_app.command("list")
def roles_list(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(5.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    列出当前模型缓存中的角色。

    核心入参:
        host/port/timeout: Runtime 地址和请求超时。

    预期输出:
        stdout 输出角色列表和当前默认角色。

    边界异常:
        Runtime 不可达时 httpx 异常会使 CLI 非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    _print_json(_run_client_request(client.list_roles()))


@roles_app.command("register")
def roles_register(
    role_name: str = typer.Argument(..., help="Role name to register in the current model cache."),
    audio_path: Optional[str] = typer.Option(
        None,
        "--audio-path",
        help="Reference audio path on the Runtime host. This is an advanced same-machine option.",
    ),
    audio_file: Optional[str] = typer.Option(
        None,
        "--audio",
        "--audio-file",
        help=(
            "Local reference audio file path. This is the recommended role registration input on Linux and Windows; "
            "omit --prompt-text to let Runtime auto-transcribe internally."
        ),
    ),
    audio_data_json: Optional[str] = typer.Option(
        None,
        "--audio-data-json",
        help="JSON array of float samples for in-memory role registration.",
    ),
    audio_data_file: Optional[str] = typer.Option(
        None,
        "--audio-data-file",
        help="Path to a JSON file containing a float sample array for in-memory role registration.",
    ),
    sample_rate: Optional[int] = typer.Option(
        None,
        "--sample-rate",
        help="Required when using in-memory audio registration.",
    ),
    prompt_text: Optional[str] = typer.Option(
        None,
        "--prompt-text",
        help="Optional reference transcript override. Omit to let Runtime auto-transcribe the reference audio internally.",
    ),
    set_default: bool = typer.Option(False, "--set-default", help="Set the registered role as the Runtime default role."),
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    注册一个持久化 Prompt 角色。

    核心入参:
        role_name/audio_path/audio_file/audio_data_json/audio_data_file/sample_rate/prompt_text/set_default/host/port/timeout: 角色注册参数。

    预期输出:
        stdout 输出 created 响应。

    边界异常:
        参数非法或 Runtime 不可达时命令非零退出。
    """

    audio_data_value = _parse_audio_data_source(audio_data_json, audio_data_file)
    audio_source_count = sum(
        source is not None
        for source in (
            audio_path,
            audio_file,
            audio_data_value,
        )
    )
    if audio_source_count != 1:
        raise typer.BadParameter(
            "exactly one of --audio/--audio-file, --audio-path or --audio-data-json/--audio-data-file must be provided"
        )
    if audio_data_value is None and sample_rate is not None:
        raise typer.BadParameter("--sample-rate is only valid with --audio-data-json or --audio-data-file")

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    if audio_file is not None:
        _print_json(
            _run_client_request(
                client.register_role_upload(
                    role_name=role_name,
                    audio_file=audio_file,
                    prompt_text=prompt_text,
                    set_default=set_default,
                )
            )
        )
        return

    _print_json(
        _run_client_request(
            client.register_role(
                role_name=role_name,
                audio_path=audio_path,
                audio_data=audio_data_value,
                sample_rate=sample_rate,
                prompt_text=prompt_text,
                set_default=set_default,
            )
        )
    )


@roles_app.command("delete")
def roles_delete(
    role_names: list[str] = typer.Argument(..., help="One or more cached role names to delete."),
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(10.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    删除一个或多个缓存角色。

    核心入参:
        role_names/host/port/timeout: 删除目标和 Runtime 地址。

    预期输出:
        stdout 输出 deleted 响应。

    边界异常:
        Runtime 不可达时命令非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    payload: str | list[str]
    if len(role_names) == 1:
        payload = role_names[0]
    else:
        payload = role_names
    _print_json(_run_client_request(client.delete_roles(payload)))


@roles_app.command("set-default")
def roles_set_default(
    role_name: str = typer.Argument(..., help="Existing cached role name to set as Runtime default."),
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(10.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    切换 Runtime 默认角色。

    核心入参:
        role_name/host/port/timeout: 默认角色更新参数。

    预期输出:
        stdout 输出 updated 响应。

    边界异常:
        角色不存在或 Runtime 不可达时命令非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    _print_json(_run_client_request(client.set_default_role(role_name)))


@roles_app.command("clear-default")
def roles_clear_default(
    host: str = typer.Option("127.0.0.1", "--host", help="Runtime HTTP host."),
    port: int = typer.Option(8765, "--port", help="Runtime HTTP port."),
    timeout: float = typer.Option(10.0, "--timeout", help="HTTP request timeout seconds."),
) -> None:
    """
    清空 Runtime 默认角色。

    核心入参:
        host/port/timeout: Runtime 地址和请求超时。

    预期输出:
        stdout 输出 updated 响应，默认角色变为 null。

    边界异常:
        Runtime 不可达时命令非零退出。
    """

    client = VoiceClient(base_url=_base_url(host, port), timeout=timeout)
    _print_json(_run_client_request(client.set_default_role(None)))


def main() -> None:
    """
    Typer console script 入口。

    核心入参:
        命令行参数由 Typer 解析。

    预期输出:
        分发到 start/selftest/benchmark/stop/status/capabilities/models/roles 等子命令。

    边界异常:
        Typer 负责把参数错误转换为 CLI 错误提示。
    """

    ensure_utf8_stdio_for_windows()
    app()


if __name__ == "__main__":
    main()
