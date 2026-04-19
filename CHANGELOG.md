# Changelog

All notable changes to AI_NueroCodingAgent are documented here.

## [0.1.0] - 2026-04-19

### Added

#### Core Engine
- **dev_agent_core.py** (531 lines) — 5-phase workflow engine
  - Phase 1: ANALYZE — Task classification + context gathering
  - Phase 2: SPEC — Generate SPEC.md from requirements
  - Phase 3: IMPLEMENT — TDD workflow (Red → Green → Refactor)
  - Phase 4: QA — Quality gates + security scan
  - Phase 5: DELIVER — Git commit + summary

#### Enterprise Patterns
- **circuit_breaker.py** — State machine with CLOSED/OPEN/HALF_OPEN states
  - Lazy state transition (failure count checked on first call after failure_window)
  - Atomic check+increment for HALF_OPEN to prevent race conditions
  - Lock NOT held during user function execution
- **retry_policy.py** — Exponential backoff with full jitter
  - Configurable retry conditions per exception type
  - Lock and config created once at decorator scope (not per-call)
- **structured_logger.py** — JSON logging
  - Reserved LogRecord field filtering via `_LOGRECORD_RESERVED`
  - `capture()` context manager for test output interception
  - Extra fields appear as top-level JSON keys (not nested under "extra")
- **tracing.py** — W3C Trace Context distributed tracing
  - Cryptographic trace_id/span_id via `secrets.choice`
  - Async-safe propagation across task boundaries

#### Tests (142 passed / 0 failed)
- `test_circuit_breaker.py` — 35 tests
- `test_structured_logger.py` — 29 tests
- `test_retry_policy.py` — 26 tests
- `test_tracing.py` — 18 tests
- `test_dev_agent.py` — 9 tests
- `test_example.py` — 4 tests

#### Agent Configuration
- `profiles/dev-agent/` — Agent persona, soul, and model routing config
- `skills/dev-agent-core/` — Core development workflow skill

### Security Fixes (Architecture Review by qwen3-max)
- H1: Git command injection prevented — subprocess list-form args
- H2: HALF_OPEN race condition eliminated
- H3: Lock not held during user function execution
- H4: TDD run_tdd() now executes real pytest (not mock)
- M5: Trace IDs use `secrets.choice` (not `random`)
- M1: JSONFormatter lock contention removed
- M2: Reserved field naming conflict resolved
- M3: Retry decorator creates lock/config once
- M4: Hardcoded paths replaced with `DEV_AGENT_ROOT` env var
