# Xiaozhi AI API reference (direct integration)

The CLI covers common cases. This file documents the raw endpoints for agents
that call the API directly (SDKs, MCP servers, workflow tools).

Base URL: `https://xzai.me`. All request and response bodies are JSON
(`Content-Type: application/json`).

## Auth (two schemes — never mix)

| Endpoint family | Header |
|---|---|
| `https://xzai.me/api.php/*` | `x-token: <XIAOZHI_API_KEY>` |
| `https://xzai.me/v1/*` (OpenAI-compatible) | `Authorization: Bearer <XIAOZHI_API_KEY>` |

Sending the wrong header returns `401`. Get the key at https://xzai.me →
个人中心 → API 接口.

## Endpoints

| Capability | Endpoint |
|---|---|
| Model list | `GET /v1/models` (Bearer) |
| Chat, OpenAI-compatible (tools, streaming, multimodal) | `POST /v1/chat/completions` (Bearer) |
| Chat, native | `POST /api.php/chat/sendText` (x-token) |
| Image gen (Seedream 5.0) | `POST /api.php/draw_seedream/seedreamSubmit` → `POST /api.php/draw_seedream/getResult` |
| Video gen (Seedance) | `POST /api.php/video/submit` → `POST /api.php/video/getResult` |
| TTS | `POST /api.php/tts/text2audio` |
| Image upload (returns a reference URL) | `POST /api.php/upload/image` (multipart, field `image`) |

## Image submit

```json
{
  "message": "prompt text (max 2000 chars)",
  "aspect_ratio": "1:1",
  "style_key": "web_image_style_2D",
  "images": ["https://example.com/ref.jpg"],
  "cate_id": 0,
  "is_share": 0
}
```

`aspect_ratio` ∈ `1:1 | 16:9 | 9:16 | 3:4 | 4:3 | 2:3 | 3:2`.

Response: `{"errno":0,"message":"","data":{"draw_id":3305}}`.
Poll `POST /api.php/draw_seedream/getResult` with `{"draw_id": 3305}`.

Output size approximates the requested ratio (16:9 → 2848×1600, 1:1 → 2048×2048
in testing). Generation takes roughly 30–90 s; the upstream provider sometimes
stalls, in which case the task ends as `state: 2` and credits are refunded.

## Video submit

```json
{
  "prompt": "a corgi running in snow, cinematic",
  "platform": "seedance",
  "model": "seedance-2.0-mini",
  "aspect_ratio": "16:9",
  "duration": 15,
  "images": ["https://example.com/first_frame.jpg"]
}
```

| `model` | Duration | Notes |
|---|---|---|
| omitted | 10s | Seedance 2.0 Fast, cheapest |
| `seedance-2.0-fast-15` | 15s | exact name required |
| `seedance-2.0-mini` | 15s | `duration: 15` is required |
| `seedance-2.5` | 30s | 30s only; supports 21:9 |

- Wrong or missing params **silently fall back** to fast-10s (you are still billed).
- `images`: omitted = text-to-video; 1 image = first-frame drive; up to 10 = multi-reference.
- Typical render time: 2.5 → 4–7 min, fast-15 / mini → 10–20 min, 10s → 4–10 min.
- Response: `{"errno":0,"data":{"video_id":12345}}`; poll `POST /api.php/video/getResult`
  with `{"video_id": 12345}`.

## Task states (video and image)

| `data.state` | Meaning |
|---|---|
| `0` | generating — poll again in 8–20 s |
| `1` | done — artifact in `data.video_url` (video) or `data.images[]` (image) |
| `2` | failed — credits auto-refunded, `data.message` holds the upstream reason |
| `-1` | not found / wrong id |

## TTS

```json
{"text": "1-500 characters", "voice": "Cherry"}
```

Voices: `Cherry | Ethan | Chelsie | Nofish | Jennifer | Ryan | Katerina`.

Response `data.audio_url` (WAV, expires ~24 h), `data.price`,
`data.characters`. Pricing is 10 credits per 10k characters, minimum 1 credit
per call, no charge on failure. There is no SSML and no speed parameter — for
different pacing, post-process with ffmpeg (`atempo`).

## Billing

- Failed generation tasks auto-refund (`state: 2`); duplicate submits do not.
- Chat is charged only on success.
- Errors follow the OpenAI shape: `400` invalid params, `401` bad key,
  `402` insufficient balance, `403` channel closed, `404` model not found,
  `429` rate limit, `502`/`504` upstream failure.

## Chat

Current model: `glm-5.3-flash`. Context window 1,048,576 tokens (1024k-token
inputs succeed, ~1.15M is rejected with 400). Supports function calling, SSE
streaming and multimodal `content` arrays.

Use it with the OpenAI SDK:

```python
from openai import OpenAI
client = OpenAI(base_url="https://xzai.me/v1", api_key="<XIAOZHI_API_KEY>")
r = client.chat.completions.create(
    model="glm-5.3-flash",
    messages=[{"role": "user", "content": "hello"}],
)
print(r.choices[0].message.content)
```
