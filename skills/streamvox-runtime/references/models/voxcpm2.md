# VoxCPM2 参考

## 适合什么场景

- 文本音色设计
- 参考克隆微调
- continuation / ref / ref_continuation 这类工作流

## 推荐怎么用

- 先读 `capabilities`
- 如果工作流要求持久化角色，先注册或命中 `role_name`
- 需要 `control_text` 或 `mode` 时，再显式传 `metadata.streamvox`

## 文本写法

- 明确语气或风格时再用控制字段
- 播报文本本身仍然保持短句
- 不要把复杂控制文本塞进每一次普通进度播报

## 关键约束

- `ref` / `continuation` / `ref_continuation` 通常需要已持久化的 `role_name`
- `control_text` 不是跨模型通用能力
- 不要在没读 `capabilities` 前盲猜参数
