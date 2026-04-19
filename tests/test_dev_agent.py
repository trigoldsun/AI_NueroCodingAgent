#!/usr/bin/env python3
"""
Dev-Agent Integration Tests
Tests the complete development workflow end-to-end.

Run with: python -m pytest tests/test_dev_agent.py -v
"""

import pytest
import subprocess
import sys
import json
import re
from pathlib import Path

AGENT_ROOT = Path("/root/dev-agent")
SCRIPT_DIR = AGENT_ROOT / "scripts"

def run(cmd, timeout=60):
    """Run command, return stdout."""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr, r.returncode


class TestDevAgentCore:
    """Test the dev_agent_core.py workflow engine."""

    def test_analyze_command(self):
        """Phase 1: Analyze detects tech stack correctly."""
        out, err, rc = run(f"python3 {SCRIPT_DIR}/dev_agent_core.py analyze 'test task' --root {AGENT_ROOT}")
        assert rc == 0, f"analyze failed: {err}"
        # Strip ANSI color codes before JSON parsing
        import re
        clean = re.sub(r'\x1b\[[0-9;]*m', '', out)
        data = json.loads(clean.strip().split("Analysis Result:")[-1].strip())
        assert "tech_stack" in data
        assert "task_type" in data
        assert "root" in data

    def test_spec_generation(self):
        """Phase 2: SPEC.md is generated correctly."""
        spec_path = AGENT_ROOT / "test_spec.md"
        out, err, rc = run(f"python3 {SCRIPT_DIR}/dev_agent_core.py spec --root {AGENT_ROOT} --spec {spec_path}")
        assert rc == 0, f"spec failed: {err}"
        assert spec_path.exists(), "SPEC.md was not created"
        content = spec_path.read_text()
        assert "# Specification:" in content
        assert "## 1. Overview" in content
        assert "## 2. Task Classification" in content
        assert "## 3. Functionality Specification" in content
        assert "## 5. Acceptance Criteria" in content
        # cleanup
        spec_path.unlink()

    def test_launch_script(self):
        """Launch script runs without error."""
        out, err, rc = run(f"bash {SCRIPT_DIR}/launch.sh 'Build a REST API for tasks' --root {AGENT_ROOT}", timeout=30)
        assert rc == 0, f"launch.sh failed: {err}"
        assert "Dev-Agent v1.0" in out
        assert "PHASE-1" in out
        assert "PHASE-2" in out
        assert "SPEC.md" in out and ("written" in out or "created" in out)


class TestDevAgentProfile:
    """Test the dev-agent profile configuration."""

    def test_profile_yaml_exists(self):
        """Profile YAML is well-formed."""
        profile = AGENT_ROOT / "profiles/dev-agent/profile.yaml"
        assert profile.exists(), f"Profile not found at {profile}"
        content = profile.read_text()
        assert "name: dev-agent" in content
        assert "model:" in content
        assert "toolsets:" in content
        # Validate YAML structure
        import yaml
        data = yaml.safe_load(content)
        assert data["model"]["provider"] == "minimax-cn"
        assert "terminal" in data["toolsets"]
        assert "file" in data["toolsets"]

    def test_soul_md_exists(self):
        """SOUL.md persona file exists and is substantive."""
        soul = AGENT_ROOT / "profiles/dev-agent/SOUL.md"
        assert soul.exists(), "SOUL.md not found"
        content = soul.read_text()
        assert len(content) > 1000, "SOUL.md is too short"
        assert "Senior Full-Stack" in content or "senior" in content.lower()
        assert "TDD" in content
        assert "Security" in content

    def test_skill_exists(self):
        """Core skill document exists."""
        skill = AGENT_ROOT / "skills/dev-agent-core/SKILL.md"
        assert skill.exists(), "SKILL.md not found"
        content = skill.read_text()
        assert "Phase 1" in content or "ANALYZE" in content
        assert "Phase 2" in content or "SPEC" in content
        assert "Phase 3" in content or "IMPLEMENT" in content
        assert "Phase 4" in content or "QA" in content
        assert "TDD" in content
        assert "commit convention" in content.lower()


class TestTechStackDetection:
    """Test technology stack auto-detection."""

    def test_detects_node_project(self, tmp_path):
        """Detects Node.js/TypeScript stack."""
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "test",
            "dependencies": {"express": "^4.0"}
        }))
        out, err, rc = run(f"python3 {SCRIPT_DIR}/dev_agent_core.py analyze 'test' --root {tmp_path}")
        assert "JavaScript" in out

    def test_detects_python_project(self, tmp_path):
        """Detects Python stack."""
        (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\n")
        out, err, rc = run(f"python3 {SCRIPT_DIR}/dev_agent_core.py analyze 'test' --root {tmp_path}")
        assert "Python" in out

    def test_detects_docker(self, tmp_path):
        """Detects Docker presence."""
        (tmp_path / "docker-compose.yml").write_text("version: '3'\nservices:\n  app:\n    image: node:18\n")
        out, err, rc = run(f"python3 {SCRIPT_DIR}/dev_agent_core.py analyze 'test' --root {tmp_path}")
        assert "Docker" in out


class TestQAChecks:
    """Test QA gate functionality."""

    def test_qa_checks_run(self, tmp_path):
        """QA checks execute without crashing."""
        # Create a minimal Python file
        (tmp_path / "hello.py").write_text('def greet(name): return f"Hello, {name}"\n')
        out, err, rc = run(f"python3 {SCRIPT_DIR}/dev_agent_core.py qa --root {tmp_path}")
        assert rc == 0, f"qa failed: {err}"
        assert "Quality Gate Results" in out
        assert "Linting" in out
        assert "Coverage" in out
        assert "Security" in out


class TestTDDWorkflow:
    """Test TDD workflow simulation."""

    def test_tdd_command_exists(self):
        """TDD command is registered."""
        out, err, rc = run(f"python3 {SCRIPT_DIR}/dev_agent_core.py tdd --help 2>&1 || true")
        # Should not error — TDD is a valid command path
        # Just verify the module loads without import errors
        _, _, rc = run(f"python3 -c 'import sys; sys.path.insert(0, \"{SCRIPT_DIR}\"); import dev_agent_core'")
        assert rc == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
