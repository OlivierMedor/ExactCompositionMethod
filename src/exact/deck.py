# A..T = 10 slots (Ace..Ten)
from typing import Tuple

Deck = Tuple[int, int, int, int, int, int, int, int, int, int]

HC_NONE = 0
HC_NOT_TEN = 1
HC_NOT_ACE = 2

def remove_card(deck: Deck, idx: int) -> Deck:
    c = deck[idx]
    if c <= 0:
        raise ValueError(f"remove_card: cannot remove rank idx={idx} from empty slot")
    lst = list(deck)
    lst[idx] -= 1
    return tuple(lst)  # immutable

def apply_hole_constraint_view(deck: Deck, hole_c: int) -> Deck:
    # returns a *view* for probability weights; does not mutate underlying deck
    if hole_c == HC_NOT_TEN:
        if deck[9] == 0: 
            return deck
        lst = list(deck); lst[9] = 0; return tuple(lst)
    if hole_c == HC_NOT_ACE:
        if deck[0] == 0:
            return deck
        lst = list(deck); lst[0] = 0; return tuple(lst)
    return deck

def deck_total(deck: Deck) -> int:
    return sum(deck)
