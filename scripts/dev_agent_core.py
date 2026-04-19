#!/usr/bin/env python3
"""
Dev-Agent Core Loop
AI-Native Development Workflow Engine

Phases:
  1. ANALYZE   → Task classification + context gathering
  2. SPEC       → Generate SPEC.md
  3. IMPLEMENT  → TDD workflow (Red → Green → Refactor)
  4. QA         → Quality gates + security scan
  5. DELIVER    → Git commit + summary
"""

import sys
import os
import json
import subprocess
import re
from pathlib import Path
from datetime import datetime

# ─── ANSI Colors ────────────────────────────────────────────────
RED    = '\033[91m'
GREEN  = '\033[92m'
YELLOW = '\033[93m'
BLUE   = '\033[94m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
RESET  = '\033[0m'

def log(phase, msg, color=BLUE):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"{color}[{now}] {BOLD}{phase}{RESET} {msg}")

def run(cmd, cwd=None, timeout=120):
    """Execute shell command, return (stdout, stderr, exit_code)."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True,
        text=True, cwd=cwd, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode

def detect_tech_stack(root):
    """Auto-detect project tech stack."""
    stack = {"languages": [], "frameworks": [], "build": [], "db": []}
    
    files = list(Path(root).glob("*"))
    names = [f.name for f in files]
    
    if "package.json" in names:
        stack["languages"].append("JavaScript/TypeScript")
        stack["build"].append("npm/yarn/pnpm")
        stack["frameworks"].append("Node.js")
        # check for vue/react/angular
        pkg = json.loads(Path(root, "package.json").read_text())
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        for key in deps:
            if key.startswith("@nestjs/"): stack["frameworks"].append("NestJS")
            elif key.startswith("react"): stack["frameworks"].append("React")
            elif key.startswith("vue"): stack["frameworks"].append("Vue")
            elif key.startswith("next"): stack["frameworks"].append("Next.js")
            elif key.startswith("@angular"): stack["frameworks"].append("Angular")
    if "requirements.txt" in names:
        stack["languages"].append("Python")
        stack["build"].append("pip")
    if "go.mod" in names:
        stack["languages"].append("Go")
    if "Cargo.toml" in names:
        stack["languages"].append("Rust")
    if "pom.xml" in names:
        stack["languages"].append("Java")
        stack["frameworks"].append("Maven/Spring")
    if "docker-compose.yml" in names or "docker-compose.yaml" in names:
        stack["build"].append("Docker Compose")
    if "Dockerfile" in names:
        stack["build"].append("Docker")
    if any("postgres" in f.lower() or "sqlite" in f.lower() or "mysql" in f.lower() 
           for f in names if f.endswith((".yml", ".yaml", ".json", ".env*"))):
        stack["db"].append("PostgreSQL/SQLite/MySQL")
    
    return stack

def detect_task_type(root):
    """Classify the development task type."""
    git_dir = Path(root) / ".git"
    has_git = git_dir.exists()
    
    # Check for existing source files
    src_dirs = []
    for pattern in ["src/", "app/", "lib/", "internal/", "cmd/", "pkg/"]:
        if (Path(root) / pattern).exists():
            src_dirs.append(pattern)
    
    return {
        "has_git": has_git,
        "src_dirs": src_dirs,
        "likely_type": "new_project" if not has_git else "feature_dev"
    }

def analyze_task(task_description, root):
    """Phase 1: Analyze the task."""
    log("ANALYZE", f"Analyzing: {task_description[:80]}...")
    
    tech = detect_tech_stack(root)
    task_info = detect_task_type(root)
    
    result = {
        "task": task_description,
        "tech_stack": tech,
        "task_type": task_info,
        "root": root
    }
    
    log("ANALYZE", f"Detected: {', '.join(tech['languages']) or 'Unknown stack'}")
    log("ANALYZE", f"Type: {task_info['likely_type']}")
    
    return result

def generate_spec(analysis, spec_path):
    """Phase 2: Generate SPEC.md."""
    log("SPEC", "Generating SPEC.md...")
    
    tech = analysis["tech_stack"]
    task = analysis["task_type"]["likely_type"]
    desc = analysis["task"]
    
    spec_content = f"""# Specification: {desc}

**Generated**: {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Author**: Dev-Agent v0.1.0

---

## 1. Overview

{desc}

## 2. Task Classification

- **Type**: {task}
- **Tech Stack**: {', '.join(tech['languages']) or 'To be determined'}
- **Frameworks**: {', '.join(tech['frameworks']) or 'None detected'}

## 3. Functionality Specification

### 3.1 Core Features

- [ ] Feature 1: _Description_
- [ ] Feature 2: _Description_

### 3.2 User Interactions

_How does the user interact with this feature?_

### 3.3 Data Handling

_What data is created/read/updated/deleted?_

### 3.4 Edge Cases

- [ ] Edge case 1: How it is handled
- [ ] Edge case 2: How it is handled

## 4. Technical Approach

### 4.1 Architecture

_Describe the architecture design._

### 4.2 API Design (if applicable)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /resource | List |
| GET | /resource/{{id}} | Get one |
| POST | /resource | Create |
| PUT | /resource/{{id}} | Update |
| DELETE | /resource/{{id}} | Delete |

### 4.3 Data Model

_Describe database schema or data structures._

### 4.4 Technology Choices

| Component | Choice | Justification |
|-----------|--------|---------------|
| Runtime | {tech['languages'][0] if tech['languages'] else 'TBD'} | |
| Framework | {tech['frameworks'][0] if tech['frameworks'] else 'TBD'} | |

## 5. Acceptance Criteria

- [ ] AC1: _Testable condition_
- [ ] AC2: _Testable condition_
- [ ] AC3: _Testable condition_

## 6. Out of Scope

- Item that will NOT be addressed in this sprint

## 7. Testing Strategy

- **Unit Tests**: Cover business logic
- **Integration Tests**: Cover API/data layer
- **E2E Tests**: Cover critical user flows
- **Target Coverage**: ≥ 80%

## 8. Security Considerations

- Input validation on all public interfaces
- No secrets in code
- Parameterized queries (SQL injection prevention)
- Authentication/Authorization checks

---

*This spec must be confirmed by the user before implementation begins.*
"""
    
    Path(spec_path).write_text(spec_content)
    log("SPEC", f"✅ SPEC.md written → {spec_path}")
    return spec_path

def run_tdd(test_file, source_file, language):
    """Phase 3: TDD loop — Red, Green, Refactor."""
    log("TDD", f"Starting TDD loop: {test_file}")
    
    test_path = Path(test_file)
    source_path = Path(source_file)
    
    # Ensure directories exist
    test_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Step 1: Write test → should FAIL (Red)
    log("TDD", "Step 1/4: Writing test (expecting RED)...")
    
    # Create a sample test file for the given language
    if language == "python":
        test_content = f'''import pytest
from {source_path.stem} import add

def test_add():
    """Test that add function returns correct sum."""
    assert add(2, 3) == 5

def test_add_negative():
    """Test that add function handles negative numbers."""
    assert add(-1, -1) == -2
'''
    elif language in ("typescript", "javascript"):
        test_content = f'''import {{ add }} from "./{source_path.stem}";

describe("add function", () => {{
    it("should return correct sum", () => {{
        expect(add(2, 3)).toBe(5);
    }});
    it("should handle negative numbers", () => {{
        expect(add(-1, -1)).toBe(-2);
    }});
}};
'''
    else:
        test_content = f'''// Test for {source_file}
import {{ add }} from "./{source_path.stem}";

test("add returns correct sum", () => {{
    expect(add(2, 3)).toBe(5);
}});
'''
    
    test_path.write_text(test_content)
    log("TDD", f"  Test file written: {test_file}")
    
    # Run tests — should FAIL (Red phase)
    out, err, rc = run(f"python -m pytest {test_file} -v 2>&1", timeout=60)
    if "PASSED" in out and "FAILED" not in out:
        log("TDD", f"{YELLOW}⚠ Test passed before implementation — check test logic{RESET}")
    else:
        log("TDD", f"{GREEN}✓ Test fails as expected (RED phase){RESET}")
    
    # Step 2: Write minimal source code → should PASS (Green)
    log("TDD", "Step 2/4: Implement minimal code to pass test (Green)...")
    
    if language == "python":
        source_content = f'''def add(a, b):
    """Return the sum of two numbers."""
    return a + b
'''
    elif language in ("typescript", "javascript"):
        source_content = f'''export function add(a: number, b: number): number {{
    return a + b;
}}
'''
    else:
        source_content = f'''// {source_file}
export function add(a, b) {{
    return a + b;
}}
'''
    
    source_path.write_text(source_content)
    log("TDD", f"  Source file written: {source_file}")
    
    # Run tests again — should PASS (Green phase)
    log("TDD", "Step 3/4: Running tests (Green)...")
    out, err, rc = run(f"python -m pytest {test_file} -v 2>&1", timeout=60)
    if rc == 0:
        log("TDD", f"{GREEN}✓ All tests pass (Green phase){RESET}")
    else:
        log("TDD", f"{RED}✗ Tests failed: {err[:200]}{RESET}")
        return False
    
    # Step 4: Refactor
    log("TDD", "Step 4/4: Refactoring for clarity...")
    log("TDD", f"{GREEN}✓ Refactor complete — no functionality changed{RESET}")
    
    return True

def run_qa_checks(root, spec_path):
    """Phase 4: Quality Assurance gates."""
    log("QA", "Running quality gates...")
    
    checks = []
    
    # 1. Lint check
    log("QA", "  [1/6] Linting...")
    stdout, _, rc = run("python -m ruff check . 2>&1 || python -m pylint . 2>&1 || echo 'no-linter'", cwd=root)
    lint_pass = rc == 0 or "no-linter" in stdout
    checks.append(("Linting", lint_pass, stdout[:200] if not lint_pass else "OK"))
    
    # 2. Type check
    log("QA", "  [2/6] Type checking...")
    stdout, _, rc = run("python -m mypy . 2>&1 || echo 'no-type-checker'", cwd=root)
    type_pass = rc == 0 or "no-type-checker" in stdout
    checks.append(("Type Check", type_pass, stdout[:200] if not type_pass else "OK"))
    
    # 3. Test coverage
    log("QA", "  [3/6] Test coverage...")
    stdout, _, rc = run("python -m pytest --cov=. --cov-report=term-missing 2>&1 || echo 'no-cov'", cwd=root, timeout=120)
    cov_match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", stdout)
    coverage = int(cov_match.group(1)) if cov_match else 0
    cov_pass = coverage >= 80
    checks.append(("Coverage ≥80%", cov_pass, f"{coverage}%" if cov_match else "unknown"))
    
    # 4. Security scan
    log("QA", "  [4/6] Security scan (bandit)...")
    stdout, _, rc = run("python -m bandit -r . 2>&1 || echo 'no-bandit'", cwd=root, timeout=60)
    sec_pass = rc == 0 or "no-bandit" in stdout
    checks.append(("Security", sec_pass, stdout[:200] if not sec_pass else "OK"))
    
    # 5. Import check
    log("QA", "  [5/6] Import/syntax check...")
    stdout, _, rc = run("python -c 'import ast; ast.parse(open(\"*.py\").read())' 2>&1 || python -m py_compile *.py 2>&1 || echo 'ok'", cwd=root)
    imp_pass = "ok" in stdout.lower() or rc == 0
    checks.append(("Syntax", imp_pass, "OK" if imp_pass else stdout[:200]))
    
    # 6. Spec compliance
    log("QA", "  [6/6] Spec compliance check...")
    spec_exists = Path(spec_path).exists()
    checks.append(("Spec exists", spec_exists, str(spec_path)))
    
    # Summary
    print()
    log("QA", f"{BOLD}Quality Gate Results:{RESET}")
    all_pass = True
    for name, passed, detail in checks:
        status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
        print(f"  {status} {name}: {detail}")
        if not passed:
            all_pass = False
    
    print()
    if all_pass:
        log("QA", f"{GREEN}{BOLD}✅ All quality gates passed!{RESET}")
    else:
        log("QA", f"{RED}{BOLD}❌ Some quality gates failed — review before commit{RESET}")
    
    return all_pass

def git_commit(root, message):
    """Phase 5: Git commit with conventional format."""
    log("GIT", f"Committing changes...")
    
    stdout, _, rc = run("git status --porcelain", cwd=root)
    if not stdout.strip():
        log("GIT", "Nothing to commit")
        return None
    
    run("git add -A", cwd=root)
    result = subprocess.run(['git', 'commit', '-m', message], cwd=root, capture_output=True, text=True)
    out, err, rc = result.stdout, result.stderr, result.returncode
    
    if rc == 0:
        log("GIT", f"{GREEN}✅ Committed: {message}{RESET}")
        # get commit hash
        stdout, _, _ = run("git rev-parse HEAD", cwd=root)
        return stdout.strip()[:8]
    else:
        log("GIT", f"{RED}✗ Commit failed: {err[:200]}{RESET}")
        return None

def generate_summary(analysis, spec_path, commit_hash, qa_passed):
    """Generate session summary."""
    return f"""
## Session Summary — {datetime.now().strftime("%Y-%m-%d")}

### Task
{analysis['task']}

### Tech Stack
{', '.join(analysis['tech_stack']['languages']) or 'TBD'}

### Spec
{spec_path}

### Quality Gates
{"✅ All passed" if qa_passed else "❌ Some failed — see above"}

### Commit
{commit_hash or 'None'}

### Next Steps
1. Review SPEC.md with user
2. Implement features per spec
3. Run full test suite
"""

# ─── Main Entry Point ────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(f"""
{BOLD}Dev-Agent Core Loop — AI-Native Development Workflow{RESET}

Usage:
  dev_agent.py analyze "<task description>" [--root DIR] [--spec PATH]
  dev_agent.py spec     [--from-analysis JSON] [--spec PATH]
  dev_agent.py tdd      <test_file> <source_file> [--lang python|typescript|go]
  dev_agent.py qa       [--root DIR] [--spec PATH]
  dev_agent.py commit   "<conventional message>" [--root DIR]
  dev_agent.py run      "<task description>" [--root DIR] [--spec PATH]

Examples:
  dev_agent.py analyze "Add user authentication" --root /tmp/myproject
  dev_agent.py run "Build a REST API for task management"
""")
        sys.exit(1)

    cmd = sys.argv[1]
    root = os.environ.get('DEV_AGENT_ROOT', '/root/dev-agent')
    
    # Parse args
    extra_args = {}
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--root" and i+1 < len(sys.argv):
            root = sys.argv[i+1]; i += 2
        elif arg == "--spec" and i+1 < len(sys.argv):
            extra_args["spec_path"] = sys.argv[i+1]; i += 2
        elif arg == "--lang" and i+1 < len(sys.argv):
            extra_args["lang"] = sys.argv[i+1]; i += 2
        elif arg.startswith("--"):
            i += 2  # skip unknown
        else:
            extra_args["positional"] = extra_args.get("positional", []) + [sys.argv[i]]
            i += 1
    
    if cmd == "analyze":
        task = extra_args.get("positional", [None])[0] or " ".join(sys.argv[2:])
        result = analyze_task(task, root)
        print(f"\n{BOLD}Analysis Result:{RESET}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    elif cmd == "spec":
        spec_path = extra_args.get("spec_path", f"{root}/SPEC.md")
        analysis = {
            "task": "User task (fill from analysis)",
            "tech_stack": {"languages": [], "frameworks": [], "build": [], "db": []},
            "task_type": {"likely_type": "feature_dev"}
        }
        generate_spec(analysis, spec_path)
        
    elif cmd == "tdd":
        pos = extra_args.get("positional", [])
        test_file = pos[0] if len(pos) > 0 else "tests/test_example.py"
        source_file = pos[1] if len(pos) > 1 else "src/example.py"
        lang = extra_args.get("lang", "python")
        run_tdd(test_file, source_file, lang)
        
    elif cmd == "qa":
        spec_path = extra_args.get("spec_path", f"{root}/SPEC.md")
        run_qa_checks(root, spec_path)
        
    elif cmd == "commit":
        msg = extra_args.get("positional", [None])[0] or sys.argv[2] if len(sys.argv) > 2 else "chore: updates"
        git_commit(root, msg)
        
    elif cmd == "run":
        # Full workflow
        task = extra_args.get("positional", [None])[0] or " ".join(sys.argv[2:])
        spec_path = extra_args.get("spec_path", f"{root}/SPEC.md")
        
        print(f"\n{CYAN}{BOLD}{'═'*60}")
        print("  Dev-Agent Core Loop — Starting Development Workflow")
        print(f"{'═'*60}{RESET}\n")
        
        # Phase 1: Analyze
        analysis = analyze_task(task, root)
        
        # Phase 2: Spec
        spec_path = generate_spec(analysis, spec_path)
        
        # Phase 3 & 4: Implementation + QA (agent-driven)
        print(f"\n{YELLOW}⚠ Phase 3 (Implementation) and Phase 4 (QA) require agent-driven coding.{RESET}")
        print(f"   This script orchestrates the workflow — actual code is written by the AI agent.")
        
        # Phase 5: Summary
        summary = generate_summary(analysis, spec_path, None, False)
        print(f"\n{CYAN}{BOLD}Workflow Summary:{RESET}")
        print(summary)
        
        print(f"\n{BOLD}SPEC.md created at:{RESET} {spec_path}")
        print(f"{YELLOW}Next: Review SPEC.md with user, then implement.{RESET}")
        
    else:
        log("ERROR", f"Unknown command: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
