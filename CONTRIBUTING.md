# 贡献指南

感谢你关注 Xenon。Xenon 是一个面向终端和编程任务的开源 AI Agent 工作区，欢迎提交问题、文档改进和代码贡献。

## 反馈渠道

- GitHub Issues：缺陷、功能设计与跨平台讨论（中文 / English 均可）。
- GitHub Pull Requests：正式代码合并入口。
- 安全问题请勿开公开 issue，按 [SECURITY.md](SECURITY.md) 的流程私下报告。

## 提交 Issue

请尽量提供：

- Xenon 版本（例如 `xenon --version` 的输出）。
- Python 版本和操作系统。
- 使用的模型或 Provider（不要粘贴 API Key）。
- 最小复现步骤、实际结果和期望结果。
- 相关命令、错误信息和经过脱敏的日志。

## 提交 Pull Request

1. 从 GitHub 的 `main` 分支创建分支；**先看 issue 是否已被 assign**——已被认领的任务请勿重复开工。
2. 保持改动聚焦，并为行为变化补充测试或文档。
3. 本地验证（与 CI 的 lint / 测试范围一致，见 `.github/workflows/ci.yml`）：

   ```bash
   ruff check xenon tests evals
   pytest -q -m "not live"
   ```

4. **PR 描述必须包含「CI 证据」段落**（评审的必读项，模板见 `.github/PULL_REQUEST_TEMPLATE.md`）：

   - 附上你**实际执行的完整命令**与**完整结果行**，例如：
     - 针对性测试：`python -m pytest tests/test_xxx.py -q` → `N passed`
     - 全量离线测试：`python -m pytest tests -m "not live" -q` → 输出尾行
     - 静态检查：`python -m ruff check xenon tests` → `All checks passed!`
   - **新增/修改的测试必须在没有你的改动时失败**（证明它真的锁住了行为），并在 PR 里说明验证方式；
   - 与 `main` 分支同命令的结果对比：**不得出现新增失败**。Windows 本地的 symlink / PTY 等已知基线失败可以不计，但请在 PR 中注明；
   - 附上 CI 运行链接。fork 首次贡献者的 workflow 需要维护者点一次批准——批准后请确保跑绿；
   - 只写「本地跑过没问题」而不附命令与输出的 PR，评审会要求补齐证据后再审。

5. 不要提交凭证、个人配置、构建产物或供应商真实响应。
