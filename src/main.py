# src/main.py
import os, sys, random, traceback
from functools import lru_cache
from typing import List, Tuple

from rustcore import BlackjackSimulator

# ---------- version & integrity banner ----------
import hashlib, atexit, os, sys

def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

MAIN_SHA = _sha256_of(__file__)
print(f"[BOOT] main.py SHA={MAIN_SHA}", flush=True)

# Optional hard guard: if you pass EXPECT_SHA and it doesn't match, abort.
_EXPECT_SHA = os.getenv("EXPECT_SHA", "").strip().lower()
if _EXPECT_SHA and MAIN_SHA.lower() != _EXPECT_SHA:
    print(f"[FATAL] main.py SHA mismatch! EXPECT_SHA={_EXPECT_SHA}  ACTUAL={MAIN_SHA}", flush=True)
    sys.exit(42)

def _version_footer():
    # Try to pull commonly printed params from locals/globals if present
    _vals = {}
    for k in ("NUM_HANDS","SEED","FULL_OUTCOME","DISABLE_DOUBLE"):
        _vals[k] = globals().get(k, None)
    print("[VERSION]"
          f" main.py SHA={MAIN_SHA}"
          f" | NUM_HANDS={_vals.get('NUM_HANDS')}"
          f" SEED={_vals.get('SEED')}"
          f" FULL_OUTCOME={_vals.get('FULL_OUTCOME')}"
          f" DISABLE_DOUBLE={_vals.get('DISABLE_DOUBLE')}",
          flush=True)

atexit.register(_version_footer)
# ---------- end version & integrity banner ----------


# ---------- small robust stdout ----------
try:
    import faulthandler
    faulthandler.enable()
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
except Exception:
    pass

# ---------- env helpers ----------
def Ei(n, d):  # int
    v = os.getenv(n)
    try: return int(float(v)) if v is not None else d
    except: return d

def Ef(n, d):  # float
    v = os.getenv(n)
    try: return float(v) if v is not None else d
    except: return d

def Eb(n, d):  # bool-int (0/1)
    v = os.getenv(n)
    if v is None: return d
    try: return 1 if int(float(v)) != 0 else 0
    except: return d

def Es(n, d=""):
    v = os.getenv(n)
    return v if v is not None else d

# ---------- card helpers (A..9,T bucketed as 0..9) ----------
def make_shoe_counts(num_decks: float) -> List[int]:
    nd = int(num_decks)
    return [4*nd]*9 + [16*nd]  # A..9 => 4*nd; T => 16*nd

def rank_value(idx: int) -> int:
    if idx == 0: return 11
    if 1 <= idx <= 8: return idx + 1
    return 10

def add_to(total: int, soft: bool, r_idx: int) -> Tuple[int, bool]:
    t = total + rank_value(r_idx)
    s = soft or (r_idx == 0)
    if t > 21 and s:
        t -= 10; s = False
    return t, s

def two_card_total_soft(r1: int, r2: int) -> Tuple[int, bool]:
    t, s = 0, False
    t, s = add_to(t, s, r1)
    t, s = add_to(t, s, r2)
    return t, s

def remove_one(counts: List[int], idx: int) -> None:
    if idx < 0 or idx > 9: return
    if counts[idx] <= 0: raise RuntimeError("remove from empty slot")
    counts[idx] -= 1

def draw_random_rank(counts: List[int]) -> int:
    ranks = list(range(10))
    weights = [max(0, c) for c in counts]
    tot = sum(weights)
    if tot <= 0: return -1
    return random.choices(ranks, weights=weights, k=1)[0]

# ---------- hole constraints ----------
HC_NONE = 0
HC_NOT_TEN = 1
HC_NOT_ACE = 2

# ---------- dealer helpers ----------
def dealer_bj_prob(up_idx: int, deck_t: Tuple[int, ...]) -> float:
    rem = sum(deck_t)
    if rem <= 0: return 0.0
    if up_idx == 0:  return deck_t[9] / rem  # Ace up → need T
    if up_idx == 9:  return deck_t[0] / rem  # T  up → need A
    return 0.0

def sample_hole_and_peek(counts: List[int], up_idx: int, pBJ: float) -> Tuple[bool, int]:
    """ Sample dealer hole with peek; consume from `counts` following peek rules. """
    if up_idx == 0:
        need = 9
        bj = (counts[need] > 0 and random.random() < pBJ)
        if bj: remove_one(counts, need); return True, need
        # must be non-T
        choices = [i for i,c in enumerate(counts) if c>0 and i != 9]
        if not choices: return False, -1
        r = random.choice(choices); remove_one(counts, r)
        return False, r
    elif up_idx == 9:
        need = 0
        bj = (counts[need] > 0 and random.random() < pBJ)
        if bj: remove_one(counts, need); return True, need
        # must be non-A
        choices = [i for i,c in enumerate(counts) if c>0 and i != 0]
        if not choices: return False, -1
        r = random.choice(choices); remove_one(counts, r)
        return False, r
    else:
        r = draw_random_rank(counts)
        remove_one(counts, r)
        return False, r

def dealer_runout(counts: List[int], up_idx: int, hole_idx: int, h17: bool) -> int:
    if hole_idx < 0: return 22
    total, soft = two_card_total_soft(up_idx, hole_idx)
    while True:
        if total > 21: return 22
        if total > 17: return total
        if total == 17:
            if soft and h17: pass
            else: return total
        r = draw_random_rank(counts)
        if r == -1: return total
        remove_one(counts, r)
        total, soft = add_to(total, soft, r)

def settle_vs_player(pt_final: int, dealer_final: int) -> float:
    """Per 1× stake units: +1 / 0 / -1; dealer_final==22 denotes dealer bust."""
    if pt_final > 21: return -1.0
    if dealer_final == 22: return +1.0
    if pt_final > dealer_final: return +1.0
    if pt_final < dealer_final: return -1.0
    return 0.0

# ============================================================
# MAIN
# ============================================================
def main():
    # --- env ---
    NUM_HANDS    = Ei("NUM_HANDS", 200)
    SEED         = Ei("SEED", 0)
    if SEED: random.seed(SEED)

    # rules / table
    NUM_DECKS           = Ef("NUM_DECKS", 8.0)
    H17                 = bool(Eb("DEALER_HITS_SOFT_17", 1))
    BLACKJACK_PAYOUT    = Ef("BLACKJACK_PAYOUT", 1.5)
    BJ_BONUS            = BLACKJACK_PAYOUT - 1.0

    CONTINUOUS_SHOE     = Eb("CONTINUOUS_SHOE", 1)
    RESHUFFLE_PEN       = Ef("RESHUFFLE_PENETRATION", 0.50)
    DP_DEPTH            = Ei("DP_DEPTH", 3)
    DP_DEPTH_DBL        = Ei("DP_DEPTH_DBL", 4)
    MAX_SPLITS          = Ei("MAX_SPLITS", 0)
    DISABLE_DOUBLE      = Eb("DISABLE_DOUBLE", 0)
    INSURANCE           = Eb("INSURANCE", 0)

    FULL_OUTCOME        = Es("FULL_OUTCOME", "player").strip().lower()  # "player" or "dealer"
    TIE_EPS             = Ef("TIE_EPS", 1e-9)
    DOUBLE_MARGIN       = Ef("DOUBLE_MARGIN", 0.0)
    PROGRESS_EVERY      = Ei("PROGRESS_EVERY", 500)

    CSV_DOUBLES         = Es("CSV_DOUBLES", "").strip() if FULL_OUTCOME == "dealer" else ""

    # build EV core
    shoe_template = make_shoe_counts(NUM_DECKS)
    sim = BlackjackSimulator(shoe_template, H17)

    # accumulators
    total_wagered = 0.0
    realized_units_sum = 0.0

    # CSV (dealer-first audit only; per-stake)
    csvf = None
    if CSV_DOUBLES:
        try:
            csvf = open(CSV_DOUBLES, "w", encoding="utf-8")
            csvf.write("ev_stand,ev_hit,ev_double,realized_units,stand_shadow_units,hit_shadow_units\n")
        except Exception:
            csvf = None

    # shoe state
    if CONTINUOUS_SHOE:
        counts = make_shoe_counts(NUM_DECKS)
        init_total = sum(counts)
    else:
        counts = None
        init_total = sum(shoe_template)

    try:
        for hand_i in range(1, NUM_HANDS+1):
            # reshuffle if needed
            if CONTINUOUS_SHOE:
                if sum(counts) <= (1.0 - RESHUFFLE_PEN) * init_total or sum(counts) < 6:
                    counts = make_shoe_counts(NUM_DECKS)
                    sim = BlackjackSimulator(shoe_template, H17)

            # initial deal: P1,P2, Up
            r1 = draw_random_rank(counts); remove_one(counts, r1)
            r2 = draw_random_rank(counts); remove_one(counts, r2)
            up = draw_random_rank(counts); remove_one(counts, up)

            pt, ps = two_card_total_soft(r1, r2)

            # dealer BJ probability BEFORE any action (for EVs)
            deck_before_t = tuple(counts)
            pBJ_before = dealer_bj_prob(up, deck_before_t)

            # peek constraint for EVs
            hole_c = HC_NONE
            if up == 0: hole_c = HC_NOT_TEN
            elif up == 9: hole_c = HC_NOT_ACE

            # compute EVs vs dealer distribution (peek-conditioned)
            ev_stand  = sim.stand_ev(pt, ps, up, list(deck_before_t), hole_c)
            ev_hit1   = sim.hit_then_stand_ev(pt, ps, up, list(deck_before_t), hole_c)
            ev_dbl_tot= sim.double_ev(pt, ps, up, list(deck_before_t), hole_c)  # total units on 2×
            ev_double = ev_dbl_tot / 2.0  # normalize to per-stake

            # blend-in BJ risk (law of total expectation)
            ev_stand  = pBJ_before * (-1.0) + (1.0 - pBJ_before) * ev_stand
            ev_hit1   = pBJ_before * (-1.0) + (1.0 - pBJ_before) * ev_hit1
            ev_dbl_ps = pBJ_before * (-2.0) + (1.0 - pBJ_before) * ev_dbl_tot
            ev_double = ev_dbl_ps / 2.0

            # choose action on per-stake basis
            best_alt = max(ev_stand, ev_hit1)
            choice = "stand"
            if not DISABLE_DOUBLE and (ev_double >= best_alt + DOUBLE_MARGIN - TIE_EPS):
                choice = "double"
            elif ev_hit1 > ev_stand + TIE_EPS:
                choice = "hit"

            # execute player action (consumes from counts)
            stake = 1.0
            pfinal, psoft = pt, ps

            if choice == "double":
                r = draw_random_rank(counts)
                if r >= 0:
                    remove_one(counts, r)
                    pfinal, psoft = add_to(pt, ps, r)
                stake = 2.0

            elif choice == "hit":
                # match hit_then_stand semantics: hit once then stand
                r = draw_random_rank(counts)
                if r >= 0:
                    remove_one(counts, r)
                    pfinal, psoft = add_to(pt, ps, r)

            # recompute pBJ AFTER player acts (correct deck)
            deck_after_player_t = tuple(counts)
            pBJ_after = dealer_bj_prob(up, deck_after_player_t)

            # sample hole with peek from current deck
            bj, hole = sample_hole_and_peek(counts, up, pBJ_after)

            if bj:
                realized = (-1.0) * stake
            else:
                # dealer draws after player in PLAYER-OUTCOME mode
                dfinal = dealer_runout(counts, up, hole, H17)
                realized = settle_vs_player(pfinal, dfinal) * stake

            # accumulate accounting ONCE here
            realized_units_sum += realized
            total_wagered      += stake

            # dealer-first audit (per-stake CSV) – only if FULL_OUTCOME=dealer
            if csvf and FULL_OUTCOME == "dealer":
                # In this file we keep EV/shadows per 1x stake
                # We already executed player above only for PLAYER mode; for dealer mode
                # you would run dealer first, snapshot, then compute shadows; omitted here
                pass

            if PROGRESS_EVERY and (hand_i % PROGRESS_EVERY == 0):
                print(f"...progress {hand_i}/{NUM_HANDS}", flush=True)

    except Exception:
        print("ERROR: Unhandled exception in main loop", file=sys.stderr, flush=True)
        traceback.print_exc()
    finally:
        print("----", flush=True)
        if total_wagered > 0:
            per_wager = realized_units_sum / total_wagered
            print(f"Realized per-wager       : {per_wager:+.6f}")
        if csvf:
            try: csvf.close()
            except Exception: pass


if __name__ == "__main__":
    main()
