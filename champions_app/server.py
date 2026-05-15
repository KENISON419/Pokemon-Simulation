from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json
import sqlite3
import sys
from urllib.parse import urlparse, parse_qs
from typing import Any, Dict

# Allow running `python champions_app/server.py` from project root on Windows/macOS/Linux
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from champions_ai import ChampionsAI, BattleState, PokemonState, Action

WEB = Path(__file__).resolve().parent / "web"
DATA = Path(__file__).resolve().parent / "data"
DB_PATH = DATA / "battles.db"
DATA.mkdir(exist_ok=True)
SESSIONS: Dict[str, Dict[str, Any]] = {}
AI = ChampionsAI(ROOT)


def build_name_key_map():
    pm = json.loads((ROOT / "pokemon_usage_json" / "pokemon_master.json").read_text(encoding="utf-8"))
    m = {}
    for row in pm.get("pokemons", []):
        n = row.get("display_name", "")
        k = row.get("pokemon_key", "")
        if n and k:
            m[n] = k
    return m

NAME_KEY_MAP = build_name_key_map()

def usage_file_by_name(name: str):
    key = NAME_KEY_MAP.get(name)
    if not key:
        return None
    fp = ROOT / "pokemon_usage_json" / "season2" / "rule0" / f"{key}_usage_season2_rule0.json"
    return fp if fp.exists() else None


def init_db() -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS battle_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        event_type TEXT,
        turn INTEGER,
        payload TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    con.commit(); con.close()


def log_event(session_id: str, event_type: str, turn: int, payload: Dict[str, Any]) -> None:
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT INTO battle_events(session_id,event_type,turn,payload) VALUES(?,?,?,?)", (session_id, event_type, turn, json.dumps(payload, ensure_ascii=False)))
    con.commit(); con.close()


def _pokemon_from_payload(p: Dict[str, Any]) -> PokemonState:
    return PokemonState(name=p.get("name", ""), hp=float(p.get("hp", 100)), status=p.get("status", ""), fainted=bool(p.get("fainted", False)), item=p.get("item", ""), moves=p.get("moves", []), revealed_moves=p.get("revealed_moves", []), mega_used=bool(p.get("mega_used", False)))


def to_state(payload: Dict[str, Any]) -> BattleState:
    return BattleState(my_active=payload.get("my_active", ""), opp_active=payload.get("opp_active", ""), my_party=[_pokemon_from_payload(p) for p in payload.get("my_party", [])], opp_party=[_pokemon_from_payload(p) for p in payload.get("opp_party", [])], selected3=payload.get("selected3", []), weather=payload.get("weather", ""), field=payload.get("field", ""), turn=int(payload.get("turn", 1)))


def _validate_state(st: BattleState) -> str:
    if len(st.my_party) != 6: return "my_party は6匹必要です"
    if len(st.selected3) != 3: return "selected3 は3匹必要です"
    if not st.my_active or not st.opp_active: return "my_active / opp_active は必須です"
    return ""



def top_pokemon_options(limit: int = 50):
    rows = []
    for name, usage in AI.usage_by_name.items():
        try:
            top = usage.get("sections", {}).get("技", {}).get("moves", [])
            score = sum(m.get("rate", 0) for m in top[:3])
        except Exception:
            score = 0
        rows.append((name, score))
    rows.sort(key=lambda x: x[1], reverse=True)
    return [r[0] for r in rows[:limit]]


def load_ranking_names(limit: int = 120):
    ranking_file = ROOT / "pokemon_usage_json" / "pokemon_usage_ranking_s2_rule0.json"
    if ranking_file.exists():
        try:
            obj = json.loads(ranking_file.read_text(encoding="utf-8"))
            arr = obj.get("ranking", [])
            if arr:
                if isinstance(arr[0], dict):
                    return [x.get("display_name","") for x in arr[:limit] if x.get("display_name")]
                return arr[:limit]
        except Exception:
            pass
    return top_pokemon_options(limit)

def usage_options_for(name: str):
    fp = usage_file_by_name(name)
    if fp is None:
        # fallback to AI cache by display_name
        u = AI.usage_by_name.get(name, {})
    else:
        u = json.loads(fp.read_text(encoding="utf-8"))
    sec = u.get("sections", {})
    moves = [m.get("name") for m in sec.get("技", {}).get("moves", []) if m.get("name")]
    items = [m.get("name") for m in sec.get("持ち物", {}).get("items", []) if m.get("name")]
    natures = [m.get("name") for m in sec.get("能力補正", {}).get("natures", []) if m.get("name")]
    spreads = [m.get("name") for m in sec.get("能力ポイント", {}).get("spreads", []) if m.get("name")]
    opts = {"moves": moves[:30], "items": items[:30], "natures": natures[:30], "spreads": spreads[:30]}
    opts["default"] = {
        "move1": moves[0] if len(moves)>0 else "",
        "move2": moves[1] if len(moves)>1 else "",
        "move3": moves[2] if len(moves)>2 else "",
        "move4": moves[3] if len(moves)>3 else "",
        "item": items[0] if items else "",
        "nature": natures[0] if natures else "",
        "spread": spreads[0] if spreads else "",
    }
    return opts


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def _json(self, code: int, obj: Dict[str, Any]) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/api/model_stats":
            return self._json(200, {"history_actions": len(AI.outcome_stats), "search_depth": AI.search_depth, "rollout_count": AI.rollout_count})
        if p == "/api/pokemon_options":
            return self._json(200, {"options": load_ranking_names(120)})
        if p.startswith("/api/usage_options"):
            qs = parse_qs(urlparse(self.path).query)
            name = qs.get("name", [""])[0]
            return self._json(200, usage_options_for(name))
        if p == "/api/history":
            con = sqlite3.connect(DB_PATH)
            rows = con.execute("SELECT session_id,event_type,turn,payload,created_at FROM battle_events ORDER BY id DESC LIMIT 100").fetchall()
            con.close()
            return self._json(200, {"events": [{"session_id": r[0], "event_type": r[1], "turn": r[2], "payload": json.loads(r[3]), "created_at": r[4]} for r in rows]})
        return super().do_GET()

    def do_POST(self):
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", "0"))
        try: data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except json.JSONDecodeError: return self._json(400, {"error": "invalid json"})

        if p == "/api/suggest":
            st = to_state(data); err = _validate_state(st)
            if err: return self._json(400, {"error": err})
            out = AI.suggest(st, top_k=int(data.get("top_k", 5)))
            opp_set = AI.predict_opponent_set(st.opp_active) if st.opp_active else None
            sid = data.get("session_id", "adhoc")
            log_event(sid, "suggest", st.turn, {"my_active": st.my_active, "opp_active": st.opp_active, "top": [x[0].__dict__ for x in out[:3]], "opp_set": opp_set.__dict__ if opp_set else {}})
            return self._json(200, {"suggestions": [{"action": a.__dict__, "score": s, "why": w} for a, s, w in out], "opponent_prediction": opp_set.__dict__ if opp_set else {}})

        if p == "/api/save_turn":
            sid = data.get("session_id", "")
            if not sid: return self._json(400, {"error": "session_id required"})
            sess = SESSIONS.setdefault(sid, {"turns": [], "result": None}); sess["turns"].append(data)
            (DATA / f"{sid}.json").write_text(json.dumps(sess, ensure_ascii=False, indent=2), encoding="utf-8")
            log_event(sid, "turn", int(data.get("turn", 0)), data)
            return self._json(200, {"ok": True, "turns": len(sess["turns"])})

        if p == "/api/record_result":
            sid = data.get("session_id", ""); action = data.get("action")
            if not sid or not action: return self._json(400, {"error": "session_id/action required"})
            AI.record_result(data.get("my_active", ""), Action(**action), bool(data.get("win", False))); AI.save_history()
            sess = SESSIONS.setdefault(sid, {"turns": [], "result": None}); sess["result"] = {**data, "result_label": data.get("result_label", "win" if data.get("win", False) else "lose")}
            (DATA / f"{sid}.json").write_text(json.dumps(sess, ensure_ascii=False, indent=2), encoding="utf-8")
            log_event(sid, "result", int(data.get("turn", 0)), sess["result"])
            return self._json(200, {"ok": True})

        if p == "/api/reset_battle":
            sid = data.get("session_id", ""); my_party = data.get("my_party", [])
            SESSIONS[sid] = {"turns": [], "result": None, "my_party": my_party}
            (DATA / f"{sid}.json").write_text(json.dumps(SESSIONS[sid], ensure_ascii=False, indent=2), encoding="utf-8")
            log_event(sid, "reset", 0, {"keep_my_party": True})
            return self._json(200, {"ok": True})
        self._json(404, {"error": "not found"})


def run(host: str = "0.0.0.0", port: int = 8080):
    init_db()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Champions app: http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run()
