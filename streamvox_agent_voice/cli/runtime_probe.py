"""Runtime 自检与基准测试辅助逻辑。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any, Awaitable, Callable, TypeVar

from ..client import VoiceClient

_T = TypeVar("_T")

_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD_PATTERN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
_PAUSE_PUNCTUATION = "，。！？；：,.!?;:"
DEFAULT_REALTIME_SELFTEST_TEXT = (
    "现在开始执行实时流式语音自检，这段文本会尽量拉长生成过程，"
    "用于观察每一个音频分片的到达间隔是否会超过上一段音频自身的可播放时长，"
    "如果后续分片明显来得过慢，就说明当前模型在这台机器上存在语音割裂风险。"
)


@dataclass(slots=True)
class TimedProbeStep:
    """
    记录一次 Runtime 探测步骤的结果。
    核心入参:
        name: 当前步骤的人类可读名称。
        duration_ms: 本步骤从发起到收到响应的总耗时，单位毫秒。
        response: Runtime 返回的原始 JSON 负载。
    预期输出:
        `to_payload()` 返回可直接输出给 CLI 的 JSON 对象。
    边界异常:
        本数据类自身不做网络请求，也不主动抛出业务异常。
    """

    name: str
    duration_ms: float
    response: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        """
        把单步探测结果转换为稳定的 CLI 输出结构。
        核心入参:
            本方法无额外入参。
        预期输出:
            返回包含步骤名、耗时和原始响应的字典。
        边界异常:
            不抛出业务异常。
        """

        return {
            "name": self.name,
            "duration_ms": round(self.duration_ms, 3),
            "response": self.response,
        }


async def measure_probe_step(
    name: str,
    request_factory: Callable[[], Awaitable[dict[str, Any]]],
) -> TimedProbeStep:
    """
    对单个异步 Runtime 请求做耗时采样。
    核心入参:
        name: 当前步骤名称。
        request_factory: 返回异步请求协程的零参函数，避免在计时前提前执行。
    预期输出:
        返回一条包含耗时与响应的 `TimedProbeStep`。
    边界异常:
        请求抛出的异常会继续向上传递，由上层 CLI 决定如何打印与退出。
    """

    started_at = perf_counter()
    response = await request_factory()
    finished_at = perf_counter()
    return TimedProbeStep(
        name=name,
        duration_ms=(finished_at - started_at) * 1000,
        response=response,
    )


async def run_runtime_selftest(
    client: VoiceClient,
    *,
    progress_text: str,
    done_text: str,
    role_name: str | None,
    include_speech: bool,
) -> dict[str, Any]:
    """
    执行安装后最小可验收的 Runtime 自检链路。
    核心入参:
        client: 指向目标 Runtime 的 HTTP 客户端。
        progress_text: 自检阶段使用的进度播报文本。
        done_text: 自检阶段使用的完成播报文本。
        role_name: 可选的显式角色名，避免依赖会话默认角色。
        include_speech: 是否真正发送播报事件；关闭时只校验控制面接口。
    预期输出:
        返回包含状态读取、自检步骤、角色状态和播报链路结果的 JSON 对象。
    边界异常:
        任一步骤失败时异常继续向上传递，由 CLI 统一转成错误退出。
    """

    steps: list[TimedProbeStep] = []

    # 先读取最关键的三个只读接口，业务意图是让 Agent 在发声前拿到完整上下文。
    status_step = await measure_probe_step("status", client.status)
    capabilities_step = await measure_probe_step("capabilities", client.capabilities)
    roles_step = await measure_probe_step("roles_list", client.list_roles)
    steps.extend([status_step, capabilities_step, roles_step])

    speech_step_names: list[str] = []
    if include_speech:
        # 先发一条非阻塞 progress，验证队列接收与排队语义。
        progress_step = await measure_probe_step(
            "progress_ack",
            lambda: client.progress(progress_text, wait=False, role_name=role_name),
        )

        # 再发一条 wait=True 的完成事件，验证完整合成链路可以走通。
        done_step = await measure_probe_step(
            "done_completion",
            lambda: client.done(done_text, wait=True, role_name=role_name),
        )
        steps.extend([progress_step, done_step])
        speech_step_names.extend([progress_step.name, done_step.name])

    status_payload = status_step.response
    roles_payload = roles_step.response

    return {
        "status": "ok",
        "runtime": {
            "base_url": client.base_url,
            "timeout_seconds": client.timeout,
        },
        "session": {
            "model": status_payload.get("model"),
            "output": status_payload.get("output"),
            "default_role_name": status_payload.get("default_role_name"),
            "role_count": len(roles_payload.get("roles", [])) if isinstance(roles_payload.get("roles"), list) else None,
        },
        "speech_enabled": include_speech,
        "speech_steps": speech_step_names,
        "checks": [step.to_payload() for step in steps],
    }


async def run_runtime_realtime_selftest(
    client: VoiceClient,
    *,
    text: str,
    role_name: str | None,
) -> dict[str, Any]:
    """
    执行仅关注流式连续性的 Runtime 自检。

    核心入参:
        client: 指向目标 Runtime 的 HTTP 客户端。
        text: 用于触发多 chunk 生成的自检文本。
        role_name: 可选的显式角色名；为空时由 Runtime 自己按默认角色、demo_role 顺序回退。

    预期输出:
        返回包含 chunk 到达时序、断裂判断和建议文案的 JSON 对象。

    边界异常:
        Runtime 不可达、角色不可用或底层探针失败时异常继续向上传递，由 CLI 统一处理。
    """

    response = await client.realtime_selftest(text=text, role_name=role_name)
    return {
        "status": "ok",
        "runtime": {
            "base_url": client.base_url,
            "timeout_seconds": client.timeout,
        },
        "selftest": response,
    }


def build_streaming_selftest_summary(report: dict[str, Any]) -> dict[str, Any]:
    """
    把完整实时自检报告压缩成更适合 CLI 直接展示的摘要结果。

    核心入参:
        report: `run_runtime_realtime_selftest()` 返回的完整报告。

    预期输出:
        返回只保留模型、角色、推理参数和最终实时结论的极简 JSON。

    边界异常:
        缺失字段时按空值降级，不主动抛出 KeyError。
    """

    selftest = report.get("selftest", {})
    measurement = selftest.get("measurement", {})
    inference_parameters = measurement.get("stream_kwargs", {})
    ready_for_realtime = selftest.get("ready_for_realtime")

    return {
        "model": measurement.get("model"),
        "role_name": measurement.get("role_name"),
        "inference_parameters": inference_parameters if isinstance(inference_parameters, dict) else {},
        # 这里把复杂判定统一折叠成人类最关心的一句话，避免 CLI 输出一堆过程细节。
        "realtime": "✅ 流畅实时语音合成。" if ready_for_realtime is True else "❌ 无法实时语音合成。",
    }


async def run_runtime_benchmark(
    client: VoiceClient,
    *,
    text: str,
    role_name: str | None,
    iterations: int,
) -> dict[str, Any]:
    """
    执行面向 Agent 的轻量基准测试。
    核心入参:
        client: 指向目标 Runtime 的 HTTP 客户端。
        text: 用于基准测试的播报文本。
        role_name: 可选的显式角色名。
        iterations: 重复测试次数，用于降低单次抖动的影响。
    预期输出:
        返回接口往返耗时、播报完成耗时、估算语音时长与实时性启发式结论。
    边界异常:
        任一次播报失败会直接向上抛出异常，由 CLI 报告失败原因。
    """

    if iterations < 1:
        raise ValueError("iterations must be at least 1")

    status_step = await measure_probe_step("status", client.status)
    capabilities_step = await measure_probe_step("capabilities", client.capabilities)
    status_payload = status_step.response
    output_backend = status_payload.get("output")
    output_dir = _resolve_output_dir(status_payload)
    known_wav_files = _list_wav_output_files(output_dir) if output_backend == "wav" else set()

    completion_steps: list[dict[str, Any]] = []
    generated_audio_seconds: list[float] = []
    for index in range(iterations):
        # 统一使用 done 作为收尾播报，避免 progress 在队列中被后续同类事件替换。
        completion_step = await measure_probe_step(
            f"done_completion_{index + 1}",
            lambda: client.done(text, wait=True, role_name=role_name),
        )
        completion_payload = completion_step.to_payload()

        # 只有当前 Runtime 会话本来就在写 wav 时，才尝试从真实生成文件读取音频时长。
        generated_audio = None
        if output_backend == "wav" and output_dir is not None:
            generated_audio = _capture_generated_wav_measurement(output_dir, known_wav_files)
            if generated_audio is not None:
                generated_audio_seconds.append(generated_audio["duration_seconds"])
        if generated_audio is not None:
            completion_payload["generated_audio"] = generated_audio

        completion_steps.append(completion_payload)

    completion_durations = [step["duration_ms"] for step in completion_steps]
    speech_estimate = estimate_speech_metrics(text)
    realtime_assessment = build_realtime_assessment(
        average_duration_ms=mean(completion_durations),
        reference_speech_seconds=_select_reference_speech_seconds(
            estimated_seconds=speech_estimate["estimated_speech_seconds"],
            generated_seconds=generated_audio_seconds,
        ),
        reference_method=_select_reference_method(generated_audio_seconds),
        output_backend=output_backend if isinstance(output_backend, str) else None,
    )

    return {
        "status": "ok",
        "runtime": {
            "base_url": client.base_url,
            "timeout_seconds": client.timeout,
            "model": status_payload.get("model"),
            "output": output_backend,
            "output_dir": str(output_dir) if output_dir is not None else None,
        },
        "benchmark": {
            "iterations": iterations,
            "text": text,
            "text_metrics": speech_estimate,
            "generated_audio_summary": build_generated_audio_summary(generated_audio_seconds),
            "network_steps": [
                status_step.to_payload(),
                capabilities_step.to_payload(),
            ],
            "completion_steps": completion_steps,
            "completion_summary": {
                "best_ms": round(min(completion_durations), 3),
                "median_ms": round(median(completion_durations), 3),
                "average_ms": round(mean(completion_durations), 3),
                "worst_ms": round(max(completion_durations), 3),
            },
            "realtime_assessment": realtime_assessment,
        },
    }


def estimate_speech_metrics(text: str) -> dict[str, Any]:
    """
    基于文本内容估算一段语音的自然播放时长。
    核心入参:
        text: 待估算的播报文本。
    预期输出:
        返回字符类型统计与 `estimated_speech_seconds`。
    边界异常:
        空文本会回退到一个保守的最小时长，避免后续实时性比例出现除零。
    """

    stripped_text = text.strip()
    cjk_char_count = len(_CJK_PATTERN.findall(stripped_text))
    latin_word_count = len(_LATIN_WORD_PATTERN.findall(stripped_text))
    number_group_count = len(_NUMBER_PATTERN.findall(stripped_text))
    punctuation_pause_count = sum(1 for character in stripped_text if character in _PAUSE_PUNCTUATION)

    # 这些系数不是声学真值，而是给 Agent 判断“是否接近实时”使用的启发式估算。
    estimated_seconds = 0.0
    estimated_seconds += cjk_char_count / 4.2
    estimated_seconds += latin_word_count / 2.6
    estimated_seconds += number_group_count / 2.4
    estimated_seconds += punctuation_pause_count * 0.18

    if not stripped_text:
        estimated_seconds = 0.8
    elif estimated_seconds == 0.0:
        estimated_seconds = max(len(stripped_text) / 8.0, 0.8)
    else:
        estimated_seconds = max(estimated_seconds, 0.8)

    return {
        "text_length": len(stripped_text),
        "cjk_char_count": cjk_char_count,
        "latin_word_count": latin_word_count,
        "number_group_count": number_group_count,
        "punctuation_pause_count": punctuation_pause_count,
        "estimated_speech_seconds": round(estimated_seconds, 3),
    }


def build_realtime_assessment(
    *,
    average_duration_ms: float,
    reference_speech_seconds: float,
    reference_method: str,
    output_backend: str | None,
) -> dict[str, Any]:
    """
    根据耗时与估算语音时长给出“是否适合实时播报”的启发式判断。
    核心入参:
        average_duration_ms: 多次完成耗时的平均值。
        estimated_speech_seconds: 基于文本长度与停顿估算的自然语音时长。
        output_backend: 当前 Runtime 的输出后端，用于解释结果语义。
    预期输出:
        返回实时系数、阈值、是否达标以及解释文本。
    边界异常:
        估算语音时长小于等于零时，会回退为不可判定状态。
    """

    if reference_speech_seconds <= 0:
        return {
            "method": reference_method,
            "ready_for_realtime": False,
            "realtime_factor": None,
            "threshold": None,
            "notes": [
                "文本过短或估算失败，无法给出实时性结论。",
            ],
        }

    threshold = 1.25 if output_backend == "speaker" else 1.1
    realtime_factor = average_duration_ms / (reference_speech_seconds * 1000)
    ready_for_realtime = realtime_factor <= threshold

    notes = [
        "这是 Runtime 侧的轻量验收基准，不等价于底层声学 profiler。",
    ]
    if reference_method == "generated_wav":
        notes.append("实时性参考时长来自 Runtime 真实生成的 wav 文件。")
    else:
        notes.append("实时性参考时长来自文本内容估算，不是生成音频真值。")
    if output_backend == "speaker":
        notes.append("speaker 输出包含真实播放链路，理想情况下整体耗时通常会接近自然语音时长。")
    elif output_backend in {"null", "wav"}:
        notes.append("null 或 wav 输出主要反映生成与写出链路，不完全等价于真实扬声器播放。")
    else:
        notes.append("未知输出后端会降低结论可信度，建议结合实际播放场景复测。")

    if ready_for_realtime:
        notes.append("当前平均完成耗时落在实时播报阈值内，可作为私人智能助手的候选配置。")
    else:
        notes.append("当前平均完成耗时高于实时播报阈值，建议更换更小模型、调整设备或改用无声输出复测。")

    return {
        "method": reference_method,
        "ready_for_realtime": ready_for_realtime,
        "realtime_factor": round(realtime_factor, 3),
        "threshold": threshold,
        "notes": notes,
    }


def build_benchmark_summary(report: dict[str, Any]) -> dict[str, Any]:
    """
    把完整基准测试报告压缩成更适合 Agent 消费的摘要结果。
    核心入参:
        report: `run_runtime_benchmark()` 返回的完整 JSON 报告。
    预期输出:
        返回聚焦模型、耗时、参考语音时长和实时性结论的紧凑对象。
    边界异常:
        缺失字段时按空值降级，不主动抛出 KeyError。
    """

    runtime = report.get("runtime", {})
    benchmark = report.get("benchmark", {})
    completion_summary = benchmark.get("completion_summary", {})
    text_metrics = benchmark.get("text_metrics", {})
    generated_audio_summary = benchmark.get("generated_audio_summary", {})
    realtime_assessment = benchmark.get("realtime_assessment", {})

    return {
        "status": report.get("status"),
        "model": runtime.get("model"),
        "output": runtime.get("output"),
        "iterations": benchmark.get("iterations"),
        "average_ms": completion_summary.get("average_ms"),
        "median_ms": completion_summary.get("median_ms"),
        "best_ms": completion_summary.get("best_ms"),
        "worst_ms": completion_summary.get("worst_ms"),
        "estimated_speech_seconds": text_metrics.get("estimated_speech_seconds"),
        "generated_audio_seconds_average": generated_audio_summary.get("average_seconds"),
        "generated_audio_measurements": generated_audio_summary.get("measured_iterations"),
        "reference_method": realtime_assessment.get("method"),
        "realtime_factor": realtime_assessment.get("realtime_factor"),
        "ready_for_realtime": realtime_assessment.get("ready_for_realtime"),
        "threshold": realtime_assessment.get("threshold"),
    }


def build_streaming_selftest_report(measurement: dict[str, Any]) -> dict[str, Any]:
    """
    把 Runtime 返回的原始 chunk 时序测量结果整理成可读自检报告。

    核心入参:
        measurement: 由 Runtime 内部探针采集到的原始测量字典。

    预期输出:
        返回包含 chunk 明细、首个断裂点和是否适合实时语音的报告。

    边界异常:
        缺失字段时按保守空值降级，不主动抛出 KeyError。
    """

    chunk_payloads = measurement.get("chunks", [])
    normalized_chunks: list[dict[str, Any]] = []
    first_gap_chunk_index: int | None = None
    first_gap_interval_ms: float | None = None
    first_gap_previous_chunk_duration_ms: float | None = None
    previous_chunk_duration_ms: float | None = None

    if not isinstance(chunk_payloads, list):
        chunk_payloads = []

    # 这里按“下一块到达是否晚于上一块可播放时长”做判定，避免只看整段耗时掩盖中途割裂。
    for raw_chunk in chunk_payloads:
        if not isinstance(raw_chunk, dict):
            continue

        interval_since_previous_ms = _coerce_optional_float(raw_chunk.get("interval_since_previous_ms"))
        current_chunk_index = _coerce_int(raw_chunk.get("index"))
        gap_from_previous = bool(
            previous_chunk_duration_ms is not None
            and interval_since_previous_ms is not None
            and interval_since_previous_ms > previous_chunk_duration_ms
        )

        if gap_from_previous and first_gap_chunk_index is None:
            first_gap_chunk_index = current_chunk_index
            first_gap_interval_ms = round(interval_since_previous_ms, 3) if interval_since_previous_ms is not None else None
            first_gap_previous_chunk_duration_ms = (
                round(previous_chunk_duration_ms, 3) if previous_chunk_duration_ms is not None else None
            )

        normalized_chunk = {
            "index": current_chunk_index,
            "arrival_offset_ms": _coerce_optional_float(raw_chunk.get("arrival_offset_ms")),
            "interval_since_previous_ms": interval_since_previous_ms,
            "sample_count": _coerce_int(raw_chunk.get("sample_count")),
            "chunk_duration_ms": _coerce_optional_float(raw_chunk.get("chunk_duration_ms")),
            "gap_from_previous": gap_from_previous,
        }
        normalized_chunks.append(normalized_chunk)
        previous_chunk_duration_ms = normalized_chunk["chunk_duration_ms"]

    chunk_count = len(normalized_chunks)
    if chunk_count <= 1:
        return {
            "status": "not_enough_chunks",
            "ready_for_realtime": None,
            "summary": "样本文本生成的 chunk 数不足，暂时无法判断是否存在流式断裂。",
            "suggestion": "建议换一段更长的文本重试，确保模型至少生成两个音频分片。",
            "first_gap_chunk_index": None,
            "first_gap_interval_ms": None,
            "previous_chunk_duration_ms": None,
            "measurement": measurement,
            "chunks": normalized_chunks,
        }

    if first_gap_chunk_index is not None:
        return {
            "status": "risk_detected",
            "ready_for_realtime": False,
            "summary": "当前模型流式生成存在断裂风险，推荐使用更小的模型。",
            "suggestion": "后续 chunk 到达时间已经晚于上一段音频可播放时长，连续播报时容易出现割裂。",
            "first_gap_chunk_index": first_gap_chunk_index,
            "first_gap_interval_ms": first_gap_interval_ms,
            "previous_chunk_duration_ms": first_gap_previous_chunk_duration_ms,
            "measurement": measurement,
            "chunks": normalized_chunks,
        }

    return {
        "status": "ok",
        "ready_for_realtime": True,
        "summary": "当前模型流式生成未发现明显断裂风险，可以继续用于实时语音播报。",
        "suggestion": "所有后续 chunk 的到达间隔都没有超过上一段音频的可播放时长。",
        "first_gap_chunk_index": None,
        "first_gap_interval_ms": None,
        "previous_chunk_duration_ms": None,
        "measurement": measurement,
        "chunks": normalized_chunks,
    }


def _resolve_output_dir(status_payload: dict[str, Any]) -> Path | None:
    """
    从 Runtime 状态快照中解析当前输出目录。
    核心入参:
        status_payload: `/status` 返回的 JSON 对象。
    预期输出:
        成功时返回 `Path`，缺失或空值时返回 `None`。
    边界异常:
        这里只做路径解析，不校验目录是否真实存在。
    """

    raw_output_dir = status_payload.get("output_dir")
    if not isinstance(raw_output_dir, str) or not raw_output_dir.strip():
        return None
    return Path(raw_output_dir)


def _coerce_optional_float(value: Any) -> float | None:
    """
    把任意数值字段安全转换成浮点数。

    核心入参:
        value: 待转换的字段值。

    预期输出:
        数值时返回保留三位小数的浮点数；缺失或非法时返回 None。

    边界异常:
        不抛异常，统一按空值降级。
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 3)


def _coerce_int(value: Any) -> int | None:
    """
    把任意数值字段安全转换成整数。

    核心入参:
        value: 待转换的字段值。

    预期输出:
        整数值时返回 int；缺失或非法时返回 None。

    边界异常:
        不抛异常，统一按空值降级。
    """

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _list_wav_output_files(output_dir: Path | None) -> set[Path]:
    """
    枚举输出目录中已经存在的 wav 文件集合。
    核心入参:
        output_dir: Runtime 当前 wav 输出目录。
    预期输出:
        返回当前已存在的 wav 路径集合。
    边界异常:
        目录不存在时返回空集合，避免 benchmark 因首次写目录失败前的状态报错。
    """

    if output_dir is None or not output_dir.exists():
        return set()
    return {path for path in output_dir.glob("*.wav") if path.is_file()}


def _capture_generated_wav_measurement(output_dir: Path, known_wav_files: set[Path]) -> dict[str, Any] | None:
    """
    捕获一次基准请求新生成的 wav 文件，并读取其真实时长。
    核心入参:
        output_dir: 当前 Runtime 的 wav 输出目录。
        known_wav_files: 本轮 benchmark 已知的 wav 文件集合，会被原地更新。
    预期输出:
        成功时返回包含文件路径和真实音频时长的字典。
    边界异常:
        如果本轮没有识别到新文件，则返回 `None`，让上层回退到文本估时。
    """

    current_wav_files = _list_wav_output_files(output_dir)
    new_wav_files = current_wav_files - known_wav_files
    known_wav_files.clear()
    known_wav_files.update(current_wav_files)

    if not new_wav_files:
        return None

    newest_wav = max(new_wav_files, key=lambda candidate: candidate.stat().st_mtime)
    duration_seconds = _read_wav_duration_seconds(newest_wav)
    return {
        "path": str(newest_wav),
        "duration_seconds": duration_seconds,
    }


def _read_wav_duration_seconds(wav_path: Path) -> float:
    """
    读取单个 wav 文件的真实音频时长。
    核心入参:
        wav_path: 由 Runtime 生成的 wav 文件路径。
    预期输出:
        返回以秒为单位的真实时长。
    边界异常:
        文件损坏或 soundfile 无法读取时会抛出底层异常，让 benchmark 明确失败。
    """

    try:
        import soundfile as sf
    except ImportError:
        import wave

        with wave.open(str(wav_path), "rb") as wav_file:
            frame_count = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
        if sample_rate <= 0:
            raise ValueError(f"invalid wav sample rate: {wav_path}")
        return round(frame_count / sample_rate, 3)

    wav_info = sf.info(str(wav_path))
    if wav_info.samplerate <= 0:
        raise ValueError(f"invalid wav sample rate: {wav_path}")
    return round(wav_info.frames / wav_info.samplerate, 3)


def _select_reference_speech_seconds(*, estimated_seconds: float, generated_seconds: list[float]) -> float:
    """
    选择实时性判断应使用的参考语音时长。
    核心入参:
        estimated_seconds: 基于文本的启发式估时。
        generated_seconds: 从真实生成 wav 读取到的时长列表。
    预期输出:
        有真实 wav 时优先使用其平均时长，否则回退到文本估时。
    边界异常:
        空列表会自动回退到估时，不抛出异常。
    """

    if generated_seconds:
        return mean(generated_seconds)
    return estimated_seconds


def _select_reference_method(generated_seconds: list[float]) -> str:
    """
    标记当前实时性判断的参考来源。
    核心入参:
        generated_seconds: 从真实生成 wav 读取到的时长列表。
    预期输出:
        有真实 wav 时返回 `generated_wav`，否则返回 `heuristic_text_estimate`。
    边界异常:
        不抛出异常。
    """

    if generated_seconds:
        return "generated_wav"
    return "heuristic_text_estimate"


def build_generated_audio_summary(generated_audio_seconds: list[float]) -> dict[str, Any]:
    """
    汇总真实生成音频时长测量结果，供完整报告和摘要模式复用。
    核心入参:
        generated_audio_seconds: 每次迭代测得的 wav 时长列表。
    预期输出:
        返回测量次数和平均时长；没有真实测量时明确给出空值。
    边界异常:
        空列表时按空结果降级，不抛出异常。
    """

    if not generated_audio_seconds:
        return {
            "measured_iterations": 0,
            "average_seconds": None,
        }

    return {
        "measured_iterations": len(generated_audio_seconds),
        "average_seconds": round(mean(generated_audio_seconds), 3),
    }
