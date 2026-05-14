from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json
import sqlite3
from urllib.parse import urlparse
from typing import Any, Dict
from champions_ai import ChampionsAI, BattleState, PokemonState, Action

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent / "web"
DATA = Path(__file__).resolve().parent / "data"
DB_PATH = DATA / "battles.db"
DATA.mkdir(exist_ok=True)
SESSIONS: Dict[str, Dict[str, Any]] = {}
AI = ChampionsAI(ROOT)


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
    if len(st.my_party) != 6 or len(st.opp_party) != 6: return "my_party と opp_party は6匹必要です"
    if len(st.selected3) != 3: return "selected3 は3匹必要です"
    if not st.my_active or not st.opp_active: return "my_active / opp_active は必須です"
    return ""


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
            sid = data.get("session_id", "adhoc")
            log_event(sid, "suggest", st.turn, {"my_active": st.my_active, "opp_active": st.opp_active, "top": [x[0].__dict__ for x in out[:3]]})
            return self._json(200, {"suggestions": [{"action": a.__dict__, "score": s, "why": w} for a, s, w in out]})

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
