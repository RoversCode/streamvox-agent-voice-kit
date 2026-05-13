"""面向 Agent 和样板应用的异步 Python 客户端。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from .events import VoiceEvent
from .policy import HIGH_LEVEL_POLICY_NAMES, resolve_voice_policy


class VoiceClient:
    """
    StreamVox Runtime 的 HTTP 客户端。

    核心入参:
        base_url: Runtime 本地 HTTP 地址，默认指向 127.0.0.1:8765。
        timeout: 单次 HTTP 请求超时时间；wait=True 时调用方可传更长超时。

    预期输出:
        say/speak_intent/error/interrupt 返回 Runtime 的 JSON 响应，stop/status 返回控制接口响应。
        error 只是语义标签，不隐式打断；interrupt 才是控制快捷方法。

    边界异常:
        Runtime 不可达或返回非 2xx 时，httpx 会抛出网络或 HTTPStatusError。
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # 关键变量：base_url 在构造时去掉尾部斜杠，避免拼接路径时出现双斜杠。
        self.base_url = base_url.rstrip("/")

        # 关键变量：timeout 统一传给 httpx，CLI 和 SDK 使用同一套超时策略。
        self.timeout = timeout

        # 关键变量：transport 仅用于测试或嵌入式场景，默认仍由 httpx 自己管理网络连接。
        self.transport = transport

    async def say(
        self,
        text: str,
        *,
        intent: str = "progress",
        action: str = "enqueue",
        interrupt: bool = False,
        wait: bool = False,
        role_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        发送一条语音播报事件。

        核心入参:
            text: 需要播报的文本。
            intent: 语义类型，默认 progress。
            action: 显式队列控制策略，默认 enqueue。
            interrupt: 是否打断当前播报。
            wait: 是否等待 Runtime 播报完成。
            role_name: 单次事件覆盖 Runtime 默认角色的角色名。
            metadata: 附加信息，第一版只透传不解释。

        预期输出:
            返回 Runtime JSON 响应；不会隐式设置 interrupt。

        边界异常:
            本方法会先本地校验 VoiceEvent；HTTP 层失败由 httpx 抛出。
        """

        return await self._send_event(
            text,
            intent=intent,
            action=action,
            interrupt=interrupt,
            wait=wait,
            role_name=role_name,
            metadata=metadata,
        )

    async def _send_event(
        self,
        text: str,
        *,
        intent: str,
        action: str,
        interrupt: bool,
        wait: bool,
        role_name: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        发送内部事件请求。

        核心入参:
            text/intent/action/interrupt/wait/role_name/metadata: Runtime 底层协议字段。

        预期输出:
            返回 Runtime JSON 响应；priority 只作为 Runtime 事件结构占位，不在 Client 层开放或选择。

        边界异常:
            本方法会先本地校验 VoiceEvent；HTTP 层失败由 httpx 抛出。
        """

        # 在客户端侧先构造事件，尽早发现非法 intent/text/action，减少 Runtime 噪声。
        # 关键变量：merged_metadata 统一承载公开 metadata 与角色覆盖。
        merged_metadata = dict(metadata or {})
        if role_name is not None:
            merged_metadata["role_name"] = role_name

        voice_event = VoiceEvent(
            intent=intent,
            text=text,
            action=action,
            interrupt=interrupt,
            wait=wait,
            metadata=merged_metadata,
        )
        voice_event.validate()  # 参数检验
        return await self._post_json("/events", voice_event.to_payload())

    async def speak_intent(
        self,
        intent: str,
        text: str,
        *,
        wait: bool = False,
        role_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        按高层意图名称统一发送播报。

        核心入参:
            intent: `info/progress/warning/urgent/done` 之一。
            text: 需要播报的文本。
            wait: 是否等待播报完成。
            role_name: 单次事件覆盖 Runtime 默认角色的角色名。
            metadata: 附加信息，第一版只透传不解释。

        预期输出:
            返回 Runtime JSON 响应；CLI 和宿主 Skill 都可复用这一个入口。

        边界异常:
            未知 intent 会抛出 ValueError。
        """

        normalized_intent = intent.strip().lower()
        if normalized_intent not in HIGH_LEVEL_POLICY_NAMES:
            raise ValueError(f"unsupported high-level intent: {intent}")
        
        # 关键变量：policy 是高层意图的唯一映射来源，避免 Client 和 CLI 各自复制一份规则后漂移。
        policy = resolve_voice_policy(normalized_intent)

        return await self._send_event(
            text,
            **policy.to_request_kwargs(),
            wait=wait,
            role_name=role_name,
            metadata=metadata,
        )


    async def error(
        self,
        text: str,
        *,
        wait: bool = False,
        role_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        发送错误播报。

        核心入参:
            text: 错误摘要。
            wait: 是否等待播报完成。
            role_name: 单次事件覆盖 Runtime 默认角色的角色名。
            metadata: 附加信息，第一版只透传不解释。

        预期输出:
            返回 Runtime JSON 响应；本方法仍保持原始语义事件，不隐式打断。

        边界异常:
            同 say。
        """

        # error 只是语义标签，不隐式打断队列；调用方需要打断时应显式使用 interrupt(...)。
        return await self._send_event(
            text,
            intent="warning",
            action="enqueue",
            interrupt=False,
            wait=wait,
            role_name=role_name,
            metadata=metadata,
        )

    async def interrupt(
        self,
        text: str,
        *,
        wait: bool = False,
        role_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        发送打断播报。

        核心入参:
            text: 打断时需要立即说出的内容。
            wait: 是否等待播报完成。
            role_name: 单次事件覆盖 Runtime 默认角色的角色名。
            metadata: 附加信息，第一版只透传不解释。

        预期输出:
            返回 Runtime JSON 响应。

        边界异常:
            同 say。
        """

        return await self._send_event(
            text,
            intent="urgent",
            action="interrupt",
            interrupt=True,
            wait=wait,
            role_name=role_name,
            metadata=metadata,
        )

    async def stop(self) -> dict[str, Any]:
        """
        停止当前播报并清空普通等待队列。

        核心入参:
            本方法没有入参。

        预期输出:
            返回 Runtime 控制接口响应。

        边界异常:
            Runtime 不可达或返回非 2xx 时由 httpx 抛出。
        """

        return await self._post_json("/stop", {})

    async def shutdown(self) -> dict[str, Any]:
        """
        请求 Runtime 进程退出。

        核心入参:
            本方法没有入参。

        预期输出:
            返回 Runtime 控制接口响应；服务会在响应后异步退出。

        边界异常:
            Runtime 不可达或返回非 2xx 时由 httpx 抛出。
        """

        return await self._post_json("/shutdown", {})

    async def status(self) -> dict[str, Any]:
        """
        查询 Runtime 状态。

        核心入参:
            本方法没有入参。

        预期输出:
            返回包含 queue/model/device 等状态字段的 JSON 字典。

        边界异常:
            Runtime 不可达或返回非 2xx 时由 httpx 抛出。
        """

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.get(f"{self.base_url}/status")
            response.raise_for_status()
            return response.json()

    async def capabilities(self) -> dict[str, Any]:
        """
        查询当前 Runtime 会话的能力快照。

        核心入参:
            本方法没有入参。

        预期输出:
            返回当前模型能力、Prompt 能力和默认角色等会话状态。

        边界异常:
            Runtime 不可达或返回非 2xx 时由 httpx 抛出。
        """

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.get(f"{self.base_url}/capabilities")
            response.raise_for_status()
            return response.json()

    async def skill_describe(self) -> dict[str, Any]:
        """
        查询 Runtime 面向基础 Skill 的聚合事实快照。

        核心入参:
            本方法没有入参。

        预期输出:
            返回 `/skill/describe` 的稳定 JSON 结构。

        边界异常:
            Runtime 不可达或返回非 2xx 时由 httpx 抛出。
        """

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.get(f"{self.base_url}/skill/describe")
            response.raise_for_status()
            return response.json()

    async def skill_fingerprint(self) -> dict[str, Any]:
        """
        查询 Runtime 面向基础 Skill 的最小指纹。

        核心入参:
            本方法没有入参。

        预期输出:
            返回只包含 `fingerprint` 的 JSON。

        边界异常:
            Runtime 不可达或返回非 2xx 时由 httpx 抛出。
        """

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.get(f"{self.base_url}/skill/fingerprint")
            response.raise_for_status()
            return response.json()

    async def realtime_selftest(
        self,
        *,
        text: str,
        role_name: str | None = None,
    ) -> dict[str, Any]:
        """
        调用 Runtime 的流式连续性自检接口。

        核心入参:
            text: 用于触发多个流式 chunk 的测试文本。
            role_name: 可选角色名；为空时由 Runtime 按默认角色和 demo_role 顺序回退。

        预期输出:
            返回 Runtime 侧整理好的实时自检报告。

        边界异常:
            Runtime 不可达、参数非法或 HTTP 非 2xx 时抛出异常。
        """

        payload: dict[str, Any] = {
            "text": text,
        }
        if role_name is not None:
            payload["role_name"] = role_name
        return await self._post_json("/selftest/realtime", payload)

    async def register_role(
        self,
        *,
        role_name: str,
        prompt_text: str | None = None,
        audio_path: str | None = None,
        audio_data: list[float] | tuple[float, ...] | None = None,
        sample_rate: int | None = None,
        set_default: bool = False,
        persist: bool = True,
    ) -> dict[str, Any]:
        """
        向 Runtime 注册一个可复用角色资产。

        核心入参:
            role_name: 角色名。
            audio_path: Runtime 本机可访问的单参考音频路径。
            audio_data: 内存中的单参考音频数组。
            sample_rate: 内存音频采样率。
            prompt_text: 与参考音频对齐的参考文本；缺失时由 Runtime 自动 ASR。
            set_default: 注册成功后是否立即切为默认角色。
            persist: 当前 Runtime 资产工作流要求为 True。

        预期输出:
            返回 Runtime 的 created 响应。

        边界异常:
            Runtime 不可达、参数非法或 HTTP 非 2xx 时抛出异常。
        """

        payload = self._build_role_registration_payload(
            role_name=role_name,
            audio_path=audio_path,
            audio_data=audio_data,
            sample_rate=sample_rate,
            prompt_text=prompt_text,
            set_default=set_default,
            persist=persist,
        )
        return await self._post_json("/roles", payload)

    async def register_role_upload(
        self,
        *,
        role_name: str,
        audio_file: str | Path,
        prompt_text: str | None = None,
        set_default: bool = False,
        persist: bool = True,
    ) -> dict[str, Any]:
        """
        通过 multipart 上传本地音频文件注册角色。

        核心入参:
            role_name: 角色名。
            audio_file: 当前客户端机器上的音频文件路径。
            prompt_text: 可选参考文本；缺失时由 Runtime 自动 ASR。
            set_default: 注册成功后是否立即切为默认角色。
            persist: 当前 Runtime 资产工作流要求为 True。

        预期输出:
            返回 Runtime 的 created 响应。

        边界异常:
            文件不存在、参数非法或 HTTP 非 2xx 时抛出异常。
        """

        audio_file_path = Path(audio_file)
        if not audio_file_path.is_file():
            raise ValueError(f"audio_file does not exist: {audio_file_path}")

        data: dict[str, str] = {
            "role_name": role_name,
            "persist": "true" if persist else "false",
            "set_default": "true" if set_default else "false",
        }
        if prompt_text is not None:
            data["prompt_text"] = prompt_text

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            with audio_file_path.open("rb") as audio_handle:
                response = await client.post(
                    f"{self.base_url}/roles/upload",
                    data=data,
                    files={"audio_file": (audio_file_path.name, audio_handle, "application/octet-stream")},
                )
            response.raise_for_status()
            return response.json()

    def _build_role_registration_payload(
        self,
        *,
        role_name: str,
        audio_path: str | None,
        audio_data: list[float] | tuple[float, ...] | None,
        sample_rate: int | None,
        prompt_text: str | None,
        set_default: bool,
        persist: bool,
    ) -> dict[str, Any]:
        """
        构造角色注册请求载荷。

        核心入参:
            role_name/audio_path/audio_data/sample_rate/prompt_text/set_default/persist: 角色注册参数。

        预期输出:
            返回适合发送给 `/roles` 的 JSON 字典。

        边界异常:
            音频来源冲突、采样率缺失或音频数组类型错误时抛出 ValueError。
        """

        if (audio_path is None) == (audio_data is None):
            raise ValueError("exactly one of audio_path or audio_data must be provided")

        payload: dict[str, Any] = {
            "role_name": role_name,
            "persist": persist,
            "set_default": set_default,
        }

        if prompt_text is not None:
            if not isinstance(prompt_text, str) or not prompt_text.strip():
                raise ValueError("prompt_text must be a non-empty string")
            payload["prompt_text"] = prompt_text.strip()

        if audio_path is not None:
            if not isinstance(audio_path, str) or not audio_path.strip():
                raise ValueError("audio_path must be a non-empty string")
            if sample_rate is not None:
                raise ValueError("sample_rate is only valid when audio_data is provided")
            payload["audio_path"] = audio_path.strip()
        else:
            normalized_audio_data = self._normalize_audio_data(audio_data)
            if sample_rate is None:
                raise ValueError("sample_rate is required when audio_data is provided")
            payload["audio_data"] = normalized_audio_data
            payload["sample_rate"] = sample_rate

        return payload

    async def list_roles(self) -> dict[str, Any]:
        """
        查询当前模型缓存中的角色列表。

        核心入参:
            本方法无入参。

        预期输出:
            返回当前模型、默认角色和角色列表。

        边界异常:
            Runtime 不可达或返回非 2xx 时由 httpx 抛出。
        """

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.get(f"{self.base_url}/roles")
            response.raise_for_status()
            return response.json()

    async def delete_roles(self, role_names: str | list[str]) -> dict[str, Any]:
        """
        删除当前模型缓存中的一个或多个角色。

        核心入参:
            role_names: 单个角色名或角色名列表。

        预期输出:
            返回 Runtime 的 deleted 响应。

        边界异常:
            Runtime 不可达或返回非 2xx 时由 httpx 抛出。
        """

        return await self._post_json("/roles/delete", {"role_names": role_names})

    async def set_default_role(self, role_name: str | None) -> dict[str, Any]:
        """
        更新 Runtime 会话级默认角色。

        核心入参:
            role_name: 新默认角色名；传 None 表示清空默认角色。

        预期输出:
            返回 Runtime 的 updated 响应。

        边界异常:
            Runtime 不可达或返回非 2xx 时由 httpx 抛出。
        """

        return await self._post_json("/session/default-role", {"role_name": role_name})

    def _normalize_audio_data(
        self,
        audio_data: list[float] | tuple[float, ...] | None,
    ) -> list[float]:
        """
        规范化内存音频数组。

        核心入参:
            audio_data: Python 列表或元组形式的音频采样数组。

        预期输出:
            返回适合 JSON 序列化的一维浮点列表。

        边界异常:
            空数组或包含非数值元素时抛出 ValueError。
        """

        if audio_data is None:
            raise ValueError("audio_data must not be null when selected as the audio source")

        normalized_audio_data = list(audio_data)
        if not normalized_audio_data:
            raise ValueError("audio_data must be a non-empty sequence of numbers")

        normalized_samples: list[float] = []
        for sample in normalized_audio_data:
            if isinstance(sample, bool) or not isinstance(sample, (int, float)):
                raise ValueError("audio_data must contain only numbers")
            normalized_samples.append(float(sample))
        return normalized_samples

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        发送 JSON POST 请求并返回响应体。

        核心入参:
            path: Runtime API 路径。
            payload: 需要发送的 JSON 对象。

        预期输出:
            返回响应 JSON 字典。

        边界异常:
            HTTP 非成功状态会抛出 HTTPStatusError。
        """
        # 非阻塞式请求
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.post(f"{self.base_url}{path}", json=payload)
            response.raise_for_status()
            return response.json()
