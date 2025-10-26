# LIVE API CHEATSHEET

### Overview
This service exposes a Blackjack EV engine through a REST API, implemented in FastAPI.  
It supports both a lightweight Python **stub backend** and a compiled **Rust backend**, selectable via an environment flag.

---

## BASE URLs

| Environment | Example |
|--------------|----------|
| Local | `http://localhost:8010` |
| Docker internal | `http://host.docker.internal:8010` |

---

## HEALTH & VERSION

```http
GET /health
→ {"ok": true}

GET /version
→ {
  "api": "1.0.0",
  "python": "3.11.14",
  "platform": "Linux-...",
  "backend": "stub",
  "use_rust_flag": false,
  "rust_available": true
}
CORE ENDPOINTS
🎯 Start a Game
http
Copy code
POST /v1/game/start
{
  "num_decks": 8,
  "rules": {
    "h17": true,
    "bj_payout": 1.5,
    "late_surrender": false,
    "das": true,
    "max_splits": 3,
    "split_aces_one": true,
    "peek_rule": "US"
  },
  "shoe_mode": { "type": "finite_cut" }
}
→ {
  "game_key": "g_20251025...",
  "created_at": "...",
  "rules": {...},
  "version": {"api": "1.0.0", "core": "rust"}
}
🃏 Apply Card Counts
http
Copy code
POST /v1/counts/apply
{
  "game_key": "g_...",
  "cards": ["A","8","A"]
}
→ {
  "ok": true,
  "remaining_cards": 413,
  "counts_hash": "sha1:...",
  "penetration": {"remaining":413,"initial":416,"ratio":0.9928},
  "shoe_edge": {"per_wager_ev":0.0,"mode":"pre-deal"}
}
🤔 Decision
http
Copy code
POST /v1/decision
{
  "game_key": "g_...",
  "dealer_up": "6",
  "hand": {
    "cards": ["5","6"],
    "can_double": true,
    "can_split": false,
    "can_surrender": false
  }
}
→ {
  "action": "double",
  "evs": {
    "stand": -0.12,
    "hit": 0.338,
    "double": 0.338,
    "split": null,
    "surrender": -0.5
  },
  "meta": {
    "peek_mode": "US",
    "conditioning": "no-dealer-BJ",
    "p_bj": 0.0,
    "rules": {...},
    "version": {"core": "rust", "api": "1.0.0"}
  }
}
🛡️ Insurance
http
Copy code
POST /v1/insurance
{
  "game_key": "g_...",
  "dealer_up": "A",
  "hand": { "cards": ["A","8"] }
}
→ {
  "decision": "NO_INSURE",
  "meta": {
    "p_bj": 0.3137,
    "break_even_p": 0.3333,
    "insurance_bet_fraction": 0.5,
    "peek_mode": "US"
  }
}
DEBUG ENDPOINTS
🧠 Compare Stub vs Rust EVs
http
Copy code
POST /debug/ev
{
  "game_key": "g_...",
  "dealer_up": "6",
  "hand": {
    "cards": ["5","6"],
    "can_double": true,
    "can_split": false,
    "can_surrender": false
  }
}
→ {
  "core": "rust",
  "stub": { "stand": -0.12, "hit": 0.338, "double": 0.338, "p_bj": 0.0 },
  "rust": { "stand": -0.121, "hit": 0.333, "double": 0.333, "p_bj": 0.0 },
  "meta": { "peek_mode": "US", "h17": true }
}
🧩 (Future) Force Deck Composition
(Requires TEST_MODE=1)

http
Copy code
POST /debug/set_counts
{
  "game_key": "g_...",
  "counts": {"A": 20, "T": 60, "2": 32, "3": 32, "4": 32, "5": 32, "6": 32, "7": 32, "8": 32, "9": 32}
}
→ { "ok": true, "remaining_cards": 314 }
ENVIRONMENT FLAGS
Variable	Description	Default
USE_RUST_CORE	Switch between stub and rust engines	0
TEST_MODE	Enables /debug/set_counts	0
NUM_HANDS	Simulation hand count	—
SEED	Simulation RNG seed	—

QUICK RUN COMMANDS
Rebuild and run

powershell
Copy code
docker compose down
docker compose build --no-cache
docker compose up -d
Verify backend

powershell
Copy code
curl.exe -s http://localhost:8010/version
Run test harness

powershell
Copy code
$env:BASE_URL="http://host.docker.internal:8010"
docker run --rm -e BASE_URL="$env:BASE_URL" `
  -v "$((Resolve-Path .\tests\assert_harness.py).Path):/work/assert_harness.py:ro" `
  python:3.11-slim `
  sh -lc "python -m pip install --no-cache-dir requests && python /work/assert_harness.py"
BACKEND MODES
Mode	Description	Flag
Stub	Deterministic test backend	USE_RUST_CORE=0
Rust	Real EV computation (deck composition, recursion, DP)	USE_RUST_CORE=1

NOTES
/v1/insurance uses manual JSON parsing (no strict Pydantic).

/debug/ev is ideal for comparing stub vs rust numerically.

All responses return consistent meta sections for traceability.

When ready for live play, telemetry & simulation logic will use identical endpoints.

yaml
Copy code

---

Would you like me to also include a concise new `README.md` (summary + quickstart for future collaborators)? It’ll tie the docs and folder structure together neatly.






