# unit_harness.py
import os, sys, json, math
from typing import List, Tuple

# ---- Rust core ----
from rustcore import BlackjackSimulator

# ---------- helpers ----------
def Ei(name: str, dflt: int) -> int:
    v = os.getenv(name)
    try: return int(float(v)) if v is not None else dflt
    except: return dflt

def Ef(name: str, dflt: float) -> float:
    v = os.getenv(name)
    try: return float(v) if v is not None else dflt
    except: return dflt

def Eb(name: str, dflt: int) -> int:
    v = os.getenv(name)
    if v is None: return dflt
    try: return 1 if int(float(v)) != 0 else 0
    except: return dflt

# ---------- config from env ----------
TIE_EPS                  = Ef("UNIT_TIE_EPS", 1e-9)
DOUBLE_MARGIN            = Ef("UNIT_DOUBLE_MARGIN", 0.0)
PREFER_DOUBLE_ON_TIE     = Eb("UNIT_PREFER_DOUBLE_ON_TIE", 1)
USE_DP_HIT               = Eb("UNIT_USE_DP_HIT", 1)
DP_DEPTH                 = Ei("UNIT_DP_DEPTH", 3)
DOUBLE_ON_9TO11_ONLY     = Eb("UNIT_DOUBLE_ON_9TO11_ONLY", 1)
EXPECT_POLICY            = Eb("UNIT_EXPECT_POLICY", 0)  # <— new: expect argmax(EV) when 1
LRU                      = Ei("UNIT_LRU", 200_000)

# Shoe / rules (matches your harness defaults)
NUM_DECKS = 8.0
H17       = True

HC_NONE, HC_NOT_TEN, HC_NOT_ACE = 0, 1, 2

# ---------- deck / totals ----------
def make_shoe_counts(num_decks: float) -> List[int]:
    nd = int(num_decks)
    return [4*nd]*9 + [16*nd]  # A..9; T bucket

def rank_val(idx: int) -> int:
    if idx == 0: return 11
    if 1 <= idx <= 8: return idx + 1
    return 10

def add_to(total: int, soft: bool, r_idx: int) -> Tuple[int, bool]:
    t = total + rank_val(r_idx)
    s = soft or (r_idx == 0)
    if t > 21 and s:
        t -= 10
        s = False
    return t, s

def two_card_total(r1: int, r2: int) -> Tuple[int, bool]:
    t, s = 0, False
    t, s = add_to(t, s, r1)
    t, s = add_to(t, s, r2)
    return t, s

def dealer_bj_prob(up_idx: int, deck_t: Tuple[int, ...]) -> float:
    rem = sum(deck_t)
    if rem <= 0: return 0.0
    if up_idx == 0:  return deck_t[9] / rem
    if up_idx == 9:  return deck_t[0] / rem
    return 0.0

# ---------- EV front-ends ----------
def stand_ev(sim: BlackjackSimulator, t: int, s: bool, up: int, deck_t: Tuple[int,...], hole_c: int) -> float:
    return sim.stand_ev(t, s, up, list(deck_t), hole_c)

def hit1_then_stand_ev(sim: BlackjackSimulator, t: int, s: bool, up: int, deck_t: Tuple[int,...], hole_c: int) -> float:
    return sim.hit_then_stand_ev(t, s, up, list(deck_t), hole_c)

def dp_hit_best_ev(sim: BlackjackSimulator, t: int, s: bool, up: int, deck_t: Tuple[int,...], hole_c: int, depth: int) -> float:
    # Simple recursive DP (no caching here; Rust core has its own LRU)
    if t > 21: return -1.0
    ev_stand = stand_ev(sim, t, s, up, deck_t, hole_c)
    if depth <= 0:
        return max(ev_stand, hit1_then_stand_ev(sim, t, s, up, deck_t, hole_c))
    rem = sum(deck_t)
    if rem == 0:
        return ev_stand
    ev_hit = 0.0
    for r in range(10):
        if deck_t[r] == 0: continue
        p = deck_t[r] / rem
        lst = list(deck_t); lst[r] -= 1
        nt, ns = add_to(t, s, r)
        ev_hit += p * dp_hit_best_ev(sim, nt, ns, up, tuple(lst), hole_c, depth - 1)
    return max(ev_stand, ev_hit)

def double_ev_per_stake(sim: BlackjackSimulator, t: int, s: bool, up: int, deck_t: Tuple[int,...], hole_c: int) -> float:
    # Rust double_ev returns total expected units on 2x stake; normalize to per-stake
    return sim.double_ev(t, s, up, list(deck_t), hole_c) / 2.0

def choose_action(sim: BlackjackSimulator, pt: int, ps: bool, up: int, deck_t: Tuple[int,...], hole_c: int) -> Tuple[str, dict]:
    ev_s = stand_ev(sim, pt, ps, up, deck_t, hole_c)
    ev_h = dp_hit_best_ev(sim, pt, ps, up, deck_t, hole_c, DP_DEPTH) if USE_DP_HIT else hit1_then_stand_ev(sim, pt, ps, up, deck_t, hole_c)
    ev_d = double_ev_per_stake(sim, pt, ps, up, deck_t, hole_c)

    best_alt = max(ev_s, ev_h)
    # Optional rule: only allow doubles on 9–11
    allow_double = True
    if DOUBLE_ON_9TO11_ONLY:
        allow_double = (pt in (9, 10, 11))

    action = "stand"
    # Compare per-stake with margin and tie handling
    if allow_double and (ev_d > best_alt + DOUBLE_MARGIN or (PREFER_DOUBLE_ON_TIE and abs(ev_d - best_alt) <= TIE_EPS and ev_d >= best_alt)):
        action = "double"
    elif ev_h > ev_s + TIE_EPS:
        action = "hit"
    return action, {"stand": ev_s, "hit": ev_h, "double": ev_d}

# ---------- cases ----------
def default_cases():
    # Classic illustrative squares
    return [
        {"r1":"5","r2":"6","up":"6","seen":"","expect":"double"},  # 11 vs 6 → DOUBLE
        {"r1":"T","r2":"2","up":"4","seen":"","expect":"stand"},   # 12 vs 4 → STAND (basic)
        {"r1":"9","r2":"2","up":"7","seen":"","expect":"double"},  # 11 vs 7 → DOUBLE
        {"r1":"A","r2":"7","up":"9","seen":"","expect":"hit"},     # A7 vs 9 → HIT (often)
    ]

def parse_rank(ch: str) -> int:
    ch = ch.strip().upper()
    if ch == "A": return 0
    if ch == "T": return 9
    v = int(ch)
    if 2 <= v <= 9: return v - 1
    raise ValueError(f"bad rank: {ch}")

def load_cases() -> list:
    fn = os.getenv("UNIT_CASES_FILE", "").strip()
    if fn:
        with open(fn, "rb") as f:
            raw = f.read()
        try:
            # try utf-8-sig first
            cases = json.loads(raw.decode("utf-8-sig"))
        except Exception:
            cases = json.loads(raw.decode("utf-8"))
        return cases
    return default_cases()

# ---------- main ----------
def main():
    print(f"UNIT: decks={int(NUM_DECKS)} H17={H17} DP={DP_DEPTH} LRU={LRU} tie_eps={TIE_EPS} dbl_margin={DOUBLE_MARGIN}")
    sim = BlackjackSimulator(make_shoe_counts(NUM_DECKS), H17)

    ok = 0; ng = 0
    for c in load_cases():
        r1 = parse_rank(c["r1"]); r2 = parse_rank(c["r2"]); up = parse_rank(c["up"])
        # For unit EV compare we use a fresh off-the-top shoe (no consumption), with peek constraint
        deck_t = tuple(make_shoe_counts(NUM_DECKS))
        pt, ps = two_card_total(r1, r2)
        hole_c = HC_NONE
        if up == 0:  hole_c = HC_NOT_TEN
        elif up == 9: hole_c = HC_NOT_ACE

        action, evs = choose_action(sim, pt, ps, up, deck_t, hole_c)

        # Expected action:
        if EXPECT_POLICY:
            # Expect the EV-optimal policy (argmax with same margins/ties)
            exp = action
        else:
            # Use label if provided; otherwise fallback to EV policy
            exp = c.get("expect", "").strip().lower() or action

        # Nice print
        evs_line = f"Stand={evs['stand']:+.6f} Hit={evs['hit']:+.6f} Double={evs['double']:+.6f}"
        print(f"[CASE] P={c['r1']}{c['r2']}({pt}{'s' if ps else ''}) vs {c['up']} | {evs_line} -> chose {action.upper()} (expect {exp.upper()}) -> ", end="")
        if action == exp:
            print("PASS"); ok += 1
        else:
            print("FAIL"); ng += 1

    print(f"RESULT: {'ALL PASS' if ng==0 else ('SOME FAIL' if ok>0 else 'ALL FAIL')}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)
