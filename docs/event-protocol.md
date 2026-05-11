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

- `--info`
- `--progress`
- `--warning`
- `--urgent`
- `--done`
- `--stop`
- `--interrupt`

示例：

```bash
streamvox-say --progress "正在读取文件"
streamvox-say --warning "我发现配置需要你稍后确认"
streamvox-say --done "处理完成"
streamvox-say --interrupt "等等，我发现了新问题"
streamvox-say --stop
```

### 底层协议入口

适合需要更细控制的调用方：

- `event`
- `action`
- `wait`

示例：

```bash
streamvox-say --event progress --action replace_pending "正在更新进度"
```

## 事件字段

### `event`

语义标签，不直接等于播放行为。当前常见值：

- `started`
- `progress`
- `warning`
- `done`
- `error`
- `interrupt`
- `stop`

推荐语义边界：

- `progress`
  - 用于阶段变化
- `warning`
  - 用于需要用户注意但任务仍可继续
- `error`
  - 用于失败或当前动作无法继续
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

### `metadata.streamvox`

`metadata.streamvox` 是模型私有参数透传入口。

当前建议只把它当成：

- 模型私有 `stream(...)` 参数传递层
- 显式的、可审计的工作流入口

而不是：

- 任意模型通用配置层
- 永久会话默认配置层

示例：

```bash
streamvox-say --streamvox-json '{"language":"Chinese"}' "这条请求显式指定语言"
```

Windows PowerShell 更推荐：

```powershell
streamvox-say --streamvox-json-file .\streamvox.json "这条请求通过 JSON 文件传递模型私有参数"
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

## 错误语义

CLI 现在会尽量把 Runtime 返回的 `detail` 直接打印出来。

典型示例：

- `Runtime request failed (400): role name assistant_voice already exists in voxcpm2-gguf`
- `Runtime request failed (400): mode ref requires a persisted role_name`

这让 Agent 能够基于错误内容直接恢复，而不是只看到模糊的 HTTP 400。
