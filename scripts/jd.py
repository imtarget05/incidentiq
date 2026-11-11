#!/usr/bin/env python3
"""Reproducible local checks and revision-bound evidence, without cloud writes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENTERPRISE = (ROOT / "backend/pom.xml").exists()

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

def commands():
    if ENTERPRISE:
        return {
            "agent": ([str(ROOT / "agent/.venv-jd/bin/python"), "-I", "-m", "pytest", "agent/tests", "tests", "-q", "-m", "not integration and not slow"], ROOT),
            "router": ([str(ROOT / "llm-router/.venv/bin/python"), "-I", "-m", "pytest", "tests", "-q"], ROOT / "llm-router"),
            "backend": (["mvn", "-B", "test"], ROOT / "backend"),
            "frontend": (["npm", "run", "test:coverage"], ROOT / "frontend"),
        }
    return {
        "api": ([str(ROOT / ".venv/bin/python"), "-I", "-m", "pytest", "tests/api", "-q"], ROOT),
        "mcp": (["npm", "test", "--", "--run"], ROOT / "mcp"),
        "typecheck": (["npm", "run", "typecheck"], ROOT / "mcp"),
    }

def run(command, cwd=ROOT):
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    # Explicit plugin loading prevents globally installed pytest plugins leaking in.
    if "pytest" in command:
        command = list(command) + ["-p", "pytest_asyncio.plugin"]
    try:
        return subprocess.run(command, cwd=cwd, env=env, check=False, timeout=1800).returncode
    except subprocess.TimeoutExpired:
        print("Command exceeded 1800 second limit", file=sys.stderr)
        return 124

def setup(node):
    if ENTERPRISE:
        for service in ("agent", "llm-router"):
            directory = ROOT / service
            environment = directory / (".venv-jd" if service == "agent" else ".venv")
            interpreter = environment / "bin/python"
            if interpreter.exists():
                version = subprocess.check_output([str(interpreter), "-I", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"], text=True, timeout=10).strip()
                if version != "3.12":
                    print(f"{environment} uses Python {version}; move it aside explicitly before setup", file=sys.stderr)
                    return 2
            result = run(["uv", "venv", "--allow-existing", "--python", "3.12", str(environment)])
            if result:
                return result
            result = run(["uv", "pip", "sync", "--python", str(environment / "bin/python"), str(directory / "requirements.lock")])
            if result:
                return result
    else:
        result = run(["uv", "sync", "--locked", "--python", "3.13"])
        if result:
            return result
    if node:
        for directory in ([ROOT / "frontend"] if ENTERPRISE else [ROOT / "mcp"]):
            result = run(["npm", "ci"], directory)
            if result:
                return result
    return 0

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "test", "collect", "build", "up", "benchmark"])
    parser.add_argument("--suite", choices=["all", *commands()], default="all")
    parser.add_argument("--node", action="store_true", help="also install Node dependencies during setup")
    parser.add_argument("--output", type=Path, help="JSON evidence output; default artifacts/jd/<UTC>.json")
    args = parser.parse_args()
    if args.action == "setup":
        return setup(args.node)
    if args.action == "build":
        suites = [(["mvn", "-B", "-DskipTests", "package"], ROOT / "backend"), (["npm", "run", "build"], ROOT / "frontend")] if ENTERPRISE else [commands()["typecheck"]]
        for command, cwd in suites:
            result = run(command, cwd)
            if result:
                return result
        return 0
    if args.action == "up":
        if ENTERPRISE:
            return run(["docker", "compose", "-f", "docker/docker-compose.local.yml", "up", "-d"])
        print("IncidentIQ local runtime requires configured bindings. Use mcp/node_modules/.bin/wrangler dev; this command does not create cloud resources.", file=sys.stderr)
        return 2
    if args.action == "benchmark":
        print("Live benchmark is not yet accepted. See tasks/todo.md; no synthetic results will be labelled live.", file=sys.stderr)
        return 2
    runtime = {"collector_executable": sys.executable, "collector_python": sys.version}
    probes = {"node": ["node", "--version"], "java": ["java", "-version"], "uv": ["uv", "--version"]}
    for name, (command, _) in commands().items():
        if "pytest" in command:
            probes[name + "_python"] = [command[0], "-I", "-c", "import sys,pytest; print(sys.executable); print(sys.version); print(pytest.__file__)"]
    for name, command in probes.items():
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
            runtime[name] = {"exit_code": result.returncode, "output": (result.stdout + result.stderr).strip()}
        except (OSError, subprocess.TimeoutExpired) as exc:
            runtime[name] = {"error": str(exc)}
    started = datetime.now(timezone.utc).isoformat()
    before = git("rev-parse", "HEAD")
    status_before = git("status", "--porcelain=v1")
    patch_hash = hashlib.sha256(subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)).hexdigest()
    results = []
    for name, (command, cwd) in commands().items():
        if args.suite not in ("all", name):
            continue
        try:
            code = run(command, cwd)
            error = None
        except FileNotFoundError as exc:
            code, error = 127, str(exc)
        results.append({"suite": name, "command": command, "exit_code": code, "error": error})
    if args.action == "collect":
        after = git("rev-parse", "HEAD")
        status_after = git("status", "--porcelain=v1")
        evidence = {"schema_version": 1, "project": "enterprise" if ENTERPRISE else "incidentiq", "tier": "local", "runtime": runtime, "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(), "revision_before": before, "revision_after": after, "tracked_diff_sha256_before": patch_hash, "working_tree_before": status_before.splitlines(), "working_tree_after": status_after.splitlines(), "concurrent_changes_detected": before != after or status_before != status_after or patch_hash != hashlib.sha256(subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)).hexdigest(), "results": results, "limitations": ["Local checks only; not hosted CI, cloud, uptime, cost or RAG quality evidence.", "Untracked file names are recorded but their contents are not included in the tracked diff hash.", "Review and redact artifacts before publication; never collect environment variables or credentials."]}
        output = args.output or ROOT / "artifacts/jd" / (started.replace(":", "-") + ".json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2) + "\n")
        print(f"Evidence: {output}")
    return 1 if any(item["exit_code"] for item in results) else 0

if __name__ == "__main__":
    sys.exit(main())
