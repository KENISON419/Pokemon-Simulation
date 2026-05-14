import json
import time
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE = "https://champs.pokedb.tokyo"

# 取得したいシーズン・ルール
# season=2 はシーズンM-2、rule=0 はシングルっぽい
SEASONS = [2]
RULES = [0]

# 最初はテスト用に 10 にすると安全。本番では None
MAX_POKEMON = None
# MAX_POKEMON = 10

# 負荷対策
SLEEP_SECONDS = 0.6

OUT_DIR = Path("pokemon_usage_json")
OUT_DIR.mkdir(exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
})


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_rate(text: str):
    if not text:
        return None
    text = clean_text(text).replace("%", "")
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if not m:
        return None
    return float(m.group(0))


def fetch_json(url: str):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_html(url: str):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def get_pokemon_master():
    url = f"{BASE}/api/pokemon/search"
    data = fetch_json(url)
    pokemons = data.get("pokemons", [])

    if MAX_POKEMON is not None:
        pokemons = pokemons[:MAX_POKEMON]

    return data, pokemons


def parse_usage_page(html: str, url: str, pokemon_key: str, display_name: str, season: int, rule: int):
    soup = BeautifulSoup(html, "html.parser")

    title = clean_text(soup.title.get_text()) if soup.title else ""

    result = {
        "pokemon_key": pokemon_key,
        "display_name": display_name,
        "season": season,
        "rule": rule,
        "url": url,
        "title": title,
        "sections": {},
        "raw_counts": {
            "move_items": 0,
            "usage_items": 0,
        }
    }

    # 各カード単位で「採用技」「特性」「持ち物」「テラスタイプ」などを拾う
    cards = soup.select(".card, .related-card")

    for card in cards:
        title_el = card.select_one(".title")
        if not title_el:
            continue

        section_title = clean_text(title_el.get_text(" ", strip=True))
        if not section_title:
            continue

        section = {
            "moves": [],
            "usages": [],
        }

        # 技系: 採用技、倒した技、倒された技など
        for item in card.select(".pokemon-trend__move-item"):
            name_el = item.select_one(".pokemon-trend__move-name")
            rate_el = item.select_one(".pokemon-trend__move-rate")
            type_el = item.select_one(".type-icon[title]")

            name = clean_text(name_el.get_text(" ", strip=True)) if name_el else ""
            rate = parse_rate(rate_el.get_text(" ", strip=True)) if rate_el else None
            type_name = type_el.get("title") if type_el else None

            if name:
                section["moves"].append({
                    "name": name,
                    "rate": rate,
                    "type": type_name,
                })

        # 円グラフ・リスト系: 特性、性格、持ち物、テラスタイプなど
        for item in card.select(".usage-list-item"):
            rank_el = item.select_one(".usage-rank")
            name_el = item.select_one(".usage-name")
            rate_el = item.select_one(".usage-rate")

            rank = clean_text(rank_el.get_text(" ", strip=True)) if rank_el else None
            name = clean_text(name_el.get_text(" ", strip=True)) if name_el else ""
            rate = parse_rate(rate_el.get_text(" ", strip=True)) if rate_el else None

            if name:
                section["usages"].append({
                    "rank": int(rank) if rank and rank.isdigit() else rank,
                    "name": name,
                    "rate": rate,
                })

        if section["moves"] or section["usages"]:
            # 同名セクションが重複した場合に備える
            key = section_title
            if key in result["sections"]:
                n = 2
                while f"{key}_{n}" in result["sections"]:
                    n += 1
                key = f"{key}_{n}"

            result["sections"][key] = section
            result["raw_counts"]["move_items"] += len(section["moves"])
            result["raw_counts"]["usage_items"] += len(section["usages"])

    return result


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    print("Pokemon usage data collector")
    print(f"output: {OUT_DIR.resolve()}")

    master, pokemons = get_pokemon_master()

    save_json(OUT_DIR / "pokemon_master.json", master)

    print(f"pokemon count: {len(pokemons)}")

    summary = {
        "base": BASE,
        "seasons": SEASONS,
        "rules": RULES,
        "total_pokemons": len(pokemons),
        "results": [],
        "errors": [],
    }

    total_jobs = len(pokemons) * len(SEASONS) * len(RULES)
    job_no = 0

    for season in SEASONS:
        for rule in RULES:
            for pokemon in pokemons:
                job_no += 1

                pokemon_key = pokemon["pokemon_key"]
                display_name = pokemon["display_name"]

                url = f"{BASE}/pokemon/show/{pokemon_key}?season={season}&rule={rule}"

                out_path = (
                    OUT_DIR
                    / f"season{season}"
                    / f"rule{rule}"
                    / f"{pokemon_key}_usage_season{season}_rule{rule}.json"
                )

                # 既に取得済みならスキップ
                if out_path.exists():
                    print(f"[{job_no}/{total_jobs}] skip {pokemon_key} {display_name}")
                    continue

                try:
                    html = fetch_html(url)
                    data = parse_usage_page(
                        html=html,
                        url=url,
                        pokemon_key=pokemon_key,
                        display_name=display_name,
                        season=season,
                        rule=rule,
                    )

                    save_json(out_path, data)

                    summary["results"].append({
                        "pokemon_key": pokemon_key,
                        "display_name": display_name,
                        "season": season,
                        "rule": rule,
                        "path": str(out_path),
                        "sections": list(data["sections"].keys()),
                        "move_items": data["raw_counts"]["move_items"],
                        "usage_items": data["raw_counts"]["usage_items"],
                    })

                    print(
                        f"[{job_no}/{total_jobs}] saved {pokemon_key} {display_name} "
                        f"sections={len(data['sections'])} "
                        f"moves={data['raw_counts']['move_items']} "
                        f"usages={data['raw_counts']['usage_items']}"
                    )

                    time.sleep(SLEEP_SECONDS)

                except Exception as e:
                    err = {
                        "pokemon_key": pokemon_key,
                        "display_name": display_name,
                        "season": season,
                        "rule": rule,
                        "url": url,
                        "error": str(e),
                    }
                    summary["errors"].append(err)
                    print(f"[ERROR] {pokemon_key} {display_name}: {e}")
                    time.sleep(2)

                # 途中経過も保存
                save_json(OUT_DIR / "summary.json", summary)

    save_json(OUT_DIR / "summary.json", summary)
    print("done")
    print(f"summary: {(OUT_DIR / 'summary.json').resolve()}")


if __name__ == "__main__":
    main()