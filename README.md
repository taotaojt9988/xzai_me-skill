# xzai_me-skill

Agent skill for [Xiaozhi AI (xzai.me)](https://xzai.me): give your AI agent
video generation (Seedance), image generation (Seedream), text-to-speech,
and an OpenAI-compatible chat endpoint.

Works with Claude Code, Codex, Cursor, OpenCode, and any agent that loads
`SKILL.md` files.

## Install

```
npx skills add taotaojt9988/xzai_me-skill
```

or manually copy `scripts/` and `SKILL.md` into your agent's skills
directory (e.g. `~/.claude/skills/xzai_me/`).

## Setup

1. Register at https://xzai.me
2. 个人中心 (avatar) → API 接口 → copy your key
3. Save it:

```bash
export XIAOZHI_API_KEY="your-key"     # Linux / macOS
setx XIAOZHI_API_KEY "your-key"       # Windows
```

## What your agent can do

| Command | Ability | Typical wait |
|---|---|---|
| `python scripts/xiaozhi.py video "..."` | Seedance text/image-to-video (10s/15s/30s) | 4-20 min |
| `python scripts/xiaozhi.py image "..."` | Seedream 5.0 text-to-image, up to 10 reference images | ~1 min |
| `python scripts/xiaozhi.py tts "..."` | Text-to-speech, 7 voices | seconds |
| `python scripts/xiaozhi.py chat "..."` | OpenAI-compatible chat, 1M context, function calling | seconds |

The CLI validates model/duration combos (the API silently falls back to the
10s model on bad input), polls async tasks, and downloads results locally
(CDN links expire).

Pricing: pay-per-use credits, failed generations auto-refund. No subscription.
