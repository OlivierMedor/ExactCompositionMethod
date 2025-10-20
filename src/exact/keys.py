from typing import Tuple
from .deck import Deck

def player_key(total: int, is_soft: bool, pair_rank: int,  # pair_rank: -1 if none
               dealer_up_idx: int, deck: Deck, depth: int,
               can_double: bool, can_split: bool,
               hole_c: int, h17: bool) -> Tuple:
    return (
        int(total), int(is_soft),
        int(pair_rank), int(dealer_up_idx),
        deck, int(depth),
        int(can_double), int(can_split),
        int(hole_c), int(h17)
    )

def dealer_pmf_key(total: int, is_soft: bool, deck: Deck, h17: bool, hole_c: int) -> Tuple:
    return (int(total), int(is_soft), deck, int(h17), int(hole_c))
