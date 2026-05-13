# 事件协议

这份文档描述的是 Runtime 公开出来的稳定事件语义，而不是底层 StreamVox SDK 的全部参数矩阵。

## 主入口

### CLI

- `streamvox-say`
- `streamvox-runtime`

### HTTP

- `GET /health`
- `GET /status`
- `GET /capabilities`
- `GET /roles`
- `GET /skill/describe`
- `GET /skill/fingerprint`
- `POST /events`
- `POST /roles`
- `POST /roles/upload`
- `POST /roles/delete`
- `POST /session/default-role`
- `POST /stop`
- `POST /shutdown`

## `streamvox-say` 的两层心智模型

### 高层意图入口

适合 Agent 直接使用：

- `--intent info --text`
- `--intent progress --text`
- `--intent warning --text`
- `--intent urgent --text`
- `--intent done --text`
- `--stop`

示例：

```bash
streamvox-say --intent progress --text "正在读取文件"
streamvox-say --intent warning --text "我发现配置需要你稍后确认"
streamvox-say --intent done --text "处理完成"
streamvox-say --intent urgent --text "等等，我发现了新问题"
streamvox-say --stop
```

默认情况下，`intent` 会映射到固定队列策略：

- `info`
  - `enqueue`
- `progress`
  - `replace_pending`
- `warning`
  - `clear_pending_then_enqueue`
- `urgent`
  - `interrupt`
- `done`
  - `clear_pending_then_enqueue`

### 底层协议入口

适合需要更细控制的调用方：

- `intent`
- `action`
- `wait`

示例：

```bash
streamvox-say --intent progress --action replace_pending "正在更新进度"
```

一旦显式传了 `--action`，CLI 会直接使用这组底层参数，不再套用高层默认策略。

## 事件字段

### `intent`

语义标签，不直接等于播放行为。当前常见值：

- `info`
- `progress`
- `warning`
- `urgent`
- `done`

推荐语义边界：

- `info`
  - 用于普通说明
- `progress`
  - 用于阶段变化
- `warning`
  - 用于需要用户注意但任务仍可继续
- `urgent`
  - 用于需要立即插播的新内容
- `done`
  - 用于任务完成

### `action`

队列控制语义。当前公开值：

- `enqueue`
- `interrupt`
- `stop`
- `replace_pending`
- `clear_pending_then_enqueue`

### `wait`

- `false`
  - Runtime 接收后快速返回
- `true`
  - 等待当前事件完成后再返回

## `metadata` 的公开语义

### `role_name`

`role_name` 已经是公开能力，不再是规划中的方向。

作用：

- 覆盖当前 Runtime 会话默认角色
- 命中一个已持久化的角色资产

示例：

```bash
streamvox-say --role-name assistant_voice "继续使用这个角色音色播报"
```

### 固定 `stream_kwargs`

模型私有 `stream(...)` 参数不再通过单条事件传递。

当前公开语义改为：

- 需要模型私有推理参数时
  - 只能在 `streamvox-runtime start` 时通过 `--streamvox-json` 或 `--streamvox-json-file` 固定
- Runtime 启动后
  - 同一会话内的所有播报复用同一组 `stream_kwargs`
- `/status` 和 `/skill/describe`
  - 会公开当前固定下来的 `stream_kwargs`

示例：

```bash
streamvox-runtime start --streamvox-json '{"mode":"ref"}'
```

## 角色注册协议

### 本机路径注册

```bash
streamvox-runtime roles register assistant_voice --audio ./reference.wav
```

### 二进制上传注册

```bash
streamvox-runtime roles register assistant_voice --audio ./reference.wav --set-default
```

说明：

- `--audio` 是当前推荐主入口
- `--prompt-text` 只作为显式覆盖入口保留
- 缺省 `prompt_text` 时由 Runtime 内部自动转写参考音频

### 内存音频注册

```bash
streamvox-runtime roles register memory_voice --audio-data-file ./samples.json --sample-rate 24000
```

## 当前公开真相

### 1. 默认角色是会话态

`default_role_name` 属于当前 Runtime 会话，不是永久全局默认值。

### 2. 角色资产是持久化的

角色注册成功后，会进入当前模型作用域下的缓存。

### 3. 角色缓存按模型隔离

同一个名字的角色，不代表可以跨模型直接复用。

### 4. `voxcpm2-gguf` 的 `ref` / `continuation` / `ref_continuation` 必须命中持久化 `role_name`

这不是建议，而是当前 Runtime 已经执行的语义约束。

### 5. `control_text` 不是跨模型通用能力

它主要属于 VoxCPM2 工作流。Agent 不应把它当成所有模型都能理解的全局控制字段。

### 6. 旧事件级推理参数入口已经关闭

以下 metadata 入口不再支持：

- `metadata.streamvox`
- `metadata.language`
- `metadata.mode`
- `metadata.control_text`
- `metadata.track_performance`

如果继续传这些字段，Runtime 会返回 `400`，并提示改用 `streamvox-runtime start --streamvox-json`。

## 错误语义

CLI 现在会尽量把 Runtime 返回的 `detail` 直接打印出来。

典型示例：

- `Runtime request failed (400): role name assistant_voice already exists in voxcpm2-gguf`
- `Runtime request failed (400): mode ref requires a persisted role_name`

这让 Agent 能够基于错误内容直接恢复，而不是只看到模糊的 HTTP 400。
