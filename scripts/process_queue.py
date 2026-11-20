#!/usr/bin/env python3
"""Legge i file JSON in queue/, li invia all'API REST di WordPress e scrive l'esito in results/.

Azioni supportate (campo "action"):
  get            -> GET  /wp-json/<path>            (solo percorsi wp/v2/ o zw-live/v1/)
  create_post    -> POST /wp-json/wp/v2/posts       (campo "post": corpo JSON)
  update_post    -> POST /wp-json/wp/v2/posts/<id>  (campi "post_id", "post")
  add_update     -> POST /wp-json/zw-live/v1/updates/<post_id>
  edit_update    -> POST /wp-json/zw-live/v1/updates/<post_id>/<update_id>  (solo i campi inviati)
  delete_update  -> DELETE /wp-json/zw-live/v1/updates/<post_id>/<update_id>
  set_status     -> POST /wp-json/zw-live/v1/status/<post_id>
  check_image    -> scarica un'immagine (solo verifica: tipo e dimensione, nessuna scrittura sul sito)
  create_post_image -> carica l'immagine (campi "image_url", "file_name", "image_title", "alt_text") nella
                    libreria media, poi crea l'articolo ("post") con quell'immagine in evidenza e lo stato
                    "final_status" (publish/draft). Se l'immagine non si carica, l'articolo nasce in bozza.
                    Usato da "Risultati automatici" al posto dello scenario Make.
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue"
RESULTS = ROOT / "results"
ALLOWED_GET_PREFIXES = ("wp/v2/", "zw-live/v1/")
# Domini da cui il ponte può scaricare pagine/feed per conto di Claude (solo lettura)
# Domini da cui si possono scaricare immagini in evidenza
IMAGE_DOMAINS = ("fightful.com", "ytimg.com", "thesmackdownhotel.com", "zonawrestling.net", "wrestleview.com",
                 "prowrestling.net", "411mania.com", "pwinsider.com", "wrestlinginc.com", "f4wonline.com",
                 "pwtorch.com", "cagesideseats.com", "postwrestling.com", "wwe.com", "allelitewrestling.com",
                 "njpw1972.com", "tnawrestling.com", "rohwrestling.com", "cloudfront.net", "wp.com")
FETCH_DOMAINS = ("wrestleview.com", "fightful.com", "prowrestling.net", "411mania.com",
                 "pwinsider.com", "wrestlinginc.com", "f4wonline.com", "pwtorch.com", "cagesideseats.com")

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


def fetch(url):
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if urlparse(url).scheme != "https" or not any(host == d or host.endswith("." + d) for d in FETCH_DOMAINS):
        return 400, {"error": "dominio non consentito"}, None
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/html;q=0.9, */*;q=0.8",
        "Cache-Control": "no-cache", "Pragma": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, {"bytes": len(body), "content_type": r.headers.get("Content-Type")}, body
    except urllib.error.HTTPError as e:
        return e.code, {"error": f"HTTP {e.code}"}, None
    except Exception as e:
        return 0, {"error": str(e)}, None


def download_image(url):
    from urllib.parse import urlparse
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not any(host == d or host.endswith("." + d) for d in IMAGE_DOMAINS):
        return None, None, f"dominio immagine non consentito: {host}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except urllib.error.HTTPError as e:
        return None, None, f"download immagine HTTP {e.code}"
    except Exception as e:
        return None, None, f"download immagine: {e}"
    if not ctype.startswith("image/"):
        return None, None, f"il file non è un'immagine (Content-Type: {ctype or 'assente'})"
    if len(data) < 2000:
        return None, None, f"immagine troppo piccola ({len(data)} byte)"
    return data, ctype, None


def upload_media(data, ctype, file_name):
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(ctype, "")
    name = re.sub(r"[^A-Za-z0-9._-]", "-", file_name or "immagine")
    if ext and not name.lower().endswith((ext, ".jpeg" if ext == ".jpg" else ext)):
        name = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", name) + ext
    req = urllib.request.Request(f"{base}/wp-json/wp/v2/media", data=data, method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "zw-live-bridge/1.0 (GitHub Actions)")
    req.add_header("Content-Type", ctype)
    req.add_header("Content-Disposition", f'attachment; filename="{name}"')
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:2000]}
    except Exception as e:
        return 0, {"error": str(e)}


def create_post_image(job):
    post = dict(job["post"])
    final_status = job.get("final_status", "publish")
    if final_status not in ("publish", "draft"):
        return 400, {"error": "final_status deve essere publish o draft"}
    out = {"image": None}
    media_id = 0
    data, ctype, err = download_image(job.get("image_url", ""))
    if err:
        out["image"] = {"ok": False, "error": err}
    else:
        st, resp = upload_media(data, ctype, job.get("file_name", ""))
        if 200 <= st < 300 and resp.get("id"):
            media_id = int(resp["id"])
            meta = {k: v for k, v in (("title", job.get("image_title")), ("alt_text", job.get("alt_text"))) if v}
            if meta:
                call("POST", f"wp/v2/media/{media_id}", meta)
            out["image"] = {"ok": True, "media_id": media_id, "source_url": resp.get("source_url")}
        else:
            out["image"] = {"ok": False, "error": f"caricamento media HTTP {st}", "response": resp}
    if media_id:
        post["featured_media"] = media_id
        post["status"] = final_status
    else:
        post["status"] = "draft"  # senza immagine non si pubblica: Giuseppe controlla
    st, resp = call("POST", "wp/v2/posts", post)
    if 200 <= st < 300 and isinstance(resp, dict):
        out["post"] = {k: resp.get(k) for k in ("id", "status", "link", "slug", "date", "featured_media", "categories", "tags")}
        out["post"]["title"] = (resp.get("title") or {}).get("rendered")
        if media_id:
            call("POST", f"wp/v2/media/{media_id}", {"post": resp.get("id")})  # collega il media all'articolo
    else:
        out["post"] = {"error": f"creazione articolo HTTP {st}", "response": resp}
    return st, out


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
        fields = {k: job[k] for k in ("title", "type", "label", "winner", "content", "link_url", "link_label", "source", "ref") if k in job}
        return call("POST", f"zw-live/v1/updates/{pid}", fields)
    if action == "edit_update":
        fields = {k: job[k] for k in ("title", "type", "label", "winner", "content", "link_url", "link_label") if k in job}
        return call("POST", f"zw-live/v1/updates/{pid}/{int(job['update_id'])}", fields)
    if action == "delete_update":
        return call("DELETE", f"zw-live/v1/updates/{pid}/{int(job['update_id'])}")
    if action == "check_image":
        data, ctype, err = download_image(job.get("image_url", ""))
        return (400, {"error": err}) if err else (200, {"content_type": ctype, "bytes": len(data)})
    if action == "create_post_image":
        return create_post_image(job)
    if action == "set_status":
        fields = {k: job[k] for k in ("status", "enabled", "end_hours", "source_url") if k in job}
        return call("POST", f"zw-live/v1/status/{pid}", fields)
    return 400, {"error": f"azione sconosciuta: {action}"}


RESULTS.mkdir(exist_ok=True)
files = sorted(QUEUE.glob("*.json"))
if not files:
    print("Coda vuota")
for f in files:
    body = None
    try:
        job = json.loads(f.read_text("utf-8"))
        if job.get("action") == "fetch":
            # Bust delle cache intermedie con un parametro sempre diverso
            url = job["url"]
            if job.get("bust", True):
                url += ("&" if "?" in url else "?") + "zwts=" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            status, resp, body = fetch(url)
        else:
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
    if body is not None:
        # Tiene solo l'ultimo scaricamento per non gonfiare il repository
        for old in RESULTS.glob("*.body"):
            old.unlink()
        (RESULTS / (f.stem + ".body")).write_text(body, "utf-8")
        out["body_file"] = f.stem + ".body"
    (RESULTS / f.name).write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    f.unlink()
    print(f"{f.name}: {job.get('action')} -> HTTP {status}")
