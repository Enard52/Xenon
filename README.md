<p align="center">
  <img src="docs/logo.svg" width="140" alt="Xenon logo">
</p>

<h1 align="center">Xenon</h1>

<p align="center"><b>Agent Harness for AI coding agents</b> —— 可信、可验证、可评测的 AI Agent 运行时</p>

Xenon 不是又一个 AI 编程助手，而是让 Agent **可信地运行**所需的基础设施：工具输出是 **Evidence**，LLM 输出只是 **Claim**，验证闭环抑制幻觉。可作命令行工具直接使用，也可作为库嵌入你的 Agent 评测流程。

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CI](https://github.com/xianyu-sheng/Xenon/actions/workflows/ci.yml/badge.svg)](https://github.com/xianyu-sheng/Xenon/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/xianyu-sheng/Xenon/branch/main/graph/badge.svg)](https://codecov.io/gh/xianyu-sheng/Xenon)
[![release v0.9.4](https://img.shields.io/badge/release-v0.9.4-orange.svg)](https://github.com/xianyu-sheng/Xenon/releases/tag/v0.9.4)

[GitHub](https://github.com/xianyu-sheng/Xenon) · [Gitee 镜像](https://gitee.com/xianyu-sheng123/Xenon)

---

## 为什么选择 Xenon

- 🔒 **证据导向**：Evidence vs Claim 验证闭环，抑制幻觉与错误传播
- 🛡️ **执行隔离**：路径围栏、命令注入拦截、权限门，所有副作用经 `ToolExecutor` 单一收敛点
- 🔄 **7 种推理范式**：ReAct / Plan-Execute / Reflection 及其组合，注册式、可替换、可观察
- 📊 **可复现评测**：SWE-bench Lite **40.0%**（同模型 **+6.7pp**），交互与评测共享同一组约束
- 🧠 **运行韧性**：智能检查点 + 语义边界续写、循环检测、空洞回答识别、多模态视觉桥

---

## 快速开始

```bash
pip install -U "git+https://github.com/xianyu-sheng/Xenon.git@v0.9.4"
# 或克隆源码后本地安装
git clone https://github.com/xianyu-sheng/Xenon.git && cd Xenon && pip install -e .
```

```bash
xenon                       # 启动；首次运行用 /setup 配置模型与 API Key
xenon> 帮我重构这个函数，提取公共逻辑
xenon> /help                # 查看全部命令
xenon> /mode plan-execute   # 切换推理范式
```

需要 Python 3.10+。更多安装与配置见 [快速上手指南](docs/GUIDE.md)。

---

## 架构概览：五层职责

Xenon 要回答的不是「模型能不能写代码」，而是「**系统的输出能不能被信任**」。

| 层 | 职责 | 实现 |
|---|---|---|
| **推理** | 如何推进任务 | 7 种范式 + `register_engine()` |
| **工具** | 副作用如何发生 | 7 阶段管线 + 10 个 tool_families |
| **约束** | 什么不允许发生 | 路径围栏 + 命令拦截 + 权限门 |
| **验证** | 凭什么相信结果 | Evidence vs Claim 闭环 |
| **度量** | 改动有没有效 | SWE-bench 官方 harness |

**约束层与验证层是承重墙**：所有文件副作用都经 `ToolExecutor` 这一条通道，一处加固即覆盖全部调用点与 7 种范式。

### 推理引擎

| 引擎 | 策略 | 适用场景 |
|---|---|---|
| `direct` | 单次 LLM 调用 | 无工具需求的简单任务 |
| `react` | Thought→Action→Observation 循环 | 需要工具交互的通用任务 |
| `plan-execute` | 计划→执行→验证闭环 | 多步骤代码修改 |
| `reflection` | 执行→审查→反馈→再执行 | 需质量审查的复杂任务 |
| `plan-react` / `plan-reflection` / `react-reflection` | 规划与审查的组合 | 结构化分解 / 完整开发流程 |

引擎经 `register_engine()` 注册，自动被 `/mode`、setup wizard 与 evals 识别。

---

## 能力一览

- **10 个工具族**：文件读写、代码搜索、shell、git/GitHub、LSP 导航、网络、MCP 等，`register_tool_handler()` 扩展
- **12 家 Provider**：OpenAI / Anthropic / DeepSeek / 火山 Ark / Google / 智谱 / 通义 / Moonshot / 百川 / MiniMax / Ollama / 小米，OpenAI 兼容协议自动适配
- **MCP 客户端**：stdio / HTTP / SSE 三种传输，自动发现外部工具
- **Cache Rails**：追加式提示词轨道，97%+ 缓存命中率（`/cache`、`/cost` 查看）
- **4 作用域记忆**：user / project-local / project-shared / session，加权检索 + token 预算自动压缩
- **韧性与感知**：检查点续写、循环 / 空洞检测、`Ctrl+Alt+V` 视觉桥、Agent Skills

---

## 项目结构

```
xenon/
├── engine/   # 7 种推理范式 + 注册机制 + 检查点/循环/空洞检测
├── nodes/    # 工具层：10 个 tool_families + ToolExecutor 收敛点
├── repl/     # 终端交互层：命令组、模型池、状态栏
├── mcp/      # MCP 客户端（transport / client / registry）
├── memory/   # 4 作用域记忆
├── tools/    # 视觉桥、剪贴板监视
└── utils/    # llm_client、缓存轨道、语义边界、原子写入、LSP
evals/        # SWE-bench 适配器、官方运行时与报告
```

---

## 扩展 Xenon

五条注册式扩展路径，无需改动核心代码：

| 路径 | 入口 |
|---|---|
| MCP 服务器 | `/mcp add`（终端） |
| Agent Skill | `/skill create`、`/skill import`（终端） |
| 工具处理器 | `register_tool_handler()` |
| 推理引擎 | `register_engine()` |
| 终端命令 | `register_command()` |

完整示例与 API 见 [贡献指南](CONTRIBUTING.md) 与 [架构设计](docs/ARCHITECTURE.md)。

---

## 文档

- [架构设计](docs/ARCHITECTURE.md) · [快速上手](docs/GUIDE.md) · [运维指南](docs/OPERATION_GUIDE.md) · [TUI 操作](docs/TUI.md)
- [评测结果](docs/EVAL_RESULTS.md) · [评测协议](docs/XENON_EVAL_PROTOCOL.md) · [横向对比](docs/COMPARISON.md)
- [DeepSeek 缓存](docs/deepseek-guide.md) · [Ark Provider](docs/ARK_PROVIDER.md) · [集成清单](docs/INTEGRATIONS.md)
- [记忆系统](docs/MEMORY_SYSTEM_SPEC.md) · [Agent Skills](docs/AGENT_SKILLS.md)
- [贡献指南](CONTRIBUTING.md) · [安全策略](SECURITY.md) · [更新日志](CHANGELOG.md)

---

## License

[MIT](LICENSE) · [GitHub](https://github.com/xianyu-sheng/Xenon) · [Gitee](https://gitee.com/xianyu-sheng123/Xenon)
