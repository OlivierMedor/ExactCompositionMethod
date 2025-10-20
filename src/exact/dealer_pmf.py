from __future__ import annotations
from typing import Dict
from functools import lru_cache
from .deck import Deck, remove_card, apply_hole_constraint_view, deck_total, HC_NONE, HC_NOT_TEN, HC_NOT_ACE
from .keys import dealer_pmf_key

# Rank values: idx 0..9 => A=11, 2..9, 10 (T)
RANK_VAL = [11,2,3,4,5,6,7,8,9,10]

def _add_rank(total: int, soft: bool, r_idx: int) -> tuple[int, bool]:
    v = RANK_VAL[r_idx]
    new_total = total + v
    new_soft = soft or (r_idx == 0)
    if new_total > 21 and new_soft:
        new_total -= 10
        new_soft = False
    return new_total, new_soft

@lru_cache(maxsize=200_000)
def _pmf_cached(key) -> Dict[int, float]:
    total, soft, deck, h17, hole_c = key

    # Standing rules
    if total >= 17:
        if total > 21:
            return {22: 1.0}  # 22 == bust
        # H17: hit on soft 17; S17: stand on all >=17
        if not (h17 and soft and total == 17):
            return {total: 1.0}

    # Draw step
    pmf: Dict[int, float] = {}
    view = apply_hole_constraint_view(deck, hole_c)  # important: *view* only
    remaining = deck_total(view)
    if remaining == 0:
        return {total if total <= 21 else 22: 1.0}

    for r_idx, cnt in enumerate(view):
        if cnt == 0: 
            continue
        p = cnt / remaining
        # Remove from the *real* deck (not the view)
        new_deck = remove_card(deck, r_idx)
        n_total, n_soft = _add_rank(total, soft, r_idx)
        child = _pmf_cached(dealer_pmf_key(n_total, n_soft, new_deck, h17, hole_c))
        for k, v in child.items():
            pmf[k] = pmf.get(k, 0.0) + p * v
    return pmf

def dealer_pmf(start_total: int, start_soft: bool, deck: Deck, h17: bool, hole_constraint: int) -> Dict[int, float]:
    return _pmf_cached(dealer_pmf_key(start_total, start_soft, deck, h17, hole_constraint))
