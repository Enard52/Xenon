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

---

# Contributing (English)

Thank you for your interest in Xenon, an open-source AI agent workspace for
terminal and programming tasks. Issues, documentation improvements and code
contributions are all welcome. The section above is the authoritative (Chinese)
version; this is a concise English mirror of the essentials.

## Feedback channels

- **GitHub Issues** — bugs, feature design, cross-platform discussion (Chinese
  or English).
- **GitHub Pull Requests** — the merge path for code.
- Security issues must **not** be filed publicly; follow the private reporting
  process in [SECURITY.md](SECURITY.md).

## Filing issues

Please include: the Xenon version (`xenon --version`), Python version and OS,
the model/provider in use (never paste API keys), minimal reproduction steps,
expected vs. actual results, and sanitized logs or error messages.

## Submitting a pull request

1. Branch from `main` and **check the issue is not already assigned** — do not
   start work on a claimed task.
2. Keep the change focused; add tests or docs for behavior changes.
3. Verify locally (same scope as CI, see `.github/workflows/ci.yml`):

   ```bash
   ruff check xenon tests evals
   pytest -q -m "not live"
   ```

4. **The PR description must include a "CI evidence" section** (required for
   review; template in `.github/PULL_REQUEST_TEMPLATE.md`):
   - The exact commands you ran and their full result lines (targeted tests,
     the offline suite, and ruff).
   - New or modified tests **must fail without your change** — state how you
     verified that.
   - A comparison against `main` with the same commands: **no new failures**.
     Known baseline failures on your platform (e.g. symlink/PTY tests on
     Windows) may be excluded if noted in the PR.
   - A link to the CI run. First-time fork contributors need a maintainer to
     approve the workflow run once — make sure it is green afterwards.
   - PRs that only say "works locally" without commands and output will be
     asked for evidence before review.
5. Never commit credentials, personal configuration, build artifacts, or real
  vendor responses.
