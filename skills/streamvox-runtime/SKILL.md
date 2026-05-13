---
name: streamvox-runtime
description: Use when the user wants the agent to initialize StreamVox voice behavior, inspect current runtime voice/model/default-role state, or speak short progress, warning, urgent, or done messages through a running local StreamVox runtime.
when_to_use: Use only after the user has already installed and started streamvox-runtime. Especially relevant when the agent needs to establish runtime state, refresh fingerprint-based session facts, choose a built-in style, or emit a short spoken update instead of text-only progress.
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
---

# StreamVox Runtime Voice Skill

## Purpose

This is a host-facing base skill for any agent system that supports `SKILL.md`.

Use it to do two things:

1. Explicitly initialize StreamVox voice behavior after the user has manually started the local runtime.
2. After initialization, keep runtime facts fresh and emit short spoken updates through stable CLI commands.

## Preconditions

- 用户已经主动安装 `streamvox-agent-voice-kit`
- 用户已经主动启动 `streamvox-runtime`
- The host skill is responsible for initialization, state refresh, text planning, and CLI invocation.
- Runtime is responsible for exposing facts, synthesizing, and playing audio.

Do not treat this skill as an installer or service manager.

## Do Not Do

- 禁止自动安装 `streamvox-agent-voice-kit`
- 禁止自动下载模型
- 禁止自动启动 `streamvox-runtime`
- 禁止自动修改 shell 配置或环境变量
- 禁止自动激活授权
- 禁止在没有用户确认的情况下安装依赖

If runtime commands fail, do not try to manage the service yourself.

## Additional Resources

- Read [assets/style-catalog.json](assets/style-catalog.json) only when you need to inspect the built-in styles, pick a `style_id`, or explain how a built-in style maps to model-specific expression.
- Read [references/models/qwen3-tts-clone.md](references/models/qwen3-tts-clone.md) only when the current runtime model is a Qwen3 TTS Clone variant.
- Read [references/models/s2-pro.md](references/models/s2-pro.md) only when the current runtime model is `s2-pro`.
- Read [references/models/voxcpm2.md](references/models/voxcpm2.md) only when the current runtime model is `voxcpm2`.

Keep `SKILL.md` itself as the execution contract. Only open support files when needed.

## Core Contract

- `style` 由本 skill 内置，不和模型绑定
- 用户只能在宿主侧微调内置 style，不允许新增 style 或覆写模板本体
- Runtime 只持有事实状态：当前模型、默认音色、已注册音色、公开能力
- 宿主只持有用户配置：当前激活 style、称呼、自称、强度、播报偏好
- 单一激活 style
- 全局只允许一个激活 style
- Runtime 不可用时，不要中断主任务，继续以文本方式工作

## Execution Workflow

### 1. Initialize Explicitly Once

When the user asks to initialize voice behavior, fetch the runtime fact snapshot first:

```bash
streamvox-runtime describe --json
```

From that result, keep two host-side state objects:

- `voice_profile`
  - `active_style_id`
  - `user_address`
  - `self_reference`
  - `persona_intensity`
  - `voice_enabled`
  - `speak_frequency`
  - `allow_role_override`
- `session_snapshot`
  - `fingerprint`
  - `model.name`
  - `roles.default_role_name`
  - `roles.available_role_names`
  - `model.capabilities`
  - `runtime.stream_kwargs`

Do not ask the user for runtime facts again if `session_snapshot` is still current.

### 2. Refresh Facts with Fingerprint

Before a new task or before a key spoken update, do a lightweight refresh:

```bash
streamvox-runtime fingerprint
```

Rules:

- If the fingerprint is unchanged:
  - Keep using the current `session_snapshot`.
- If the fingerprint changed:
  - Run `streamvox-runtime describe --json` again.
  - Refresh `session_snapshot`.
  - Do not reset `voice_profile`.

### 3. Use Only the Stable CLI Surface

The host should rely on only these stable commands:

```bash
streamvox-runtime describe --json
streamvox-runtime fingerprint
streamvox-say --intent progress --text "我正在整理调用链"
```

Remember these exact command surfaces:

- `streamvox-runtime describe --json`
- `streamvox-runtime fingerprint`
- `streamvox-say --intent progress --text`

### 4. Understand What `describe --json` Means

Treat `streamvox-runtime describe --json` as the authoritative runtime fact contract. It should give you:

- `fingerprint`
- current `model.name`
- current `model.capabilities`
- current `roles.default_role_name`
- current `roles.available_role_names`
- `roles.capabilities`
- `runtime.public_commands`
- `runtime.stream_kwargs`

Treat `streamvox-runtime fingerprint` as a minimal change detector. The current fingerprint is only based on:

- current loaded model identifier
- current default role name

## Built-in Styles

This skill ships with a style catalog:

- [assets/style-catalog.json](assets/style-catalog.json)

v1 built-in `style_id` values:

- `professional_assistant`
- `earnest_gentle`
- `strict_teacher`
- `laid_back_expert`
- `ancient_swordsman`
- `seductive_diva`
- `green_tea_girl`
- `hotheaded_bro`
- `extreme_chuunibyou`

Shared rules:

- styles should be distinctive
- styles should stay dramatic but restrained
- do not auto-switch style
- if the next task needs another style, the user must explicitly change it

## Model Differences

- `qwen3`
  - does not support sub-language style control
  - style should still exist, but only through text wording
- `s2-pro`
  - supports freeform style description
  - style can be expressed as freeform style guidance
- `voxcpm2`
  - supports limited style-language control
  - style should use a fixed mapping table
  - the base skill should standardize on `mode=2`

Style always exists. Model capability only changes how style is expressed, not whether style exists.

Runtime startup fixes the current model stream parameters for the whole session.

- do not try to change model-private stream parameters per spoken event
- if the user wants another runtime stream behavior, they should restart `streamvox-runtime` with another startup configuration

## Speaking Policy

Speak only at high-value moments:

- starting a user-visible long task
- changing from one phase to another
- finding a key structure, issue, or conclusion
- warning the user about a meaningful risk or constraint
- completing a task with a concise summary

Do not speak for:

- normal file reads
- high-frequency loop steps
- tiny internal reasoning updates
- noisy progress the user can already read directly
- unstable draft thoughts without a conclusion

Use one short sentence whenever possible.

### Preferred Speak Entry

Prefer the unified intent entry:

```bash
streamvox-say --intent info --text "我准备开始扫描项目结构"
streamvox-say --intent progress --text "我已经完成代码结构扫描，正在整理调用链"
streamvox-say --intent warning --text "我发现当前默认音色和上次初始化结果不一致"
streamvox-say --intent urgent --text "当前任务需要你先处理一个阻塞问题"
streamvox-say --intent done --text "我已经完成本轮分析，准备给出结论"
```

Intent meanings:

- `info`
  - ordinary announcement when a long task begins
- `progress`
  - ordinary progress when a phase advances
- `warning`
  - user should pay attention, but work can continue
- `urgent`
  - interrupt with a new blocking issue or urgent risk
- `done`
  - final completion summary

这里继续保留基础约定：

- `done` 用于任务完成

## Text Guidance

- Say the result first, then add the smallest necessary qualifier.
- Keep it spoken and natural, not verbose.
- Focus on one point at a time.
- Prefer a summary over a long list.
- First build a neutral semantic skeleton, then project it into the active style.
- If the current model does not support some style parameter, degrade only the parameter expression and keep the style itself.

Examples:

- 好：`我正在读取项目结构`
- 好：`我找到了 CLI 入口文件`
- 好：`我发现 Runtime 状态管理可以简化`
- 好：`我已经完成检查，主要有三个建议`
- 差：`我现在要先读取项目结构然后继续扫描更多文件之后再看看可能有哪些问题`

## Role Rules

- Do not override the runtime default role by default.
- Only pass `--role-name` when the user explicitly wants another existing role, or when the current spoken update must use a specific existing role.
- This base skill does not proactively orchestrate “register a new role”.
- The host should still understand that runtime supports role registration and default-role switching.

## Failure Handling

If runtime probing or speaking fails:

- do not block the main task
- do not keep retrying aggressively in the same task
- continue in plain text mode
- only try runtime commands again when a later step actually needs voice behavior

## Final Rule

Always trust the current runtime facts from `streamvox-runtime describe --json` more than old assumptions. Do not assume `qwen3`, `s2-pro`, and `voxcpm2` behave the same. Read support files only when the current model or current style decision actually requires them.
