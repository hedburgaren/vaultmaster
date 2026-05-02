# Versioned git hooks

This directory holds **shared git hooks** that travel with the repo, instead of
the per-clone `.git/hooks/` (which is not tracked).

## Setup (run once per clone)

```bash
git config core.hooksPath .githooks
```

That's it. Every commit then runs the hooks here.

## What's installed

### `pre-commit`

Blocks commits that contain known-secret patterns:

- **Filename blocklist:** `.env`, `.env.bak*`, `*.bak`, `*.pem`, `*.key`,
  `id_rsa`, `id_ed25519`, `*credentials*.json`
- **Content scan** of the staged diff for:
  - Anthropic/OpenAI/GitHub/Slack/Discord/AWS API keys
  - `password=`, `secret_key=`, `passwd=` followed by 16+ chars
  - Postgres URLs with embedded passwords
  - Fernet/master-key format (`v1:...`)

Allowlisted (won't trigger): `.env.example`, `*.example`, `*.sample`.

### Bypass

```bash
git commit --no-verify
```

Use only when you genuinely mean to commit a value the scanner caught
(e.g. moving a documented example into place). The whole point of the hook
is to make the bypass *visible* — every `--no-verify` should be a conscious
decision, not a habit.

## History

Installed 2026-05-02 after `.env.bak-20260502_132815` slipped into
`81fe2bc` via `git add -A` and triggered the first GitGuardian alert
on this repo. The leaked values were already rotated mid-session, but the
incident was a process failure that this hook prevents going forward.
