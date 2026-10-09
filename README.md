# hermes-swarm-protocol

Swarm Wiki is deployed to all eight existing project boards and 43 identities.
See the [fleet rollout results](docs/swarm-wiki-fleet-rollout.md) and
[acceptance receipts](docs/swarm-wiki-fleet-acceptance.json) for the tested
immutable release, live canaries and retained historical source findings.

Swarm coordination semantics for [Hermes Agent](https://hermes-agent.nousresearch.com/)
fleets: a thin protocol layer over Hermes Kanban (work state) and ByteRover (shared
project knowledge), with a generated Swarm Wiki for readable knowledge and audit.
No new coordination datastore, daemon or networking: Kanban cards/comments remain
canonical, original evidence is immutable, and wiki pages are disposable.

```text
Kanban        = work state
ByteRover     = project knowledge
workers       = automatic authors
orchestrators = read-mostly coordinators
swarm         = request / verify / route semantics
memory        = evidence, never sole verification authority
wiki          = generated knowledge / human audit projection
```

## What it provides

- **`swarm-protocol`** — a Hermes user plugin registering five tools (toolset `swarm`):
  - `swarm_request` — create a linked Kanban card carrying a `hermes-swarm/v1` envelope;
    identity comes from the runtime profile, never from tool args (anti-spoofing).
  - `swarm_verify` — two-phase independent verification. `inspect` normalizes ByteRover
    outcomes into `MEMORY_AVAILABLE / MEMORY_EMPTY / MEMORY_TIMEOUT / MEMORY_ERROR`;
    `commit` refuses `pass` without non-memory **live evidence** (test output, git
    commit/diff, file inspection, runtime result). Verdicts: `pass / fail / inconclusive /
    blocked`.
  - `swarm_route` — deterministic config-driven routing (`plugins.entries.swarm-protocol
    .settings.projects.<project>.<role>`); unknown project/role → `ROUTE_UNRESOLVED`,
    never a guess.
- **ByteRover curate timeout compatibility** — when ByteRover is active, raises Hermes'
  hard-coded curate timeout floor from 120 seconds to 660 seconds by default, without lowering
  a larger future upstream value. This covers explicit `brv_curate` and ByteRover's automatic
  curation paths while leaving the shared project trees unchanged.
- **Hermes #129021 status-integrity guard** — worker boards receive persistent SQLite triggers
  that reject off-enum task statuses before a raw write can corrupt dependency gating. Current
  Hermes already injects dispatcher-worker lifecycle tools; this repository does not override
  that upstream behavior. See `docs/kanban-worker-safety.md`.
- **`ops/repair_kanban_status.py`** — audit-first recovery for boards already containing the
  incident's `status='completed'`; `--apply` backs up the DB and repairs only rows with matching
  completion evidence.
- **`ops/migrate_fleet_memory.py`** — fleet memory migration/audit tool: maps worker
  profiles to shared per-project ByteRover trees (`memory.byterover.workdir`), roots are
  read-mostly (`auto_extract: false`), with backup/audit/recovery invariants.
- **Regression tests** pinning the four incident invariants: key preservation,
  `HERMES_HOME` pollution immunity, exact-pattern backup discovery, ambiguous-block
  refusal.

## Install

Clone the repository wherever you keep source checkouts. The plugin path is derived from
the checkout itself; no specific directory such as `~/Documents/Personal` is required.

```bash
git clone https://github.com/raelldottin/hermes-swarm-protocol.git
cd hermes-swarm-protocol

PLUGIN_SRC="$(pwd)/hermes_swarm_protocol"

mkdir -p "$HOME/.hermes/plugins"
ln -sfn "$PLUGIN_SRC" "$HOME/.hermes/plugins/swarm-protocol"

hermes plugins enable swarm-protocol
```

If you use named Hermes profiles, make the same plugin available inside each profile
and enable it there:

```bash
PROFILE="<profile-name>"

mkdir -p "$HOME/.hermes/profiles/$PROFILE/plugins"
ln -sfn "$PLUGIN_SRC" "$HOME/.hermes/profiles/$PROFILE/plugins/swarm-protocol"

hermes -p "$PROFILE" plugins enable swarm-protocol
```

Repeat the profile block for each worker or orchestrator profile that should expose the
`swarm` toolset. Worker profiles that should install the status-integrity guard must have the
plugin enabled so the board trigger is created before model work begins.

Routing config (per profile):
```yaml
plugins:
  entries:
    swarm-protocol:
      settings:
        projects:
          opnory:
            verification: opnory-verifier
            builder: opnory-builder
```

ByteRover curate timeout (optional; default is 660 seconds):
```yaml
plugins:
  entries:
    swarm-protocol:
      settings:
        byterover_curate_timeout_seconds: 660
```

Set the floor to at least ByteRover's `llm.iterationBudgetMs / 1000 + 60` when you
increase ByteRover's task budget. The compatibility patch clamps values to 120–7200
seconds and only ever raises Hermes' current timeout; it never lowers an upstream value.

## Test

```bash
python -m pytest tests/ -q
```

`tests/test_swarm_protocol.py` runs the plugin through real Hermes discovery and
Kanban paths (needs the Hermes source tree importable); set
`SWARM_PROTOCOL_PLUGIN_DIR` to point at a non-default plugin location.

## Repository layout

```text
hermes_swarm_protocol/   plugin (plugin.yaml + __init__.py) — the loadable unit
ops/              fleet migration/audit tooling + guarded Kanban status repair
tests/            plugin tests + migration regression tests
docs/recovery.md  fleet policy + recovery runbook (canonical)
docs/kanban-worker-safety.md  Hermes #129021 compatibility + repair runbook
```

See `docs/kanban-worker-safety.md` for the worker terminal-path/status-integrity guard.
See `docs/recovery.md` for the canonical fleet memory policy and the recovery rules
distilled from the 2026-09-28 config incident.

## Swarm Wiki

Plugin v1.2 is deployed with compatible v1/v2 publications. The latest recorded
pilot check has zero unresolved findings while retaining explicit historical
unknowns. See [delivery and integration evidence](docs/swarm-wiki-delivery.md)
and the [source finding register](docs/swarm-wiki-audit-findings.json).
Repeat source preflight before rollout; delayed ByteRover index writes can
reopen findings after an earlier successful check.

`swarm_capture` preserves original workspace files as immutable, hashed evidence.
`swarm_publish` records authenticated claims, scoped verification, contradictions,
reconciliations, decisions, consequences, routes and accepted ByteRover synthesis
in Kanban comments. Neither tool edits generated pages.

`ops/build_wiki.py` reads canonical sources, renders index/digest/topic/history
pages, lints uncertainty and provenance, and atomically publishes a generation.
`--check` compares all bytes without changing output. Existing request/verify/route
semantics remain compatible.

See [operations and payloads](docs/swarm-wiki-usage.md),
[design contract](docs/swarm-wiki-design.md),
[maintenance rules](docs/SWARM_WIKI.md), and
[research, plan and QA evidence](docs/swarm-wiki-implementation.md).

Run tests with the installed Hermes virtualenv, this checkout's plugin path and
inherited Kanban routing pins removed, as shown in the design contract. Generated
wiki output is not proof that its underlying claims have passed verification.
