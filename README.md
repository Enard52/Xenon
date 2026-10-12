# Xenon

一个交互式 **AI 编码代理（Agent Harness）**：在终端里与多模型协作完成任务——读写代码、执行命令、验证结果，每一步都经过确定性校验与可审计的权限边界。

> **定位：唯一一个把"机器验证到什么程度"透明说给用户听的 Agent Harness。**
> Claude Code / Codex 的哲学是"我不验证语义，你信我"；Xenon 的哲学是
> **证据我管、真伪你核**——机器只对「过程真实性」负责，对「内容正确性」
> 做分级透明披露。核心不是"又一个 LLM 客户端"，而是围绕
> **证据哈希链、单一语义通道、可回溯会话树** 构建的代理骨架。

## 三层可信度模型（核心差异）

| 层 | 机制 | 机器职责 |
|---|---|---|
| **L0 证据层** | 会话事件日志是 append-only 哈希链：每条事件带内容哈希 + 前驱哈希，`/evidence` 命令随时重算自证（当前会话 / 全局 / 指定会话） | 证明**过程真实**（做了什么、成败几何、链是否被篡改） |
| **L1 结构层** | 空洞回答（确定性、无语义盲点）是唯一阻断类校验：命中才反馈重试（半预算），同因熔断 | 拦截**没干活**的回答 |
| **L2 语义层** | 宣称审计 / 完成准则 / 文件声称 / 写入后验证：**不阻断发布**，命中时附黄色「待人工核验清单」面板随答案输出；重试耗尽 → 降级发布 | 把**核不到的**醒目列给用户自核 |

语义判定只有一处（`xenon/turn/gate.py`），引擎内部没有第二套验证循环；
工具成败只由工具回执的 `success` 字段决定（单一语义通道），不用关键词猜。

`/evidence` 实际输出（结构化回合摘要 + 一行链自证）：

<img src="docs/evidence-chain.png" alt="/evidence 输出示例" width="720">

## 其他核心能力

| 能力 | 说明 |
|---|---|
| **会话树（TurnTree）** | 每个用户回合是一个节点（状态/产物/判定/事件指针）。`/rewind` 回退、`/fork` 分叉、裸"继续"自动从**中断/熔断节点**续接 |
| **预算检查点（非固定步数）** | 窗口耗尽时有进展 → 挂起审批"是否继续"；原地打转 → LoopDetector 熔断；同因基础设施错误连续两轮 → 快速熔断并给出指引 |
| **结构化回合归档** | 长对话自动压缩：旧回合确定性折叠为意图/工具成败/失败日志/决策/产物归档块，零 LLM 开销；同时是检索摘要源 |
| **边界审批** | 工作区内写免问；越界写与命令询问（统一面板 + diff 预览 + `a` 登记带 TTL 的会话规则）。审批是封闭词表、fail-closed，授权不随检索/恢复复活 |
| **子代理默认只读** | `spawn_agent` 委派的子代理执行级别封顶 READ_ONLY，`read_only=false` 显式放行 |
| **沙箱 seam** | 只读模式 + 命令白名单 + WSL/Docker 检测（诚实声明：软件边界，非真隔离） |
| **诚实截断标注** | 输出因长度限制被截断时，回复尾部可见标记，不伪装完整 |
| **hooks** | 用户/项目 `.xenon/hooks.yaml`：PreToolUse / PostToolUse / Stop / SubagentStop（exit 2 阻断，JSON stdin） |

## 快速开始

当前版本：**v0.9.2**（版本单一来源 `xenon.__version__`，历史见 [CHANGELOG](CHANGELOG.md)，发行包见 [GitHub Releases](https://github.com/xianyu-sheng/Xenon/releases)）。

```bash
# 克隆源码本地安装（editable，源码即运行版）
git clone https://github.com/xianyu-sheng/Xenon.git
cd Xenon
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # Windows
source .venv/bin/activate && pip install -e .   # Linux/macOS

# 启动
xenon
# 首次运行会引导配置（/setup：Key、模型、范式）
```

常用命令：`/evidence`（L0 证据账本自证）`/plan` `/goal` `/review` `/rewind <n>` `/fork [n]` `/compact` `/sessions` `/permissions` `/tools` `/help`

## 会话状态机（每回合）

```
用户输入 → 单一语义通道（TurnContract，LLM 意图分类器 + 正则护栏）
  → 引擎执行（纯执行器：预算检查点护栏 + 中断 + 循环检测）
  → TurnGate 回合校验（唯一判定点）
      pass   → 发布
      remind → 发布 + 待人工核验清单（L2 语义层，不阻断）
      fail   → 同回合反馈重试（预算=首轮实际步数/2，clamp[10,40]）；
               耗尽 → 降级发布（degraded + 核验清单）
      fuse   → 同因结构失败熔断，按未完成交付
  → 树节点状态落盘 + 哈希链事件追加 + 回合归档
```

## 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `XENON_APPROVAL_TTL` | 会话级 `a` 授权规则 TTL（秒） | 1800 |
| `XENON_VERIFY_RETRIES` | 结构层失败后同回合重试次数 | 2 |
| `XENON_RETRY_BUDGET_MIN/MAX` | 重试轮预算 clamp | 10 / 40 |
| `XENON_GATE_FUSE_THRESHOLD` | 同因结构失败熔断阈值 | 2 |
| `XENON_MAX_ITERATIONS` | 单次运行步数（检查点窗口基准） | 40 |
| `XENON_CHECKPOINT_STEPS` | 检查点窗口大小 | = 步数上限 |
| `XENON_MAX_TOKENS` | 单次 LLM 调用输出上限 | 8192 |
| `XENON_MAX_CONTINUATIONS` | 截断自动续写次数 | 3 |
| `XENON_READ_ONLY` | 只读模式（禁止一切写/执行工具） | 关 |
| `XENON_COMMAND_ALLOWLIST` | 命令首词白名单（逗号分隔） | 空=不限 |
| `XENON_SESSION_EVENTS(_DIR)` | 事件日志（哈希链）开关/目录 | 开 |
| `XENON_HOOKS` | hooks 开关 | 开 |
| `GITHUB_TOKEN` / `GH_TOKEN` | GitHub 工具认证（提升 API 限额，自动带入 git clone） | 空 |
| `XENON_INTENT_CLASSIFIER_ENABLED` | LLM 意图分类器 | 开 |

## 架构分层

```
xenon/
├── repl/        交互层：REPL 主循环、引擎宿主(engine_host)、渲染(render)、
│                回合契约(turn_contract)、任务状态(task_state)、命令组
├── turn/        回合层：TurnGate 唯一校验层（L1 结构 / L2 语义提醒）
├── session/     结构层：tree(会话树) / events(哈希链事件日志) / archive(回合归档)
│                / projection(目标投影) / query(查询)
├── engine/      引擎层：react / plan_execute / 组合引擎（纯执行器）
├── nodes/       工具层：tool_executor / approval_policy / path_targets
├── hooks/       本地 hooks 执行器
└── sandbox/     沙箱 seam：只读模式 + 命令白名单 + WSL/Docker 检测
```

## Windows 说明

- Windows Terminal (ConPTY) + PowerShell 全功能支持（粘贴、中文 IME、方向键）。
- `XENON_TERMINAL_ANIMATION=0` 可关闭动画。
- 推送 Git 若网络异常：`git -c http.proxy= -c https.proxy= -c http.sslBackend=openssl push`（或走代理 `http://127.0.0.1:3067`）。

## 诚实边界

- **机器不验证语义**：L2 语义层（宣称/准则/文件声称）命中时只提醒不阻断——内容真伪请以「待人工核验清单」为准自行核对。
- **哈希链自证的是过程不是结论**：`/evidence` 证明事件流未被篡改，不证明模型回答正确。
- **沙箱是检测 + 软件边界，不是真隔离**：不可信代码请在 WSL/Docker 容器内运行 Xenon。
- `/review` 的 revert 只覆盖有 `.bak` 备份的编辑；用 git 管理不可替代。
- 意图分类器默认走最快可用模型，有 ~1s 延迟；不可用自动降级正则（保守）。

## License

MIT
