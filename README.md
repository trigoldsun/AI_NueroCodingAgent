# AI_NueroCodingAgent

> Enterprise-grade AI Coding Agent — 5-phase TDD workflow with circuit breaker, retry policy, structured logging, and distributed tracing.

## Features

- 🔄 **5-Phase Workflow**: ANALYZE → SPEC → IMPLEMENT (TDD) → QA → DELIVER
- ⚡ **Circuit Breaker**: Automatic failure isolation with HALF_OPEN recovery
- 🔁 **Retry Policy**: Exponential backoff with jitter, configurable retry conditions
- 📋 **Structured Logging**: JSON output with reserved field filtering, capture() for testing
- 🔍 **Distributed Tracing**: W3C Trace Context, async-safe propagation
- 🔐 **Security**: No command injection, no hardcoded paths, cryptographic trace IDs

## Architecture

```
dev_agent_core.py       # 5-phase workflow engine (531 lines)
├── structured_logger.py # JSON logging + capture()
├── retry_policy.py     # Exponential backoff + jitter
├── circuit_breaker.py  # State machine (CLOSED/OPEN/HALF_OPEN)
└── tracing.py          # W3C TraceContext propagation
```

## Quick Start

```bash
cd /root/dev-agent
python scripts/dev_agent_core.py
```

## Test Suite

```bash
pytest tests/ -v
```

**Current: 142 passed / 0 failed** ✅

## Enterprise Patterns

| Pattern | Implementation | Location |
|---------|---------------|----------|
| Circuit Breaker | State machine with lazy transition | `scripts/circuit_breaker.py` |
| Retry | Exponential backoff + full jitter | `scripts/retry_policy.py` |
| Structured Log | JSON with reserved field filter | `scripts/structured_logger.py` |
| Distributed Trace | W3C TraceContext propagation | `scripts/tracing.py` |
| TDD Workflow | Red → Green → Refactor phases | `scripts/dev_agent_core.py` |

## Security Fixes (from Architecture Review)

- ✅ Git command injection prevented (list-form subprocess args)
- ✅ HALF_OPEN race condition eliminated (atomic check+increment)
- ✅ Lock not held during user function execution
- ✅ Cryptographic trace IDs (`secrets.choice` not `random`)
- ✅ No hardcoded paths (uses `DEV_AGENT_ROOT` env var)

## License

MIT
