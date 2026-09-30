# Kanban worker lifecycle safety

This repository carries a compatibility guard for [NousResearch/hermes-agent#129021](https://github.com/NousResearch/hermes-agent/issues/129021).

## What upstream verification established

Current Hermes `main` (`f42f579cf8`) already guarantees task-scoped Kanban lifecycle
tools for dispatcher-owned workers. `_select_tool_names` force-adds the `kanban`
toolset when `HERMES_KANBAN_TASK` is present and the process is a dispatcher-owned
worker. The same selection feeds the normal tool schema and `tool_search` catalog.

The upstream maintainer traced that behavior to commits `3f7c2adea4f` and
`4666479e709` from September 2, 2026, before the 0.21.4 and 0.21.5 releases.
Accordingly, this plugin no longer carries a worker-toolset compatibility shim.
The incident's reported version may have come from a stale clone/tag while older
code was actually running, consistent with the separate version-reporting issue
NousResearch/hermes-agent#129003.

The independent failure that remains worth preventing is durable state corruption:
a raw SQLite write can persist an off-enum value such as `tasks.status='completed'`,
while dependency promotion recognizes canonical statuses such as `done`.

## Persistent task-status constraint

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

Worker profiles need the plugin enabled for the persistent board-status guard to
be installed before their model turn. No dispatcher monkey patch is required.

The normal installation instructions in the repository README cover named profiles.

## Removal

Once Hermes itself enforces the task-status enum at the schema or write boundary,
this defense-in-depth trigger and repair helper can be removed without changing
the swarm protocol envelope or model-facing tool contracts.
