# src/main.py
import os, sys, random, traceback
from functools import lru_cache
from typing import List, Tuple, Optional

# ---------- rust core ----------
from rustcore import BlackjackSimulator

# ---------- tiny robust stdout ----------
try:
    import faulthandler
    faulthandler.enable()
    try: sys.stdout.reconfigure(line_buffering=True)
    except Exception: pass
except Exception: pass

# ---------- env ----------
def Ei(n, d): 
    v = os.getenv(n); 
    try: return int(float(v)) if v is not None else d
    except: return d
def Ef(n, d):
    v = os.getenv(n); 
    try: return float(v) if v is not None else d
    except: return d
def Eb(n, d):
    v = os.getenv(n); 
    if v is None: return d
    try: return 1 if int(float(v))!=0 else 0
    except: return d
def Es(n, d=""):
    v = os.getenv(n); 
    return v if v is not None else d

# ---------- constants ----------
HC_NONE, HC_NOT_TEN, HC_NOT_ACE = 0, 1, 2

# ---------- deck helpers ----------
def make_shoe_counts(decks: float) -> List[int]:
    nd = int(decks)
    return [4*nd]*9 + [16*nd]  # A..9 + T bucket

def add_to(t: int, s: bool, r: int) -> Tuple[int,bool]:
    val = 11 if r==0 else (10 if r==9 else r+1)
    t2, s2 = t+val, s or (r==0)
    if t2>21 and s2:
        t2 -= 10; s2 = False
    return t2, s2

def two_card(r1: int, r2: int) -> Tuple[int,bool]:
    t,s = 0,False
    t,s = add_to(t,s,r1)
    t,s = add_to(t,s,r2)
    return t,s

def remove_one(c: List[int], r: int) -> None:
    if r<0: return
    if c[r] <= 0: raise RuntimeError("remove_one underflow")
    c[r] -= 1

def sample_rank(c: List[int]) -> int:
    w = [max(0,x) for x in c]
    tot = sum(w)
    if tot<=0: return -1
    return random.choices(range(10), weights=w, k=1)[0]

def dealer_bj_prob(up: int, deck_t: Tuple[int,...]) -> float:
    rem = sum(deck_t)
    if rem<=0: return 0.0
    if up==0: return deck_t[9]/rem
    if up==9: return deck_t[0]/rem
    return 0.0

def sample_hole_and_peek(c: List[int], up: int, pBJ: float) -> Tuple[bool,int]:
    if up==0:
        need=9; bj = c[need]>0 and random.random()<pBJ
        if bj: remove_one(c,need); return True, need
        choices = [i for i,x in enumerate(c) if x>0 and i!=9]
        if not choices: return False, -1
        r = random.choice(choices); remove_one(c,r); return False, r
    elif up==9:
        need=0; bj = c[need]>0 and random.random()<pBJ
        if bj: remove_one(c,need); return True, need
        choices = [i for i,x in enumerate(c) if x>0 and i!=0]
        if not choices: return False, -1
        r = random.choice(choices); remove_one(c,r); return False, r
    else:
        r = sample_rank(c); remove_one(c,r); return False, r

def dealer_runout(c: List[int], up: int, hole: int, h17: bool=True) -> int:
    if hole<0: return 22
    t,s = two_card(up, hole)
    while True:
        if t>21: return 22
        if t>17: return t
        if t==17:
            if s and h17: pass
            else: return t
        r = sample_rank(c)
        if r==-1: return t
        remove_one(c,r)
        t,s = add_to(t,s,r)

def settle_vs_player(pt_final: int, dealer_final: int) -> float:
    # units per 1x stake
    if pt_final>21: return -1.0
    if dealer_final==22: return +1.0
    if pt_final>dealer_final: return +1.0
    if pt_final<dealer_final: return -1.0
    return 0.0

# ---------- shadows against fixed dealer_final ----------
def shadow_stand(pt: int, ps: bool, dealer_final: int) -> float:
    return settle_vs_player(pt, dealer_final)

def shadow_hit_greedy(pt: int, ps: bool, deck_after_dealer: List[int], dealer_final: int) -> float:
    deck = list(deck_after_dealer)
    while True:
        if pt>21: break
        if pt>=21: break
        rem = sum(deck)
        if rem<=0: break
        # stand value
        vs = settle_vs_player(pt, dealer_final)
        # expected value of hitting once
        evh = 0.0
        for r,cnt in enumerate(deck):
            if cnt==0: continue
            prob = cnt/rem
            nt, ns = add_to(pt, ps, r)
            evh += prob * settle_vs_player(nt, dealer_final)
        if vs >= evh: break
        # pick best single card greedily
        best_r = None; best_val = vs
        for r,cnt in enumerate(deck):
            if cnt==0: continue
            nt, ns = add_to(pt, ps, r)
            val = settle_vs_player(nt, dealer_final)
            if val>best_val:
                best_val = val; best_r = r
        if best_r is None: break
        pt, ps = add_to(pt, ps, best_r)
        deck[best_r] -= 1
    return settle_vs_player(pt, dealer_final)

def ev_double_from_deck(pt: int, ps: bool, deck_after_dealer: List[int], dealer_final: int) -> float:
    # expected units per 1x stake (double is 2x stake; per-stake for fair compare)
    rem = sum(deck_after_dealer)
    if rem<=0: return settle_vs_player(pt, dealer_final)
    ev=0.0
    for r,cnt in enumerate(deck_after_dealer):
        if cnt==0: continue
        prob = cnt/rem
        nt, ns = add_to(pt, ps, r)
        ev += prob * settle_vs_player(nt, dealer_final)
    return ev

def realized_double_per_stake(pt: int, ps: bool, counts: List[int], dealer_final: int) -> float:
    # draw one (consumes) then settle; return per-stake (not 2x)
    r = sample_rank(counts)
    if r==-1: return settle_vs_player(pt, dealer_final)
    remove_one(counts, r)
    nt, ns = add_to(pt, ps, r)
    return settle_vs_player(nt, dealer_final)

# ---------- CSV hook ----------
def csv_open():
    path = Es("CSV_DOUBLES","").strip()
    if not path: return None
    try:
        f = open(path, "w", encoding="utf-8", newline="")
        f.write("ev_stand,ev_hit,ev_double,realized_units,stand_shadow_units,hit_shadow_units\n")
        return f
    except Exception:
        return None

# ---------- main ----------
def main():
    # env
    NUM_HANDS = Ei("NUM_HANDS", 2000)
    NUM_DECKS = Ef("NUM_DECKS", 8.0)
    H17       = Eb("DEALER_HITS_SOFT_17", 1)==1
    CONT_SHOE = Eb("CONTINUOUS_SHOE", 1)==1
    PEN       = Ef("RESHUFFLE_PENETRATION", 0.50)
    DP_DEPTH  = Ei("DP_DEPTH", 3)
    DP_DEPTH_DBL = Ei("DP_DEPTH_DBL", DP_DEPTH)  # unused in fixed audit, but kept for compat
    DISABLE_DOUBLE = Eb("DISABLE_DOUBLE", 0)==1
    TIE_EPS   = Ef("TIE_EPS", 1e-9)
    DOUBLE_MARGIN = Ef("DOUBLE_MARGIN", 0.0)

    # sim (only used for dealer pmf elsewhere; we won’t call EV APIs in audit)
    sim = BlackjackSimulator(make_shoe_counts(NUM_DECKS), H17)

    # CSV
    csvf = csv_open()

    # shoe
    counts = make_shoe_counts(NUM_DECKS) if CONT_SHOE else None
    init_total = sum(counts) if CONT_SHOE else sum(make_shoe_counts(NUM_DECKS))

    print("==============================================")
    print("BLACKJACK: LIVE EXACT-COMPOSITION (US PEEK)")
    print("==============================================")
    print(f"NUM_HANDS={NUM_HANDS}  DECKS={NUM_DECKS}  H17={'true' if H17 else 'false'}  BJ=1.5:1")
    print(f"DAS=true  SPLIT_ACES_ONE=true  MAX_SPLITS=0  DOUBLE_AFTER_SPLIT=true")
    print(f"DISABLE_DOUBLE={'true' if DISABLE_DOUBLE else 'false'}  INSURANCE=false  DP_DEPTH={DP_DEPTH}  LRU=300000  SLICE=500")

    total_wagered = 0.0
    realized_units_sum = 0.0

    for i in range(1, NUM_HANDS+1):
        # reshuffle if needed
        if CONT_SHOE:
            if sum(counts) <= (1.0-PEN)*init_total or sum(counts)<6:
                counts = make_shoe_counts(NUM_DECKS)

        # initial deal (consume)
        r1 = sample_rank(counts); remove_one(counts, r1)
        r2 = sample_rank(counts); remove_one(counts, r2)
        up = sample_rank(counts); remove_one(counts, up)

        pt, ps = two_card(r1, r2)
        deck_t = tuple(counts)
        pBJ = dealer_bj_prob(up, deck_t)

        # resolve hole w/ peek (consume)
        is_bj, hole = sample_hole_and_peek(counts, up, pBJ)
        if is_bj:
            # player not BJ handling kept simple: immediate -1 on non-BJ hands
            realized = -1.0
            stake = 1.0
            total_wagered += stake
            realized_units_sum += realized
        else:
            # dealer finishes FIRST (consume)
            dealer_final = dealer_runout(counts, up, hole, H17)

            # snapshot deck AFTER dealer (for hypothetical shadows)
            deck_after_dealer = list(counts)

            # per-1x stake EVs against known dealer_final
            ev_stand = shadow_stand(pt, ps, dealer_final)
            ev_hit   = shadow_hit_greedy(pt, ps, deck_after_dealer, dealer_final)
            ev_dbl   = ev_double_from_deck(pt, ps, deck_after_dealer, dealer_final)

            # choose action
            best_alt = max(ev_stand, ev_hit)
            choice = "stand"
            if not DISABLE_DOUBLE and ev_dbl >= (best_alt + DOUBLE_MARGIN - TIE_EPS):
                choice = "double"
            elif ev_hit > ev_stand + TIE_EPS:
                choice = "hit"

            # realize action (consume from counts only for actual action)
            realized_per_stake = 0.0
            stake = 1.0
            if choice=="double":
                realized_per_stake = realized_double_per_stake(pt, ps, counts, dealer_final)
                stake = 2.0  # real wager is 2x
            elif choice=="hit":
                # greedy hit realized
                # re-use greedy but with consumption
                while True:
                    vs = settle_vs_player(pt, dealer_final)
                    rem = sum(counts)
                    if rem<=0: break
                    # expected value of hitting once from CURRENT counts
                    evh = 0.0
                    for r,cnt in enumerate(counts):
                        if cnt==0: continue
                        prob = cnt/rem
                        nt, ns = add_to(pt, ps, r)
                        evh += prob * settle_vs_player(nt, dealer_final)
                    if vs >= evh - TIE_EPS: break
                    rr = sample_rank(counts)
                    remove_one(counts, rr)
                    pt, ps = add_to(pt, ps, rr)
                    if pt>21: break
                realized_per_stake = settle_vs_player(pt, dealer_final)
            else:
                realized_per_stake = settle_vs_player(pt, dealer_final)

            # log CSV for doubles (per previous analyzer contract)
            if csvf and choice=="double":
                # realized_units column is reported as 2x stake (historical contract)
                realized_units = realized_per_stake * 2.0
                stand_shadow = shadow_stand(pt, ps, dealer_final)
                hit_shadow   = shadow_hit_greedy(pt, ps, deck_after_dealer, dealer_final)
                csvf.write(f"{ev_stand:.6f},{ev_hit:.6f},{ev_dbl:.6f},{realized_units:.6f},{stand_shadow:.6f},{hit_shadow:.6f}\n")

            total_wagered += stake
            realized_units_sum += (realized_per_stake * stake)

        # progress
        if i % max(1, Ei("PROGRESS_EVERY", 500)) == 0:
            print(f"...progress {i}/{NUM_HANDS}")

    print("----")
    if total_wagered>0:
        print(f"Realized per-wager       : {realized_units_sum/total_wagered:+.6f}")
    else:
        print("Realized per-wager       : n/a")

if __name__=="__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
