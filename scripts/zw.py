#!/usr/bin/env python3
"""Strumenti a riga di comando per le dirette di Zona Wrestling (uso di Claude).

  python3 scripts/zw.py send FILE.json [FILE.json ...]   invia job alla coda e attende gli esiti
  python3 scripts/zw.py job '{"action": "get", ...}'      come send, ma con il JSON in linea
  python3 scripts/zw.py feed SHOW DATA [--key CHIAVE]      scarica il feed Wrestleview tramite GitHub,
                                                           trova il report dello show e stampa SOLO
                                                           i paragrafi nuovi rispetto al giro precedente
        SHOW = raw | nxt | smackdown | dynamite | collision   DATA = AAAA-MM-GG (data USA dello show)
  python3 scripts/zw.py page URL --key CHIAVE              come feed ma su una pagina (fonte di riserva)
  python3 scripts/zw.py state CHIAVE [--set k=v ...]       legge/aggiorna lo stato della diretta (state/CHIAVE.json)
"""
import html
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE, RESULTS, STATE = ROOT / "queue", ROOT / "results", ROOT / "state"
FEED_URL = "https://www.wrestleview.com/feed/"

SHOW_WORDS = {
    "raw": ["raw"],
    "nxt": ["nxt"],
    "smackdown": ["smackdown"],
    "dynamite": ["dynamite"],
    "collision": ["collision"],
}


def git(*args, check=True):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=check)


def sync():
    git("pull", "-q", "--rebase", "origin", "main", check=False)


def push(msg):
    git("add", "-A")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    git("commit", "-qm", msg)
    for _ in range(5):
        if git("push", "-q", "origin", "main", check=False).returncode == 0:
            return
        sync()
        time.sleep(3)
    sys.exit("push fallito")


def send(jobs, timeout=240):
    """jobs: lista di (nome, dict). Ritorna la lista degli esiti (dict)."""
    sync()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    names = []
    for i, (name, job) in enumerate(jobs):
        fn = f"{stamp}-{i:02d}-{re.sub(r'[^a-z0-9-]', '-', name.lower())[:40]}.json"
        (QUEUE / fn).write_text(json.dumps(job, ensure_ascii=False), "utf-8")
        names.append(fn)
    push(f"coda: {', '.join(n for n, _ in jobs)[:60]}")
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(10)
        sync()
        if all((RESULTS / n).exists() for n in names):
            return [json.loads((RESULTS / n).read_text("utf-8")) for n in names]
    sys.exit(f"Timeout: nessun esito dopo {timeout}s per {names} (controlla GitHub Actions)")


def summarize(res):
    r = res.get("response")
    txt = json.dumps(r, ensure_ascii=False)
    if len(txt) > 700:
        txt = txt[:700] + "…"
    return f"[{res['http_status']}] {res['action']} {res['file']}: {txt}"


def strip_html(fragment):
    fragment = re.sub(r"(?is)<(script|style).*?</\1>", " ", fragment)
    fragment = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"(?i)</(p|h[1-6]|li|div|blockquote)>", "\n\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    paras = [re.sub(r"[ \t\xa0]+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return [p for p in paras if p]


def date_patterns(d):
    dt = datetime.strptime(d, "%Y-%m-%d")
    m, day, yy = dt.month, dt.day, dt.strftime("%y")
    return [f"{m}/{day}/{yy}", f"{m}-{day}-{yy}", f"{m:02d}/{day:02d}/{yy}", f"{m}/{day}/{dt.year}",
            dt.strftime("%B ") + str(day)]


def diff_and_save(key, paras, meta):
    STATE.mkdir(exist_ok=True)
    latest = STATE / f"{key}.source.txt"
    prev = latest.read_text("utf-8").split("\n\n") if latest.exists() else []
    seen = set(prev)
    new = [p for p in paras if p not in seen]
    latest.write_text("\n\n".join(paras), "utf-8")
    print(json.dumps(meta, ensure_ascii=False))
    print(f"Paragrafi totali: {len(paras)} | nuovi o modificati rispetto al giro precedente: {len(new)}")
    if any("touch up" in p.lower() or "refresh" in p.lower() for p in paras[-3:]):
        print("NOTA: il report risulta ancora in aggiornamento.")
    print("=" * 60)
    for p in new:
        print(p, end="\n\n")


def cmd_feed(show, d, key):
    res = send([("fetch-feed", {"action": "fetch", "url": FEED_URL})])[0]
    if not res["ok"]:
        sys.exit(f"Feed non scaricato: {summarize(res)}")
    body = (RESULTS / res["body_file"]).read_text("utf-8")
    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    root = ET.fromstring(body)
    words, dates = SHOW_WORDS[show], date_patterns(d)
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        hay = (title + " " + link).lower()
        if any(w in hay for w in words) and "result" in hay and any(p.lower() in hay or p.replace("/", "-").lower() in hay for p in dates):
            content = item.findtext("content:encoded", default="", namespaces=ns) or item.findtext("description") or ""
            meta = {"title": title, "link": link, "pubDate": item.findtext("pubDate")}
            diff_and_save(key, strip_html(content), meta)
            return
    titles = [i.findtext("title") for i in root.iter("item")][:12]
    print("REPORT NON ANCORA PRESENTE NEL FEED. Ultimi titoli:")
    for t in titles:
        print(" -", t)


def cmd_page(url, key):
    res = send([("fetch-page", {"action": "fetch", "url": url})])[0]
    if not res["ok"]:
        sys.exit(f"Pagina non scaricata: {summarize(res)}")
    body = (RESULTS / res["body_file"]).read_text("utf-8")
    m = re.search(r'(?is)<div[^>]+class="[^"]*(entry-content|td-post-content|article-content|post-content)[^"]*"[^>]*>(.*)', body)
    diff_and_save(key, strip_html(m.group(2) if m else body), {"url": url})


def cmd_state(key, sets):
    STATE.mkdir(exist_ok=True)
    f = STATE / f"{key}.json"
    st = json.loads(f.read_text("utf-8")) if f.exists() else {}
    if sets:
        sync()
        st = json.loads(f.read_text("utf-8")) if f.exists() else {}
        for kv in sets:
            k, v = kv.split("=", 1)
            if k == "add_ref":
                st.setdefault("refs", [])
                if v not in st["refs"]:
                    st["refs"].append(v)
            else:
                try:
                    st[k] = json.loads(v)
                except ValueError:
                    st[k] = v
        st["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        f.write_text(json.dumps(st, ensure_ascii=False, indent=2), "utf-8")
        push(f"stato {key}")
    print(json.dumps(st, ensure_ascii=False, indent=2))


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    cmd = argv[1]
    if cmd == "send":
        jobs = [(Path(a).stem, json.loads(Path(a).read_text("utf-8"))) for a in argv[2:]]
        for r in send(jobs):
            print(summarize(r))
    elif cmd == "job":
        job = json.loads(argv[2])
        for r in send([(job.get("action", "job"), job)]):
            print(summarize(r))
    elif cmd == "feed":
        key = argv[argv.index("--key") + 1] if "--key" in argv else f"{argv[2]}-{argv[3]}"
        cmd_feed(argv[2], argv[3], key)
    elif cmd == "page":
        cmd_page(argv[2], argv[argv.index("--key") + 1])
    elif cmd == "state":
        sets = [a for a in argv[3:] if a != "--set"]
        cmd_state(argv[2], sets)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
