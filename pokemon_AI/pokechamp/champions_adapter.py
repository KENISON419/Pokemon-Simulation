"""Champions adapter over pokechamp core for local app integration.

This module is the bridge requested: app -> pokechamp(champions-tuned) directly.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Any
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from champions_ai.engine import ChampionsAI, BattleState, PokemonState


@dataclass
class ChampionsPokechampAdapter:
    root: Path
    mode: str = "pokechamp"

    def __post_init__(self):
        self.ai = ChampionsAI(self.root)
        self.ai.set_strength_profile(self.mode)

    def suggest(self, payload: Dict[str, Any], top_k: int = 5) -> Dict[str, Any]:
        st = BattleState(
            my_active=payload.get("my_active", ""),
            opp_active=payload.get("opp_active", ""),
            my_party=[PokemonState(**p) for p in payload.get("my_party", [])],
            opp_party=[PokemonState(**p) for p in payload.get("opp_party", [])],
            selected3=payload.get("selected3", []),
            weather=payload.get("weather", ""),
            field=payload.get("field", ""),
            turn=int(payload.get("turn", 1)),
        )
        out = self.ai.suggest(st, top_k=top_k)
        opp = self.ai.predict_opponent_set(st.opp_active) if st.opp_active else None
        return {
            "suggestions": [{"action": a.__dict__, "score": s, "why": w} for a, s, w in out],
            "opponent_prediction": opp.__dict__ if opp else {},
        }

    def set_mode(self, mode: str):
        self.mode = mode
        self.ai.set_strength_profile(mode)
