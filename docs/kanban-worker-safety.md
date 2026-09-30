# Kanban worker lifecycle safety

This repository carries a compatibility guard for [NousResearch/hermes-agent#129021](https://github.com/NousResearch/hermes-agent/issues/129021).

## Failure mode

Hermes Agent 0.21.5 can spawn a dispatcher-owned Kanban worker with the assignee
profile's explicit CLI toolset selection but without the `kanban` toolset. The
same worker is prohibited from mutating Kanban through the `hermes kanban` CLI.

That creates a dead end:

1. the worker finishes its actual work;
2. `kanban_complete`, `kanban_block`, `kanban_request_review`, and
   `kanban_request_changes` are absent;
3. CLI mutation is refused because the process is a delegated/dispatcher worker;
4. a model may fall back to raw SQLite mutation;
5. an off-enum value such as `tasks.status='completed'` can persist and keep
   dependent tasks gated forever because Hermes expects canonical `done`.

Hermes `main` now includes task-scoped Kanban lifecycle injection during tool
schema assembly. The compatibility layer here is kept for 0.21.5-era
installations and remains safe on newer Hermes versions.

## Guard 1: dispatcher toolset injection

When `swarm-protocol` is loaded in the dispatching Hermes process, it wraps
`hermes_cli.kanban_db_dispatch._resolve_worker_cli_toolsets`.

For every profile-scoped worker resolution it:

- preserves the profile's selected toolsets;
- adds `kanban`;
- fails closed if the profile toolsets cannot be resolved at all.

Hermes' own Kanban visibility checks still hide orchestrator-only mutations from
a dispatcher-owned worker. Adding the toolset therefore exposes the lifecycle
handoff tools the worker needs without granting general board-routing authority.

The shim is idempotent and is tagged internally so plugin reloads do not stack
wrappers.

## Guard 2: persistent task-status constraint

A dispatcher-owned worker also installs two SQLite triggers on its board before
model work starts:

- `hermes_swarm_tasks_status_insert_guard`
- `hermes_swarm_tasks_status_update_guard`

The allowed values are read from the running Hermes build's
`kanban_db.VALID_STATUSES`, rather than hard-coded into the plugin. The
triggers live in `kanban.db`, so a later raw `sqlite3` write is still
rejected even when it does not use Hermes' Python write path.

Existing invalid rows are reported and left unchanged. The plugin does not guess
how to repair durable state.

## Repairing a board that already has `status='completed'`

Audit first:

```bash
python ops/repair_kanban_status.py \
  --db ~/.hermes/kanban/boards/<board>/kanban.db
```

The command exits non-zero when it finds invalid rows. Nothing is changed.

To repair:

```bash
python ops/repair_kanban_status.py \
  --db ~/.hermes/kanban/boards/<board>/kanban.db \
  --apply
```

Automatic repair is deliberately narrow. A row is eligible only when all of the
following are true:

- the invalid value is exactly `completed`;
- `completed_at` is populated;
- `task_runs` contains a `status='done', outcome='completed'` row;
- `task_events` contains a `kind='completed'` event.

If any invalid row lacks that evidence, `--apply` refuses to modify **any**
row. When repair is allowed, the script creates a SQLite backup first and then
maps `completed -> done`.

After repair, leave the gateway running or run a dispatcher tick so dependency
promotion recomputes children against the canonical `done` status.

## Installation requirement

The plugin must be enabled in the profile/process that owns the dispatcher, not
only copied into worker profiles. Worker profiles still need the plugin enabled
for the persistent board-status guard to be installed before their model turn.

The normal installation instructions in the repository README cover both root
and named profiles.

## Removal

Once your installed Hermes release contains the upstream lifecycle injection and
a durable status constraint, this compatibility code can be removed without
changing the swarm protocol envelope or tool contracts. The safeguards are
isolated in `hermes_swarm_protocol.__init__` under the issue #129021 section.
