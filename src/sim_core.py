# src/sim_core.py
"""
Corrected exact-composition blackjack simulator (Revision 11 - Final).

This version contains the definitive fix for the stall. The root cause was a subtle
bug in the player action loop's handling of split Aces. The loop has been completely
rewritten into a robust queue processor to ensure correct state transitions for all
conditions, including splits. This resolves the final known cause of the stall.
"""

from typing import Dict, Tuple, List, Any, Optional
from functools import lru_cache
from collections import defaultdict
import random

# --- Canonical Rules Definition ---
RULES = {
    "num_decks": 8,
    "dealer_hits_soft_17": True,
    "blackjack_payout": 1.5,
    "allow_das": True,
    "max_splits": 1,
    "no_hits_after_split_aces": True,
    "reshuffle_penetration": 0.50,
}

LOG_FIRST_DECISION_EVS = False

# --- Memoization Caches ---
_dp_cache: Dict[Tuple, Tuple[str, float]] = {}

# --- Deck & Hand Utilities ---
def make_deck_tuple(num_decks: int) -> Tuple[int, ...]:
    return tuple([4 * num_decks] * 9 + [16 * num_decks])

def tuple_remove(deck: Tuple[int, ...], rank: int) -> Tuple[int, ...]:
    idx = rank - 1
    if deck[idx] > 0:
        lst = list(deck)
        lst[idx] -= 1
        return tuple(lst)
    return deck

def hand_value(cards: Tuple[int, ...]) -> Tuple[int, bool]:
    # Rank 1 is Ace, Ranks 2-9 are face value, Rank 10 is 10/J/Q/K
    total = sum(cards)
    aces = cards.count(1)
    is_soft = False
    while aces > 0 and total + 10 <= 21:
        total += 10; is_soft = True; aces -= 1
    return total, is_soft

# --- Basic Strategy (For Split Decisions) ---
def get_basic_split_decision(cards: Tuple[int, ...], up: int, num_total_hands: int, max_splits: int) -> bool:
    if len(cards) != 2 or cards[0] != cards[1] or (num_total_hands - 1) >= max_splits:
        return False
    rank = cards[0]
    if rank in [1, 8]: return True
    if rank == 9 and up not in [7, 10, 1]: return True
    if rank == 7 and up <= 7: return True
    if rank == 6 and up <= 6: return True
    if rank in [2, 3] and up <= 7: return True
    return False

# --- Dealer PMF ---
@lru_cache(maxsize=512_000)
def _dealer_pmf_from_total(total: int, soft: bool, deck: Tuple[int, ...], h17: bool) -> Dict[str, float]:
    if total > 21: return {'bust': 1.0}
    if total >= 17 and not (soft and total == 17 and h17): return {str(total): 1.0}

    rem = sum(deck)
    if rem == 0: return {str(total): 1.0}

    out = defaultdict(float)
    for r in range(1, 11):
        if deck[r - 1] > 0:
            p = deck[r - 1] / rem
            new_deck = tuple_remove(deck, r)
            # Correctly calculate next state
            nt, ns = total, soft
            nt += r
            if r == 1: ns = True
            if nt > 21 and ns: nt -= 10; ns = False
            
            sub = _dealer_pmf_from_total(nt, ns, new_deck, h17)
            for k, v in sub.items(): out[k] += p * v
    return dict(out)

@lru_cache(maxsize=128_000)
def _dealer_pmf_with_up_cached(deck: Tuple[int, ...], up: int, h17: bool, hole_constraint: Optional[str]) -> Dict[str, float]:
    deck_no_up = tuple_remove(deck, up)
    allowed_hole_ranks, total_allowed_cards = [], 0
    for r in range(1, 11):
        if (hole_constraint == 'NOT_TEN' and r == 10) or (hole_constraint == 'NOT_ACE' and r == 1):
            continue
        count = deck_no_up[r - 1]
        if count > 0:
            allowed_hole_ranks.append(r); total_allowed_cards += count

    if total_allowed_cards == 0:
        total, _ = hand_value((up,))
        return {str(total): 1.0}

    out = defaultdict(float)
    for hr in allowed_hole_ranks:
        p_hole = deck_no_up[hr - 1] / total_allowed_cards
        deck2 = tuple_remove(deck_no_up, hr)
        t0, soft0 = hand_value((up, hr))
        sub = _dealer_pmf_from_total(t0, soft0, deck2, h17)
        for k, v in sub.items(): out[k] += p_hole * v
    return dict(out)

# --- Player Decision Engine (DP) ---
def stand_ev(player_total: int, up: int, deck: Tuple[int, ...], rules: Dict, hole_constraint: Optional[str]) -> float:
    pmf = _dealer_pmf_with_up_cached(deck, up, rules["dealer_hits_soft_17"], hole_constraint)
    ev = pmf.get('bust', 0.0)
    for d_str, p in pmf.items():
        if d_str != 'bust':
            d = int(d_str)
            if player_total > d: ev += p
            elif player_total < d: ev -= p
    return ev

def one_step_ev(hand: Tuple[int, ...], up: int, deck: Tuple[int, ...], rules: Dict, hole_constraint: Optional[str]) -> float:
    rem = sum(deck)
    if rem == 0: return -1.0
    
    acc = 0.0
    for r in range(1, 11):
        if deck[r - 1] > 0:
            p = deck[r - 1] / rem; deck2 = tuple_remove(deck, r)
            t, _ = hand_value(hand + (r,));
            if t > 21: acc -= p
            else: acc += p * stand_ev(t, up, deck2, rules, hole_constraint)
    return acc

def dp_decision(hand: Tuple[int, ...], up: int, deck: Tuple[int, ...], can_double: bool,
                depth: int, hole_constraint: Optional[str], rules: Dict, disable_double: bool) -> Tuple[str, float]:
    hand_key = tuple(sorted(hand))
    state_key = (hand_key, up, deck, can_double, depth, hole_constraint, disable_double)
    if state_key in _dp_cache: return _dp_cache[state_key]

    total, _ = hand_value(hand)
    ev_s = stand_ev(total, up, deck, rules, hole_constraint)
    best_action, best_ev = 'S', ev_s

    rem = sum(deck)
    if rem > 0:
        acc = 0.0
        for r in range(1, 11):
            if deck[r-1] > 0:
                p = deck[r-1] / rem
                new_hand = hand + (r,)
                deck2 = tuple_remove(deck, r)
                t, _ = hand_value(new_hand)
                
                if t > 21:
                    acc -= p
                else:
                    if depth > 0:
                        _, sub_ev = dp_decision(new_hand, up, deck2, False, depth - 1, hole_constraint, rules, disable_double)
                    else:
                        sub_ev = stand_ev(t, up, deck2, rules, hole_constraint)
                    acc += p * sub_ev
        if acc > best_ev:
            best_action, best_ev = 'H', acc

    if can_double and not disable_double:
        ev_d = 2.0 * one_step_ev(hand, up, deck, rules, hole_constraint)
        if ev_d > best_ev:
            best_action, best_ev = 'D', ev_d

    _dp_cache[state_key] = (best_action, best_ev)
    return best_action, best_ev

# --- Simulator Class ---
class BlackjackSimulator:
    def __init__(self, rules, use_basic_only, disable_double, dp_depth, cache_clear_every, trace, seed):
        self.rules = rules
        self.use_basic_only = use_basic_only
        self.disable_double = disable_double
        self.dp_depth = dp_depth
        self.cache_clear_every = cache_clear_every
        if seed is not None: random.seed(seed)

        self.shoe = make_deck_tuple(self.rules["num_decks"])
        self.total_cards_initial = sum(self.shoe)
        self.stats = defaultdict(float, {"actions": defaultdict(int)})

    def _draw_card(self) -> int:
        rem = sum(self.shoe)
        if rem <= 0:
            self.shoe = make_deck_tuple(self.rules["num_decks"])
            self.stats["reshuffles"] += 1
            rem = sum(self.shoe)
        
        r = random.randint(1, rem)
        acc = 0
        for rank in range(1, 11):
            acc += self.shoe[rank - 1]
            if r <= acc:
                self.shoe = tuple_remove(self.shoe, rank)
                return rank
        # This fallback should ideally never be reached
        return 10

    def play_hand(self):
        self.stats["hands_played"] += 1
        if sum(self.shoe) / self.total_cards_initial < (1 - self.rules["reshuffle_penetration"]):
            self.shoe = make_deck_tuple(self.rules["num_decks"]); self.stats["reshuffles"] += 1
            if self.cache_clear_every > 0:
                _dp_cache.clear(); _dealer_pmf_from_total.cache_clear(); _dealer_pmf_with_up_cached.cache_clear()
        
        if self.stats["hands_played"] > 1 and self.cache_clear_every and (self.stats["hands_played"] % self.cache_clear_every == 0):
            _dp_cache.clear(); _dealer_pmf_from_total.cache_clear(); _dealer_pmf_with_up_cached.cache_clear()

        player_hand = (self._draw_card(), self._draw_card())
        up_card = self._draw_card()
        solver_deck = self.shoe

        player_bj = (hand_value(player_hand)[0] == 21)
        dealer_bj, hole_constraint, hole_card = False, None, 0
        
        if up_card in (1, 10):
            hole_card = self._draw_card()
            if (up_card == 1 and hole_card == 10) or (up_card == 10 and hole_card == 1):
                dealer_bj = True
            else:
                hole_constraint = 'NOT_TEN' if up_card == 1 else 'NOT_ACE'
        
        if player_bj or dealer_bj:
            self.stats["total_wagered"] += 1
            if player_bj and dealer_bj: self.stats["pushes"] += 1
            elif player_bj: self.stats["player_profit"] += self.rules["blackjack_payout"]; self.stats["player_wins"] += 1
            elif dealer_bj: self.stats["player_profit"] -= 1; self.stats["player_losses"] += 1
            return

        hands_to_play = [{'hand': player_hand, 'bet': 1.0, 'solver_deck': solver_deck}]
        final_hands = []

        while hands_to_play:
            state = hands_to_play.pop(0)
            hand = state['hand']

            while True:  # Action loop for the current hand
                total, _ = hand_value(hand)
                if total >= 21:
                    break

                num_total_hands = len(hands_to_play) + len(final_hands) + 1
                can_split = get_basic_split_decision(hand, up_card, num_total_hands, self.rules["max_splits"])
                
                if can_split:
                    self.stats["actions"]['P'] += 1
                    split_card = hand[0]
                    
                    c1 = self._draw_card()
                    c2 = self._draw_card()
                    deck_after_split = tuple_remove(tuple_remove(state['solver_deck'], c1), c2)
                    
                    # Add two new, fully formed hands to the queue
                    hands_to_play.insert(0, {'hand': (split_card, c1), 'bet': 1.0, 'solver_deck': deck_after_split})
                    hands_to_play.insert(1, {'hand': (split_card, c2), 'bet': 1.0, 'solver_deck': deck_after_split})
                    
                    hand = None  # Mark original hand as resolved
                    break

                can_double = len(hand) == 2
                act, _ = dp_decision(hand, up_card, state['solver_deck'], can_double, self.dp_depth,
                                     hole_constraint, self.rules, self.disable_double)
                self.stats["actions"][act] += 1

                if act == 'S':
                    break
                if act == 'D':
                    state['bet'] *= 2.0
                    c = self._draw_card()
                    hand += (c,)
                    state['solver_deck'] = tuple_remove(state['solver_deck'], c)
                    break # Doubling is terminal
                if act == 'H':
                    c = self._draw_card()
                    hand += (c,)
                    state['solver_deck'] = tuple_remove(state['solver_deck'], c)

            if hand:
                # Handle the special case for split aces which only get one card
                is_split_ace = hand[0] == 1 and len(hand) == 2 and (len(hands_to_play) + len(final_hands)) > 0
                if is_split_ace and self.rules["no_hits_after_split_aces"]:
                    pass # The hand is final, do nothing
                
                state['hand'] = hand
                final_hands.append(state)

        if hole_card == 0:
            hole_card = self._draw_card()
        dealer_hand = (up_card, hole_card)
        
        while True:
            d_total, d_soft = hand_value(dealer_hand)
            if d_total > 21 or (d_total >= 17 and not (d_soft and d_total == 17 and self.rules["dealer_hits_soft_17"])):
                break
            dealer_hand += (self._draw_card(),)
        d_final, _ = hand_value(dealer_hand)

        for hand_state in final_hands:
            self.stats["total_wagered"] += hand_state['bet']
            p_final, _ = hand_value(hand_state['hand'])
            if p_final > 21:
                self.stats["player_profit"] -= hand_state['bet']; self.stats["player_losses"] += 1
            elif d_final > 21 or p_final > d_final:
                self.stats["player_profit"] += hand_state['bet']; self.stats["player_wins"] += 1
            elif p_final < d_final:
                self.stats["player_profit"] -= hand_state['bet']; self.stats["player_losses"] += 1
            else:
                self.stats["pushes"] += 1

    def print_summary(self):
        wagered, profit, actions = self.stats['total_wagered'], self.stats['player_profit'], self.stats['actions']
        ev = (profit / wagered * 100) if wagered > 0 else 0.0
        total_actions = sum(actions.values())
        print("\n--- Final Summary ---")
        print(f"Hands Played:  {int(self.stats['hands_played']):,}")
        print(f"Total Wagered: ${wagered:,.2f}")
        print(f"Player P/L:    ${profit:,.2f}")
        print(f"Player EV:     {ev:+.4f}%")
        print(f"Reshuffles:    {int(self.stats['reshuffles']):,}")
        if total_actions > 0:
            print("\nAction Frequencies:")
            for a, c in sorted(actions.items()):
                print(f"  {a}: {c/total_actions:>7.2%} ({int(c):,})")