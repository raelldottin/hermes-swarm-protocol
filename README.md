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
- **`ops/migrate_fleet_memory.py`** — fleet memory migration/audit tool: maps worker
  profiles to shared per-project ByteRover trees (`memory.byterover.workdir`), roots are
  read-mostly (`auto_extract: false`), with backup/audit/recovery invariants.
- **Regression tests** pinning the four incident invariants: key preservation,
  `HERMES_HOME` pollution immunity, exact-pattern backup discovery, ambiguous-block
  refusal.

## Install

The plugin lives at `~/.hermes/plugins/swarm-protocol` (symlink to
`hermes_swarm_protocol/` in the canonical checkout):

```bash
ln -s ~/Documents/Personal/hermes-swarm-protocol/hermes_swarm_protocol ~/.hermes/plugins/swarm-protocol
# then per profile:
#   plugins.enabled: [swarm-protocol, ...]   (or: hermes plugins enable swarm-protocol)
```

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
ops/              fleet migration/audit tooling
tests/            plugin tests + migration regression tests
docs/recovery.md  fleet policy + recovery runbook (canonical)
```

See `docs/recovery.md` for the canonical fleet memory policy and the recovery rules
 distilled from the 2026-09-28 config incident.
