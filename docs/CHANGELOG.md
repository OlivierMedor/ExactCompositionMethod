# CHANGELOG

## 2025-10-25
- ✅ Harness 1–8 fully passing in both stub and rust modes.
- ✅ Introduced `/debug/ev` endpoint for side-by-side EV introspection.
- ✅ Added dynamic backend switch via `USE_RUST_CORE=1`.
- ✅ Established roadmap for testing → simulation → live play.
- ✅ Project cleaned to minimal, modular structure.

## 2025-10-24
- Fixed `/v1/insurance` validation issue (missing optional fields).
- Added robust raw-JSON handler for `/v1/insurance`.
- All tests pass on stub backend.

## 2025-10-22
- Restored build stability for Docker multi-stage with `maturin`.
- Confirmed Rust build compiles and links under Python 3.11.
- Added health/version checks.
