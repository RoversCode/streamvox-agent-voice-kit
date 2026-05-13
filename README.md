# StreamVox Agent Voice Kit

面向 AI Agent 的本地语音运行时工具包。

这份 README 只保留当前项目的实际使用教程，按下面顺序使用即可：

1. 安装项目依赖
2. 安装你的 `streamvox` 私有 wheel
3. 启动 `streamvox-runtime`
4. 做一次自检
5. 注册一个角色
6. 用 `streamvox-say` 发语音事件
7. 需要时给 Agent 安装 skill

## 项目提供什么

- `streamvox-runtime`
  - 本地常驻 Runtime 服务
- `streamvox-say`
  - 向 Runtime 发送播报事件
- `streamvox-agent`
  - 为支持的 Agent 安装内置 skill

## 前提条件

- Python `3.10`
- 可用的 `uv`
- 一个可安装的 `streamvox` 私有 wheel
- 如果要本机直接播音：
  - 可用音频设备
- 如果只做静音服务调用：
  - 使用 `--output null`

## 安装

### Linux / WSL

```bash
uv venv .venv --python 3.10 --python-preference only-managed
uv sync --python .venv/bin/python
uv pip install --python .venv/bin/python <your-streamvox-wheel>
source .venv/bin/activate
```

### Windows PowerShell

```powershell
uv venv .venv --python 3.10 --python-preference only-managed
uv sync --python .venv\Scripts\python.exe
uv pip install --python .venv\Scripts\python.exe <your-streamvox-wheel>
.\.venv\Scripts\Activate.ps1
```

## 启动 Runtime

### 本机播音

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker
```

`streamvox-runtime start` 现在会在启动阶段自动检查当前模型缓存里是否已经存在 `demo_role`：

- 如果不存在：
  - 自动用 `examples/Condition3.wav` 构建 `demo_role`
  - `prompt_text` 不需要手工传入，Runtime 会自动做内部 ASR
- 如果你没有显式传 `--default-role-name`：
  - Runtime 会把 `demo_role` 设成当前会话默认角色
- 如果你显式传了 `--default-role-name`：
  - Runtime 仍然会确保 `demo_role` 存在，但不会覆盖你指定的默认角色

### 静音运行

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output null
```

--output null的意思是，Runtime 仍然会正常接收事件、排队、调用模型生成语音，但生成出来的音频不会播放，也不会写文件

### 语音输出到文件夹

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output wav --output-dir ./streamvox_outputs
```

如果你启动时只给了 `--model`，但没有显式传 `--streamvox-json` 或 `--streamvox-json-file`：

- Runtime 会自动从 `streamvox_agent_voice/config/stream_kwargs.yaml`
- 按当前模型名读取默认推理参数

如果你连 `--model` 都不传：

- Runtime 默认启动 `qwen3-tts-clone-0.6b-gguf`
- 并自动读取 `streamvox_agent_voice/config/stream_kwargs.yaml` 里这个模型对应的默认推理参数

### 启动时固定推理参数

```bash
streamvox-runtime start --model voxcpm2-gguf --streamvox-json '{"mode":"ref", "control_text": "闽南语"}' --device auto --output wav --output-dir ./streamvox_outputs
```

如果参数较长，更推荐文件入口：

```bash
streamvox-runtime start --model voxcpm2-gguf --streamvox-json-file ./streamvox.json
```

这里的 `--streamvox-json*` 只在 Runtime 启动时生效：

- 当前会话里的所有播报都会复用这组固定 `stream(...)` 参数
- `streamvox-say` 不再支持按单条事件覆盖模型推理参数
- 如果启动时不传，Runtime 会先尝试从 `streamvox_agent_voice/config/stream_kwargs.yaml` 按模型读取默认值
- 如果该模型在 YAML 里没有配置，再回退到当前模型自己的默认推理行为

常用启动参数：

- `--model`
  - 模型名或本地模型目录；默认是 `qwen3-tts-clone-0.6b-gguf`
- `--device`
  - 常用值是 `auto`、`cpu`、`gpu`、`gpu:<index>`
- `--output`
  - 常用值是 `speaker`、`null`、`wav`
- `--output-dir`
  - 当输出模式是 `wav` 时指定音频输出目录
- `--streamvox-json` / `--streamvox-json-file`
  - 在 Runtime 启动时固定当前会话的模型推理参数

## 安装后先做自检

### 最小检查

```bash
streamvox-runtime status
streamvox-runtime capabilities
streamvox-runtime roles list
```

其中：

- `status`
  - 查看当前 Runtime 是否已完成初始化，以及模型、设备、输出后端和队列状态
- `capabilities`
  - 直接输出当前 Runtime 模型对应的能力说明 Markdown 文档，适合给脚本或 Agent 直接阅读

### 建议检查

```bash
streamvox-runtime selftest
```

`selftest` 现在只做一件事：

- 检查当前模型的流式 chunk 生成是否跟得上实时播放
- 如果后一个 chunk 到达时间晚于前一个 chunk 自身的可播放时长，会直接判定存在语音割裂风险
- 这时通常应该换更小的模型，或者调整硬件和设备配置

### 查看模型信息

```bash
streamvox-runtime models list
```

其中：

- `models list`
  - 默认输出极简纯文本，每行一个模型和当前硬件是否适合流畅运行的结论

## 注册角色

当前推荐使用本地音频文件注册角色：

```bash
streamvox-runtime roles register assistant_voice --audio ./examples/Condition3.wav --set-default
```

这条命令会做两件事：

- 注册一个名为 `assistant_voice` 的持久化角色
- 立即把它设成当前 Runtime 默认角色

角色相关常用命令：

```bash
streamvox-runtime roles list
streamvox-runtime roles set-default assistant_voice
streamvox-runtime roles clear-default
streamvox-runtime roles delete assistant_voice
```

角色注册规则：

- 优先使用 `--audio`
- `--prompt-text` 只在你要显式覆盖参考文本时再传
- 如果不传 `--prompt-text`，Runtime 会自己转写参考音频
- `--audio-path` 只适合同机高级用法，不是默认主路径

## 发送语音事件

### 最简单的播报

```bash
streamvox-say "我正在整理答案，请稍等。"   # 我咧整理答案，等我一下哦。  我正在整理答案，请稍等
```

### 推荐使用高层事件接口

```bash
streamvox-say --intent progress --text "我正在读取项目结构"
streamvox-say --intent warning --text "我发现有一项配置需要你稍后确认"
streamvox-say --intent done --text "检查已经完成"
```

### 指定角色播报

```bash
streamvox-say --role-name assistant_voice --intent progress --text "现在使用指定角色播报"
```

### 等待当前事件播报完成

```bash
streamvox-say --intent done --text "处理完成" --wait
```

### 中断当前播报

```bash
streamvox-say --intent urgent --text "请先处理更紧急的任务"
streamvox-say --stop
```

如果你显式传了 `--action`，CLI 会把它当成底层队列控制入口：

- 不再使用 `intent` 对 `action` 的默认映射
- 适合脚本或调试场景

高层事件建议这样理解：

- `progress`
  - 适合阶段推进中的普通进展
- `warning`
  - 适合提醒用户注意，但任务还能继续
- `done`
  - 适合任务收尾
- `urgent`
  - 适合需要立即插播的新内容
- `info`
  - 适合普通说明

## 给 Agent 安装 skill

当你已经手动安装并启动 Runtime 后，可以把内置 skill 装到支持的 Agent 默认目录。

当前支持两个目标：

- `codex`
- `claude-code`

### 同时安装到两个宿主

```bash
streamvox-agent init
```

默认安装位置：

```text
~/.codex/skills/streamvox-runtime/
~/.claude/skills/streamvox-runtime/
```

### 只安装到一个宿主

```bash
streamvox-agent init --target codex
streamvox-agent init --target claude-code
```

### 覆盖已存在的安装

```bash
streamvox-agent init --target codex --force
```

仓库内置 skill 源文件位于：

- [skills/streamvox-runtime/SKILL.md](skills/streamvox-runtime/SKILL.md)

## 常见问题

### Runtime 启动失败

先检查这几项：

- `streamvox` 私有 wheel 是否真的安装在当前虚拟环境
- `--model` 指向的模型是否可用
- 当前设备参数是否适合你的机器
- 用 `streamvox-runtime doctor --model <model>` 看诊断结果

### `streamvox-say` 请求失败

先看 CLI 打出来的服务端 `detail`，常见原因有：

- 角色不存在
- 默认角色为空
- Runtime 还没启动
- 当前模型或参数不支持本次请求

### 角色存在但播报没命中默认角色

先执行：

```bash
streamvox-runtime roles list
```

如果默认角色为空，执行：

```bash
streamvox-runtime roles set-default assistant_voice
```

或者每次调用时显式指定：

```bash
streamvox-say --role-name assistant_voice "你好"
```

streamvox-say --intent info --text "我开始处理了"
streamvox-say --intent progress --text "我正在读取项目结构"
streamvox-say --intent warning --text "我发现这里有风险"
streamvox-say --intent urgent --text "这里有阻塞问题"
streamvox-say --intent done --text "我已经处理完成"
