# Fleet Memory Policy & Recovery Runbook

Canonical policy for the Hermes worker fleet's shared ByteRover memory. The migration
tooling that enforces it lives in `ops/migrate_fleet_memory.py`; the regression tests in
`tests/test_migrate_fleet_memory.py` pin each invariant.

## Fleet policy

Workers (read-write authors):
```yaml
memory:
  memory_enabled: true
  provider: byterover
  byterover:
    workdir: <project-tree>      # ~/.hermes/byterover-projects/<project>/
    auto_extract: true
```

Root orchestrators (read-mostly coordinators):
```yaml
memory:
  memory_enabled: true
  provider: byterover
  byterover:
    workdir: <same-project-tree>
    auto_extract: false
```

`auto_extract` gates exactly the three automatic write paths (`sync_turn`,
`on_memory_write`, `on_pre_compress`). Retrieval (`brv_query`/`prefetch`) and explicit
curation (`brv_curate`) remain available to roots — read-mostly means "no automatic
authorship", not "read-only".

## Operational separation (proven live)

```text
Kanban        = work state
ByteRover     = project knowledge
workers       = automatic authors
orchestrators = read-mostly coordinators
swarm         = request / verify / route semantics
memory        = evidence, never sole verification authority
```

## Ownership map

```text
Kanban        owns task state / dependencies / worker lifecycle
ByteRover     owns shared project knowledge (per-project trees)
swarm-protocolowns request/verify/route semantics (this repo's plugin)
orchestrator  coordinates; never auto-authors project memory
```

## Migration / audit commands

```bash
# Read-only audit of every profile's memory config (blocks, workdir, policy)
python3 ops/migrate_fleet_memory.py

# Apply worker policy (read-write, auto_extract: true)
python3 ops/migrate_fleet_memory.py --apply

# Apply root policy (read-mostly, auto_extract: false)
python3 ops/migrate_fleet_memory.py --roots --apply

# Machine-readable audit
python3 ops/migrate_fleet_memory.py --json
```

## Recovery rules (from the 2026-09-28 incident)

1. **Backup identity is content, not filename.** This script writes
   `config.<YYYYMMDD-HHMMSS>.bak` — `find_backups()` matches that pattern exactly.
   Other tools write `config.yaml.pre-*.bak`, `*.snap`, `config.yaml.*.bak`. Restoring
   from a foreign backup silently rolled back GLM-5.3 model config, swarm-protocol
   enablement, and routing on 26 profiles. When recovering, verify a backup by content
   markers (model id, enabled plugins, routing tables, memory keys) before restoring.
2. **Never trust YAML last-wins.** A config with two top-level `memory:` blocks is
   ambiguous; the migration refuses it (`ambiguous-memory-blocks`) instead of writing on
   top. Resolve manually: keep the block with the correct workdir + policy, delete the
   other, re-run the audit.
3. **The fleet root is machine-global.** `~/.hermes/profiles` and
   `~/.hermes/byterover-projects` are pinned to `Path.home()` — worker sessions export
   `HERMES_HOME=<profile>` and the script must ignore it (regression-tested).
4. **A migration must preserve unknown keys.** `write_approval`, `memory_char_limit`,
   `user_char_limit`, `flush_min_turns`, `nudge_interval` survived only because they
   were re-added by hand once; the rewrite now preserves every non-policy key verbatim
   (regression-tested).
5. **After any recovery, re-run the full audit** and confirm: one `memory:` block per
   profile, correct workdir, correct `auto_extract` policy per role, model config
   intact, plugins enabled, routing present.

## ByteRover curate timeout compatibility

Hermes' bundled ByteRover provider currently uses a 120-second process timeout for every
curate. ByteRover itself defaults to a 600-second agentic task budget, so Hermes can kill a
healthy curate long before ByteRover reaches its own deadline. When the active provider is
ByteRover, swarm-protocol raises the Hermes module-level curate timeout to a 660-second floor.

The patch is intentionally monotonic: if a future Hermes release already uses a larger value,
swarm-protocol leaves it unchanged. The same provider method backs explicit `brv_curate`,
turn auto-extraction, memory mirroring, and pre-compression curation, so the floor applies to
all of those paths. It does not alter ByteRover storage, shared-tree ownership, or the
`swarm_verify` rule that memory is evidence rather than verification authority.

Override the floor per profile when ByteRover's own iteration budget is larger:

```yaml
plugins:
  entries:
    swarm-protocol:
      settings:
        byterover_curate_timeout_seconds: 1260  # e.g. 20m ByteRover budget + 60s
```

Keep the Hermes floor at least `llm.iterationBudgetMs / 1000 + 60`. Accepted values are
120–7200 seconds. In a multiplexed gateway the effective module timeout is process-wide and
monotonic, so a profile may raise the floor but cannot shorten a sibling profile's deadline.

## Known operational facts

- The four shared trees: `~/.hermes/byterover-projects/{opnory,alepes,tachikoma,tunory}`.
- brv extraction model must be a reliable tool-caller; `z-ai/glm-5.3` verified,
  `nemotron-3-super-120b-a12b` produced empty responses / zero-op curations.
- Deep (T3) brv queries take 17–128 s; the Hermes provider's 10 s query timeout surfaces
  them as `MEMORY_TIMEOUT` — by design: the verifier proceeds on live evidence or returns
  `inconclusive`.
- 169 pre-existing pending review operations in the main tree
  (`~/.hermes/byterover`) are a separate maintenance task, untouched by this migration.
