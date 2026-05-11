---
name: StreamVox Runtime Voice Skill
description: 在支持 skills 的智能体里，通过本地 StreamVox Runtime 在关键节点播报简短的进度、提醒、错误和完成语音。
allowed-tools: Bash, Read, Grep, Glob
---

# StreamVox Runtime Voice Skill

## 说明

这是一份通用 skill，不再区分 Claude Code、Codex 或其他支持 skill 的宿主。

它只定义一件事：**当用户已经手动安装并启动好 Runtime 后，Agent 如何在关键节点调用 `streamvox-say`。**

## 前提

- 用户已经主动安装 `streamvox-agent-voice-kit`
- 用户已经主动启动 `streamvox-runtime`
- Agent 只负责调用 `streamvox-say`
- Runtime 负责合成和播放

不要把这个 skill 当成安装器或服务管理器。

## 宿主适配

- Claude Code：把这份 skill 安装到项目后，直接按本 skill 的规则执行
- Codex：把这份 skill 安装到项目后，直接按本 skill 的规则执行
- 其他支持 skills 的 Agent：如果能读 `SKILL.md` 与 `references/`，就按同一规则使用

不再维护宿主专属接线文档。

## 关键规则

- 只在关键节点播报，不要每一步都播报
- 每条语音尽量短，优先一句话
- `progress` 用于阶段变化
- `warning` 用于需要用户注意但任务仍可继续
- `error` 用于失败或当前动作无法继续
- `done` 用于任务完成
- Runtime 不可用时，不要中断主任务，继续以文本方式工作

## 禁止事项

- 禁止自动安装 `streamvox-agent-voice-kit`
- 禁止自动下载模型
- 禁止自动启动 `streamvox-runtime`
- 禁止自动修改 shell 配置或环境变量
- 禁止自动激活授权
- 禁止在没有用户确认的情况下安装依赖

## 推荐调用方式

### 1. 本轮任务第一次需要播报时，只做一次轻量探测

优先做一次快速可用性检查：

```bash
streamvox-runtime status
```

如果这一步失败，说明 Runtime 当前不可用。

### 2. 探测成功后，只在关键节点调用 `streamvox-say`

常用示例：

```bash
streamvox-say --progress "我正在读取项目结构"
streamvox-say --warning "我发现配置需要你稍后确认"
streamvox-say --error "执行失败，需要检查日志"
streamvox-say --done "我已经完成检查，主要有三个建议"
```

### 3. 探测失败或首次播报失败后，本轮任务后续禁用语音

业务意图是避免 Agent 在同一轮任务里反复尝试连接一个明显不可用的 Runtime。

失败后：

- 不再重复调用 `streamvox-runtime status`
- 不再反复尝试 `streamvox-say`
- 后续改为纯文本继续任务

## 什么时候该播报

- 开始一个用户可感知的长任务时
- 从一个阶段切到另一个阶段时
- 找到关键结构、关键问题或关键结论时
- 需要用户注意风险、约束或下一步动作时
- 任务完成并能给出总结时

## 什么时候不要播报

- 普通文件读取
- 高频循环步骤
- 连续的小型内部推理
- 用户已经能从终端直接看到的细碎进度
- 还没有形成稳定结论的草稿想法

## 文本写法建议

- 先说结果，再补一个最小必要限定
- 口语化，但不要啰嗦
- 一次只说一个重点
- 避免长名单，优先先报摘要

示例：

- 好：`我正在读取项目结构`
- 好：`我找到了 CLI 入口文件`
- 好：`我发现 Runtime 状态管理可以简化`
- 好：`我已经完成检查，主要有三个建议`
- 差：`我现在要先读取项目结构然后继续扫描更多文件之后再看看可能有哪些问题`

## 模型参考

优先按当前 Runtime 已公开支持的模型工作流使用：

- `references/models/qwen3-tts-clone.md`
- `references/models/s2-pro.md`
- `references/models/voxcpm2.md`

先读当前 Runtime 能力快照，再决定是否显式传模型私有参数。

## 示例

典型链路：

1. 用户先启动 Runtime
2. Agent 读取项目并准备开始较长任务
3. Agent 先做一次 `streamvox-runtime status` 探测
4. Runtime 可用时，在关键节点调用 `streamvox-say`
5. Runtime 不可用时，Agent 直接退回纯文本，不中断任务
