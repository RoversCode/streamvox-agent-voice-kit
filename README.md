# StreamVox Agent Voice Kit

面向 AI Agent 的本地流式语音 Runtime。

这个仓库的目标不是解释 StreamVox SDK 的全部背景，而是提供一套可直接接入的 `CLI-first` 合同：

- `streamvox-runtime`：启动并常驻一个本地 TTS Runtime。
- `streamvox-say`：向 Runtime 发送进度、完成、打断和停止事件。
- `GET /status`、`GET /capabilities`、`GET /roles`：供 Agent 在调用前读取当前状态。

如果你的目标是让 Claude Code、Codex 或其他 Agent 直接安装并调用，这个仓库应该被当成“语音执行层”，而不是“项目背景说明书”。

## 接入前提

- Python `>=3.10`
- `uv`
- 一个可用的 `streamvox` 私有 wheel
- 可选音频后端：
  - 本机播放：`sounddevice`
  - 无声服务器：`--output null`
  - 落盘调试：`--output wav`

`streamvox` 仍然是外部前置依赖。本项目当前的“可直接接入”定义是：

拿到私有 wheel 后，不读源码，只看文档，就能在 Linux bash 或 Windows PowerShell 中完成安装、启动、注册角色、发声和排障。

## 最短开始

### Linux / WSL

```bash
./scripts/install.sh
source .venv/bin/activate
streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker
```

### Windows PowerShell

```powershell
.\scripts\install.ps1
.\.venv\Scripts\Activate.ps1
streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker
```

更完整的安装与平台差异见 [docs/install.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/install.md)。

## Agent 能否自己选对 whl

可以，前提是它先做系统探测。

当前仓库已经提供安装引导：

- `scripts/install.sh`
- `scripts/install.ps1`
- `python -m streamvox_agent_voice.bootstrap --dry-run`

它会根据当前系统和显卡状态，自动做两层判断：

1. 选择项目依赖 extra
   - Windows NVIDIA GPU：`windows-cuda`
   - Windows AMD / Intel GPU：`windows-dml`
   - Windows 无合适 GPU：`windows-cpu`
2. 从 `https://github.com/RoversCode/StreamVox/releases` 自动挑选最匹配的 wheel 资产

如果 Agent 想先判定再执行，可以先跑：

```bash
python -m streamvox_agent_voice.bootstrap --dry-run
```

这会输出 JSON 计划，包括：

- 当前系统画像
- 推荐加速方案
- 命中的 Release 资产
- 需要安装的 optional extra

## Agent 最短工作流

无论是哪种 Agent，推荐都按这个顺序调用：

1. 启动 Runtime。
2. 读取 `streamvox-runtime status`。
3. 读取 `streamvox-runtime capabilities`。
4. 读取 `streamvox-runtime roles list`。
5. 如果当前模型需要持久化角色，先注册或选择 `role_name`。
6. 再发送 `streamvox-say`。

最小检查命令：

```bash
streamvox-runtime status
streamvox-runtime capabilities
streamvox-runtime roles list
streamvox-runtime selftest
```

最小播报命令：

```bash
streamvox-say --progress "正在处理请求"
streamvox-say --done "处理完成"
```

如果你希望 Agent 在正式接线前先自行验收，再判断这台机器是否适合做实时语音助手，可以继续执行：

```bash
streamvox-runtime selftest
streamvox-runtime benchmark --text "您好，我正在整理答案，请稍等片刻。"
streamvox-runtime benchmark --json-summary-only --text "您好，我正在整理答案，请稍等片刻。"
```

`selftest` 用来验证 `status`、`capabilities`、`roles list` 和最小播报链路。  
`benchmark` 给出一个实时性结论，帮助 Agent 判断当前模型和设备是否适合作为私人智能助手的实时播报配置。  
如果当前 Runtime 会话本来就是 `--output wav`，benchmark 会优先读取真实生成 wav 的音频时长；否则回退到文本内容估时。  
`--json-summary-only` 适合 Agent 或脚本直接消费，只保留模型、耗时、参考语音时长和实时性结论这些核心字段。

## Windows 重点

PowerShell 不适合长期依赖复杂内联 JSON。推荐优先使用 `--streamvox-json-file`。

示例 `streamvox-voice.json`：

```json
{
  "mode": "ref",
  "control_text": "四川话，轻松一点"
}
```

PowerShell 调用：

```powershell
streamvox-say --role-name assistant_voice --streamvox-json-file .\streamvox-voice.json "这条请求显式指定 VoxCPM2 风格控制"
```

角色注册同样支持文件输入：

```powershell
streamvox-runtime roles register assistant_voice `
  --audio-file .\examples\Condition3.wav `
  --streamvox-json-file .\prompt-config.json `
  --set-default
```

## 模型怎么选

- `qwen3-tts-clone-0.6b-gguf`
  - 低延迟、低资源、短句播报优先。
- `qwen3-tts-clone-1.7b-gguf`
  - 更自然、更稳的单参考克隆与正式播报。
- `s2-pro-4b-gguf`
  - 高保真演播、多说话人、长文本内容成片。
- `voxcpm2-gguf`
  - 纯文本音色设计、参考克隆微调、续写与非语言标签控制。

具体参数、适用场景和文本写法见：

- [docs/models/qwen3-tts-clone.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/models/qwen3-tts-clone.md)
- [docs/models/s2-pro.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/models/s2-pro.md)
- [docs/models/voxcpm2.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/models/voxcpm2.md)

## 官方接入文档

- [docs/agent-contract.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/agent-contract.md)
- [docs/install.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/install.md)
- [docs/event-protocol.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/event-protocol.md)
- [docs/claude-code.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/claude-code.md)
- [docs/codex.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/codex.md)

## 机器可读能力快照

`streamvox-runtime capabilities` 现在不只返回“支持哪些字段”，还会返回 Agent 可直接消费的建议信息：

- `best_for`
- `recommended_workflows`
- `recommended_parameters`
- `parameter_notes`
- `text_writing_tips`
- `known_constraints`

这意味着 Agent 可以先读能力快照，再决定：

- 当前该选哪个模型
- 要不要显式传 `language`
- 是否必须先拿到持久化 `role_name`
- 当前是否适合使用 `control_text`、`speaker` 或 speaker tags

## 仍然不做什么

- 不把 `streamvox` 私有 wheel 变成公网依赖
- 不把 Runtime 变成完整的参数裁判器
- 不把所有模型压平为同一种“控制文本”接口
- 不负责 Agent 的记忆系统、工作流编排或 ASR 产品化能力
