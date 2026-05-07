# Agent 接入合同

这份文档定义的是接入顺序、状态语义和错误恢复规则。对 Agent 来说，它比项目背景更重要。

## 官方主接入面

当前项目的官方主合同是 CLI：

- `streamvox-runtime`
- `streamvox-say`

HTTP API 与 Python `VoiceClient` 是等价补充层，但不应该成为首次阅读入口。

## Agent 调用前必须知道的事实

### 1. Runtime 是会话态

`streamvox-runtime start` 启动的是一个常驻会话。

这意味着：

- 当前模型由 Runtime 会话持有
- 当前输出后端由 Runtime 会话持有
- 当前 `default_role_name` 也是 Runtime 会话态

### 2. 角色资产是持久化的，但默认角色不是

- 角色本身会缓存在当前模型作用域下
- `default_role_name` 只是当前 Runtime 会话里的默认值

所以“角色存在”不等于“默认角色已经设置”。

### 3. 角色缓存按模型隔离

在 `qwen3-tts-clone-1.7b-gguf` 下注册的角色，不能直接在 `voxcpm2-gguf` 下复用。

### 4. Agent 不应该盲猜模型能力

在发送第一条播报前，应该先读取：

1. `streamvox-runtime status`
2. `streamvox-runtime capabilities`
3. `streamvox-runtime roles list`

## 推荐的最小调用顺序

### 1. 启动 Runtime

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker
```

### 2. 读取状态

```bash
streamvox-runtime status
streamvox-runtime capabilities
streamvox-runtime roles list
```

### 3. 根据能力快照做决策

至少读这些字段：

- `resolved_model`
- `controls`
- `prompt`
- `best_for`
- `recommended_workflows`
- `recommended_parameters`
- `parameter_notes`
- `text_writing_tips`
- `known_constraints`
- `session.default_role_name`

### 4. 如果需要持久化角色，先注册或选择角色

```bash
streamvox-runtime roles register assistant_voice --audio-file ./examples/Condition3.wav --set-default
```

或者：

```bash
streamvox-runtime roles set-default assistant_voice
```

### 5. 再发送播报事件

```bash
streamvox-say --progress "正在处理请求"
streamvox-say --done "处理完成"
```

## 什么时候必须显式传 `--role-name`

以下场景建议或必须显式传 `--role-name`：

- 当前 `default_role_name` 为 `null`
- 你不想依赖当前 Runtime 会话默认值
- 你要临时切换到另一个已注册角色
- 当前模型是 `voxcpm2-gguf`，并且你要使用：
  - `mode=ref`
  - `mode=continuation`
  - `mode=ref_continuation`

示例：

```bash
streamvox-say --role-name assistant_voice --streamvox-json-file ./streamvox-voice.json "这条请求显式指定角色和模型私有参数"
```

## 什么时候必须读 `capabilities`

### 1. 启动后第一次调用前

因为 Agent 需要知道当前模型支持：

- `language` 还是 `control_text`
- 是否支持 `speaker_tags`
- 是否支持 `temperature/top_p/top_k`
- 是否存在显式 `mode`

### 2. Runtime 模型变更后

模型一旦变，角色缓存作用域和可用参数语义也会一起变。

### 3. 你准备构造模型私有参数时

不要假设所有模型都支持：

- `control_text`
- `language`
- `speaker`
- `mode`

## 角色管理规则

### 注册角色

```bash
streamvox-runtime roles register assistant_voice --audio-file ./examples/Condition3.wav --set-default
```

### 查看角色

```bash
streamvox-runtime roles list
```

返回里重点看：

- `model`
- `default_role_name`
- `roles`

### 设置默认角色

```bash
streamvox-runtime roles set-default assistant_voice
```

### 清空默认角色

```bash
streamvox-runtime roles clear-default
```

## 常见失败恢复

### `Runtime request failed (400): role name ... already exists`

含义：

- 角色早已注册成功
- 你正在重复注册

恢复动作：

- 不要重复 `register`
- 直接 `roles list`
- 必要时 `roles set-default <role_name>`

### `Runtime request failed (400): mode ref requires a persisted role_name`

含义：

- 当前模型是 `voxcpm2-gguf`
- 当前 `mode` 需要一个已持久化角色
- 你没有命中可用 `role_name`

恢复动作：

- 先 `roles list`
- 如果角色存在但默认角色为空：
  - `roles set-default assistant_voice`
- 或直接显式传：
  - `streamvox-say --role-name assistant_voice ...`

### `default_role_name` 为 `null`

含义：

- 当前 Runtime 会话没有默认角色
- 不代表角色资产不存在

恢复动作：

- 重新 `set-default`
- 或每次显式传 `--role-name`

### 模型能力和传参不匹配

含义：

- 你向不支持该参数的模型传了私有参数
- 或者参数能透传，但当前工作流语义不成立

恢复动作：

- 回到 `capabilities`
- 只暴露当前模型明确推荐的参数

## Windows 专用建议

对 PowerShell，推荐把复杂私有参数写入 JSON 文件，而不是长期使用复杂内联 JSON：

```json
{
  "mode": "ref",
  "control_text": "四川话，轻松一点"
}
```

```powershell
streamvox-say --role-name assistant_voice --streamvox-json-file .\streamvox-voice.json "这条请求显式指定 VoxCPM2 风格控制"
```

同理，角色注册也支持：

```powershell
streamvox-runtime roles register assistant_voice `
  --audio-file .\examples\Condition3.wav `
  --streamvox-json-file .\prompt-config.json `
  --set-default
```
