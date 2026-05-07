# Codex 接线手册

这份文档描述的是 Codex 如何把自己接到 `streamvox-runtime` 与 `streamvox-say` 上。

## 接入原则

Codex 应该把本项目当成一个独立的语音执行层：

- Runtime 负责持有模型会话
- CLI 负责稳定的事件语义
- 能力快照负责告诉 Codex 当前该怎么选模型和参数

如果 Codex 需要从零安装环境，优先调用：

- Linux / WSL：
  - `./scripts/install.sh`
- Windows PowerShell：
  - `.\scripts\install.ps1`

如果 Codex 想先判断会装哪个 wheel，再决定是否执行安装，可以先跑：

```bash
python -m streamvox_agent_voice.bootstrap --dry-run
```

## 最小接入步骤

### 1. 完成安装

先完成 [install.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/install.md)。

### 2. 启动 Runtime

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker
```

### 3. 启动后先读状态

```bash
streamvox-runtime status
streamvox-runtime capabilities
streamvox-runtime roles list
```

Codex 应至少读取：

- `resolved_model`
- `controls`
- `prompt`
- `recommended_workflows`
- `recommended_parameters`
- `parameter_notes`
- `known_constraints`
- `session.default_role_name`

### 4. 再决定发送什么事件

推荐高层调用：

```bash
streamvox-say --progress "正在处理请求"
streamvox-say --done "处理完成"
```

## 角色相关建议

如果模型工作流要求持久化角色：

```bash
streamvox-runtime roles register assistant_voice --audio-file ./examples/Condition3.wav --set-default
```

如果角色已经存在但当前默认角色为空：

```bash
streamvox-runtime roles set-default assistant_voice
```

如果你不想依赖会话默认值，就显式传：

```bash
streamvox-say --role-name assistant_voice --progress "正在处理请求"
```

## Codex 不应盲猜的内容

- 当前模型是否支持 `language`
- 当前模型是否支持 `control_text`
- 当前模型是否支持 speaker tags
- 当前模型是否要求持久化 `role_name`

这些信息都应该来自 `capabilities`，而不是来自硬编码假设。

## Windows PowerShell 建议

对 Codex 来说，Windows 下最稳的调用方式是 `--streamvox-json-file`。

示例：

```json
{
  "mode": "ref",
  "control_text": "四川话，轻松一点"
}
```

```powershell
streamvox-say --role-name assistant_voice --streamvox-json-file .\voxcpm2-ref.json "这条请求显式指定 VoxCPM2 风格控制"
```

## 模型选择入口

- 低延迟、低资源、单参考克隆：
  - [qwen3-tts-clone.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/models/qwen3-tts-clone.md)
- 高保真演播、多说话人与长文本：
  - [s2-pro.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/models/s2-pro.md)
- 文本音色设计、参考克隆微调与续写：
  - [voxcpm2.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/models/voxcpm2.md)
