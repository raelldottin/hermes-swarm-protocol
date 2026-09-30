# hermes-swarm-protocol

Swarm coordination semantics for [Hermes Agent](https://hermes-agent.nousresearch.com/)
fleets: a thin protocol layer over Hermes Kanban (work state) and ByteRover (shared
project knowledge). No new storage, no daemon, no networking — Kanban cards and
comments are the durable state.

```text
Kanban        = work state
ByteRover     = project knowledge
workers       = automatic authors
orchestrators = read-mostly coordinators
swarm         = request / verify / route semantics
memory        = evidence, never sole verification authority
```

## What it provides

- **`swarm-protocol`** — a Hermes user plugin registering three tools (toolset `swarm`):
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
- **Hermes #129021 safety guard** — dispatcher workers are guaranteed the `kanban`
  lifecycle toolset even when their profile omits it, and worker boards receive persistent
  SQLite triggers that reject off-enum task statuses before a raw write can corrupt dependency
  gating. See `docs/kanban-worker-safety.md`.
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
`swarm` toolset. Keep the plugin enabled in the profile/process that owns the dispatcher as
well: the Hermes 0.21.5 compatibility guard is installed there before workers are spawned.

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
