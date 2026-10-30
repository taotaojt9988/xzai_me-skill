#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Xiaozhi AI (xzai.me) media CLI: video / image / tts / chat / models / status / doctor.

Dependency-free (Python 3.8+ stdlib only). Auth: XIAOZHI_API_KEY env var.
api.php endpoints use the `x-token` header; /v1/* endpoints use `Authorization: Bearer`.

Exit codes: 0 ok | 2 usage/config error | 3 still pending | 4 task failed
"""
import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

VERSION = "1.1.1"
UA = "Mozilla/5.0 (compatible; xiaozhi-skill/%s)" % VERSION
BASE = os.environ.get("XIAOZHI_BASE_URL", "https://xzai.me").rstrip("/")
KEY = os.environ.get("XIAOZHI_API_KEY", "").strip()

VIDEO_MODELS = {
    None: 10,                        # default = Seedance 2.0 Fast 10s
    "seedance-2.0-fast-15": 15,
    "seedance-2.0-mini": 15,
    "seedance-2.5": 30,
}
VIDEO_RATIOS = {"16:9", "9:16", "1:1", "3:4", "4:3"}
WIDE_RATIOS = VIDEO_RATIOS | {"21:9"}
IMAGE_RATIOS = {"1:1", "16:9", "9:16", "3:4", "4:3", "2:3", "3:2"}
TTS_VOICES = {"Cherry", "Ethan", "Chelsie", "Nofish", "Jennifer", "Ryan", "Katerina"}

RETRY_ERRORS = (urllib.error.URLError, ssl.SSLError, socket.timeout,
                ConnectionError, TimeoutError)


def die(msg, code=2):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(code)


def note(msg):
    print(msg, file=sys.stderr)


def need_key():
    if not KEY:
        die(
            "XIAOZHI_API_KEY is not set. Setup (about 2 minutes):\n"
            "  1. Open https://xzai.me and register / log in\n"
            "  2. 个人中心 (avatar) -> API 接口\n"
            "  3. Copy your API key\n"
            "  4. Save it, e.g.:\n"
            "       export XIAOZHI_API_KEY=\"your-key\"      # Linux / macOS\n"
            "       setx XIAOZHI_API_KEY \"your-key\"        # Windows (new terminals)\n"
            "Then re-run this command. Tip: `doctor` verifies the key for free."
        )
    return KEY


def _open(req, timeout, attempts=5):
    """urlopen with retries on transient network/TLS failures."""
    last = None
    for i in range(attempts):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise                      # real HTTP status: caller decides
        except RETRY_ERRORS as e:
            last = e
            if i < attempts - 1:
                wait = 2 * (i + 1)
                note("network hiccup (%s), retrying in %ss..." % (type(e).__name__, wait))
                time.sleep(wait)
    die("network error talking to %s after %d attempts: %s\n"
        "Check connectivity / proxy and retry." % (BASE, attempts, last), 1)


def http_json(path, payload=None, bearer=False, timeout=60):
    url = path if path.startswith("http") else BASE + path
    if bearer:
        headers = {"Content-Type": "application/json",
                   "Authorization": "Bearer " + need_key()}
    else:
        headers = {"Content-Type": "application/json", "x-token": need_key()}
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with _open(req, timeout) as r:
            body = r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        hint = {401: "bad or missing API key", 402: "insufficient credits",
                429: "rate limited, slow down"}.get(e.code)
        die("HTTP %s from %s%s\n%s" % (e.code, url,
                                       " (%s)" % hint if hint else "", body[:500]), 2)
    try:
        return json.loads(body)
    except ValueError:
        die("non-JSON response from %s:\n%s" % (url, body[:500]), 1)


def _curl_fetch(url, out, timeout=300):
    """Download with curl when available — more tolerant of flaky TLS than urllib."""
    exe = shutil.which("curl")
    if not exe:
        return False
    cmd = [exe, "-sS", "-L", "--retry", "3", "--retry-delay", "2",
           "--max-time", str(timeout), "-A", UA, "-o", out, url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    except Exception:
        return False
    if r.returncode != 0:
        note("curl failed (%s): %s" % (r.returncode, (r.stderr or "").strip()[:200]))
        return False
    return os.path.exists(out) and os.path.getsize(out) > 0


def download(url, out):
    if _curl_fetch(url, out):
        size = os.path.getsize(out)
        return size
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with _open(req, 300, attempts=5) as r, open(out, "wb") as f:
        f.write(r.read())
    size = os.path.getsize(out)
    if size == 0:
        die("downloaded file is empty: %s (remote url may have expired)" % out, 1)
    return size


def safe_download(url, out, kind):
    """Download but never lose the artifact url on failure."""
    try:
        n = download(url, out)
        print("saved %s (%d bytes) -> %s" % (kind, n, out))
        return n
    except SystemExit:
        note("download failed — the task itself SUCCEEDED.")
        note("Open this url in a browser or fetch it manually: %s" % url)
        note("Then save it as: %s" % out)
        return 0


def poll(path, field, task_id, out, interval=20, max_wait=1800, kind="task"):
    """Poll a getResult endpoint until done, then download the artifact."""
    deadline = time.time() + max_wait
    elapsed = 0
    while True:
        r = http_json(path, {field: task_id})
        d = r.get("data") or {}
        state = d.get("state")
        if state == 1:
            url = d.get("video_url") or (d.get("images") or [None])[0]
            if not url:
                die("task %s finished but returned no artifact URL:\n%s"
                    % (task_id, json.dumps(r, ensure_ascii=False)[:500]), 4)
            safe_download(url, out, kind)
            print("url:", url)
            if kind != "image":
                print("NOTE: remote url expires; the local file is the durable copy.")
            return 0
        if state == 2:
            msg = d.get("message") or ""
            die("task %s FAILED (credits auto-refunded). %s" % (task_id, msg), 4)
        if state == -1:
            die("task %s not found: %s" % (task_id, d.get("message") or ""), 4)
        if time.time() > deadline:
            print("PENDING: task %s still running after %ss." % (task_id, max_wait))
            print("Resume polling (free, does not re-submit):")
            print("  python %s status %s --kind %s" % (sys.argv[0], task_id,
                                                       "image" if kind == "image" else "video"))
            print("When it finishes, download the printed url manually.")
            sys.exit(3)
        print("state=0 generating... (%ds elapsed)" % elapsed)
        time.sleep(interval)
        elapsed += interval


def cmd_video(args):
    model = args.model
    if model not in VIDEO_MODELS:
        die("model must be one of: %s (got %r).\n"
            "Wrong names silently fall back to the 10s model upstream."
            % (", ".join(filter(None, VIDEO_MODELS)), model))
    need_dur = VIDEO_MODELS[model]
    if args.duration and args.duration != need_dur:
        die("model %s only supports --duration %d (got %d)"
            % (model or "default", need_dur, args.duration))
    ratio = args.ratio
    allowed = WIDE_RATIOS if model in ("seedance-2.5", "seedance-2.0-fast-15") else VIDEO_RATIOS
    if ratio not in allowed:
        die("ratio %s not supported for model %s; use one of %s"
            % (ratio, model or "default", sorted(allowed)))
    payload = {"prompt": args.prompt, "platform": "seedance", "aspect_ratio": ratio}
    if model:
        payload["model"] = model
    if model == "seedance-2.0-mini":
        payload["duration"] = 15      # REQUIRED for mini, ignored by other models
    if args.images:
        payload["images"] = args.images[:10]
    if args.dry_run:
        _dry(payload, "/api.php/video/submit", need_dur, ratio)
        return 0
    r = http_json("/api.php/video/submit", payload)
    vid = (r.get("data") or {}).get("video_id")
    if not vid:
        die("submit failed:\n%s" % json.dumps(r, ensure_ascii=False)[:500], 4)
    print("submitted video_id=%s model=%s duration=%ds ratio=%s"
          % (vid, model or "fast(10s)", need_dur, ratio))
    if args.no_wait:
        print("not waiting (--no-wait). Check later: python %s status %s" % (sys.argv[0], vid))
        return 0
    return poll("/api.php/video/getResult", "video_id", vid, args.out, kind="video",
                max_wait=40 * 60 if model in ("seedance-2.0-fast-15", "seedance-2.0-mini")
                else 15 * 60)


def cmd_image(args):
    if args.ratio not in IMAGE_RATIOS:
        die("ratio must be one of %s" % sorted(IMAGE_RATIOS))
    payload = {"message": args.prompt, "aspect_ratio": args.ratio, "is_share": 0}
    if args.style:
        payload["style_key"] = args.style
    if args.images:
        payload["images"] = args.images[:10]
    if args.dry_run:
        _dry(payload, "/api.php/draw_seedream/seedreamSubmit", None, args.ratio)
        return 0
    r = http_json("/api.php/draw_seedream/seedreamSubmit", payload)
    did = (r.get("data") or {}).get("draw_id")
    if not did:
        die("submit failed:\n%s" % json.dumps(r, ensure_ascii=False)[:500], 4)
    print("submitted draw_id=%s ratio=%s" % (did, args.ratio))
    if args.no_wait:
        print("not waiting (--no-wait). Check later: "
              "python %s status %s --kind image" % (sys.argv[0], did))
        return 0
    return poll("/api.php/draw_seedream/getResult", "draw_id", did, args.out,
                kind="image", interval=8, max_wait=10 * 60)


def _dry(payload, path, duration, ratio):
    print("DRY RUN (nothing submitted, no credits used)")
    print("endpoint:", BASE + path)
    print("payload :", json.dumps(payload, ensure_ascii=False))
    if duration:
        print("duration:", duration, "s")
    print("ratio   :", ratio)


def cmd_tts(args):
    text = args.text
    if not (1 <= len(text) <= 500):
        die("TTS accepts 1-500 characters per call (got %d). Split longer text into chunks."
            % len(text))
    voice = args.voice
    if voice not in TTS_VOICES:
        die("voice must be one of %s (got %r)" % (sorted(TTS_VOICES), voice))
    r = http_json("/api.php/tts/text2audio", {"text": text, "voice": voice})
    d = r.get("data") or {}
    url = d.get("audio_url")
    if not url:
        die("tts failed:\n%s" % json.dumps(r, ensure_ascii=False)[:500], 4)
    n = download(url, args.out)
    print("saved audio (%d bytes) -> %s (price=%s credits, chars=%s)"
          % (n, args.out, d.get("price"), d.get("characters")))
    print("NOTE: remote url expires in ~24h; local copy saved.")
    return 0


def cmd_chat(args):
    messages = [{"role": "user", "content": args.prompt}]
    r = http_json("/v1/chat/completions",
                  {"model": args.model, "messages": messages,
                   "max_tokens": args.max_tokens},
                  bearer=True, timeout=300)
    try:
        content = r["choices"][0]["message"].get("content")
    except (KeyError, IndexError):
        die("unexpected response:\n%s" % json.dumps(r, ensure_ascii=False)[:500], 1)
    print(content or "(empty content; model returned reasoning only: %s)"
          % json.dumps(r.get("usage"), ensure_ascii=False))
    return 0


def cmd_models(_):
    r = http_json("/v1/models", bearer=True, timeout=30)
    ids = [m.get("id") for m in r.get("data", [])]
    for i in ids:
        print(i)
    if not ids:
        note("no models returned: %s" % json.dumps(r, ensure_ascii=False)[:300])
    return 0


def cmd_status(args):
    path = "/api.php/draw_seedream/getResult" if args.kind == "image" \
        else "/api.php/video/getResult"
    field = "draw_id" if args.kind == "image" else "video_id"
    r = http_json(path, {field: int(args.task_id)})
    print(json.dumps(r, ensure_ascii=False, indent=2))
    d = r.get("data") or {}
    state = d.get("state")
    url = d.get("video_url") or (d.get("images") or [None])[0]
    if url:
        print("\nartifact url:", url)
        if args.out:
            safe_download(url, args.out, args.kind)
    elif state == 0:
        print("\nstill generating")
    return 0


def cmd_doctor(_):
    """Free connectivity + auth check. Uses no credits."""
    ok = True
    print("xiaozhi-skill", VERSION)
    print("base url   :", BASE)
    print("api key    :", "set (%s...%s)" % (KEY[:4], KEY[-4:]) if len(KEY) > 8 else "NOT SET")
    print("python     :", sys.version.split()[0])
    if not KEY:
        print("\nresult: key missing -> run: export XIAOZHI_API_KEY=\"...\"")
        return 2
    try:
        with _open(urllib.request.Request(BASE + "/v1/models",
                  headers={"Authorization": "Bearer " + KEY}), 20) as r:
            d = json.loads(r.read().decode(errors="replace"))
        ids = [m.get("id") for m in d.get("data", [])]
        print("models     : %d available%s" % (len(ids), (" (" + ", ".join(ids[:5]) + ")") if ids else ""))
    except Exception as e:
        ok = False
        print("models     : FAILED ->", e)
    try:                                           # optional: balance endpoint may not exist
        req = urllib.request.Request(BASE + "/api.php/user/info", data=b"{}",
                                     headers={"Content-Type": "application/json",
                                              "x-token": KEY})
        with _open(req, 20) as r:
            d = (json.loads(r.read().decode(errors="replace")) or {}).get("data") or {}
        shown = [(k, d[k]) for k in ("credits", "balance", "score", "points") if k in d]
        print("account    : ok" + ("" if not shown else
                                   " (" + ", ".join("%s=%s" % kv for kv in shown) + ")"))
    except Exception:
        pass                                       # endpoint is optional; stay quiet
    print("\nresult:", "READY" if ok else "PROBLEMS FOUND")
    return 0 if ok else 1


def _add_common(p):
    p.add_argument("--out", default=None, help="local output path")
    p.add_argument("--dry-run", action="store_true",
                   help="print the request without submitting (no credits)")
    p.add_argument("--no-wait", action="store_true",
                   help="submit and exit immediately instead of polling")


def main():
    p = argparse.ArgumentParser(
        prog="xiaozhi.py",
        description="Xiaozhi AI (xzai.me) media CLI: Seedance video, Seedream image, TTS, chat.",
        epilog="Get a free key at https://xzai.me (个人中心 -> API 接口). "
               "Run `doctor` first to verify setup.")
    p.add_argument("--version", action="version", version="xiaozhi-skill " + VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("video", help="generate a video (Seedance)")
    v.add_argument("prompt", help="text prompt describing the video")
    v.add_argument("--model", default=None,
                   help="omit=fast10s | seedance-2.0-fast-15 | seedance-2.0-mini | seedance-2.5")
    v.add_argument("--ratio", default="16:9", help="16:9 (default) | 9:16 | 1:1 | 3:4 | 4:3 | 21:9")
    v.add_argument("--duration", type=int, default=None, help="must match the model")
    v.add_argument("--images", nargs="*", help="reference image URLs (max 10)")
    v.add_argument("--out", default="output.mp4")
    v.add_argument("--dry-run", action="store_true", help="print request, do not submit")
    v.add_argument("--no-wait", action="store_true", help="submit then exit")
    v.set_defaults(fn=cmd_video)

    i = sub.add_parser("image", help="generate an image (Seedream 5.0)")
    i.add_argument("prompt", help="text prompt describing the image")
    i.add_argument("--ratio", default="1:1")
    i.add_argument("--style", default=None, help="optional style key")
    i.add_argument("--images", nargs="*", help="reference image URLs (max 10)")
    i.add_argument("--out", default="output.jpg")
    i.add_argument("--dry-run", action="store_true", help="print request, do not submit")
    i.add_argument("--no-wait", action="store_true", help="submit then exit")
    i.set_defaults(fn=cmd_image)

    t = sub.add_parser("tts", help="text to speech (wav)")
    t.add_argument("text", help="1-500 characters")
    t.add_argument("--voice", default="Cherry", help=" | ".join(sorted(TTS_VOICES)))
    t.add_argument("--out", default="output.wav")
    t.set_defaults(fn=cmd_tts)

    c = sub.add_parser("chat", help="OpenAI-compatible chat completion")
    c.add_argument("prompt")
    c.add_argument("--model", default="glm-5.3-flash")
    c.add_argument("--max-tokens", type=int, default=1024, dest="max_tokens")
    c.set_defaults(fn=cmd_chat)

    sub.add_parser("models", help="list available chat models").set_defaults(fn=cmd_models)

    s = sub.add_parser("status", help="check a task and optionally download the result")
    s.add_argument("task_id", help="video_id or draw_id")
    s.add_argument("--kind", choices=["video", "image"], default="video")
    s.add_argument("--out", default=None, help="download the artifact to this path")
    s.set_defaults(fn=cmd_status)

    sub.add_parser("doctor", help="verify key and connectivity (free)").set_defaults(fn=cmd_doctor)

    args = p.parse_args()
    return args.fn(args) or 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as exc:                       # never dump a raw traceback at users
        print("ERROR: unexpected failure: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        print("Re-run with `doctor` to check setup.", file=sys.stderr)
        sys.exit(1)
