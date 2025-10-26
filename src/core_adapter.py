# src/core_adapter.py
from __future__ import annotations

from typing import Dict, Optional

# Rank order used across the project
_RANKS = ("A","2","3","4","5","6","7","8","9","T")
_INDEX = {r:i for i,r in enumerate(_RANKS)}

# Hole constraints (match rustcore)
HC_NONE     = 0
HC_NOT_TEN  = 1
HC_NOT_ACE  = 2

def _counts_to_vec(counts: Dict[str, int]) -> list[int]:
    """Order counts as [A,2,3,4,5,6,7,8,9,T]"""
    return [int(counts.get(r, 0)) for r in _RANKS]

def _hole_constraint(peek_mode: str, up: str) -> int:
    pm = (peek_mode or "US").upper()
    if pm == "US":
        if up == "A": return HC_NOT_TEN
        if up == "T": return HC_NOT_ACE
    return HC_NONE

def p_bj(counts: Dict[str, int], up: str) -> float:
    """Dealer BJ probability from current counts (used for insurance/meta)."""
    tot = sum(int(v) for v in counts.values())
    if tot <= 0:
        return 0.0
    if up == "A":
        return counts.get("T", 0) / float(tot)
    if up == "T":
        return counts.get("A", 0) / float(tot)
    return 0.0

# --- Try to import the rustcore simulator ---
try:
    from rustcore import BlackjackSimulator as _Sim
except Exception as e:
    _Sim = None

def _require() -> None:
    if _Sim is None:
        raise RuntimeError("rustcore module not available")

def stand_ev(pt_total: int, pt_soft: bool, up: str,
             counts: Dict[str,int], peek_mode: str, *,
             h17: bool = True,
             dp_depth: Optional[int] = None) -> float:
    """
    Per-stake EV if player stands immediately.
    """
    _require()
    vec = _counts_to_vec(counts)
    sim = _Sim(vec, bool(h17), dp_depth, None)
    hc  = _hole_constraint(peek_mode, up)
    return float(sim.stand_ev(int(pt_total), bool(pt_soft), _INDEX[up], vec, int(hc), dp_depth))

def hit_then_stand_ev(pt_total: int, pt_soft: bool, up: str,
                      counts: Dict[str,int], peek_mode: str, *,
                      h17: bool = True,
                      dp_depth: Optional[int] = None) -> float:
    """
    Per-stake EV for exactly one hit, then stand (matches execution).
    """
    _require()
    vec = _counts_to_vec(counts)
    sim = _Sim(vec, bool(h17), dp_depth, None)
    hc  = _hole_constraint(peek_mode, up)
    return float(sim.hit_then_stand_ev(int(pt_total), bool(pt_soft), _INDEX[up], vec, int(hc), dp_depth))

def double_ev_per_stake(pt_total: int, pt_soft: bool, up: str,
                        counts: Dict[str,int], peek_mode: str, *,
                        h17: bool = True,
                        dp_depth_dbl: Optional[int] = None) -> float:
    """
    Per-stake EV for double (one card then stand).
    If the rust function returns total ±2 units, we normalize to per-stake.
    In our rustcore, double_ev == hit_then_stand_ev per-stake, so this is direct.
    """
    _require()
    vec = _counts_to_vec(counts)
    sim = _Sim(vec, bool(h17), None, dp_depth_dbl)
    hc  = _hole_constraint(peek_mode, up)
    ev  = float(sim.double_ev(int(pt_total), bool(pt_soft), _INDEX[up], vec, int(hc), dp_depth_dbl))
    # If you ever switch rust to ±2 total semantics, divide by 2 here.
    return ev

def split_ev_per_stake(pair_rank: str, up: str,
                       counts: Dict[str,int], peek_mode: str, rules: Dict,
                       *, h17: bool = True,
                       dp_depth_split: Optional[int] = None) -> Optional[float]:
    """
    Per original stake EV for splitting a pair (average of two child hands’ per-stake EVs).
    May return None if rust doesn’t expose split_ev.
    """
    _require()
    if not hasattr(_Sim, "split_ev"):
        return None
    vec  = _counts_to_vec(counts)
    sim  = _Sim(vec, bool(h17), None, None)
    hc   = _hole_constraint(peek_mode, up)
    up_i = _INDEX[up]
    pr_i = _INDEX[pair_rank]
    das  = bool(rules.get("das", True))
    spl1 = bool(rules.get("split_aces_one", True))
    try:
        return float(sim.split_ev(int(pr_i), int(up_i), vec, int(hc), das, spl1, dp_depth_split))
    except Exception:
        return None
