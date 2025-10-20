from __future__ import annotations
from typing import Dict, Tuple
from .dealer_pmf import dealer_pmf
from .deck import Deck, remove_card, HC_NONE, HC_NOT_ACE, HC_NOT_TEN

def stand_ev(player_total: int, player_soft: bool,
             dealer_up_idx: int, deck_post_deal: Deck,
             h17: bool, hole_c: int, wager: float = 1.0) -> float:
    # dealer upcard contributes its value to start_total/soft
    up_soft = (dealer_up_idx == 0)
    up_val = 11 if up_soft else (10 if dealer_up_idx == 9 else dealer_up_idx + 1)
    # if ace as 11 overflows >21 at start, reduce to 1 (not really needed on first draw, but safe)
    start_total = up_val
    start_soft = up_soft

    pmf = dealer_pmf(start_total, start_soft, deck_post_deal, h17, hole_c)
    bust_p = pmf.get(22, 0.0)

    win = bust_p + sum(p for t, p in pmf.items() if 17 <= t <= 21 and t < player_total <= 21)
    push = pmf.get(player_total, 0.0)
    lose = 1.0 - win - push

    return wager * (win - lose)

def hit_then_stand_ev(player_total: int, player_soft: bool,
                      dealer_up_idx: int, deck: Deck,
                      h17: bool, hole_c: int, wager: float = 1.0) -> float:
    from .dealer_pmf import RANK_VAL
    rem = sum(deck)
    if rem == 0:
        return stand_ev(player_total, player_soft, dealer_up_idx, deck, h17, hole_c, wager)

    ev = 0.0
    for r_idx, cnt in enumerate(deck):
        if cnt == 0: 
            continue
        p = cnt / rem
        v = RANK_VAL[r_idx]
        nt = player_total + v
        ns = player_soft or (r_idx == 0)
        if nt > 21 and ns:
            nt -= 10
            ns = False
        nd = remove_card(deck, r_idx)
        ev += p * stand_ev(nt, ns, dealer_up_idx, nd, h17, hole_c, wager)
    return ev
