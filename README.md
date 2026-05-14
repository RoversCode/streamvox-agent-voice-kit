<div align="center">
    <h1>StreamVox Agent Voice Kit</h1>
    <p><strong>基于 StreamVox SDK 的本地 Agent 语音播报工具</strong></p>
    <p>
        <a href="https://item.taobao.com/item.htm?ft=t&id=1044813462201&spm=a21dvs.23580594.0.0.6781645ez4U7cp">
            <img alt="SDK Key 购买" src="https://img.shields.io/badge/SDK%20Key-%E8%B4%AD%E4%B9%B0%E9%93%BE%E6%8E%A5-ff6a00?style=for-the-badge">
        </a>
        <img alt="QQ 交流群" src="https://img.shields.io/badge/QQ%E4%BA%A4%E6%B5%81%E7%BE%A4-1097818796-12b886?style=for-the-badge">
        <img alt="Trial" src="https://img.shields.io/badge/Trial-%E5%85%88%E6%B5%8B%E5%90%8E%E4%B9%B0-228be6?style=for-the-badge">
    </p>
    <p>
        <strong>SDK Key 购买：</strong>
        <a href="https://item.taobao.com/item.htm?ft=t&id=1044813462201&spm=a21dvs.23580594.0.0.6781645ez4U7cp">淘宝授权入口</a>
        &nbsp;&nbsp; | &nbsp;&nbsp;
        <strong>QQ 交流群：</strong>1097818796
    </p>
</div>

StreamVox Agent Voice Kit 是一个完全围绕 [streamvox](https://github.com/RoversCode/StreamVox) 能力封装的 Agent Voice Kit。本地启动 Runtime 后，Codex 和 Claude Code 可以通过安装 `streamvox-runtime` skill，在任务执行过程中根据预设人格，在关键状态变化时自动播报语音。

## 它是什么

StreamVox Agent Voice Kit 不是独立的 TTS 引擎。它做的是围绕 `streamvox` 补齐一整套 Agent 场景接入层，包括：

- 本地常驻 Runtime
- `streamvox-runtime`、`streamvox-say`、`streamvox-agent` 三个命令行入口
- 面向 Codex / Claude Code 的 skill 安装能力
- 人格文档驱动的播报文案协议
- 角色缓存、默认角色、参考音色注册与切换

这个项目的核心目标不是“做一个网页配音器”，而是让智能体在真实工作流里开口说话。比如开始耗时步骤、发现风险、出现阻塞、阶段完成、整体完成时，AI 会按你设定的人格风格发出合适的语音播报。

这里有一个非常重要的概念区分：

- “人格”控制的是播报文案风格，也就是 AI 说话时的语气、节奏、称呼和风格边界。
- “角色”控制的是参考音色，也就是 Runtime 实际发声时使用哪一个声音资产。

两者不是一个东西。只改人格，不会改变音色；只改角色，不会改变文案风格。

## 授权说明

> [!IMPORTANT]
> [streamvox](https://github.com/RoversCode/StreamVox) 需要授权 key，才能正常发声。没有授权 key 时，本项目不能替代上游授权体系，也不能绕过 `streamvox` 的授权机制。

授权 key 的购买方式、使用说明和相关介绍，请参考飞书文档：

- <https://my.feishu.cn/wiki/PjIFwRETHidexMkd9wFcsCnGnoe?docs_banner_login=>

模型能力、授权机制、上游模型更新细节，均以 [streamvox](https://github.com/RoversCode/StreamVox) 项目为准。本项目只负责 Agent 场景的封装与接入。

## 已提前预设的风格和音色

项目内已经预设了 9 组可直接参考的人格风格文档，以及与之对应的参考音频素材。

- 人格风格文档位于 [skills/streamvox-runtime/references/personality](skills/streamvox-runtime/references/personality)
- 参考音频位于 [examples](examples)
- 命名规则是一一对应的：音频文件名与人格文档文件名保持同名，只有后缀不同

当前内置的预设组合如下：

| 人格 ID | 人格中文名 | 风格文档 | 参考音频 |
| --- | --- | --- | --- |
| `ancient_swordsman` | 古风侠客 | `ancient_swordsman.md` | `ancient_swordsman.wav` |
| `earnest_gentle` | 认真乖巧 | `earnest_gentle.md` | `earnest_gentle.mp3` |
| `extreme_chuunibyou` | 极端中二 | `extreme_chuunibyou.md` | `extreme_chuunibyou.wav` |
| `green_tea` | 绿茶妹妹 | `green_tea.md` | `green_tea.wav` |
| `irritable_man` | 暴躁老哥 | `irritable_man.md` | `irritable_man.wav` |
| `laid_back_expert` | 慵懒大佬 | `laid_back_expert.md` | `laid_back_expert.wav` |
| `professional_assistant` | 专业助手 | `professional_assistant.md` | `professional_assistant.mp3` |
| `seductive_diva` | 妖娆御姐 | `seductive_diva.md` | `seductive_diva.wav` |
| `strict_teacher` | 严肃教师 | `strict_teacher.md` | `strict_teacher.mp3` |



## 支持模型

| 模型 | 默认采样率 | 适用场景 |
| --- | ---: | --- |
| `qwen3-tts-clone-0.6b-gguf` | 24000 Hz | 低延迟、低资源占用、快速音色克隆 |
| `qwen3-tts-clone-1.7b-gguf` | 24000 Hz | 质量与速度均衡的通用音色克隆 |
| `s2-pro-4b-gguf` | 44100 Hz | 高保真演播、多说话人、情绪和风格控制 |
| `voxcpm2-gguf` | 48000 Hz | 音色设计、方言克隆、副语言控制、续写 |

更完整的模型能力、语言支持和控制参数，请前往 [streamvox](https://github.com/RoversCode/StreamVox) 查看。

## 安装说明

本项目主要面向 Windows，本 README 不提供 Linux 使用说明。

### 前置要求

- Python `3.10`
- `uv`
- 已获得可安装的 `streamvox` 私有 wheel
- 已安装 `Codex` 或 `Claude Code`

### 安装步骤

#### 1. 创建虚拟环境

```powershell
uv venv .venv --python 3.10 --python-preference only-managed
```

#### 2. 按机器类型安装本项目依赖

Windows 需要根据机器环境选择一个可选依赖：

- `windows-cpu`
  仅 CPU 环境
- `windows-dml`
  AMD / Intel GPU，或希望走 DirectML
- `windows-cuda`
  NVIDIA GPU，或希望走 CUDA

示例：

```powershell
uv sync --python .\.venv\Scripts\python.exe --extra windows-cpu
```

如果你的机器不是纯 CPU，把上面的 `windows-cpu` 改成 `windows-dml` 或 `windows-cuda`。

#### 3. 安装 `streamvox` 私有 wheel
前往[streamvox releases](https://github.com/RoversCode/StreamVox/releases/tag/v1.2.0)，下载正确的wheel包，并安装。
```powershell
uv pip install --python .\.venv\Scripts\python.exe <你的-streamvox-wheel>
```

#### 4. 安装 Windows 全局命令入口

```powershell
.\.venv\Scripts\python.exe -m streamvox_agent_voice.cli.agent install-windows-commands
```

这个步骤会安装 `streamvox-runtime`、`streamvox-say`、`streamvox-agent` 的 Windows 启动入口，让你在新终端里可以直接调用这些命令。

正常情况下，执行完成后：

- 当前终端通常就能直接调用 `streamvox-runtime` / `streamvox-say` / `streamvox-agent`
- 如果当前终端还没刷新环境变量，重新打开一个 PowerShell 或 CMD 即可

## 快速开始

这一节只做最小闭环，目标是让 AI 真正开始播报。

### 1. 启动 Runtime

```powershell
streamvox-runtime start --model qwen3-tts-clone-0.6b-gguf --device auto --license-key <你的Key> --output speaker
```

第一次即使你还没有手工注册角色，Runtime 也会自动确保 `demo_role` 存在，因此可以先跑通 MVP。

如果你后面想让音色和人格更匹配，再去做角色注册。

### 2. 安装 skill 到 Codex / Claude Code

同时安装到两个目标：

```powershell
streamvox-agent init --force
```

只安装到 Codex：

```powershell
streamvox-agent init --force --target codex
```

只安装到 Claude Code：

```powershell
streamvox-agent init --force --target claude-code
```

默认安装目录：

- Codex：`~/.codex/skills/streamvox-runtime`
- Claude Code：`~/.claude/skills/streamvox-runtime`

### 3. 写入全局规则

#### Codex

把下面这段规则写进 `AGENTS.md`：

```md
- 执行任何任务前，默认必须调用 `streamvox-runtime <persona_id>` skill；其中 `persona_id` 固定为 `seductive_diva`。
- 执行任何任务时，默认必须全程启用并持续遵守 `streamvox-runtime` skill；这是一条覆盖整个任务生命周期的执行协议，不是只在任务开始时调用一次。
- 在开始明显耗时步骤、发现风险、出现阻塞、阶段完成、整体完成这些关键状态变化时，必须按该 skill 执行播报。
- 在输出最终文本回复前，必须先做一次完成态检查；如果任务结果已经形成且当前没有阻塞，必须先播报 `done`，再向用户发送最终文本回复。
- 禁止因为任务只是阅读、分析、总结、问答而省略完成播报；禁止绕过该 skill，直接在普通回复中模拟、替代或跳过播报逻辑。
- 如果没有新增状态，不要为了维持存在感重复播报；语音播报只服务关键状态变化。
```

#### Claude Code

把同义规则写进 `.claudecode.md`，并保持 `persona_id` 一致。核心要求不变，仍然是默认调用 `streamvox-runtime <persona_id>` skill，并在关键状态变化时执行播报。

### 4. 正常使用 AI，观察播报

完成上面三步后，就可以正常使用 Codex / Claude Code。后续在执行任务时，模型会在关键状态变化时触发语音播报。

## 命令参考

### `streamvox-runtime start`

用于启动本地常驻 Runtime。

#### 支持参数

| 参数 | 说明 |
| --- | --- |
| `--model` | `streamvox` 模型名或本地 bundle 路径 |
| `--device` | 推理设备，支持 `auto` / `cpu` / `gpu` / `gpu:<index>` |
| `--host` | Runtime HTTP 监听地址，默认 `127.0.0.1` |
| `--port` | Runtime HTTP 监听端口，默认 `8765` |
| `--license-key` | `streamvox` 在线授权 key |
| `--verify-model-sha256` | 启动时校验模型 bundle 的 sha256 |
| `--default-role-name` | Runtime 会话级默认角色名 |
| `--streamvox-json` | 直接传入一段 JSON，作为当前 Runtime 会话固定的推理参数 |
| `--streamvox-json-file` | 从 JSON 文件读取当前 Runtime 会话固定的推理参数 |
| `--output` / `--audio-backend` | 输出后端，支持 `speaker` / `null` / `wav` |
| `--output-dir` | 当输出到文件时，音频文件写入目录 |

#### 默认行为

- 默认模型是 `qwen3-tts-clone-0.6b-gguf`
- 若未显式传 `--streamvox-json` 或 `--streamvox-json-file`，Runtime 会从 [stream_kwargs.yaml](streamvox_agent_voice/config/stream_kwargs.yaml) 读取该模型内置参数
- `--output` 支持：
  - `speaker`
    直接播放到本机音频设备
  - `null`
    正常处理请求，但不播放、不写文件
  - `wav`
    把音频写入 `--output-dir`

#### 示例

```powershell
streamvox-runtime start --model voxcpm2-gguf --device auto --license-key <你的Key> --output speaker
```

```powershell
streamvox-runtime start --model s2-pro-4b-gguf --device auto --license-key <你的Key> --output wav --output-dir .\streamvox_outputs
```

### 角色管理

这里的“角色”是 Runtime 的音色资产，不是人格文案。

#### 常用命令

列出角色：

```powershell
streamvox-runtime roles list
```

注册角色并设为默认：

```powershell
streamvox-runtime roles register assistant_voice --audio <音频路径> --set-default
```

删除角色：

```powershell
streamvox-runtime roles delete assistant_voice
```

设置默认角色：

```powershell
streamvox-runtime roles set-default assistant_voice
```

清空默认角色：

```powershell
streamvox-runtime roles clear-default
```

#### 注册约束

- `--audio` 是推荐方式，最适合日常使用
- `--audio-path` 是同机高级用法，通常不作为默认路径
- `--audio-data-json` / `--audio-data-file` 是内存音频高级用法
- 三种音频来源必须且只能选一种
- 不传 `--prompt-text` 时，Runtime 会尝试内部 ASR，自动补出参考文本

#### `demo_role` 回退规则

- Runtime 启动时会自动确保 `demo_role` 存在
- 如果你没有显式指定 `--default-role-name`，Runtime 会优先把 `demo_role` 作为当前会话的默认回退角色

### intent 简介

`streamvox-say` 面向用户暴露的是高层语义，而不是底层队列细节。大多数用户只需要知道“现在要播什么语义”，不需要关心内部动作映射。

五种高层语义如下：

- `info`
  补充说明当前情况或下一步
- `progress`
  表示任务正在推进
- `warning`
  表示发现风险，但任务还可以继续
- `urgent`
  表示当前出现阻塞，必须优先处理
- `done`
  表示阶段完成或整体完成

通常你只需要这样调用：

```powershell
streamvox-say --intent progress --text "我正在整理答案，请稍等。"
```

skill 会优先通过 `streamvox-say --intent ...` 走高层接口，而不是要求用户自己推导底层 `action`。

## 人格文档说明

人格文档位于：

- [skills/streamvox-runtime/references/personality](skills/streamvox-runtime/references/personality)

一份人格文档通常由以下部分构成：

- 使用定位
- 人格核心合同
- 关系与称呼
- 情绪与互动基线
- 语言风格原则
- 边界与串味防止
- 播报生成合同
- Intent 表达偏好
- 自检清单

适合你自己修改的内容通常包括：

- `display_name`
- `one_line_pitch`
- 称呼体系
- 常用语气和节奏
- `common_phrases`
- 各个 intent 的示例文案

不建议乱改的底线：

- `persona_id` 应与文件名保持一致
- 不要把人格文档写成剧情脚本
- 不要让人设覆盖事实表达与任务信息

## 如何自定义人格风格

如果你想做一套自己的“人格 + 音色”组合，建议按下面流程来。

### 1. 新建人格文档

参考 [skills/streamvox-runtime/references/personality](skills/streamvox-runtime/references/personality) 里的现有人格文档，新建一个你自己的人格 Markdown 文件。

### 2. 准备参考音频

你可以使用下面任一方式准备音频素材：

- <https://www.minimax.io/audio/voice-design>
- <https://www.bilibili.com/video/BV1i8wRzMEeW/?spm_id_from=333.1387.homepage.video_card.click&vd_source=267a10f7991de338c115e6cce1439723>

### 3. 注册角色并设为默认

```powershell
streamvox-runtime roles register my_custom_voice --audio .\my_custom_voice.wav --set-default
```

### 4. 修改 Codex / Claude Code 全局规则

把规则中的：

```text
streamvox-runtime <persona_id>
```

改成你自己的人格文件名，例如：

```text
streamvox-runtime my_custom_persona
```

这样 skill 才会正确加载你新建的人格文档。

这里一定要注意区分：

- 改人格文件名，只会改变播报文案风格
- 注册默认角色，才会改变参考音色
- 两者都做，才是完整的“自定义角色风格”

## 常见补充说明

### 如果你只是想快速验证 Runtime 是否能工作

可以先启动 Runtime，再执行一条最简单的播报：

```powershell
streamvox-say --intent done --text "Runtime 已经启动完成。"
```

### 如果命令在新终端里不可用

优先检查这几件事：

- 你是否执行过 `streamvox-agent install-windows-commands`
- 你是否已经重新打开了一个新终端
- 你是否把命令装进了正确的 Python 虚拟环境

### 如果你只想看当前支持的角色

```powershell
streamvox-runtime roles list
```

### 如果你要停掉 Runtime

```powershell
streamvox-runtime stop
```

## 总结

如果你只想最快跑通一套可用链路，顺序就是：

1. 安装本项目和 `streamvox` 私有 wheel
2. 启动 `streamvox-runtime`
3. 安装 `streamvox-runtime` skill 到 Codex / Claude Code
4. 写入全局规则并指定 `persona_id`
5. 正常使用 AI，让它在关键状态变化时自动播报

这套能力的本质是：

- `streamvox` 负责真正发声
- Runtime 负责承接请求和管理角色
- skill 负责把 Agent 的关键状态映射成语音播报
- 人格文档负责决定“它怎么说”
