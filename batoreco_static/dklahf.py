import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests


BASE = "https://batoreco.com"
START_URLS = [
    "https://batoreco.com/damage-calc",
]

OUT_DIR = Path("batoreco_static")
SLEEP = 0.2

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
})

seen = set()
queue = list(START_URLS)


def normalize_url(url: str) -> str:
    url = url.replace("\\/", "/")
    url = urljoin(BASE, url)
    return url


def should_download(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.netloc == "batoreco.com"
        and (
            parsed.path.startswith("/_next/static/")
            or parsed.path == "/damage-calc"
        )
    )


def save_path_for(url: str) -> Path:
    parsed = urlparse(url)
    path = unquote(parsed.path.lstrip("/"))

    if parsed.path == "/damage-calc":
        path = "damage-calc.html"

    return OUT_DIR / path


def extract_next_static_urls(text: str):
    found = set()

    # /_next/static/... を拾う
    for m in re.findall(r'["\']([^"\']*?_next/static/[^"\']+)["\']', text):
        found.add(normalize_url(m))

    # HTML内のエスケープされた \/ を拾う
    for m in re.findall(r'([^"\']*_next\\/static\\/[^"\']+)', text):
        found.add(normalize_url(m))

    # Next.js の Flight 内に出る static/chunks/... を拾う
    for m in re.findall(r'["\'](static/[^"\']+\.(?:js|css)(?:\?[^"\']*)?)["\']', text):
        found.add(urljoin(BASE + "/_next/", m))

    # CSS内の url(/_next/static/...) を拾う
    for m in re.findall(r'url\(([^)]+_next/static/[^)]+)\)', text):
        found.add(normalize_url(m.strip("\"'")))

    return found


while queue:
    url = queue.pop(0)
    url = normalize_url(url)

    if url in seen:
        continue
    seen.add(url)

    if not should_download(url):
        continue

    print("GET", url)

    try:
        res = session.get(url, timeout=30)
        res.raise_for_status()
    except Exception as e:
        print("ERROR", url, e)
        continue

    path = save_path_for(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(res.content)

    content_type = res.headers.get("content-type", "")
    is_text = (
        "text" in content_type
        or "javascript" in content_type
        or "json" in content_type
        or url.endswith(".js")
        or url.endswith(".css")
        or url.endswith("/damage-calc")
    )

    if is_text:
        try:
            text = res.text
            for next_url in extract_next_static_urls(text):
                if next_url not in seen:
                    queue.append(next_url)
        except Exception:
            pass

    time.sleep(SLEEP)

print("done")
print("saved to:", OUT_DIR.resolve())
print("files:", len(list(OUT_DIR.rglob("*"))))