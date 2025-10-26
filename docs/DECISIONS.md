# Key Design Decisions

## Architecture
- The API runs as a **FastAPI service** exposing Blackjack EV computations.
- The **Rust core** (`rustcore`) performs deterministic EV calculations.
- A **Python adapter** (`core_adapter.py`) abstracts the interface; when `USE_RUST_CORE=0`, the stub model is used for consistency and testing.

## Environment Variables
| Variable | Purpose | Default |
|-----------|----------|----------|
| `USE_RUST_CORE` | Enables compiled rustcore backend | `0` |
| `TEST_MODE` | Enables test-only endpoints like `/debug/set_counts` | `0` |
| `NUM_HANDS`, `SEED`, etc. | Used in simulation scripts | — |

## Backend Parity
- **Stub** mimics the API contract but returns simplified, deterministic EVs.
- **Rust core** computes full deck-composition EVs with `peek`, `double`, `split`, and recursion depth parameters.
- Both paths produce compatible JSON for all endpoints.

## Testing & Validation
- `/debug/ev` compares **stub vs rust** output in a single call.
- The **assert harness** validates key Blackjack mechanics: legality, conditioning, insurance, and EV normalization.
- Future tests will use `/debug/set_counts` to validate deck-composition strategy correctness.

## Deployment & Simulation
- Docker multi-stage builds produce a self-contained API image.
- Simulation runs (`run_short_sim.ps1`, `run_long_sim.ps1`) will use the same backend API, ensuring consistency between simulated and live decision calls.
