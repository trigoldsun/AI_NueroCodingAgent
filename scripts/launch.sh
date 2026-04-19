#!/usr/bin/env bash
# Dev-Agent Launcher — Wraps dev_agent_core.py with Hermes Agent integration
# Usage: ./launch.sh "task description" [--root DIR] [--model MODEL]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Color codes
RED='\033[91m'
GREEN='\033[92m'
YELLOW='\033[93m'
CYAN='\033[96m'
BOLD='\033[1m'
RESET='\033[0m'

log() {
    echo -e "${CYAN}[$(date +%H:%M:%S)]${RESET} ${BOLD}$1${RESET} $2"
}

show_banner() {
    echo -e "
${BOLD}${CYAN}═══════════════════════════════════════════════════════════${RESET}
   Dev-Agent v0.1.0 — AI-Native Development Workflow
   Built on: Hermes Agent Framework
   Output by: Hermes01 (MiniMax-M2.7)
═══════════════════════════════════════════════════════════${RESET}
"
}

# Parse arguments
TASK=""
ROOT_DIR="/root/dev-agent"
SPEC_PATH=""
MODEL="MiniMax-M2.7"

while [[ $# -gt 0 ]]; do
    case $1 in
        --root)
            ROOT_DIR="$2"; shift 2 ;;
        --spec)
            SPEC_PATH="$2"; shift 2 ;;
        --model)
            MODEL="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 <task description> [options]"
            echo "  --root DIR       Working directory (default: /root/dev-agent)"
            echo "  --spec PATH      Spec file path"
            echo "  --model MODEL    Model to use"
            exit 0 ;;
        *)
            TASK="$1"; shift ;;
    esac
done

[[ -z "$TASK" ]] && { echo "Error: task description required"; exit 1; }

show_banner

log "ANALYZE" "Task: $TASK"
log "MODEL"   "Using: $MODEL"

# Phase 1: Analysis
log "PHASE-1" "Running analysis..."
ANALYSIS=$(python3 "$SCRIPT_DIR/dev_agent_core.py" analyze "$TASK" --root "$ROOT_DIR" 2>/dev/null)
echo "$ANALYSIS"

# Phase 2: Spec
log "PHASE-2" "Generating SPEC.md..."
SPEC_OUT=$(python3 "$SCRIPT_DIR/dev_agent_core.py" spec --root "$ROOT_DIR" --spec "${SPEC_PATH:-$ROOT_DIR/SPEC.md}" 2>/dev/null)
echo "$SPEC_OUT"

log "PHASE-3" "Implementation → AI Agent driven (Hermes/Claude Code)"
log "PHASE-4" "QA Gates → Automated"
log "PHASE-5" "Git Commit → Conventional format"

echo -e "\n${GREEN}${BOLD}✅ Dev-Agent workflow initialized${RESET}"
echo -e "   Review SPEC.md, then the AI agent will implement the code."
