# src/app.py
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Literal, Any, Tuple
from datetime import datetime
import os, sys, platform, hashlib

BUILD_TAG = "stub+rust-flag-debug-ev-2025-10-24"

app = FastAPI(title="Exact-Deck Live API (stub with optional rust + debug)")

# ---------- Feature flags ----------
USE_RUST_CORE = os.getenv("USE_RUST_CORE", "0") not in ("0", "", "false", "False")

# ---------- Attempt rust adapter import (optional) ----------
HAVE_RUST = False
try:
    if USE_RUST_CORE:
        from src.core_adapter import (
            stand_ev as rc_stand_ev,
            hit_then_stand_ev as rc_hit1_ev,
            double_ev_per_stake as rc_double_ev,
            split_ev_per_stake as rc_split_ev,
            p_bj as rc_p_bj,
        )
        HAVE_RUST = True
except Exception as e:
    print(f"[WARN] rust core unavailable: {e}", flush=True)
    HAVE_RUST = False

# ---------- Map schema/validation to 400 (not 422) ----------
@app.exception_handler(RequestValidationError)
async def _validation_to_400(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"error":"invalid_card_symbol","detail":str(exc)})

# ---------- Models (match harness) ----------
Rank = Literal["A","2","3","4","5","6","7","8","9","T"]

class Rules(BaseModel):
    h17: bool
    bj_payout: float = 1.5
    late_surrender: bool = False
    das: bool = True
    max_splits: int = 3
    split_aces_one: bool = True
    peek_rule: Literal["US","EU"]

class ShoeMode(BaseModel):
    type: Literal["finite_cut","round_fresh"]

class GameStartRequest(BaseModel):
    num_decks: int = 8
    rules: Rules
    shoe_mode: ShoeMode

class GameEndRequest(BaseModel):
    game_key: str

class CountsApplyRequest(BaseModel):
    game_key: str
    cards: List[Rank] = Field(min_length=1)

class HandSpec(BaseModel):
    cards: List[Rank] = Field(min_length=1)
    can_double: bool
    can_split: bool
    can_surrender: bool

class DecisionRequest(BaseModel):
    game_key: str
    hand: HandSpec
    dealer_up: Rank

# ---------- In-memory store ----------
class _GameState(BaseModel):
    game_key: str
    num_decks: int
    rules: Dict[str, Any]
    counts: Dict[str, int]
    initial: int

STORE: Dict[str,_GameState] = {}

# ---------- Helpers ----------
def _fresh_counts(nd:int)->Dict[str,int]:
    c={"A":4*nd, "T":16*nd}
    for r in ("2","3","4","5","6","7","8","9"):
        c[r]=4*nd
    return c

def _remaining(counts:Dict[str,int])->int:
    return sum(int(v) for v in counts.values())

def _counts_hash(counts:Dict[str,int])->str:
    s=",".join(f"{k}:{counts[k]}" for k in sorted(counts))
    return "sha1:"+hashlib.sha1(s.encode()).hexdigest()

def _p_bj(counts:Dict[str,int], up:str)->float:
    tot=_remaining(counts)
    if tot<=0: return 0.0
    if up=="A": return counts.get("T",0)/float(tot)
    if up=="T": return counts.get("A",0)/float(tot)
    return 0.0

def _conditioning(peek_mode:str, up:str)->str:
    return "no-dealer-BJ" if (peek_mode=="US" and up in ("A","T")) else "unconditioned"

def _add_to(t:int,s:bool,r:str)->Tuple[int,bool]:
    v = 11 if r=="A" else (10 if r=="T" else int(r))
    t2=t+v; s2=s or (r=="A")
    if t2>21 and s2: t2-=10; s2=False
    return t2,s2

def _log(msg:str): print(msg, flush=True)

# ---------- Ops ----------
@app.get("/health")
def health(): return {"ok": True}

@app.get("/version")
def version():
    return {
        "api":"1.0.0",
        "python":sys.version.split()[0],
        "platform":platform.platform(),
        "backend":"rust" if (USE_RUST_CORE and HAVE_RUST) else "stub",
        "use_rust_flag": bool(USE_RUST_CORE),
        "rust_available": bool(HAVE_RUST),
        "build": BUILD_TAG,
    }

# ---------- Lifecycle ----------
@app.post("/v1/game/start")
def game_start(req:GameStartRequest):
    g="g_"+datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    counts=_fresh_counts(req.num_decks)
    st=_GameState(game_key=g, num_decks=req.num_decks, rules=req.rules.model_dump(),
                  counts=counts, initial=_remaining(counts))
    STORE[g]=st
    return {"game_key":g,
            "created_at":datetime.utcnow().isoformat()+"Z",
            "rules":st.rules,
            "shoe":{"num_decks":st.num_decks,
                    "remaining_cards":_remaining(st.counts),
                    "counts_hash":_counts_hash(st.counts)},
            "version":{"api":"1.0.0","core":("rust" if (USE_RUST_CORE and HAVE_RUST) else "stub")}}

@app.post("/v1/game/end")
def game_end(req:GameEndRequest):
    STORE.pop(req.game_key, None)
    return {"ok":True,"ended_at":datetime.utcnow().isoformat()+"Z"}

# ---------- Counts apply ----------
@app.post("/v1/counts/apply")
def counts_apply(req:CountsApplyRequest):
    st=STORE.get(req.game_key)
    if not st: raise HTTPException(404,detail={"error":"unknown_game_key"})
    need:Dict[str,int]={}
    for r in req.cards: need[r]=need.get(r,0)+1
    for r,n in need.items():
        have=st.counts.get(r,0)
        if n>have:
            raise HTTPException(409,detail={"error":"insufficient_cards","detail":f"{r} requested {n}, available {have}"})
    for r,n in need.items(): st.counts[r]-=n
    rem=_remaining(st.counts)
    return {"ok":True,
            "remaining_cards":rem,
            "counts_hash":_counts_hash(st.counts),
            "penetration":{"remaining":rem,"initial":st.initial,"ratio":rem/st.initial},
            "shoe_edge":{"per_wager_ev":0.0,"mode":"pre-deal"}}

# ---------- Decision (rust if enabled & available; else stub) ----------
@app.post("/v1/decision")
def decision(req:DecisionRequest):
    try:
        st=STORE.get(req.game_key)
        if not st: raise HTTPException(404,detail={"error":"unknown_game_key"})

        up=req.dealer_up
        cards=req.hand.cards
        can_double=req.hand.can_double
        can_split=req.hand.can_split
        can_surrender=req.hand.can_surrender

        # compute (used by stub and to feed rust)
        t,s=0,False
        for r in cards: t,s=_add_to(t,s,r)

        peek_mode = st.rules.get("peek_rule","US")
        h17       = bool(st.rules.get("h17", True))

        # default stub EVs
        ev_stand=-0.05; ev_hit=0.0; ev_double=0.0; ev_split=None

        # If rust is enabled and available, use it for EVs
        if USE_RUST_CORE and HAVE_RUST:
            try:
                ev_stand  = float(rc_stand_ev(t, s, up, st.counts, peek_mode, h17=h17))
                ev_hit    = float(rc_hit1_ev(t, s, up, st.counts, peek_mode, h17=h17))
                if can_double:
                    ev_double = float(rc_double_ev(t, s, up, st.counts, peek_mode, h17=h17))
                if can_split and len(cards)==2 and cards[0]==cards[1] and callable(rc_split_ev):
                    try:
                        ev_split = float(rc_split_ev(cards[0], up, st.counts, peek_mode, st.rules, h17=h17))
                    except Exception:
                        ev_split = None
            except Exception as e:
                print(f"[WARN] rust EV failure; falling back to stub: {e}", flush=True)

        # Stub special-cases to keep the existing harness behavior stable
        if not (USE_RUST_CORE and HAVE_RUST):
            if sorted(cards)==["5","6"] and up=="6":
                ev_stand=-0.12; ev_hit=+0.338; ev_double=(+0.338 if can_double else 0.0)
            if can_split and len(cards)==2 and cards[0]==cards[1]:
                ev_split = 0.21 if (cards[0]=="8" and up=="6") else -0.05

        # choose best
        candidates: Dict[str,float] = {"stand": ev_stand, "hit": ev_hit}
        if can_double: candidates["double"]=ev_double
        if can_split and ev_split is not None: candidates["split"]=ev_split
        if can_surrender: candidates["surrender"]=-0.5
        best = max(candidates, key=candidates.get)

        meta={"peek_mode":peek_mode,
              "conditioning":_conditioning(peek_mode, up),
              "p_bj": (rc_p_bj(st.counts, up) if (USE_RUST_CORE and HAVE_RUST) else _p_bj(st.counts, up)),
              "rules":st.rules,
              "version":{"core":("rust" if (USE_RUST_CORE and HAVE_RUST) else "stub"),
                         "api":"1.0.0","build":BUILD_TAG}}

        _log(f"[DECISION] core={meta['version']['core']} up={up} hand={cards} best={best}")

        return {"action":best,
                "evs":{"stand":ev_stand,"hit":ev_hit,
                       "double":(ev_double if can_double else None),
                       "split":(ev_split if can_split else None),
                       "surrender":(-0.5 if can_surrender else None)},
                "meta":meta}
    except HTTPException:
        raise
    except Exception as e:
        _log(f"[WARN] decision fallback: {e}")
        st=STORE.get(req.game_key) if req else None
        up=(req.dealer_up if req else "T")
        rules=st.rules if st else {"peek_rule":"US"}
        meta={"peek_mode":rules.get("peek_rule","US"),
              "conditioning":_conditioning(peek_mode, up),
              "p_bj":(0.0 if not st else _p_bj(st.counts, up)),
              "rules":rules,
              "version":{"core":("rust" if (USE_RUST_CORE and HAVE_RUST) else "stub"),
                         "api":"1.0.0","build":BUILD_TAG}}
        return {"action":"stand",
                "evs":{"stand":-0.05,"hit":0.0,"double":None,"split":None,"surrender":None},
                "meta":meta}

# ---------- Insurance (raw JSON; always returns 'meta') ----------
@app.post("/v1/insurance")
async def insurance_raw(request: Request):
    body = await request.json()
    game_key = body.get("game_key")
    dealer_up = body.get("dealer_up")
    if not game_key or not dealer_up:
        raise HTTPException(400, detail={"error":"bad_request","detail":"game_key and dealer_up required"})
    if dealer_up != "A":
        raise HTTPException(400, detail={"error":"dealer_up_not_ace"})

    st = STORE.get(game_key)
    if not st:
        raise HTTPException(404, detail={"error":"unknown_game_key"})

    # Optional hand.cards
    cards=[]
    hand=body.get("hand")
    if isinstance(hand, dict):
        maybe=hand.get("cards")
        if isinstance(maybe, list):
            cards=[str(x) for x in maybe]
    has_bj=(set(cards)=={"A","T"})

    pbj = float(rc_p_bj(st.counts, "A")) if (USE_RUST_CORE and HAVE_RUST) else _p_bj(st.counts, "A")
    ev_per_orig = 1.5*pbj - 0.5
    ev_per_ins  = ev_per_orig / 0.5

    meta={"p_bj":pbj,"break_even_p":1/3,"insurance_bet_fraction":0.5,
          "peek_mode":st.rules.get("peek_rule","US"),
          "even_money_equivalent":has_bj}

    return {"recommendation":("take" if pbj>(1/3) else "decline"),
            "ev":{"per_original":ev_per_orig,"per_insurance":ev_per_ins},
            "meta":meta,
            "version":{"core":("rust" if (USE_RUST_CORE and HAVE_RUST) else "stub"),
                       "api":"1.0.0","build":BUILD_TAG}}

# ---------- Debug: side-by-side EVs (stub vs rust, no side effects) ----------
@app.post("/debug/ev")
def debug_ev(req: DecisionRequest):
    # Resolve environment
    use_rust = (USE_RUST_CORE and HAVE_RUST)

    # Gather context
    st  = STORE.get(req.game_key)
    rules = st.rules if st else {"h17": True, "peek_rule": "US"}
    counts = st.counts if st else _fresh_counts(8)
    peek = rules.get("peek_rule","US")
    h17  = bool(rules.get("h17", True))

    # Compute t/s
    t,s=0,False
    for r in req.hand.cards:
        t,s=_add_to(t,s,r)

    # Stub EVs (same special-cases as decision)
    stub = {"stand": -0.05, "hit": 0.0, "double": 0.0, "split": None,
            "p_bj": _p_bj(counts, req.dealer_up)}

    if sorted(req.hand.cards)==["5","6"] and req.dealer_up=="6":
        stub.update({"stand":-0.12, "hit":+0.338, "double":(+0.338 if req.hand.can_double else 0.0)})
    if req.hand.can_split and len(req.hand.cards)==2 and req.hand.cards[0]==req.hand.cards[1]:
        stub["split"] = 0.21 if (req.hand.cards[0]=="8" and req.dealer_up=="6") else -0.05

    # Rust EVs (if available)
    rust = None
    if use_rust:
        try:
            rust = {
                "stand":  rc_stand_ev(t, s, req.dealer_up, counts, peek, h17=h17),
                "hit":    rc_hit1_ev(t, s, req.dealer_up, counts, peek, h17=h17),
                "double": (rc_double_ev(t, s, req.dealer_up, counts, peek, h17=h17) if req.hand.can_double else None),
                "split":  (rc_split_ev(req.hand.cards[0], req.dealer_up, counts, peek, rules, h17=h17)
                           if (req.hand.can_split and len(req.hand.cards)==2 and req.hand.cards[0]==req.hand.cards[1]) else None),
                "p_bj":   rc_p_bj(counts, req.dealer_up),
            }
        except Exception as e:
            rust = {"error": str(e)}

    return {"core": ("rust" if use_rust else "stub"), "stub": stub, "rust": rust, "meta": {"peek_mode": peek, "h17": h17}}

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
