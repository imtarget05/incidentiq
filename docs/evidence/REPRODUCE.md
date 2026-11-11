# Reproducing local checks and collecting evidence

Supported minor runtimes: Node 22 (`.nvmrc`), Enterprise Python 3.12 + Java 17; IncidentIQ Python 3.13. Use Node22 before `npm ci`; lockfiles pin Node dependencies. `uv==0.12.0` is used in IncidentIQ CI. The host observed during initial work was Node26, Python3.15 and Java17; don't mistake host output for pinned-runtime results.

From the repository root:

```sh
python3 scripts/jd.py setup --node
python3 scripts/jd.py test
python3 scripts/jd.py collect --suite all
python3 scripts/jd.py build
```

`setup` creates isolated service Python environments and syncs locked dependencies; Node installation requires `--node`. It does not download models, launch cloud resources or configure secrets. Enterprise agent uses a separate `agent/.venv-jd` so the pre-existing `.venv` is preserved. Enterprise agent installation includes ML dependencies and may be large. Pinned-minor checks reject a mismatched existing Enterprise environment instead of silently reusing it. Do not put user files inside virtual environments. IncidentIQ uv sync may recreate its .venv.

Use `--suite agent|router|backend|frontend` in Enterprise or `--suite api|mcp|typecheck` in IncidentIQ for a focused check. Python suites run through the environment's interpreter with `-I`, disabled third-party plugin auto-discovery and explicit asyncio plugin. This prevents global pytest executables/PYTHONPATH/user site plugins from contaminating results.

Enterprise `up` starts only the existing local infrastructure Compose file; Docker daemon must be available. IncidentIQ `up` exits 2 and explains the binding-dependent Wrangler workflow rather than pretending it created a complete environment. `benchmark` currently exits 2: live benchmark acceptance is pending in the backlog. These non-success states are deliberate and must not be reported as completed capabilities.

`collect` runs selected suites and writes private `artifacts/jd/*.json`, preserving failing exit status. JSON records UTC time, HEAD before/after, changed file names, tracked diff fingerprint, commands/exit codes, runtime probes and concurrent-change warning. Logs remain console output; retain/redact raw output separately when publishing evidence. It never dumps environment variables or credentials. Untracked contents are not fingerprinted. A dirty-tree run is not proof for clean HEAD or hosted CI.

Review and redact evidence before moving it to reviewed documentation. Record cloud runs separately with environment, deployment revision, dataset version, configuration, cost window and limits. Never turn fixture scores into live quality claims. Standard build/test commands do not establish production readiness.

Refresh Python lockfiles intentionally after dependency changes; review the lock diff and rerun affected suites. Enterprise: `uv pip compile <service>/requirements[-dev].txt --python-version 3.12 --output-file <service>/requirements.lock`; router uses requirements-dev.txt, agent requirements.txt. IncidentIQ: `uv lock` then `uv sync --locked --python 3.13`.
