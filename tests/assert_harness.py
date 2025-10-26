# tests/assert_harness.py
#!/usr/bin/env python3
import os, sys, time, json, math
import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
API_KEY  = os.getenv("API_KEY", "")
TIMEOUT  = float(os.getenv("TIMEOUT", "10"))

HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["Authorization"] = f"Bearer {API_KEY}"

RULES_US = {
    "h17": True, "bj_payout": 1.5, "late_surrender": False,
    "das": True, "max_splits": 3, "split_aces_one": True, "peek_rule": "US",
}
RULES_EU = {**RULES_US, "peek_rule": "EU"}

def post(path, payload):
    r = requests.post(f"{BASE_URL}{path}", headers=HEADERS, json=payload, timeout=TIMEOUT)
    return r.status_code, (r.json() if r.content else {})

def start_game(num_decks=8, rules=RULES_US):
    code, body = post("/v1/game/start", {
        "num_decks": num_decks, "rules": rules, "shoe_mode": {"type": "finite_cut"}, "table": {"min_unit": 1, "max_unit": 100}
    })
    if code != 200:
        raise RuntimeError(f"start_game failed: {code} {body}")
    return body["game_key"], body

def end_game(game_key):
    post("/v1/game/end", {"game_key": game_key})

def apply_cards(game_key, cards):
    return post("/v1/counts/apply", {"game_key": game_key, "cards": cards})

def decision(game_key, hand_cards, dealer_up, can_double=True, can_split=False, can_surrender=False):
    req = {"game_key": game_key, "hand": {"cards": hand_cards, "can_double": can_double, "can_split": can_split, "can_surrender": can_surrender}, "dealer_up": dealer_up}
    return post("/v1/decision", req)

def insurance(game_key, dealer_up="A", hand_cards=None):
    req = {"game_key": game_key, "dealer_up": dealer_up}
    if hand_cards:
        req["hand"] = {"cards": hand_cards}
    return post("/v1/insurance", req)

EPS = 1e-9
def approx(a,b,eps=1e-6): return abs(a-b) <= eps
def is_num(x): 
    return isinstance(x, (int,float)) and math.isfinite(x)

def check(result, ok, msg):
    result["checks"].append({"ok": bool(ok), "msg": msg})
    if not ok: result["passed"] = False

def test_1_initial_deal_and_decision():
    res = {"name":"Test 1 — Initial deal batched + decision 11v6", "passed": True, "checks":[]}
    g, _ = start_game(8, RULES_US)
    try:
        code, body = apply_cards(g, ["5","6","6"])
        check(res, code==200, f"apply initial deal 200: got {code}")
        code, dec = decision(g, ["5","6"], "6", can_double=True, can_split=False, can_surrender=False)
        check(res, code==200, f"decision 200: got {code}")
        meta, evs = dec["meta"], dec["evs"]
        check(res, meta.get("conditioning")=="unconditioned", "conditioning == unconditioned for up=6")
        for k in ("stand","hit","double"):
            check(res, is_num(evs[k]), f"EV {k} is number")
        st, hi, db = evs["stand"], evs["hit"], evs["double"]
        check(res, db >= max(st,hi)-0.05, "double near-best vs 11v6 (sanity)")
    finally:
        end_game(g)
    return res

def test_2_us_peek_ace_up_insurance_and_decision():
    res = {"name":"Test 2 — US peek with Ace up: insurance & conditioned EV", "passed": True, "checks":[]}
    g, _ = start_game(8, RULES_US)
    try:
        code, body = apply_cards(g, ["A","8","A"])
        check(res, code==200, f"apply 200: got {code}")
        code, ins = insurance(g, dealer_up="A", hand_cards=["A","8"])
        check(res, code==200, f"insurance 200: got {code}")
        p_bj = ins["meta"]["p_bj"]
        ev_po = ins["ev"]["per_original"]
        be = ins["meta"]["break_even_p"]
        check(res, approx(be, 1/3), "break-even p ~= 1/3")
        check(res, approx(ev_po, 1.5*p_bj - 0.5, 1e-6), "insurance EV formula holds")
        code, dec = decision(g, ["A","8"], "A", True, False, True)
        check(res, code==200, f"decision 200: got {code}")
        check(res, dec["meta"]["conditioning"]=="no-dealer-BJ", "conditioning == no-dealer-BJ for up=A")
        for k in ("stand","hit","double"):
            v = dec["evs"][k]
            check(res, v is None or is_num(v), f"EV {k} is number or null (surrender may be null)")
    finally:
        end_game(g)
    return res

def test_3_dealer_bj_reveal_at_peek():
    res = {"name":"Test 3 — Dealer BJ revealed at peek (Up=T, Hole=A)", "passed": True, "checks":[]}
    g, _ = start_game(8, RULES_US)
    try:
        code, b1 = apply_cards(g, ["9","7","T"])
        check(res, code==200, f"apply initial 200: got {code}")
        rem_before = b1.get("remaining_cards")
        code, b2 = apply_cards(g, ["A"])
        check(res, code==200, f"apply hole 200: got {code}")
        rem_after = b2.get("remaining_cards")
        check(res, rem_after == rem_before-1, "remaining decreased by exactly 1 on BJ hole reveal")
        code, dec = decision(g, ["9","7"], "T", True, False, False)
        check(res, code==200, f"decision 200: got {code}")
        check(res, dec["meta"]["conditioning"]=="no-dealer-BJ", "conditioning == no-dealer-BJ for up=T")
    finally:
        end_game(g)
    return res

def test_4_split_gating():
    res = {"name":"Test 4 — Split gating & legality", "passed": True, "checks":[]}
    g, _ = start_game(8, RULES_US)
    try:
        apply_cards(g, ["8","8","6"])
        code, dec1 = decision(g, ["8","8"], "6", can_double=True, can_split=True, can_surrender=False)
        check(res, code==200, "decision with can_split=true ok")
        sv = dec1["evs"]["split"]
        check(res, sv is None or is_num(sv), "split EV present or number")
        code, dec2 = decision(g, ["8","8"], "6", can_double=True, can_split=False, can_surrender=False)
        check(res, code==200, "decision with can_split=false ok")
        check(res, dec2["evs"]["split"] is None, "split EV null when can_split=false")
        code, dec3 = decision(g, ["8","7"], "6", can_double=True, can_split=True, can_surrender=False)
        check(res, code==200, "decision non-pair ok")
        check(res, dec3["evs"]["split"] is None, "split EV null for non-pair")
    finally:
        end_game(g)
    return res

def test_5_apply_atomicity_and_conflicts():
    res = {"name":"Test 5 — Apply atomicity & conflicts", "passed": True, "checks":[]}
    g, _ = start_game(8, RULES_US)
    try:
        code, b0 = apply_cards(g, ["5"])
        check(res, code==200, "seed apply ok")
        rem_a = b0["remaining_cards"]
        code, b1 = apply_cards(g, ["X"])
        check(res, code==400, "invalid symbol returns 400")
        code, b2 = apply_cards(g, ["2"])
        rem_b = b2["remaining_cards"]
        check(res, rem_b == rem_a-1, "remaining decreased by exactly 1 after valid apply")
        too_many = ["A"] * 200
        code, b3 = apply_cards(g, too_many)
        check(res, code in (409,400), "over-apply returns conflict/invalid")
    finally:
        end_game(g)
    return res

def test_6_shoe_edge_presence():
    res = {"name":"Test 6 — shoe_edge present & numeric", "passed": True, "checks":[]}
    g, _ = start_game(8, RULES_US)
    try:
        code, b1 = apply_cards(g, ["5","6","6"])
        check(res, code==200, "apply ok")
        se = b1.get("shoe_edge", {})
        check(res, "per_wager_ev" in se and is_num(se["per_wager_ev"]), "shoe_edge.per_wager_ev is numeric")
        pen = b1.get("penetration", {})
        check(res, "remaining" in pen and "initial" in pen and "ratio" in pen, "penetration present")
    finally:
        end_game(g)
    return res

def test_7_eu_mode_unconditioned():
    res = {"name":"Test 7 — EU peek mode: unconditioned EVs", "passed": True, "checks":[]}
    g, _ = start_game(8, RULES_EU)
    try:
        apply_cards(g, ["A","8","A"])
        code, dec = decision(g, ["A","8"], "A", True, False, True)
        check(res, code==200, "decision ok")
        meta = dec["meta"]
        check(res, meta.get("peek_mode")=="EU", "peek_mode == EU")
        check(res, meta.get("conditioning")=="unconditioned", "conditioning == unconditioned under EU")
    finally:
        end_game(g)
    return res

def test_8_double_and_split_normalization():
    res = {"name":"Test 8 — Double & Split normalization", "passed": True, "checks":[]}
    g, _ = start_game(8, RULES_US)
    try:
        apply_cards(g, ["5","6","6"])
        code, dec = decision(g, ["5","6"], "6", can_double=True, can_split=False, can_surrender=False)
        check(res, code==200, "decision ok (11v6)")
        dv = dec["evs"]["double"]
        check(res, is_num(dv), "double EV is numeric")
        check(res, abs(dv) <= 1.0+1e-9, "double EV is per-stake (|double|<=1)")
        code, _ = apply_cards(g, ["8","8","6"])
        code, dec2 = decision(g, ["8","8"], "6", can_double=True, can_split=True, can_surrender=False)
        check(res, code==200, "decision ok (8,8v6)")
        sv = dec2["evs"]["split"]
        check(res, sv is None or is_num(sv), "split EV present or numeric")
        if sv is not None:
            check(res, abs(sv) <= 1.0+1e-9, "split EV is per original stake (reasonable magnitude)")
    finally:
        end_game(g)
    return res

TESTS = [
    test_1_initial_deal_and_decision,
    test_2_us_peek_ace_up_insurance_and_decision,
    test_3_dealer_bj_reveal_at_peek,
    test_4_split_gating,
    test_5_apply_atomicity_and_conflicts,
    test_6_shoe_edge_presence,
    test_7_eu_mode_unconditioned,
    test_8_double_and_split_normalization,
]

def main():
    print(f"Live API Assert Harness v1  |  BASE_URL={BASE_URL}")
    passed_all = True
    for t in TESTS:
        t0 = time.time()
        try:
            res = t()
        except Exception as e:
            res = {"name": t.__name__, "passed": False, "checks":[{"ok":False,"msg":f"EXCEPTION: {e}"}]}
        res["latency_ms"] = int((time.time()-t0)*1000)
        passed_all &= res["passed"]
        status = "PASS" if res["passed"] else "FAIL"
        print(f"\n[{status}] {res['name']}  ({res['latency_ms']} ms)")
        for c in res["checks"]:
            mark = "✔" if c["ok"] else "✘"
            print(f"  {mark} {c['msg']}")
    print("\nOVERALL:", "PASS" if passed_all else "FAIL")
    sys.exit(0 if passed_all else 1)

if __name__ == "__main__":
    main()
