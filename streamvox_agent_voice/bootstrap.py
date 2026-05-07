"""StreamVox Agent Voice Kit 安装引导模块。"""

from __future__ import annotations

import argparse
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_DEFAULT_STREAMVOX_REPO = "RoversCode/StreamVox"


@dataclass(frozen=True, slots=True)
class SystemProfile:
    """
    描述当前机器与安装决策相关的系统信息。

    核心入参:
        os_name: 规范化后的操作系统名，例如 windows、linux、macos。
        arch: 规范化后的架构名，例如 x86_64、arm64。
        accelerator: 推荐的推理加速方案，例如 cuda、dml、cpu。
        gpu_vendor: 探测到的主要显卡厂商，可为空。
        gpu_name: 探测到的主要显卡名称，可为空。
        python_tag: 当前解释器对应的 Python 标签，例如 cp310、cp311、cp313。

    预期输出:
        供安装器根据平台和显卡状态选择合适的 wheel 与依赖 extra。

    边界异常:
        本数据类不做额外校验；探测逻辑负责保证字段值合理。
    """

    os_name: str
    arch: str
    accelerator: str
    gpu_vendor: str | None
    gpu_name: str | None
    python_tag: str


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    """
    描述 GitHub Release 中的单个安装资产。

    核心入参:
        name: 资产文件名。
        url: 浏览器可下载地址。
        size: 资产大小，单位字节。

    预期输出:
        供安装器筛选最匹配的 StreamVox wheel。

    边界异常:
        本数据类不做额外校验。
    """

    name: str
    url: str
    size: int


@dataclass(frozen=True, slots=True)
class ReleaseSelection:
    """
    描述一次安装决策的最终结果。

    核心入参:
        system: 当前系统探测结果。
        runtime_extra: 应安装的项目 optional extra，可为空。
        wheel_asset: 最终命中的 StreamVox wheel 资产。
        release_name: Release 标识，用于回显给用户或 Agent。

    预期输出:
        供 `--dry-run`、安装日志与后续执行步骤复用。

    边界异常:
        该对象只承载已完成的选择结果，不负责容错。
    """

    system: SystemProfile
    runtime_extra: str | None
    wheel_asset: ReleaseAsset
    release_name: str

    def to_payload(self) -> dict[str, Any]:
        """
        转换为稳定的 JSON 字典。

        核心入参:
            本方法无入参。

        预期输出:
            返回可供 Agent 直接消费的安装决策结果。

        边界异常:
            不抛异常。
        """

        return {
            "system": asdict(self.system),
            "runtime_extra": self.runtime_extra,
            "release_name": self.release_name,
            "wheel_asset": asdict(self.wheel_asset),
        }


def detect_system_profile(*, variant_override: str) -> SystemProfile:
    """
    探测当前系统平台、架构与推荐加速方案。

    核心入参:
        variant_override: 调用方指定的变体；为 auto 时自动探测。

    预期输出:
        返回当前机器的系统画像，供后续选择 wheel 和依赖 extra。

    边界异常:
        不支持的平台会抛出 RuntimeError；探测不到 GPU 时会保守回退到 cpu 或 dml。
    """

    os_name = _normalize_os_name(platform.system())
    arch = _normalize_arch_name(platform.machine())

    if variant_override != "auto":
        accelerator = variant_override
        gpu_vendor, gpu_name = _detect_gpu_details(prefer_accelerator=accelerator)
        return SystemProfile(
            os_name=os_name,
            arch=arch,
            accelerator=accelerator,
            gpu_vendor=gpu_vendor,
            gpu_name=gpu_name,
            python_tag=_current_python_tag(),
        )

    gpu_vendor, gpu_name = _detect_gpu_details(prefer_accelerator="auto")
    if os_name == "windows":
        if gpu_vendor == "nvidia":
            accelerator = "cuda"
        elif gpu_vendor in {"amd", "intel"}:
            accelerator = "dml"
        else:
            accelerator = "cpu"
    elif os_name == "linux":
        accelerator = "cuda" if gpu_vendor == "nvidia" else "cpu"
    else:
        raise RuntimeError(f"unsupported operating system for bootstrap: {os_name}")

    return SystemProfile(
        os_name=os_name,
        arch=arch,
        accelerator=accelerator,
        gpu_vendor=gpu_vendor,
        gpu_name=gpu_name,
        python_tag=_current_python_tag(),
    )


def fetch_release_assets(*, repo: str, release_tag: str) -> tuple[str, list[ReleaseAsset]]:
    """
    从 GitHub Release API 读取可用资产列表。

    核心入参:
        repo: GitHub 仓库名，例如 RoversCode/StreamVox。
        release_tag: Release 标签；latest 表示最新正式版。

    预期输出:
        返回 release 名称和资产列表。

    边界异常:
        网络错误、API 错误或 JSON 非法时抛出 RuntimeError。
    """

    if release_tag == "latest":
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    else:
        api_url = f"https://api.github.com/repos/{repo}/releases/tags/{release_tag}"

    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "streamvox-agent-voice-kit-bootstrap",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        # GitHub API 在某些网络环境里会直接 403；这里回退到 HTML 解析，尽量保证无人值守安装仍可继续。
        return _fetch_release_assets_from_html(repo=repo, release_tag=release_tag)

    release_name = payload.get("tag_name") or payload.get("name") or release_tag
    assets: list[ReleaseAsset] = []
    for item in payload.get("assets", []):
        name = item.get("name")
        url = item.get("browser_download_url")
        size = item.get("size")
        if isinstance(name, str) and isinstance(url, str) and isinstance(size, int):
            assets.append(ReleaseAsset(name=name, url=url, size=size))
    if not assets:
        raise RuntimeError("no downloadable assets were found in the selected GitHub release")
    return str(release_name), assets


def choose_release_selection(*, repo: str, release_tag: str, variant_override: str) -> ReleaseSelection:
    """
    综合系统探测与 Release 资产列表，选出最合适的安装方案。

    核心入参:
        repo: GitHub 仓库名。
        release_tag: Release 标签。
        variant_override: 变体覆盖，支持 auto/cuda/dml/cpu。

    预期输出:
        返回最终的安装决策结果。

    边界异常:
        找不到匹配 wheel 时抛出 RuntimeError。
    """

    system = detect_system_profile(variant_override=variant_override)
    release_name, assets = fetch_release_assets(repo=repo, release_tag=release_tag)
    wheel_asset = choose_streamvox_wheel(assets=assets, system=system)
    runtime_extra = choose_runtime_extra(system=system)
    return ReleaseSelection(
        system=system,
        runtime_extra=runtime_extra,
        wheel_asset=wheel_asset,
        release_name=release_name,
    )


def choose_runtime_extra(*, system: SystemProfile) -> str | None:
    """
    根据系统画像选择本项目的 optional extra。

    核心入参:
        system: 当前系统画像。

    预期输出:
        Windows 返回 windows-cuda/windows-dml/windows-cpu；Linux 当前返回空。

    边界异常:
        不抛异常，未知平台在上游探测阶段已被拦截。
    """

    if system.os_name != "windows":
        return None
    if system.accelerator == "cuda":
        return "windows-cuda"
    if system.accelerator == "dml":
        return "windows-dml"
    return "windows-cpu"


def choose_streamvox_wheel(*, assets: list[ReleaseAsset], system: SystemProfile) -> ReleaseAsset:
    """
    从 Release 资产中选出最适合当前系统的 StreamVox wheel。

    核心入参:
        assets: Release 中的所有资产。
        system: 当前系统画像。

    预期输出:
        返回评分最高的 wheel 资产。

    边界异常:
        没有任何 wheel 或没有匹配项时抛出 RuntimeError。
    """

    wheel_assets = [asset for asset in assets if asset.name.lower().endswith(".whl")]
    if not wheel_assets:
        raise RuntimeError("no wheel assets were found in the selected GitHub release")

    scored_assets: list[tuple[int, ReleaseAsset]] = []
    for asset in wheel_assets:
        score = _score_wheel_asset(asset=asset, system=system)
        if score > -10_000:
            scored_assets.append((score, asset))

    if not scored_assets:
        available_names = ", ".join(asset.name for asset in wheel_assets)
        raise RuntimeError(
            "failed to find a compatible StreamVox wheel for "
            f"{system.os_name}/{system.arch}/{system.accelerator}. available assets: {available_names}"
        )

    scored_assets.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    return scored_assets[0][1]


def install_from_selection(
    *,
    selection: ReleaseSelection,
    repo_root: Path,
    venv_dir: Path,
    skip_sync: bool,
) -> None:
    """
    根据安装决策执行真实安装。

    核心入参:
        selection: 已完成的安装决策。
        repo_root: 当前仓库根目录。
        venv_dir: 目标虚拟环境目录。
        skip_sync: 是否跳过 `uv sync`。

    预期输出:
        在目标虚拟环境中安装本项目依赖和 StreamVox wheel。

    边界异常:
        命令执行失败时抛出 RuntimeError。
    """

    python_exe = ensure_virtualenv(venv_dir=venv_dir)
    if not skip_sync:
        sync_command = ["uv", "sync", "--inexact"]
        if selection.runtime_extra is not None:
            sync_command.extend(["--extra", selection.runtime_extra])
        _run_command(sync_command, cwd=repo_root)

    with tempfile.TemporaryDirectory(prefix="streamvox-bootstrap-") as temp_dir:
        wheel_path = Path(temp_dir) / selection.wheel_asset.name
        _download_file(url=selection.wheel_asset.url, dest=wheel_path)
        install_command = [
            "uv",
            "pip",
            "install",
            "--python",
            str(python_exe),
            str(wheel_path),
        ]
        _run_command(install_command, cwd=repo_root)


def ensure_virtualenv(*, venv_dir: Path) -> Path:
    """
    确保目标虚拟环境存在，并返回其中的 Python 可执行文件。

    核心入参:
        venv_dir: 虚拟环境目录。

    预期输出:
        返回虚拟环境内的 Python 可执行文件路径。

    边界异常:
        创建失败或虚拟环境结构异常时抛出 RuntimeError。
    """

    python_exe = _venv_python_path(venv_dir)
    if python_exe.exists():
        return python_exe

    _run_command([sys.executable, "-m", "venv", str(venv_dir)], cwd=Path.cwd())
    if not python_exe.exists():
        raise RuntimeError(f"virtual environment was created but python was not found: {python_exe}")
    return python_exe


def build_arg_parser() -> argparse.ArgumentParser:
    """
    构建安装引导命令行参数解析器。

    核心入参:
        无。

    预期输出:
        返回 argparse 解析器。

    边界异常:
        不抛异常。
    """

    parser = argparse.ArgumentParser(description="Bootstrap installer for streamvox-agent-voice-kit.")
    parser.add_argument("--repo", default=_DEFAULT_STREAMVOX_REPO, help="GitHub repo containing StreamVox wheel releases.")
    parser.add_argument("--release-tag", default="latest", help="GitHub release tag to use. Defaults to latest.")
    parser.add_argument(
        "--variant",
        choices=("auto", "cuda", "dml", "cpu"),
        default="auto",
        help="Preferred StreamVox wheel variant. Defaults to auto.",
    )
    parser.add_argument("--venv", default=".venv", help="Target virtual environment directory.")
    parser.add_argument("--skip-sync", action="store_true", help="Skip `uv sync --inexact` and only install the StreamVox wheel.")
    parser.add_argument("--dry-run", action="store_true", help="Only print the selected install plan as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    安装引导主入口。

    核心入参:
        argv: 可选参数数组；为空时读取真实命令行。

    预期输出:
        返回 0 表示成功，非 0 表示失败。

    边界异常:
        所有可恢复异常会被转换成 stderr 消息和非零退出码。
    """

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    venv_dir = (repo_root / args.venv).resolve() if not Path(args.venv).is_absolute() else Path(args.venv)
    try:
        selection = choose_release_selection(
            repo=args.repo,
            release_tag=args.release_tag,
            variant_override=args.variant,
        )
        if args.dry_run:
            payload = selection.to_payload()
            payload["venv"] = str(venv_dir)
            payload["repo_root"] = str(repo_root)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        install_from_selection(
            selection=selection,
            repo_root=repo_root,
            venv_dir=venv_dir,
            skip_sync=args.skip_sync,
        )
        print(json.dumps(
            {
                "installed": True,
                "venv": str(venv_dir),
                "runtime_extra": selection.runtime_extra,
                "wheel_asset": selection.wheel_asset.name,
                "next_steps": [
                    "Activate the virtual environment.",
                    "Run `streamvox-runtime doctor --model voxcpm2-gguf`.",
                    "Run `streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker`.",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _normalize_os_name(raw_value: str) -> str:
    """
    规范化操作系统名称。

    核心入参:
        raw_value: `platform.system()` 返回值。

    预期输出:
        返回标准化后的 os 名称。

    边界异常:
        不支持的平台返回小写原值，交由上游统一处理。
    """

    normalized = raw_value.strip().lower()
    if normalized.startswith("win"):
        return "windows"
    if normalized.startswith("linux"):
        return "linux"
    if normalized.startswith("darwin"):
        return "macos"
    return normalized


def _normalize_arch_name(raw_value: str) -> str:
    """
    规范化 CPU 架构名称。

    核心入参:
        raw_value: `platform.machine()` 返回值。

    预期输出:
        返回标准化后的架构名。

    边界异常:
        未命中的值保持小写原样返回。
    """

    normalized = raw_value.strip().lower()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    return aliases.get(normalized, normalized)


def _detect_gpu_details(*, prefer_accelerator: str) -> tuple[str | None, str | None]:
    """
    探测当前机器的主要 GPU 信息。

    核心入参:
        prefer_accelerator: 调用方偏好的加速方案；为 auto 时自动探测。

    预期输出:
        返回 `(gpu_vendor, gpu_name)`。

    边界异常:
        探测失败时返回 `(None, None)`，由上层保守降级。
    """

    if prefer_accelerator == "cuda":
        name = _detect_nvidia_gpu_name()
        return ("nvidia", name) if name is not None else ("nvidia", None)
    if prefer_accelerator == "dml":
        vendor, name = _detect_windows_gpu_vendor()
        return vendor or "amd", name
    if prefer_accelerator == "cpu":
        return None, None

    nvidia_name = _detect_nvidia_gpu_name()
    if nvidia_name is not None:
        return "nvidia", nvidia_name

    if _normalize_os_name(platform.system()) == "windows":
        return _detect_windows_gpu_vendor()
    return None, None


def _detect_nvidia_gpu_name() -> str | None:
    """
    通过 `nvidia-smi` 探测 NVIDIA GPU 名称。

    核心入参:
        无。

    预期输出:
        有 NVIDIA GPU 时返回第一张卡的名称，否则返回空。

    边界异常:
        命令不存在、执行失败或输出为空时返回空。
    """

    if shutil.which("nvidia-smi") is None:
        return None
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        name = line.strip()
        if name:
            return name
    return None


def _detect_windows_gpu_vendor() -> tuple[str | None, str | None]:
    """
    在 Windows 上探测显卡厂商与名称。

    核心入参:
        无。

    预期输出:
        返回 `(vendor, name)`；未命中时返回 `(None, None)`。

    边界异常:
        PowerShell 不存在或命令失败时保守返回空。
    """

    if _normalize_os_name(platform.system()) != "windows":
        return None, None

    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        return None, None
    command = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object -ExpandProperty Name"
    )
    try:
        completed = subprocess.run(
            [powershell, "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None

    if completed.returncode != 0:
        return None, None

    for raw_line in completed.stdout.splitlines():
        name = raw_line.strip()
        if not name:
            continue
        lowered = name.lower()
        if "nvidia" in lowered:
            return "nvidia", name
        if "amd" in lowered or "radeon" in lowered:
            return "amd", name
        if "intel" in lowered or "arc" in lowered:
            return "intel", name
    return None, None


def _score_wheel_asset(*, asset: ReleaseAsset, system: SystemProfile) -> int:
    """
    为单个 wheel 资产计算兼容性评分。

    核心入参:
        asset: 候选 wheel 资产。
        system: 当前系统画像。

    预期输出:
        返回一个整数评分；分数越高说明越匹配。

    边界异常:
        明显不兼容的资产返回极小分，便于上层直接过滤。
    """

    name = asset.name.lower()
    score = 0

    python_compatibility_score = _score_python_compatibility(asset_name=name, python_tag=system.python_tag)
    if python_compatibility_score <= -10_000:
        return python_compatibility_score
    score += python_compatibility_score

    if system.os_name == "windows":
        if not _contains_any(name, ("win", "windows")):
            return -10_000
        score += 50
    elif system.os_name == "linux":
        if not _contains_any(name, ("linux", "manylinux", "ubuntu")):
            return -10_000
        score += 50

    if system.arch == "x86_64":
        if _contains_any(name, ("x86_64", "amd64", "win_amd64", "manylinux")):
            score += 20
    elif system.arch == "arm64":
        if _contains_any(name, ("arm64", "aarch64")):
            score += 20
        else:
            score -= 200

    if system.accelerator == "cuda":
        if _contains_any(name, ("cuda", "cu11", "cu12", "gpu")):
            score += 40
        if _contains_any(name, ("dml", "directml")):
            score -= 100
        if "cpu" in name:
            score -= 50
    elif system.accelerator == "dml":
        if _contains_any(name, ("dml", "directml")):
            score += 40
        if _contains_any(name, ("cuda", "cu11", "cu12")):
            score -= 100
        if "cpu" in name:
            score -= 20
    else:
        if "cpu" in name:
            score += 30
        if _contains_any(name, ("cuda", "cu11", "cu12", "dml", "directml")):
            score -= 100

    # 关键变量：没有出现任何明显加速标签时，允许把它当成“通用 wheel”参与比较。
    if not _contains_any(name, ("cuda", "cu11", "cu12", "dml", "directml", "cpu", "gpu")):
        score += 5

    return score


def _score_python_compatibility(*, asset_name: str, python_tag: str) -> int:
    """
    评估 wheel 与当前 Python 版本标签是否兼容。

    核心入参:
        asset_name: wheel 文件名，小写。
        python_tag: 当前解释器标签，例如 cp310、cp311、cp313。

    预期输出:
        兼容时返回正分，不兼容时返回极小分。

    边界异常:
        如果资产未显式写出 Python 标签，则保守给少量正分并允许继续比较。
    """

    if python_tag in asset_name:
        return 30

    # 关键逻辑：只要 wheel 显式写了别的 CPython 版本而没写当前版本，就认为不兼容。
    explicit_python_tags = set(re.findall(r"cp\d{2,3}|py\d{1,2}", asset_name))
    if explicit_python_tags:
        generic_py3_tags = {"py3"}
        if explicit_python_tags.issubset(generic_py3_tags):
            return 10
        return -10_000

    return 5


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    """
    判断字符串中是否包含任意一个候选子串。

    核心入参:
        value: 被搜索的字符串。
        needles: 候选子串集合。

    预期输出:
        命中任意子串时返回真，否则返回假。

    边界异常:
        不抛异常。
    """

    return any(needle in value for needle in needles)


def _venv_python_path(venv_dir: Path) -> Path:
    """
    返回虚拟环境内 Python 可执行文件的预期路径。

    核心入参:
        venv_dir: 虚拟环境目录。

    预期输出:
        Windows 返回 Scripts/python.exe，Linux 返回 bin/python。

    边界异常:
        不抛异常。
    """

    if _normalize_os_name(platform.system()) == "windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _current_python_tag() -> str:
    """
    返回当前解释器对应的 CPython 版本标签。

    核心入参:
        无。

    预期输出:
        返回形如 cp310、cp311、cp313 的字符串。

    边界异常:
        不抛异常。
    """

    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def _download_file(*, url: str, dest: Path) -> None:
    """
    下载远程文件到本地路径。

    核心入参:
        url: 下载地址。
        dest: 本地目标路径。

    预期输出:
        下载完成后目标文件存在。

    边界异常:
        网络错误或写入失败时抛出 RuntimeError。
    """

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "streamvox-agent-voice-kit-bootstrap"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as file_handle:
            shutil.copyfileobj(response, file_handle)
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"failed to download wheel asset from {url}: {exc}") from exc


def _fetch_release_assets_from_html(*, repo: str, release_tag: str) -> tuple[str, list[ReleaseAsset]]:
    """
    当 GitHub API 不可用时，从公开 Release HTML 页面回退解析 wheel 资产。

    核心入参:
        repo: GitHub 仓库名。
        release_tag: Release 标签；latest 表示最新正式版。

    预期输出:
        返回 release 名称和资产列表。

    边界异常:
        页面请求失败或解析不到 wheel 时抛出 RuntimeError。
    """

    if release_tag == "latest":
        page_url = f"https://github.com/{repo}/releases/latest"
    else:
        page_url = f"https://github.com/{repo}/releases/tag/{release_tag}"

    request = urllib.request.Request(
        page_url,
        headers={"User-Agent": "streamvox-agent-voice-kit-bootstrap"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            html_text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"failed to fetch GitHub release page: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to fetch GitHub release page: {exc.reason}") from exc

    release_name = final_url.rstrip("/").split("/")[-1] or release_tag
    expanded_assets_url = _extract_expanded_assets_url(repo=repo, html_text=html_text)
    if expanded_assets_url is not None:
        html_text = _fetch_html_page(expanded_assets_url)

    asset_pattern = re.compile(
        rf'href="(?P<href>/{re.escape(repo)}/releases/download/[^"]+\.whl)"',
        flags=re.IGNORECASE,
    )
    seen_urls: set[str] = set()
    assets: list[ReleaseAsset] = []
    for match in asset_pattern.finditer(html_text):
        relative_href = html.unescape(match.group("href"))
        absolute_url = f"https://github.com{relative_href}"
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)
        asset_name = relative_href.rsplit("/", 1)[-1]
        assets.append(ReleaseAsset(name=asset_name, url=absolute_url, size=0))

    if not assets:
        raise RuntimeError("failed to parse any wheel assets from the GitHub release page")
    return release_name, assets


def _extract_expanded_assets_url(*, repo: str, html_text: str) -> str | None:
    """
    从 GitHub Release 主页面中提取懒加载资产片段地址。

    核心入参:
        repo: GitHub 仓库名。
        html_text: Release 主页面 HTML。

    预期输出:
        找到 `expanded_assets` 片段时返回绝对地址，否则返回空。

    边界异常:
        不抛异常。
    """

    pattern = re.compile(
        rf'src="(?P<href>https://github\.com/{re.escape(repo)}/releases/expanded_assets/[^"]+)"',
        flags=re.IGNORECASE,
    )
    match = pattern.search(html_text)
    if match is None:
        return None
    return html.unescape(match.group("href"))


def _fetch_html_page(url: str) -> str:
    """
    抓取一个公开 HTML 页面并返回文本内容。

    核心入参:
        url: 页面地址。

    预期输出:
        返回 UTF-8 解码后的 HTML 文本。

    边界异常:
        请求失败时抛出 RuntimeError。
    """

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "streamvox-agent-voice-kit-bootstrap"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"failed to fetch GitHub expanded assets page: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to fetch GitHub expanded assets page: {exc.reason}") from exc


def _run_command(command: list[str], *, cwd: Path) -> None:
    """
    执行一个外部命令，并在失败时抛出可读错误。

    核心入参:
        command: 命令及参数数组。
        cwd: 执行工作目录。

    预期输出:
        命令成功时无返回值。

    边界异常:
        命令不存在、返回码非零或执行异常时抛出 RuntimeError。
    """

    try:
        completed = subprocess.run(command, cwd=str(cwd), check=False)
    except OSError as exc:
        raise RuntimeError(f"failed to execute command {' '.join(command)}: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {' '.join(command)}")


if __name__ == "__main__":
    raise SystemExit(main())
