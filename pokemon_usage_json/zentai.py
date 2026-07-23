import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests

BASE = "https://champs.pokedb.tokyo"
URL = f"{BASE}/pokemon/list?season=2&rule=0"

# zentai.py と同じフォルダに保存
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_PATH = SCRIPT_DIR / "pokemon_usage_ranking_s2_rule0.json"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

res = session.get(URL, timeout=30)
res.raise_for_status()
html = res.text

updated_at = None
m_updated = re.search(
    r'<span class="tag is-light is-info">更新日</span>\s*'
    r'<span class="tag is-light">([^<]+)</span>',
    html,
    re.S
)
if m_updated:
    updated_at = unescape(m_updated.group(1)).strip()

card_pattern = re.compile(
    r'<div class="column[^"]*"[^>]*data-pokemon-item[^>]*>.*?'
    r'<a href="([^"]+)" class="list-pokemon button is-fullwidth">(.*?)</a>\s*</div>',
    re.S
)

ranking = []

for href, body in card_pattern.findall(html):
    rank_match = re.search(
        r'<div class="pokemon-rank[^"]*">\s*(\d+)\s*</div>',
        body,
        re.S
    )
    name_match = re.search(
        r'<div class="pokemon-name">([^<]+)</div>',
        body,
        re.S
    )

    if not rank_match or not name_match:
        continue

    full_url = urljoin(BASE, unescape(href))
    parsed = urlparse(full_url)
    qs = parse_qs(parsed.query)

    key_match = re.search(r"/pokemon/show/([^/?#]+)", parsed.path)

    ranking.append({
        "rank": int(rank_match.group(1)),
        "pokemon_key": key_match.group(1) if key_match else None,
        "display_name": unescape(name_match.group(1)).strip(),
        "season": int(qs.get("season", [2])[0]),
        "rule": int(qs.get("rule", [0])[0]),
        "url": full_url
    })

ranking.sort(key=lambda x: x["rank"])

result = {
    "source_url": URL,
    "season": 2,
    "rule": 0,
    "updated_at": updated_at,
    "count": len(ranking),
    "ranking": ranking
}

OUT_PATH.write_text(
    json.dumps(result, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"saved: {OUT_PATH}")
print(f"count: {len(ranking)}")