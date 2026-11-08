#!/usr/bin/env python3
"""Legge i file JSON in queue/, li invia all'API REST di WordPress e scrive l'esito in results/.

Azioni supportate (campo "action"):
  get            -> GET  /wp-json/<path>            (solo percorsi wp/v2/ o zw-live/v1/)
  create_post    -> POST /wp-json/wp/v2/posts       (campo "post": corpo JSON)
  update_post    -> POST /wp-json/wp/v2/posts/<id>  (campi "post_id", "post")
  add_update     -> POST /wp-json/zw-live/v1/updates/<post_id>
  delete_update  -> DELETE /wp-json/zw-live/v1/updates/<post_id>/<update_id>
  set_status     -> POST /wp-json/zw-live/v1/status/<post_id>
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue"
RESULTS = ROOT / "results"
ALLOWED_GET_PREFIXES = ("wp/v2/", "zw-live/v1/")

base = os.environ.get("WP_BASE_URL", "").rstrip("/")
user = os.environ.get("WP_USER", "")
pwd = os.environ.get("WP_APP_PASSWORD", "")
if not (base and user and pwd):
    sys.exit("Segreti WP_BASE_URL / WP_USER / WP_APP_PASSWORD mancanti")

auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()


def call(method, path, body=None):
    url = f"{base}/wp-json/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "zw-live-bridge/1.0 (GitHub Actions)")
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except Exception as e:  # rete, DNS, timeout
        return 0, {"error": str(e)}
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, {"raw": raw[:2000]}


def handle(job):
    action = job.get("action")
    pid = int(job.get("post_id", 0) or 0)
    if action == "get":
        path = str(job.get("path", "")).lstrip("/")
        if ".." in path or not path.startswith(ALLOWED_GET_PREFIXES):
            return 400, {"error": "percorso non consentito"}
        return call("GET", path)
    if action == "create_post":
        return call("POST", "wp/v2/posts", job["post"])
    if action == "update_post":
        return call("POST", f"wp/v2/posts/{pid}", job["post"])
    if action == "add_update":
        fields = {k: job[k] for k in ("title", "type", "label", "winner", "content", "source", "ref") if k in job}
        return call("POST", f"zw-live/v1/updates/{pid}", fields)
    if action == "delete_update":
        return call("DELETE", f"zw-live/v1/updates/{pid}/{int(job['update_id'])}")
    if action == "set_status":
        fields = {k: job[k] for k in ("status", "enabled", "end_hours", "source_url") if k in job}
        return call("POST", f"zw-live/v1/status/{pid}", fields)
    return 400, {"error": f"azione sconosciuta: {action}"}


RESULTS.mkdir(exist_ok=True)
files = sorted(QUEUE.glob("*.json"))
if not files:
    print("Coda vuota")
for f in files:
    try:
        job = json.loads(f.read_text("utf-8"))
        status, resp = handle(job)
    except Exception as e:
        status, resp = 0, {"error": f"file non valido: {e}"}
        job = {}
    out = {
        "file": f.name,
        "action": job.get("action"),
        "http_status": status,
        "ok": 200 <= status < 300,
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "response": resp,
    }
    (RESULTS / f.name).write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    f.unlink()
    print(f"{f.name}: {job.get('action')} -> HTTP {status}")
