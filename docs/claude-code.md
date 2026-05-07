# Claude Code 接线手册

这份文档只关注一件事：怎样把 Claude Code 接到本仓库的 CLI 合同上。

## 推荐接入方式

优先使用 CLI，而不是让 Claude Code 直接耦合底层 SDK。

原因：

- CLI 是当前项目的官方主合同
- `streamvox-runtime` 负责常驻模型会话
- `streamvox-say` 负责事件语义和排队控制
- 出错时 CLI 会直接打印 Runtime `detail`

如果 Claude Code 需要从零安装环境，优先调用：

- Linux / WSL：
  - `./scripts/install.sh`
- Windows PowerShell：
  - `.\scripts\install.ps1`

如果 Claude Code 想先判断会装哪个包，再决定是否执行，可以先跑：

```bash
python -m streamvox_agent_voice.bootstrap --dry-run
```

## 最小接线顺序

### 1. 环境准备

先完成 [install.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/install.md)。

### 2. 启动 Runtime

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker
```

### 3. 在 Claude Code 开始正式播报前读取状态

```bash
streamvox-runtime status
streamvox-runtime capabilities
streamvox-runtime roles list
```

### 4. 根据能力快照决定播报方式

建议 Claude Code 读取并使用：

- `resolved_model`
- `recommended_parameters`
- `parameter_notes`
- `known_constraints`
- `session.default_role_name`

### 5. 发送高层事件

```bash
streamvox-say --progress "正在处理请求"
streamvox-say --done "处理完成"
```

## 推荐的触发时机

- 开始长任务时：
  - `--progress`
- 状态发生显著变化时：
  - `--progress`
- 发现更紧急的信息时：
  - `--interrupt`
- 任务结束时：
  - `--done`

## 角色工作流

如果当前模型需要持久化角色，先注册：

```bash
streamvox-runtime roles register assistant_voice --audio-file ./examples/Condition3.wav --set-default
```

如果角色已经存在但默认角色为空：

```bash
streamvox-runtime roles set-default assistant_voice
```

更稳的做法是播报时显式传 `--role-name`：

```bash
streamvox-say --role-name assistant_voice --progress "正在处理请求"
```

## Claude Code 不应该做什么

- 不要假设所有模型都支持 `control_text`
- 不要在不知道模型能力前直接传 `speaker`、`language` 或 `mode`
- 不要把“角色存在”误当成“当前默认角色已设置”

## PowerShell 建议

如果 Claude Code 运行在 Windows PowerShell 环境，推荐把模型私有参数写入文件：

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

- 低延迟单参考克隆：
  - [qwen3-tts-clone.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/models/qwen3-tts-clone.md)
- 多说话人和演播：
  - [s2-pro.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/models/s2-pro.md)
- 文本音色设计与续写：
  - [voxcpm2.md](/g:/Workspace/projects/streamvox-agent-voice-kit/docs/models/voxcpm2.md)
