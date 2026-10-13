# Xenon 外部集成 CLI

Xenon 为 Ark CLI、安装脚本和其他 Agent 管理器提供独立于交互式 REPL 的稳定命令。
这些命令不启动模型，默认不探测网络（`verify --connect-mcp` 除外）；
传入 `--json` 后，stdout 只输出一个 JSON 对象，
错误说明和普通日志不会混入结构化结果。

## 能力发现

```bash
xenon integrations describe --json
```

输出包含契约版本、Xenon 运行版本、用户/项目 Skill 目录、MCP transport 能力和
建议命令模板。外部工具应先读取 `schema_version`，再决定如何安装；不要直接修改
Xenon 的私有 YAML。

退出码约定：

| 退出码 | 含义 |
|---|---|
| `0` | 成功，结构化结果可用 |
| `1` | 请求合法，但安装、校验或持久化失败 |
| `2` | 命令或参数用法错误 |

## 端到端验证

安装器完成 Skill 或 MCP 配置后，可以运行只读的集成验证：

```bash
xenon integrations verify --json
```

默认验证四层 Skill 根目录、所有 `SKILL.md` frontmatter、MCP 配置格式、stdio
命令可用性和凭证文件权限，不启动任何 MCP 子进程，也不访问网络。若需要验证真实
MCP 协议链路，必须显式开启连接：

```bash
xenon integrations verify --connect-mcp --timeout 5 --json
xenon integrations verify --connect-mcp --server dataPro-search --json
```

连接验证会对选中的服务器执行 `initialize → notifications/initialized →
tools/list`，但不会调用工具。`--timeout` 是单次 MCP 请求的墙钟上限，允许范围为
0.1–30 秒；一次最多验证 32 个服务器。JSON 结果包含标准 Skill 数、加载错误数、
MCP 可达数、工具数、协商后的协议版本和每个服务器的握手耗时。env/header 值、URL
query 和服务器返回中的控制字符不会进入报告。

这一命令适合外部安装器的安装后健康检查：退出码 `0` 表示 Skill、静态 MCP 配置和
所有已请求连接均通过，`1` 表示至少一项失败。

## 安装 Agent Skill

```bash
xenon skill install ./my-skill --json
xenon skill install ./my-skill --scope project --json
xenon skill install ./my-skill --scope shared-user --force --json
xenon skill list --json
xenon skill doctor --json
```

作用域为 `user`、`shared-user`、`project`、`shared-project`。默认写入
`~/.xenon/skills`；共享用户层写入 `~/.agents/skills`。项目作用域要求 Xenon 能
确定当前项目边界。

安装源可以是技能目录或其中的 `SKILL.md`。Xenon 会先验证 frontmatter、文件数、
总大小和符号链接边界，再复制到目标旁的临时目录并原子改名。已有同名技能不会被
静默覆盖；只有显式 `--force` 才会替换，并在 JSON 回执中返回 `replaced: true`。

## 配置 MCP

不含密钥的简单本地 MCP 可以直接添加：

```bash
xenon mcp add filesystem npx --json -- -y @modelcontextprotocol/server-filesystem .
```

包含 token、环境变量或认证头时，应通过 stdin 传 JSON/YAML，避免密钥进入 shell
history 和进程参数列表：

```bash
printf '%s' "$MCP_CONFIG_JSON" | xenon mcp add dataPro-search --config - --json
```

stdio 配置形态：

```json
{
  "transport": "stdio",
  "command": "uvx",
  "args": ["some-mcp-server"],
  "env": {"SERVICE_API_KEY": "<secret>"}
}
```

HTTP 配置形态（仅适用于下述 POST JSON-RPC 原型）：

```json
{
  "transport": "http",
  "url": "https://example.com/mcp",
  "headers": {"Authorization": "Bearer <secret>"}
}
```

也可以用 `--config /protected/path/config.json`。配置写入
`~/.xenon/credentials.yaml`，使用 `0600` 权限和跨进程锁；服务器在 Xenon 下次
启动或首次调用时惰性连接。

```bash
xenon mcp list --json
xenon mcp doctor --json
xenon mcp remove dataPro-search --json
```

`list` 和写入回执只显示 env/header 的键名、参数数量与脱敏 URL；不会回显值或 URL
query。`doctor` 只做本地格式、命令可用性与文件权限检查，不会连接远端服务器。

### MCP 传输边界

`integrations describe` 中的 `stdio`、`http`、`sse` 是可接受的配置名称，
不代表三种完整实现的传输协议。`sse` 配置会归一化为 `http`，两者均使用
当前的 `SSETransport` 原型：

- `request()` 向配置的 URL 直接 POST JSON-RPC，并读取该 HTTP 响应的 JSON。
- `send()` 向同一 URL POST 通知，检查 HTTP 状态，但丢弃响应正文。
- `receive()` 单独打开 GET 流，只读取首个非空 `data:` 行；它不会发现
  `endpoint` 事件中的 POST 地址，也不会按请求 ID 关联流上的响应。

因此，要求先建立 SSE 连接、从 `endpoint` 事件发现消息地址、再从流上接收
响应的服务器目前不受支持；这也不是完整的 Streamable HTTP 实现。示例中的
`/mcp` 只是占位路径，不会自动把普通 SSE 服务器转换为可用的 POST 端点。

配置保存成功或 `xenon mcp doctor --json` 通过，都不证明握手成功。对已配置的
服务器，使用 `xenon integrations verify --connect-mcp --server <name> --json`
实际执行初始化和工具发现；通过表示当前客户端完成了上述请求流程，不等于
严格的协议符合性验证，也不证明所有 MCP HTTP/SSE 服务器兼容或验证工具调用。
完整传输实现、失败提示及回归测试
仍由 [#103](https://github.com/xianyu-sheng/Xenon/issues/103) 跟踪。

## ArkCLI 与 VeADK 边界

- ArkCLI 的 `+connect --path ~/.agents/skills` 产物是标准 Agent Skills，Xenon 会从
  共享用户层直接发现；ArkCLI 是否自动识别 Xenon，仍取决于 ArkCLI 上游的 agent
  注册表。
- VeADK 使用的本地 `SKILL.md` 与 MCP stdio 配置可以复用 Xenon 加载链路；
  HTTP 服务器须满足上述 POST JSON-RPC 原型的限制。
  `integrations verify --connect-mcp` 可记录当前客户端对所选服务器执行初始化和
  工具发现的结果，不代表严格的协议符合性验证。
- “协议兼容”不等于 VeADK 已支持 `runtime="xenon"`。后者需要 VeADK 上游新增运行时
  适配和事件翻译；在其正式合并前，Xenon 不会把自己标记为官方 VeADK runtime。
