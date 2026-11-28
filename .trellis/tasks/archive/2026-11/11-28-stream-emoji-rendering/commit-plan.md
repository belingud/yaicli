# 提交计划

沿用用户此前对当前重构及后续修复的自主实施、测试和提交授权，分两次提交；不修改master，不合并PR，不发布。

1. `fix(render): require emoji-aware Rich for live streaming`
   - pyproject.toml、uv.lock、tests/test_stream_unicode_width.py
   - .trellis/spec/py/cli-and-rendering.md
   - .trellis/spec/repo/build-and-release.md
   - .trellis/spec/guides/cross-layer-thinking-guide.md
   - docs/dev/debug-cli.md
   - .trellis/tasks/11-28-stream-emoji-rendering/全部本任务记录
   - .trellis/tasks/11-27-session-state-boundaries/research/debug-stream-display.md
   - .trellis/tasks/11-27-session-state-boundaries/research/debug-stream-protocol.md
   - 既有父任务和S3任务verification.md中的本缺陷跟进记录
2. `chore(task): record stream rendering acceptance`
   - fix提交hash与交付状态
   - .trellis/workspace/belingud/index.md、journal-1.md中的本轮会话

保留既有无关改动：.trellis/.template-hashes.json、.agents/skills/trellis-start/、trellis-continue/、trellis-finish-work/及.codex/。使用显式文件清单，不使用git add .。第二次提交后合并推送当前分支一次，等待最新head CI，合并仍须用户明确批准。
