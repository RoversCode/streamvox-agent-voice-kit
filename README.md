# StreamVox Agent Voice Kit

让 AI Agent 可以实时播报进度、错误和最终结果。

Agent 决定“说什么”。  
StreamVox Runtime 决定“怎么说”。

`streamvox-agent-voice-kit` 是一个面向 Agent 工作流的本地流式语音运行时。它会以常驻进程的方式持续加载 StreamVox，然后让任意 Agent 通过 CLI 或 Python 客户端发送轻量级语音事件。

## 这是什么

- `streamvox-runtime`：启动本地 HTTP Runtime，预加载 `TTSEngine`，并将音频分块流式输出到指定接收端。
- `streamvox-say`：向 Runtime 发送 `progress`、`done`、`error`、`interrupt` 和 `stop` 等事件。
- `VoiceClient`：异步 Python 客户端，可用于 Jarvis 风格命令行、Claude Code SDK 包装层、Codex Hook、OpenClaw Skill 或自定义 Agent。
- 事件协议：使用一个小而稳定的 JSON 结构，让 Agent 逻辑与 TTS 播放逻辑保持解耦。

## 这不是什么

- 不是 Agent 框架。
- 不提供通用 ASR 服务；内部 ASR 仅服务于角色注册场景，用于在缺少 `prompt_text` 时辅助生成角色资产。
- 不是记忆系统或人格系统。
- 不是 StreamVox SDK 的替代品。

## 安装

请使用项目自己的虚拟环境。这个仓库会把 StreamVox Runtime 相关依赖维护在 `pyproject.toml` 中；如果你使用的是私有或本地构建的 StreamVox wheel，请先把它安装到 `.venv`，再启动 Runtime。

```bash
source .venv/bin/activate
uv sync --inexact
```

`--inexact` 会保留本地已经安装的私有 wheel，例如 StreamVox SDK。详见 [docs/install.md](docs/install.md)。

如果你希望直接通过本地扬声器播放，并且当前环境还没有安装 `sounddevice`，请补装：

```bash
uv pip install sounddevice
```

## 启动 Runtime

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker
```

如果是在没有音频设备的服务器上运行：

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output null
```

如果你希望把每一次请求都保存成 wav 文件：

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output wav --output-dir streamvox_outputs
```

Runtime 会只加载一次 `streamvox.TTSEngine`，并持续保持预热状态。
如果使用角色自动 ASR 工作流，Runtime 也会在启动阶段准备内部 ASR：缺少权重时自动下载，并与 `TTSEngine` 一起完成初始化和预热；当前热身方式是一秒静音 forward，一次即可。

补充说明：`control_text` 不再作为 Runtime 启动参数持久挂在会话上；如果当前模型需要它，应在单次请求里通过 `streamvox` 私有参数显式传入。

## 音色与角色预设

根据 `ref_code/streamvox_release_github/README.md` 中的 SDK 用法，StreamVox 的常规工作流通常是：

1. 先调用 `TTSEngine.make_prompt(...)` 构建或持久化 prompt 资产。
2. 再在 `TTSEngine.stream(..., role_name=...)` 时指定角色名或对应 prompt 引用。

这意味着，对于 Agent 持续播报场景，理想的使用方式不应该只是“每次传一句文本”，而应该支持“先确定一个默认角色音色，后续所有播报默认沿用它”。

当前 `streamvox-agent-voice-kit` 的现状是：

- 已支持 Runtime 级模型常驻、队列控制和输出 sink。
- 已支持 `make_prompt(...)` 角色注册、角色列表 / 删除、默认角色切换，以及事件级 `role_name` 覆盖与默认角色继承。
- 已支持三类单参考角色注册入口：
  - Runtime 本机路径 `audio_path`
  - multipart 二进制/文件上传 `audio_file`
  - 单条内存音频 `audio_data + sample_rate`
- 已支持在缺少 `prompt_text` 时，内部自动 ASR 参考音频并回填到 `make_prompt(...)`。
- 已对角色参考音频增加 30 秒上限，避免大体积资产拖慢上传、ASR 和 Prompt 构建。
- 角色缓存直接复用 StreamVox SDK 自身的按模型隔离机制，不会跨模型混用。
- 已支持 VoxCPM2 的 `control_text` 事件级透传，但它仍然只是部分模型能力，不是角色资产本身。
- 当前产品明确只支持持久化、单参考角色资产；即使底层 SDK 某些模型支持多参考，Agent Voice Runtime 也不会对外公开这一工作流。
- Runtime 会尽量透传 `language`、`stream`、`icl`、`max_length`、`min_length`、`remove_meaningless_chars`、`mode`、`control_text`、`temperature/top_p/top_k`、`speaker` 等模型私有参数，主要交给 StreamVox SDK 自身过滤、忽略或校验，而不是在 Runtime 层维护一套严格的参数支持矩阵。

因此，当前 README 中的 CLI 示例应理解为“使用当前 Runtime 会话上下文进行播报”；如果你已经设置了默认角色，后续普通事件会自动继承它。

## 模型兼容与设计方向

阅读 `ref_code/streamvox_release_github/doc/usage.md` 以及各模型说明文档后，可以明确一点：

> StreamVox SDK 的入口虽然统一是 `TTSEngine`，但不同模型的最佳工作流并不相同。

这意味着，`streamvox-agent-voice-kit` 的长期目标不应该是“把所有模型都压扁成同一套 `control_text` 接口”，而应该是：

> 成为一个兼容 StreamVox SDK 全能力的 Agent 语音 Runtime。

### 已确认的模型差异

- Qwen3 TTS Clone：
  - 以单参考 Prompt 为主。
  - 正式生成时通常建议显式指定 `language`。
  - 支持缓存角色，并且角色按模型隔离。
- S2-Pro：
  - 底层 SDK 支持单参考和多参考 Prompt。
  - 支持多说话人 `speaker` 标记。
  - 支持大量内联风格标签和 `temperature/top_p/top_k` 等采样参数。
- VoxCPM2：
  - 支持 `text`、`ref`、`continuation`、`ref_continuation` 四种模式。
  - `control_text` 只在 `text` / `ref` 模式下生效，不是跨模型通用能力。
  - `ref` / `continuation` / `ref_continuation` 模式需要持久化角色资产。

### 这对 Agent Voice Kit 的设计意味着什么

- Runtime 启动前，使用者应先根据机器硬件能力和业务目标选择合适模型。
- Runtime 启动后，应能查询“当前模型的能力摘要和推荐用法”，而不是让 Agent 猜测。
- Runtime 应管理默认角色、Prompt 资产和当前模型会话，而不是只维护一个文本播报队列。
- 事件协议应保留稳定的通用字段，同时允许模型私有参数按显式方式透传。

### 推荐的能力分层

- 部署期：
  - 提供模型列表、模型说明、硬件建议和模型推荐。
- 运行期：
  - 持有当前模型、当前默认角色、当前能力快照和当前输出 sink。
- 事件期：
  - 统一处理 `event/action/wait` 等控制语义。
  - 允许事件级覆盖 `role_name` 或传入模型私有参数。

### 当前现状

- 已具备稳定的本地 Runtime、队列控制、打断控制和输出 sink。
- 已具备面向 Agent 的 CLI / Python 调用链路。
- 已具备 Prompt 角色注册、角色列表 / 删除、默认角色切换和能力快照接口。
- 当前能力快照更偏向“文档化摘要与运行期提示”，而不是对所有模型私有参数做强约束。
- 目前已经从“VoxCPM2 风格播报器”迈出关键一步，但离完整的 StreamVox 全能力 Runtime 还有剩余工作。

后续演进方向会优先补齐：

- 更完整的模型私有参数透传文档与能力说明。
- 更多 SDK 模型的注册表能力描述与启动前体检结论。

## 启动前先看推荐

如果你还没有决定启动哪个模型，可以先让 Runtime CLI 读取本机硬件并给出建议：

```bash
streamvox-runtime models recommend
streamvox-runtime doctor --model voxcpm2-gguf
streamvox-runtime doctor --model s2-pro-4b-gguf
```

其中：

- `models recommend` 会输出当前机器的 CPU / RAM / GPU 摘要，并按“更稳妥可跑”到“需要手工确认”的顺序给出模型建议。
- `doctor --model ...` 会只针对一个模型输出体检结果，例如推荐 `gpu:0`、只能 `cpu` 回退，或者当前硬件明显不足。

## 角色管理

当前 Runtime 已把 Prompt 资产工作流封装成公开能力。

### 推荐：直接上传参考音频

```bash
streamvox-runtime roles register assistant_voice \
  --audio-file reference.wav \
  --set-default
```

如果你不传 `--prompt-text`，Runtime 会先对参考音频做一次内部自动 ASR，再把转写结果传给 `TTSEngine.make_prompt(...)`。

### 本机路径型角色注册

如果 Runtime 和命令行在同一台机器上，也可以直接把路径传给 Runtime：

```bash
streamvox-runtime roles register assistant_voice \
  --audio-path reference.wav \
  --prompt-text "这是参考音频对应的转写文本。" \
  --set-default
```

### 内存音频角色注册

如果你手里已经是内存里的采样数组，而不是 wav 文件，可以通过 JSON 数组注册；`prompt_text` 也可以省略，由 Runtime 自动 ASR：

```bash
streamvox-runtime roles register memory_voice \
  --audio-data-file samples.json \
  --sample-rate 24000
```

其中 `samples.json` 的内容应是一维浮点数组，例如：

```json
[0.0, 0.12, -0.08, 0.03]
```

### 角色列表、切换与删除

```bash
streamvox-runtime roles list
streamvox-runtime roles set-default assistant_voice
streamvox-runtime roles clear-default
streamvox-runtime roles delete assistant_voice
```

### 当前角色管理约束

- 角色缓存按模型隔离；在 `qwen3-tts-clone-1.7b-gguf` 下注册的角色，不能直接拿去 `voxcpm2-gguf` 使用。
- Runtime 当前只支持持久化角色注册，也就是 `persist=True` 工作流。
- Runtime 明确不支持临时 Prompt / `prompt_ref` 资产工作流；角色资产统一走持久化缓存和 `role_name` 复用。
- Runtime 当前公开协议只支持单参考角色资产；即使底层 SDK 某些模型支持多参考 Prompt，本项目也不会对外开放多参考注册工作流。
- 内存音频入口当前只支持单参考一维数组，并且必须显式传 `sample_rate`。
- `audio_path`、`audio_file` 和 `audio_data` 三类参考音频都受 30 秒上限约束。
- 缺少 `prompt_text` 时，Runtime 会在角色注册期内部调用 SenseVoice ONNX 自动转写参考音频。
- 内部自动 ASR 默认把权重缓存到 `~/.cache/streamvox-agent-voice-kit/sensevoice_onnx`；可通过 `STREAMVOX_ASR_MODEL_DIR` 覆盖目录，通过 `STREAMVOX_ASR_PROVIDER` 指定 `cpu` / `cuda` / `dml`。
- 如果启动 Runtime 时传了 `--default-role-name`，但当前模型缓存里没有这个角色，Runtime 会在初始化阶段直接报错。

### 按模型理解当前 Prompt 约束与常见参数

- `qwen3-tts-clone-0.6b-gguf` / `qwen3-tts-clone-1.7b-gguf`
  - 适合单参考角色工作流。
  - 允许文件型单参考和内存音频单参考。
  - 文档和能力快照会标注 `language`、`stream`、`icl`、`max_length`、`min_length`、`remove_meaningless_chars` 这类常见参数。
  - 正式合成时通常建议显式传 `language`，可以通过 `streamvox-say --streamvox-json '{"language":"zh"}'` 透传。
- `s2-pro-4b-gguf`
  - 底层 SDK 支持文件型单参考和多参考 Prompt，但 Runtime 当前只公开单参考角色工作流。
  - 常见透传参数包括 `temperature`、`top_p`、`top_k`、`speaker`、`max_length`、`min_length`、`remove_meaningless_chars`。
- `voxcpm2-gguf`
  - 角色注册当前按单参考工作流处理。
  - `control_text` 和 `mode` 是模型私有能力，不是通用 Prompt 资产。
  - `control_text` 更适合作为单次推理参数显式传入，而不是 Runtime 启动期默认值。
  - `ref` / `continuation` / `ref_continuation` 模式必须命中一个已持久化的 `role_name`。

## 在另一个终端发声

```bash
streamvox-say --event progress "我正在读取文件"
streamvox-say --event done "处理完成，我找到了三个重点"
streamvox-say --event error "保存结果失败"
streamvox-say --interrupt "等等，我发现了新的问题"
streamvox-say --event progress --action replace_pending "我更新了进度"
streamvox-say --stop
```

默认情况下，`streamvox-say` 在事件被 Runtime 接收后就会立即返回。使用 `--wait` 可以等待播报完成。`event` 只是一个语义标签，`error` 并不会自动打断当前播放；如果你需要显式控制打断行为，请使用 `--interrupt` 或 `--interrupt-current`。

如果你已经给 Runtime 绑定了默认角色，但某一条播报希望临时切换音色或透传模型私有参数，可以这样写：

```bash
streamvox-say --role-name assistant_voice "我继续沿用角色音色播报"
streamvox-say --streamvox-json '{"language":"zh"}' "这条请求显式指定语言"
streamvox-say --streamvox-json '{"mode":"ref","control_text":"四川话，轻松一点"}' "这条请求显式指定 VoxCPM2 风格控制"
streamvox-say --role-name narrator --streamvox-json '{"temperature":0.7}' "这条请求临时切换角色并透传采样参数"
```

补充说明：

- Runtime 默认尽量透传 `streamvox` 私有参数。
- 参数是否真正生效、是否被忽略、或是否由底层模型报错，主要以 StreamVox SDK 自身行为为准。
- 例如：给 VoxCPM2 传 `mode="ref"` 但没有任何持久化 `role_name`，也会在请求阶段直接失败。
- README 和 `/capabilities` 返回的模型信息，主要用于帮助 Agent 理解“常见能力”和“推荐用法”，不代表 Runtime 会逐项强制拦截所有私有参数。
- 尚未收录进模型注册表的额外 SDK 参数，目前仍保持透传，不保证已经被 Runtime 完整校验。

## Python 客户端

```python
from streamvox_agent_voice import VoiceClient

voice = VoiceClient()

await voice.register_role_upload(
    role_name="assistant_voice",
    audio_file="reference.wav",
    set_default=True,
)

await voice.say("我正在读取你的记忆", event="progress")
await voice.done("整理完成")
await voice.interrupt("等等，我发现了新的问题")
await voice.stop()
```

## Runtime API

- `GET /health`
- `GET /status`
- `GET /capabilities`
- `GET /roles`
- `POST /events`
- `POST /roles`
- `POST /roles/upload`
- `POST /roles/delete`
- `POST /session/default-role`
- `POST /stop`
- `POST /shutdown`

更多细节见 [docs/event-protocol.md](docs/event-protocol.md) 和 [docs/runtime.md](docs/runtime.md)。

## MVP 边界

第一个版本有意把边界收得很小：

- Agent 负责产出文本事件。
- Runtime 负责 TTS 与播放。
- StreamVox SDK 仍然是外部依赖。
- 通用 ASR、Jarvis Voice Shell、smart-me memory 以及 Claude Code SDK 编排逻辑都放在独立层中处理；角色注册期的一次性自动 ASR 只是 Runtime 内部辅助能力。
