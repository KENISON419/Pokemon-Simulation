from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from copy import deepcopy
import hashlib
import json
import math
import random
import re


@dataclass
class PokemonState:
    name: str
    hp: float = 100.0
    status: str = ""
    fainted: bool = False
    item: str = ""
    moves: List[str] = field(default_factory=list)
    revealed_moves: List[str] = field(default_factory=list)
    mega_used: bool = False


@dataclass
class BattleState:
    my_active: str
    opp_active: str
    my_party: List[PokemonState]
    opp_party: List[PokemonState]
    selected3: List[str]
    weather: str = ""
    field: str = ""
    turn: int = 1


@dataclass(frozen=True)
class Action:
    kind: str
    name: str
    mega: bool = False


@dataclass(frozen=True)
class BattleStateHash:
    hp_bins: Tuple[int, int]
    active_pair: Tuple[str, str]
    remaining: Tuple[int, int]
    turn_bin: int
    weather: str
    field: str


@dataclass
class InferredSet:
    moves: Dict[str, float]
    items: Dict[str, float]
    abilities: Dict[str, float]
    spreads: Dict[str, float]


class MinimaxCache:
    def __init__(self, max_size: int = 12000):
        self.max_size = max_size
        self._cache: Dict[Tuple[BattleStateHash, str, str, int], float] = {}

    def get(self, key: Tuple[BattleStateHash, str, str, int]) -> Optional[float]:
        return self._cache.get(key)

    def set(self, key: Tuple[BattleStateHash, str, str, int], value: float) -> None:
        if len(self._cache) >= self.max_size:
            for k in list(self._cache.keys())[: self.max_size // 3]:
                del self._cache[k]
        self._cache[key] = value


class ChampionsAI:
    """poke_champ流をChampions向けに移植した高度探索AI。"""

    def __init__(self, root: str | Path, history_path: Optional[str | Path] = None, search_depth: int = 3, rollout_count: int = 24):
        self.root = Path(root)
        self.history_path = Path(history_path or self.root / "champions_ai" / "battle_history.json")
        self.search_depth = search_depth
        self.rollout_count = rollout_count
        self.usage_by_name: Dict[str, dict] = {}
        self.outcome_stats: Dict[str, Dict[str, int]] = {}
        self.cache = MinimaxCache()
        self.pokechamp_sets: Dict[str, dict] = {}
        self._load_usage()
        self._load_pokechamp_sets()
        self._load_history()

    def _load_usage(self) -> None:
        summary = json.loads((self.root / "pokemon_usage_json" / "summary.json").read_text(encoding="utf-8"))
        for row in summary.get("results", []):
            p = row.get("path")
            if not p:
                continue
            fp = self.root / p.replace("\\", "/")
            if fp.exists():
                d = json.loads(fp.read_text(encoding="utf-8"))
                self.usage_by_name[d.get("display_name", "")] = d

    def _load_pokechamp_sets(self) -> None:
        files = [
            self.root / "pokemon_AI" / "poke_env" / "data" / "static" / "gen9" / "ou" / "sets_1825.json",
            self.root / "pokemon_AI" / "poke_env" / "data" / "static" / "gen9" / "ou" / "sets_1500.json",
            self.root / "pokemon_AI" / "poke_env" / "data" / "static" / "gen9" / "vgc" / "sets_1760.json",
        ]
        merged: Dict[str, dict] = {}
        for fp in files:
            if not fp.exists():
                continue
            for k, v in json.loads(fp.read_text(encoding="utf-8")).items():
                merged[k] = v
        self.pokechamp_sets = merged

    def _load_history(self) -> None:
        if self.history_path.exists():
            self.outcome_stats = json.loads(self.history_path.read_text(encoding="utf-8")).get("outcome_stats", {})

    def save_history(self) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps({"outcome_stats": self.outcome_stats}, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_result(self, my_active: str, action: Action, win: bool) -> None:
        key = self._history_key(my_active, action)
        stat = self.outcome_stats.setdefault(key, {"w": 0, "n": 0})
        stat["n"] += 1
        stat["w"] += int(win)

    def suggest(self, st: BattleState, top_k: int = 5) -> List[Tuple[Action, float, str]]:
        my_actions = self._legal_actions(st, is_me=True)
        opp_model = self._infer_opponent_model(st)
        opp_actions = self._opponent_actions_with_prob(st, opp_model)
        scored = []
        for a in my_actions:
            tree_v = self._expectiminimax(st, a, opp_actions, self.search_depth, -1e9, 1e9)
            mc_v = self._rollout_value(st, a, opp_model)
            hist_v = self._action_posterior_bonus(st, a)
            v = 0.60 * tree_v + 0.30 * mc_v + 0.10 * hist_v
            scored.append((a, round(v, 3), self._explain(st, a, tree_v, mc_v, hist_v)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _expectiminimax(self, st: BattleState, my_action: Action, opp_actions: List[Tuple[Action, float]], depth: int, alpha: float, beta: float) -> float:
        value = 0.0
        for opp_action, prob in opp_actions:
            key = (self._hash_state(st), self._action_key(my_action), self._action_key(opp_action), depth)
            cached = self.cache.get(key)
            if cached is not None:
                value += prob * cached
                continue
            nxt = self._simulate_turn(st, my_action, opp_action)
            if depth <= 1 or self._terminal(nxt):
                ev = self._evaluate_state(nxt)
            else:
                child_opp_model = self._infer_opponent_model(nxt)
                child_opp_actions = self._opponent_actions_with_prob(nxt, child_opp_model)
                ev = -1e9
                for ca in self._legal_actions(nxt, is_me=True):
                    cv = self._expectiminimax(nxt, ca, child_opp_actions, depth - 1, alpha, beta)
                    ev = max(ev, cv)
                    alpha = max(alpha, ev)
                    if beta <= alpha:
                        break
            self.cache.set(key, ev)
            value += prob * ev
        return value

    def _rollout_value(self, st: BattleState, first_action: Action, opp_model: InferredSet) -> float:
        total = 0.0
        opp_actions = self._opponent_actions_with_prob(st, opp_model)
        for _ in range(self.rollout_count):
            sim = deepcopy(st)
            # first turn fixed action
            oa = self._sample_action(opp_actions)
            sim = self._simulate_turn(sim, first_action, oa)
            # follow-up random-policy guided by priors
            for _t in range(2):
                if self._terminal(sim):
                    break
                my_actions = self._legal_actions(sim, True)
                if not my_actions:
                    break
                my_a = random.choice(my_actions)
                om = self._infer_opponent_model(sim)
                oa = self._sample_action(self._opponent_actions_with_prob(sim, om))
                sim = self._simulate_turn(sim, my_a, oa)
            total += self._evaluate_state(sim)
        return total / max(1, self.rollout_count)

    def _sample_action(self, dist: List[Tuple[Action, float]]) -> Action:
        r = random.random()
        c = 0.0
        for a, p in dist:
            c += p
            if r <= c:
                return a
        return dist[-1][0] if dist else Action("move","わるあがき",False)


    def _usage_profile(self, mon_name: str) -> InferredSet:
        usage = self.usage_by_name.get(mon_name, {})
        sec = usage.get("sections", {})
        moves = {m.get("name", ""): m.get("rate", 0.0) for m in sec.get("技", {}).get("moves", [])}
        items = {m.get("name", ""): m.get("rate", 0.0) for m in sec.get("持ち物", {}).get("items", [])}
        abilities = {m.get("name", ""): m.get("rate", 0.0) for m in sec.get("特性", {}).get("abilities", [])}
        spreads = {m.get("name", ""): m.get("rate", 0.0) for m in sec.get("能力ポイント", {}).get("spreads", [])}
        return InferredSet(moves, items, abilities, spreads)

    def _infer_opponent_model(self, st: BattleState) -> InferredSet:
        key = self._normalize_name(st.opp_active)
        row = self.pokechamp_sets.get(key, {})
        moves = {m.get("name", ""): m.get("percentage", 0.0) for m in row.get("moves", [])}
        items = {m.get("name", ""): m.get("percentage", 0.0) for m in row.get("items", [])}
        abilities = {m.get("name", ""): m.get("percentage", 0.0) for m in row.get("abilities", [])}
        spreads = {m.get("name", ""): m.get("percentage", 0.0) for m in row.get("spreads", [])}
        use = self._usage_profile(st.opp_active)
        for k, v in use.moves.items():
            moves[k] = 0.65 * moves.get(k, 0.0) + 0.35 * v
        for k, v in use.items.items():
            items[k] = 0.65 * items.get(k, 0.0) + 0.35 * v
        for k, v in use.abilities.items():
            abilities[k] = 0.65 * abilities.get(k, 0.0) + 0.35 * v
        for k, v in use.spreads.items():
            spreads[k] = 0.65 * spreads.get(k, 0.0) + 0.35 * v
        opp = self._find(st.opp_party, st.opp_active)
        if opp:
            for mv in opp.revealed_moves:
                moves[mv] = max(moves.get(mv, 0.0), 120.0)
            if opp.item:
                items[opp.item] = max(items.get(opp.item, 0.0), 120.0)
        return InferredSet(moves, items, abilities, spreads)

    def _opponent_actions_with_prob(self, st: BattleState, model: InferredSet) -> List[Tuple[Action, float]]:
        acts = self._legal_actions(st, is_me=False)
        if not acts:
            acts = [Action("move", "わるあがき", False)]
        usage = self.usage_by_name.get(st.opp_active, {})
        usage_moves = {m.get("name"): m.get("rate", 0.0) for m in usage.get("sections", {}).get("技", {}).get("moves", [])}
        scores = []
        for a in acts:
            if a.kind == "switch":
                scores.append(0.55)
                continue
            s = 1.0
            s += usage_moves.get(a.name, 0.0) / 90.0
            s += model.moves.get(a.name, 0.0) / 120.0
            scores.append(s)
        z = sum(scores) or 1.0
        return [(a, s / z) for a, s in zip(acts, scores)]

    def _simulate_turn(self, st: BattleState, my_action: Action, opp_action: Action) -> BattleState:
        nxt = deepcopy(st)
        me = self._find(nxt.my_party, nxt.my_active)
        opp = self._find(nxt.opp_party, nxt.opp_active)
        if me is None or opp is None:
            return nxt
        if my_action.kind == "switch":
            nxt.my_active = my_action.name
            me = self._find(nxt.my_party, nxt.my_active)
        if opp_action.kind == "switch":
            nxt.opp_active = opp_action.name
            opp = self._find(nxt.opp_party, nxt.opp_active)

        my_dmg = self._expected_damage(nxt.my_active, nxt.opp_active, my_action)
        opp_dmg = self._expected_damage(nxt.opp_active, nxt.my_active, opp_action)
        first_my = self._acts_first(my_action, opp_action, nxt.turn)
        if first_my:
            opp.hp = max(0.0, opp.hp - my_dmg)
            if opp.hp <= 0: opp.fainted = True
            else:
                me.hp = max(0.0, me.hp - opp_dmg)
                if me.hp <= 0: me.fainted = True
        else:
            me.hp = max(0.0, me.hp - opp_dmg)
            if me.hp <= 0: me.fainted = True
            else:
                opp.hp = max(0.0, opp.hp - my_dmg)
                if opp.hp <= 0: opp.fainted = True
        if my_action.mega:
            me.mega_used = True
        nxt.turn += 1
        return nxt

    def _evaluate_state(self, st: BattleState) -> float:
        my_hp = sum(p.hp for p in st.my_party if not p.fainted)
        opp_hp = sum(p.hp for p in st.opp_party if not p.fainted)
        my_alive = sum(1 for p in st.my_party if not p.fainted)
        opp_alive = sum(1 for p in st.opp_party if not p.fainted)
        bad = {"やけど", "どく", "まひ", "ねむり"}
        my_st = sum(1 for p in st.my_party if p.status in bad and not p.fainted)
        opp_st = sum(1 for p in st.opp_party if p.status in bad and not p.fainted)
        opp_act = self._find(st.opp_party, st.opp_active)
        tempo = 10 if opp_act and opp_act.hp <= 35 else 0
        opp_model = self._infer_opponent_model(st)
        item_threat = max(opp_model.items.values()) / 100.0 if opp_model.items else 0.0
        return (my_hp - opp_hp) + 38 * (my_alive - opp_alive) + 5 * (opp_st - my_st) + tempo - 2.0 * item_threat

    def _legal_actions(self, st: BattleState, is_me: bool) -> List[Action]:
        party = st.my_party if is_me else st.opp_party
        active_name = st.my_active if is_me else st.opp_active
        active = self._find(party, active_name)
        if not active or active.fainted:
            return []
        out: List[Action] = []
        for mv in active.moves[:4]:
            if not mv:
                continue
            out.append(Action("move", mv, False))
            if is_me and ("メガ" in active.item or "ストーン" in active.item) and not active.mega_used:
                out.append(Action("move", mv, True))
        if not out:
            out.extend(Action("move", mv) for mv in self._top_usage_moves(active.name, 4))
        bench = st.selected3 if is_me else [p.name for p in party]
        for n in bench:
            p = self._find(party, n)
            if p and n != active_name and not p.fainted:
                out.append(Action("switch", n))
        return out

    def _top_usage_moves(self, name: str, k: int) -> List[str]:
        usage = self.usage_by_name.get(name, {})
        return [m.get("name") for m in usage.get("sections", {}).get("技", {}).get("moves", [])[:k] if m.get("name")]

    def _expected_damage(self, atk_name: str, def_name: str, action: Action) -> float:
        if action.kind == "switch":
            return 0.0
        usage = self.usage_by_name.get(atk_name, {})
        u = {m.get("name"): m.get("rate", 0.0) for m in usage.get("sections", {}).get("技", {}).get("moves", [])}
        p = self._pokechamp_move_prior(atk_name)
        blended = 0.55 * u.get(action.name, 8.0) + 0.45 * p.get(action.name, 8.0)
        dmg = 14.0 + 0.65 * blended
        if action.mega:
            dmg *= 1.20
        return max(4.0, min(95.0, dmg))

    def _action_posterior_bonus(self, st: BattleState, a: Action) -> float:
        rec = self.outcome_stats.get(self._history_key(st.my_active, a))
        if not rec or rec["n"] == 0:
            return 0.0
        n, w = rec["n"], rec["w"]
        p = w / n
        conf = math.sqrt(max(1e-9, math.log(1 + n) / n))
        return 18.0 * (p - 0.5) + 8.0 * conf

    def _history_key(self, my_active: str, a: Action) -> str:
        return f"{my_active}::{a.kind}:{a.name}::mega={int(a.mega)}"

    def _normalize_name(self, name: str) -> str:
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if key in self.pokechamp_sets:
            return key
        alias = {"ピカチュウ": "pikachu", "フシギダネ": "bulbasaur", "ヒトカゲ": "charmander"}
        return alias.get(name, key)

    def _pokechamp_move_prior(self, mon_name: str) -> Dict[str, float]:
        row = self.pokechamp_sets.get(self._normalize_name(mon_name), {})
        return {m.get("name", ""): m.get("percentage", 0.0) for m in row.get("moves", [])}

    def _acts_first(self, my_action: Action, opp_action: Action, turn: int) -> bool:
        h = int(hashlib.md5(f"{my_action}|{opp_action}|{turn}".encode()).hexdigest()[:8], 16)
        return (h % 100) < 50

    def _hash_state(self, st: BattleState) -> BattleStateHash:
        me = self._find(st.my_party, st.my_active)
        opp = self._find(st.opp_party, st.opp_active)
        hp_bins = (int((me.hp if me else 0) // 10), int((opp.hp if opp else 0) // 10))
        rem = (sum(not p.fainted for p in st.my_party), sum(not p.fainted for p in st.opp_party))
        return BattleStateHash(hp_bins, (st.my_active, st.opp_active), rem, st.turn // 2, st.weather, st.field)

    def _terminal(self, st: BattleState) -> bool:
        return (not any(not p.fainted for p in st.my_party)) or (not any(not p.fainted for p in st.opp_party))

    def _action_key(self, a: Action) -> str:
        return f"{a.kind}:{a.name}:m{int(a.mega)}"

    def _find(self, party: List[PokemonState], name: str) -> Optional[PokemonState]:
        return next((p for p in party if p.name == name), None)

    def _explain(self, st: BattleState, a: Action, tree_v: float, mc_v: float, hist_v: float) -> str:
        tags = [f"tree={tree_v:.1f}", f"mc={mc_v:.1f}", f"hist={hist_v:.1f}"]
        if a.mega:
            tags.append("mega")
        tags.append("switch" if a.kind == "switch" else "attack")
        return " | ".join(tags)

    @staticmethod
    def dump_state(st: BattleState) -> dict:
        return asdict(st)
