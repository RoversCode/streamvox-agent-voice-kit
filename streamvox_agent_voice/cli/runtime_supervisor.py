"""streamvox-runtime 启动监督与中断清理工具。"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


_CHILD_SHUTDOWN_GRACE_SECONDS = 3.0
_SUPERVISED_WAIT_POLL_SECONDS = 0.2
_RUNTIME_CHILD_ENV = "STREAMVOX_AGENT_VOICE_RUNTIME_CHILD"
_WINDOWS_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
_WINDOWS_CTRL_BREAK_EVENT = getattr(signal, "CTRL_BREAK_EVENT", None)


class RuntimeShutdownGuard:
    """
    保护 Runtime 子进程内部启动和运行阶段的异常退出。

    核心入参:
        runtime_app: 已创建但可能尚未完成 startup 的 FastAPI 应用。
        server: 当前 uvicorn Server 实例。

    预期输出:
        收到 SIGINT/SIGTERM 或外层异常时，尽力释放 Runtime 资源并清理子进程。

    边界异常:
        清理过程不向外抛出二次异常，避免中断路径再次卡住。
    """

    def __init__(self, runtime_app: Any, server: Any) -> None:
        # 关键变量：_interrupted 用来区分第一次中断和重复中断，重复中断直接强制退出。
        self._interrupted = False
        self._runtime_app = runtime_app
        self._server = server
        self._previous_handlers: dict[int, Any] = {}

    def install(self) -> None:
        """
        安装进程级中断处理器。

        核心入参:
            无。

        预期输出:
            SIGINT/SIGTERM 会进入当前 guard 的清理路径。

        边界异常:
            某些环境不允许设置信号处理器时，沿用 Python 默认异常。
        """

        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle_signal)

    def restore(self) -> None:
        """
        恢复进入 start 命令前的信号处理器。

        核心入参:
            无。

        预期输出:
            当前命令结束后不污染其他测试或嵌入式调用方。

        边界异常:
            信号恢复失败时忽略，退出路径不应再引入新错误。
        """

        for signum, handler in self._previous_handlers.items():
            with contextlib.suppress(Exception):
                signal.signal(signum, handler)

    def shutdown_for_exception(self) -> None:
        """
        外层捕获异常时执行一次常规清理。

        核心入参:
            无。

        预期输出:
            尽量停止 uvicorn、Runtime speaker 和残留子进程。

        边界异常:
            清理异常会被吞掉，原始异常应继续向外传播。
        """

        self._request_uvicorn_exit()
        self._shutdown_initialized_speaker()
        self._terminate_descendants()

    def _handle_signal(self, signum: int, _frame: Any) -> None:
        """
        处理中断信号，并保证命令最终退出。

        核心入参:
            signum: 当前收到的信号编号。
            _frame: Python 信号处理器传入的栈帧，本逻辑不需要使用。

        预期输出:
            第一次中断执行 best-effort 清理后退出；重复中断直接强制清理子进程后退出。

        边界异常:
            不依赖 uvicorn startup 是否完成；startup 阶段尚无 HTTP shutdown 接口时也能退出。
        """

        exit_code = 128 + signum
        if self._interrupted:
            _write_stderr_line("重复收到中断信号，正在强制退出。")
            self._terminate_descendants(grace_seconds=0.0)
            os._exit(exit_code)

        self._interrupted = True
        _write_stderr_line("收到中断信号，正在清理 Runtime 资源。")
        self._request_uvicorn_exit()
        self._shutdown_initialized_speaker()
        self._terminate_descendants()
        os._exit(exit_code)

    def _request_uvicorn_exit(self) -> None:
        """
        通知 uvicorn 停止服务循环。

        核心入参:
            无。

        预期输出:
            已完成 startup 的服务会尽快进入 shutdown；未完成 startup 时也不会阻塞。

        边界异常:
            server 对象状态异常时忽略。
        """

        with contextlib.suppress(Exception):
            self._server.should_exit = True
            self._server.force_exit = True

    def _shutdown_initialized_speaker(self) -> None:
        """
        在 Runtime 已完成初始化时释放 TTS 引擎。

        核心入参:
            无。

        预期输出:
            已初始化的 speaker 执行 shutdown；初始化中的 speaker 交给进程退出释放底层资源。

        边界异常:
            shutdown 失败时忽略，随后仍会清理子进程。
        """

        speaker = getattr(getattr(self._runtime_app, "state", None), "speaker", None)
        if speaker is None or not getattr(speaker, "initialized", False):
            return
        with contextlib.suppress(Exception):
            speaker.shutdown()

    def _terminate_descendants(self, *, grace_seconds: float = _CHILD_SHUTDOWN_GRACE_SECONDS) -> None:
        """
        终止当前进程派生出的全部子进程。

        核心入参:
            grace_seconds: SIGTERM 后等待子进程自行退出的秒数。

        预期输出:
            先 SIGTERM，超时后 SIGKILL，覆盖 StreamVox 初始化阶段派生的 worker。

        边界异常:
            子进程已经退出、权限不足或 /proc 不可读时忽略。
        """

        descendant_pids = collect_descendant_pids(os.getpid())
        for pid in descendant_pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGTERM)

        deadline = time.monotonic() + max(grace_seconds, 0.0)
        while descendant_pids and time.monotonic() < deadline:
            descendant_pids = [pid for pid in descendant_pids if process_exists(pid)]
            if descendant_pids:
                time.sleep(0.05)

        for pid in descendant_pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)


def is_runtime_child_process() -> bool:
    """
    判断当前进程是否是真正运行 Runtime 的子进程。

    核心入参:
        无。

    预期输出:
        子进程返回 True，父进程 supervisor 返回 False。

    边界异常:
        不抛异常。
    """

    return os.getenv(_RUNTIME_CHILD_ENV) == "1"


def run_supervised_start(
    *,
    model: str,
    device: str,
    host: str,
    port: int,
    license_key: str | None,
    license_path: str | None,
    verify_model_sha256: bool,
    default_role_name: str | None,
    streamvox_json: str | None,
    streamvox_json_file: str | None,
    audio_backend: str,
    output_dir: str,
) -> int:
    """
    在父进程中监督真正的 Runtime 子进程。

    核心入参:
        model/device/host/port/license/default_role_name/streamvox_json/audio_backend/output_dir: start 命令的完整启动参数。

    预期输出:
        返回子进程最终退出码；收到中断时会先清理子进程组再返回 130/143。

    边界异常:
        子进程启动失败时沿用 subprocess 异常。
    """

    child_command = build_child_start_command(
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
    child_env = dict(os.environ)
    child_env[_RUNTIME_CHILD_ENV] = "1"

    process = subprocess.Popen(
        child_command,
        **build_child_popen_kwargs(env=child_env),
    )
    supervisor = RuntimeProcessSupervisor(process)
    supervisor.install()
    try:
        return wait_for_supervised_process_exit(process)
    finally:
        supervisor.restore()


def wait_for_supervised_process_exit(
    process: subprocess.Popen[Any],
    *,
    poll_seconds: float = _SUPERVISED_WAIT_POLL_SECONDS,
) -> int:
    """
    以短轮询方式等待 Runtime 子进程退出。

    核心入参:
        process: 被监督的 Runtime 子进程。
        poll_seconds: 单次等待超时时间，默认使用较短轮询间隔。

    预期输出:
        子进程退出后返回它的退出码。

    边界异常:
        不吞掉除 `TimeoutExpired` 之外的异常；这样启动失败、句柄异常等问题仍然会直接暴露。
    """

    # Windows 上直接 `process.wait()` 可能长时间卡在底层等待对象上，导致 Ctrl+C 不能稳定回到 Python 层。
    # 这里改成短轮询，让父监督进程持续有机会处理 SIGINT/SIGTERM，再去收敛整个 Runtime 子进程树。
    resolved_poll_seconds = max(float(poll_seconds), 0.05)
    while True:
        try:
            return process.wait(timeout=resolved_poll_seconds)
        except subprocess.TimeoutExpired:
            continue


def build_child_start_command(
    *,
    model: str,
    device: str,
    host: str,
    port: int,
    license_key: str | None,
    license_path: str | None,
    verify_model_sha256: bool,
    default_role_name: str | None,
    streamvox_json: str | None,
    streamvox_json_file: str | None,
    audio_backend: str,
    output_dir: str,
) -> list[str]:
    """
    构造真正执行 Runtime 的子进程命令。

    核心入参:
        model/device/host/port/license/default_role_name/streamvox_json/audio_backend/output_dir: start 命令参数。

    预期输出:
        返回可传给 subprocess.Popen 的 argv。

    边界异常:
        不抛业务异常。
    """

    command = [
        sys.executable,
        "-m",
        "streamvox_agent_voice.cli.runtime",
        "start",
        "--model",
        model,
        "--device",
        device,
        "--host",
        host,
        "--port",
        str(port),
        "--output",
        audio_backend,
        "--output-dir",
        output_dir,
    ]
    if license_key is not None:
        command.extend(["--license-key", license_key])
    if license_path is not None:
        command.extend(["--license-path", license_path])
    if verify_model_sha256:
        command.append("--verify-model-sha256")
    if default_role_name is not None:
        command.extend(["--default-role-name", default_role_name])
    if streamvox_json is not None:
        command.extend(["--streamvox-json", streamvox_json])
    if streamvox_json_file is not None:
        command.extend(["--streamvox-json-file", streamvox_json_file])
    return command


def build_child_popen_kwargs(*, env: dict[str, str]) -> dict[str, Any]:
    """
    构造启动 Runtime 子进程时需要传给 `subprocess.Popen(...)` 的平台参数。

    核心入参:
        env: 子进程环境变量字典。

    预期输出:
        Linux / macOS 返回 `start_new_session=True`；
        Windows 返回 `CREATE_NEW_PROCESS_GROUP`，以便父进程后续发送 CTRL_BREAK_EVENT 并收敛整棵进程树。

    边界异常:
        不抛业务异常；仅返回可直接透传给 `subprocess.Popen(...)` 的参数字典。
    """

    popen_kwargs: dict[str, Any] = {"env": env}

    # Windows 没有 POSIX 风格的 session / process group 语义，必须显式创建新的 console process group，
    # 后续父进程才能优先发送 CTRL_BREAK_EVENT 做温和收敛。
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = _WINDOWS_CREATE_NEW_PROCESS_GROUP
        return popen_kwargs

    # 非 Windows 维持原有 start_new_session 行为，确保 killpg 可以只影响本次 Runtime 子树。
    popen_kwargs["start_new_session"] = True
    return popen_kwargs


class RuntimeProcessSupervisor:
    """
    监督 Runtime 子进程组，并在中断时强制收敛退出。

    核心入参:
        process: 通过平台对应的独立进程组参数启动的 Runtime 子进程。

    预期输出:
        SIGINT/SIGTERM 到达父进程时，终止整个 Runtime 进程组。

    边界异常:
        子进程已经退出、进程组不存在或权限不足时忽略清理错误。
    """

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        # 关键变量：process 是唯一真正加载模型的子进程，父进程只负责监督它。
        self._process = process
        self._interrupted = False
        self._previous_handlers: dict[int, Any] = {}

    def install(self) -> None:
        """
        安装父进程中断处理器。

        核心入参:
            无。

        预期输出:
            Ctrl+C 由父进程接管，并转化成对子进程组的清理。

        边界异常:
            信号安装失败时沿用 Python 默认异常。
        """

        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle_signal)

    def restore(self) -> None:
        """
        恢复父进程进入 supervisor 前的信号处理器。

        核心入参:
            无。

        预期输出:
            不污染同一 Python 进程内后续测试或嵌入式调用。

        边界异常:
            恢复失败时忽略。
        """

        for signum, handler in self._previous_handlers.items():
            with contextlib.suppress(Exception):
                signal.signal(signum, handler)

    def _handle_signal(self, signum: int, _frame: Any) -> None:
        """
        父进程收到中断时清理 Runtime 子进程组。

        核心入参:
            signum: 当前信号。
            _frame: Python 信号回调栈帧，本逻辑不使用。

        预期输出:
            第一次中断执行 SIGTERM + SIGKILL 收敛；重复中断立即 SIGKILL。

        边界异常:
            不抛异常，直接以 shell 约定退出码结束父进程。
        """

        exit_code = 128 + signum
        if self._interrupted:
            _write_stderr_line("重复收到中断信号，正在强制结束 Runtime 子进程。")
            self._terminate_runtime_process(grace_seconds=0.0)
            os._exit(exit_code)

        self._interrupted = True
        _write_stderr_line("收到中断信号，正在结束 Runtime 子进程组。")
        self._terminate_runtime_process()
        os._exit(exit_code)

    def _terminate_runtime_process(self, *, grace_seconds: float = _CHILD_SHUTDOWN_GRACE_SECONDS) -> None:
        """
        终止 Runtime 子进程所在进程组。

        核心入参:
            grace_seconds: SIGTERM 后等待子进程组退出的秒数。

        预期输出:
            子进程组先收到 SIGTERM，超时未退出再收到 SIGKILL。

        边界异常:
            进程已退出或进程组不存在时忽略。
        """

        if self._process.poll() is not None:
            return

        # Windows 不支持 os.killpg / SIGKILL，需要改走 CTRL_BREAK_EVENT + terminate/taskkill 的分支。
        if sys.platform == "win32":
            self._terminate_runtime_process_windows(grace_seconds=grace_seconds)
            return

        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self._process.pid, signal.SIGTERM)

        try:
            self._process.wait(timeout=max(grace_seconds, 0.0))
            return
        except subprocess.TimeoutExpired:
            pass

        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self._process.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self._process.wait(timeout=1.0)

    def _terminate_runtime_process_windows(self, *, grace_seconds: float) -> None:
        """
        在 Windows 上终止 Runtime 子进程及其后代进程。

        核心入参:
            grace_seconds: 温和终止后等待子进程自行退出的秒数。

        预期输出:
            先尝试向独立进程组发送 CTRL_BREAK_EVENT；
            若超时仍未退出，再退化到 terminate，最终使用 `taskkill /T /F` 强制收敛整个进程树。

        边界异常:
            Windows 控制台事件不可用、taskkill 缺失或目标进程已退出时都忽略，避免在中断路径上引入新异常。
        """

        # 优先发送 CTRL_BREAK_EVENT，让 Python/uvicorn/模型子任务有机会沿正常清理路径退出。
        if _WINDOWS_CTRL_BREAK_EVENT is not None:
            with contextlib.suppress(Exception):
                self._process.send_signal(_WINDOWS_CTRL_BREAK_EVENT)
            with contextlib.suppress(subprocess.TimeoutExpired):
                self._process.wait(timeout=max(grace_seconds, 0.0))
                return

        # 如果控制台事件没有生效，再尝试普通 terminate；这样比一上来 taskkill 更温和。
        with contextlib.suppress(Exception):
            self._process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            self._process.wait(timeout=max(grace_seconds, 0.0))
            return

        _force_kill_process_tree_windows(self._process.pid)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self._process.wait(timeout=1.0)


def collect_descendant_pids(root_pid: int) -> list[int]:
    """
    收集指定进程的全部后代进程。

    核心入参:
        root_pid: 根进程 PID，通常是当前 CLI 进程。

    预期输出:
        返回按父子层级发现的后代 PID 列表。

    边界异常:
        非 Linux 或 /proc 不可读时返回空列表。
    """

    parent_map = read_parent_map()
    pending = [root_pid]
    descendants: list[int] = []
    while pending:
        parent_pid = pending.pop(0)
        children = [pid for pid, ppid in parent_map.items() if ppid == parent_pid and pid != root_pid]
        descendants.extend(children)
        pending.extend(children)
    return descendants


def read_parent_map() -> dict[int, int]:
    """
    读取当前平台可见的 pid -> ppid 映射。

    核心入参:
        无。

    预期输出:
        Linux / macOS 优先读取 `/proc`；
        Windows 通过 PowerShell 查询 `Win32_Process`，统一返回父子关系映射。

    边界异常:
        任一平台的数据源不可用时返回空字典，而不是让中断清理路径失败。
    """

    if sys.platform == "win32":
        return read_windows_parent_map()
    return read_proc_parent_map()


def read_proc_parent_map() -> dict[int, int]:
    """
    从 /proc 读取 pid -> ppid 映射。

    核心入参:
        无。

    预期输出:
        返回当前系统可见进程的父子关系。

    边界异常:
        单个进程读取失败时跳过该进程；整体不可读时返回空字典。
    """

    proc_dir = Path("/proc")
    if not proc_dir.exists():
        return {}

    parent_map: dict[int, int] = {}
    for child in proc_dir.iterdir():
        if not child.name.isdigit():
            continue
        stat_path = child / "stat"
        try:
            raw_stat = stat_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ppid = parse_proc_stat_ppid(raw_stat)
        if ppid is not None:
            parent_map[int(child.name)] = ppid
    return parent_map


def read_windows_parent_map() -> dict[int, int]:
    """
    在 Windows 上读取 pid -> ppid 映射。

    核心入参:
        无。

    预期输出:
        返回当前系统可见进程的父子关系，供 `collect_descendant_pids(...)` 做递归遍历。

    边界异常:
        PowerShell 不可用、WMI 读取失败或输出格式异常时返回空字典。
    """

    completed = _run_best_effort_command(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,ParentProcessId | "
            "ConvertTo-Csv -NoTypeInformation",
        ]
    )
    if completed is None or completed.returncode != 0:
        return {}

    parent_map: dict[int, int] = {}
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('"ProcessId"'):
            continue
        fields = [field.strip().strip('"') for field in line.split(",", 1)]
        if len(fields) != 2:
            continue
        try:
            process_id = int(fields[0])
            parent_process_id = int(fields[1])
        except ValueError:
            continue
        parent_map[process_id] = parent_process_id
    return parent_map


def parse_proc_stat_ppid(raw_stat: str) -> int | None:
    """
    解析 /proc/<pid>/stat 中的 ppid 字段。

    核心入参:
        raw_stat: stat 文件原始内容。

    预期输出:
        成功时返回父进程 PID；格式不符合预期时返回 None。

    边界异常:
        不抛异常。
    """

    close_paren_index = raw_stat.rfind(")")
    if close_paren_index < 0:
        return None
    fields_after_command = raw_stat[close_paren_index + 2 :].split()
    if len(fields_after_command) < 2:
        return None
    try:
        return int(fields_after_command[1])
    except ValueError:
        return None


def process_exists(pid: int) -> bool:
    """
    判断进程是否仍然存在。

    核心入参:
        pid: 目标进程 PID。

    预期输出:
        存在返回 True，不存在返回 False。

    边界异常:
        无权限访问时按仍存在处理，避免误判后跳过 SIGKILL。
    """

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _write_stderr_line(message: str) -> None:
    """
    向 stderr 写入一行状态信息。

    核心入参:
        message: 需要提示用户的文本。

    预期输出:
        stderr 可写时输出并刷新。

    边界异常:
        stderr 异常时忽略。
    """

    with contextlib.suppress(Exception):
        sys.stderr.write(f"\n{message}\n")
        sys.stderr.flush()


def _force_kill_process_tree_windows(pid: int) -> None:
    """
    在 Windows 上强制终止指定进程及其整棵子进程树。

    核心入参:
        pid: 根进程 PID。

    预期输出:
        调用 `taskkill /PID <pid> /T /F`，确保 Runtime 退出后不会遗留模型子进程。

    边界异常:
        `taskkill` 不可用、目标已退出或系统拒绝访问时忽略，并退化到单进程 kill。
    """

    completed = _run_best_effort_command(["taskkill", "/PID", str(pid), "/T", "/F"])
    if completed is not None and completed.returncode == 0:
        return

    # taskkill 失败时退化到单进程 kill，至少避免父监督进程自己一直挂住。
    with contextlib.suppress(Exception):
        os.kill(pid, signal.SIGTERM)


def _run_best_effort_command(argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    """
    执行一个只服务于清理/探测路径的本地命令。

    核心入参:
        argv: 要执行的命令及参数。

    预期输出:
        成功时返回 `CompletedProcess[str]`，供调用方读取退出码和输出文本。

    边界异常:
        命令不存在或无法启动时返回 None，避免把辅助命令失败升级成主流程失败。
    """

    try:
        return subprocess.run(argv, check=False, capture_output=True, text=True)
    except OSError:
        return None
