<!-- PR 描述必须包含下方「CI evidence」段落；只写"本地跑过"而没有命令与输出的 PR 会被打回补充。 / PRs without the CI-evidence section below will be sent back. -->

## Summary
<!-- What changed, and why. Link the issue with `Fixes #N`. -->

Fixes #

## CI evidence (required)

<!-- Paste the exact commands you ran and their full result lines. "It should pass" is not evidence. -->

- Targeted tests: `python -m pytest tests/test_xxx.py -q` →
- Full offline suite: `python -m pytest tests -m "not live" -q` →
- Lint: `python -m ruff check xenon tests` →
- Do the new/changed tests fail **without** the change? (yes/no — how you verified)
- New failures vs the `main` baseline? (none / list + why they are platform-specific)
- CI run link:

## Checklist

- [ ] Issue linked above, and not already assigned to someone else
- [ ] Change is focused — no unrelated refactors bundled in
- [ ] Docs updated if user-visible behavior changed
- [ ] No credentials, personal configs, build artifacts, or raw vendor responses included
- [ ] CI green (or a note that the workflow run needs a maintainer approval)
