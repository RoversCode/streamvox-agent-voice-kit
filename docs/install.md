# 安装与平台差异

这份文档只回答一件事：怎样在 Linux bash 或 Windows PowerShell 中，把 `streamvox-agent-voice-kit` 安装到可以直接被 Agent 调用的状态。

## 前提

- Python `>=3.10`
- `uv`
- 一个可用的 `streamvox` 私有 wheel
- 如果要本机播音：
  - `sounddevice`
- 如果只做服务器调用：
  - 使用 `--output null` 即可

## 自动安装入口

如果你希望 Agent 或脚本自动判断应该装哪个 StreamVox wheel，优先使用：

- Linux / WSL：
  - `./scripts/install.sh`
- Windows PowerShell：
  - `.\scripts\install.ps1`
- 通用调试入口：
  - `python -m streamvox_agent_voice.bootstrap --dry-run`

安装引导会做两件事：

1. 根据系统和显卡状态选择本项目的 optional extra
2. 从 `https://github.com/RoversCode/StreamVox/releases` 自动选择最匹配的 StreamVox wheel

当前默认策略是：

- Windows + NVIDIA GPU：
  - `windows-cuda`
  - 优先匹配 `cuda` wheel
- Windows + AMD / Intel GPU：
  - `windows-dml`
  - 优先匹配 `dml` / `directml` wheel
- Windows + 无合适 GPU：
  - `windows-cpu`
  - 优先匹配 `cpu` wheel
- Linux + NVIDIA GPU：
  - 优先匹配 `cuda` wheel
- Linux + 无 NVIDIA GPU：
  - 优先匹配 `cpu` wheel

如果 Agent 想先判断、再执行安装，可以先跑：

```bash
python -m streamvox_agent_voice.bootstrap --dry-run
```

它会输出 JSON，包括当前系统画像、推荐变体、命中的 release 资产和 virtualenv 目标目录。

## Linux / WSL

### 1. 创建环境

```bash
./scripts/install.sh
source .venv/bin/activate
```

### 2. 启动 Runtime

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker
```

无声服务器：

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output null
```

### 3. 冒烟检查

```bash
streamvox-runtime status
streamvox-runtime capabilities
streamvox-runtime roles list
streamvox-say --progress "Runtime 已启动"
streamvox-say --done "链路验证完成"
```

## Windows PowerShell

### 1. 创建环境

```powershell
.\scripts\install.ps1
.\.venv\Scripts\Activate.ps1
```

如果你想先看 Agent 会选哪个包，不立刻安装：

```powershell
python -m streamvox_agent_voice.bootstrap --dry-run
```

### 2. 启动 Runtime

```powershell
streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker
```

无声服务器：

```powershell
streamvox-runtime start --model voxcpm2-gguf --device auto --output null
```

### 3. 冒烟检查

```powershell
streamvox-runtime status
streamvox-runtime capabilities
streamvox-runtime roles list
streamvox-say --progress "Runtime 已启动"
streamvox-say --done "链路验证完成"
```

## PowerShell 专项注意

### 1. 不要照抄 bash 的续行符

下面这种写法是 bash，不是 PowerShell：

```bash
streamvox-runtime roles register assistant_voice \
  --audio-file examples/Condition3.wav \
  --set-default
```

PowerShell 要么写成单行，要么用反引号续行：

```powershell
streamvox-runtime roles register assistant_voice `
  --audio-file .\examples\Condition3.wav `
  --set-default
```

### 2. 不要长期依赖复杂内联 JSON

PowerShell 在原生命令参数传递上容易把 JSON 引号处理得不稳定。推荐优先用 `--streamvox-json-file`。

示例：

```json
{
  "mode": "ref",
  "control_text": "四川话，轻松一点"
}
```

```powershell
streamvox-say --role-name assistant_voice --streamvox-json-file .\streamvox-voice.json "这条请求显式指定 VoxCPM2 风格控制"
```

## 私有 wheel 与 `uv sync --inexact`

安装引导内部仍然使用 `uv sync --inexact`。原因是：

- 它会同步本项目依赖。
- 它不会轻易移除你已经安装在虚拟环境中的私有 `streamvox` wheel。

如果你先装了 wheel，再执行 `uv sync --inexact`，通常能保留这个私有依赖。

## 失败时先查什么

### Runtime 启不来

- 检查 `streamvox` wheel 是否真的安装在当前虚拟环境中。
- 检查模型文件、许可证和设备参数是否可用。
- 用 `streamvox-runtime doctor --model <model>` 先看硬件建议。

### `streamvox-say` 返回 400

先看 CLI 现在打印出的服务端 `detail`，再区分：

- `role name ... already exists`
  - 说明是重复注册角色。
- `mode ref requires a persisted role_name`
  - 说明当前模式要求持久化角色，但你没有命中角色。
- `default_role_name` 为空
  - 说明角色资产仍在，但当前 Runtime 会话没有默认角色。

### 角色明明存在却不能直接用

先检查：

```bash
streamvox-runtime roles list
```

重点看：

- `roles` 里角色是否存在
- `default_role_name` 是否为 `null`

如果角色存在但默认角色为空，执行：

```bash
streamvox-runtime roles set-default assistant_voice
```

或者每次显式传：

```bash
streamvox-say --role-name assistant_voice "..."
```
## 瀹夎鍚庣殑鏈€灏忛獙鏀惰矾寰?

濡傛灉浣犲笇鏈?Agent 鍦ㄦ寮忔帴绾垮墠鍏堝仛涓€娆￠潪浜や簰鑷獙锛屽彲浠ョ洿鎺ヨ窇锛?

```bash
streamvox-runtime selftest
streamvox-runtime benchmark --text "您好，我正在整理答案，请稍等片刻。"
streamvox-runtime benchmark --json-summary-only --text "您好，我正在整理答案，请稍等片刻。"
```

`selftest` 鐢ㄤ簬楠岃瘉 `status`銆乣capabilities`銆乣roles list` 鍜屾渶灏忔挱鎶ラ摼璺€?  
`benchmark` 浼氳緭鍑哄钩鍧囧畬鎴愯€楁椂銆佸弬鑰冭闊虫椂闀垮拰鍚彂寮忓疄鏃舵€у垽鏂紝甯姪 Agent 鍒ゅ畾褰撳墠妯″瀷鍜岃澶囨槸鍚﹂€傚悎鍋氱浜烘櫤鑳藉姪鎵嬬殑瀹炴椂鎾姤閰嶇疆銆?  
濡傛灉褰撳墠 Runtime 浼氳瘽鏄?`--output wav`锛屽畠浼氫紭鍏堣鍙栫湡瀹炵敓鎴?wav 鏃堕暱锛涘惁鍒欏洖閫€鍒版枃鏈唴瀹逛及鏃躲€?  
`--json-summary-only` 鐢ㄤ簬鏈哄櫒鐩存帴娑堣垂 benchmark 缁撴灉锛屽彧杈撳嚭鎽樿瀛楁銆?
