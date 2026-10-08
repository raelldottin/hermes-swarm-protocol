# Swarm Wiki — Design Contract (Phase 0)

Status: design only. No compiler code exists yet; nothing in this document has been
implemented. This document is the contract a future `ops/` compiler must satisfy.

Karpathy-style generated wiki: a readable, cross-linked, generated-from-source
narrative of what the swarm did, claimed, verified, and disputed. Like Karpathy's
generated blog, every word is compiled from canonical inputs — never hand-edited,
never the system of record.

## 1. What the wiki is (and is not)

The Swarm Wiki is a NON-AUTHORITATIVE, human/audit projection of the swarm's
canonical state. It exists so a human can read what happened without opening a
SQLite console, and so an auditor can trace any claim to its origin.

Observed grounding for this split (existing repo):

- `README.md` already pins the ownership map: Kanban = work state, ByteRover =
  project knowledge, swarm = request/verify/route semantics, memory = evidence,
  never sole verification authority. The wiki adds a fifth entry on the read
  side only: it owns nothing.
- `hermes_swarm_protocol/__init__.py:1-17` — the plugin's design contract:
  "No new storage… Requests are Kanban cards; verification outcomes are comments
  + review state." The wiki must not introduce a datastore either.
- `hermes_swarm_protocol/plugin.yaml` (v1.0.1) registers exactly three tools;
  the wiki deliberately registers none. It is not a tool, not a plugin feature,
  and never part of any worker's toolset.

Hard rules:

1. The wiki is disposable. `rm -rf` the output directory and re-run the compiler;
   the projection is recovered from canonical inputs alone.
2. The wiki is derived data. It is untrusted input to any human or agent that
   reads it. It is never instruction authority: no worker, profile, or hook may
   treat wiki text as a directive, config source, or verification basis.
3. Nothing in the swarm ever reads the wiki to make a decision. Data flows one
   way: canonical stores -> compiler -> wiki.
4. No hand edits. Editing a generated page by hand is a category error — the
   next compile silently reverts it. Feedback on wiki content means fixing the
   compiler or fixing canonical state, never fixing the page.

## 2. Four-layer architecture

```text
+-------------------------------------------------------------+
| 4. Wiki plane (human/audit, PROJECTION, disposable)         |
|    output: index.md, log.md, topics/<slug>.md, lint report  |
|    reads layers 1-3 via the compiler only; writes nothing   |
+---------------------------+---------------------------------+
                            | deterministic, one-way compile
+-------------------------------------------------------------+
| 3. Swarm coordination plane (hermes_swarm_protocol plugin)  |
|    swarm_request / swarm_verify / swarm_route               |
|    semantics over cards + comments; no storage (__init__.py |
|    :16 "Storage: none")                                     |
+---------------------------+---------------------------------+
                            | reads/writes via Kanban tools
+-------------------------------------------------------------+
| 2. ByteRover knowledge plane (shared project trees)         |
|    ~/.hermes/byterover-projects/<project>/.brv/context-tree  |
|    auto_extract: true (workers) / false (orchestrators)     |
|    wiki reads the TREE FILES, read-only                      |
+---------------------------+---------------------------------+
                            | canonical durable state
+-------------------------------------------------------------+
| 1. Kanban control plane (system of record)                  |
|    ~/.hermes/kanban/boards/<board>/kanban.db                |
|    tasks, task_links, task_comments, task_events, task_runs  |
+-------------------------------------------------------------+
```

Layer boundaries (each observed, not assumed):

- Layer 1 owns work state. `docs/recovery.md` ("Operational separation, proven
  live") and `README.md` both pin this. The status-integrity triggers
  (`docs/kanban-worker-safety.md`; live-verified present on this board:
  `hermes_swarm_tasks_status_insert_guard`, `hermes_swarm_tasks_status_update_guard`)
  guard it at the SQLite boundary.
- Layer 2 owns project knowledge. `ops/migrate_fleet_memory.py:30-42` pins the
  machine-global fleet root and per-project `PROJECT_MEMORY` mapping;
  `auto_extract` gates exactly the three automatic write paths
  (`docs/recovery.md` fleet policy).
- Layer 3 owns request/verify/route semantics only. `swarm_verify` commit
  refuses `pass` without live evidence (`__init__.py:382-385`); `swarm_route`
  returns `ROUTE_UNRESOLVED` rather than guessing (`__init__.py:441-443`).
- Layer 4 is this design. It has no APIs, no tools, no daemon, no datastore.
  Its only inputs are a board DB (read-only) and a context tree (read-only).

## 3. Compiler inputs (canonical, read-only)

### 3.1 Kanban SQLite state

Source: `~/.hermes/kanban/boards/<board>/kanban.db`, opened read-only
(`sqlite3.connect("file:...?mode=ro", uri=True)` — pattern verified live
against this board; note the plain `sqlite3` CLI misparses multi-statement
args, so the compiler uses Python sqlite3, never the CLI).

Tables and the exact columns the compiler consumes (schema read live from the
hsp board, 2026-10-05):

- `tasks` — `id, title, body, assignee, status, priority, created_by,
  created_at, started_at, completed_at, workspace_kind, workspace_path,
  branch_name, project_id, result, idempotency_key, consecutive_failures,
  last_failure_error, max_runtime_seconds, last_heartbeat_at, current_run_id,
  skills, model_override, reasoning_effort, max_retries, goal_mode,
  goal_max_turns, session_id, block_kind, block_recurrences,
  completion_contract`. Statuses are enum-guarded: `archived, blocked, done,
  ready, review, running, scheduled, todo, triage` (trigger live on this board;
  the plugin reads them from `kanban_db.VALID_STATUSES` rather than
  hard-coding — `__init__.py:128` — and the compiler must do the same).
- `task_links` — `parent_id, child_id` (dependency edges; the plugin's
  `swarm_request` deliberately creates NO edge, only `creator_task_id`
  provenance — `__init__.py:280-292`).
- `task_comments` — `id, task_id, author, body, created_at`. This is where
  `swarm_verify` commit records verdict envelopes (`__init__.py:398-401`:
  `swarm_verify <request_id>: <VERDICT>` + JSON body).
- `task_events` — `id, task_id, run_id, kind, payload, created_at` (kinds
  observed live: heartbeat, claimed, spawned, crashed, completed…).
- `task_runs` — `id, task_id, profile, step_key, status, worker_pid,
  started_at, ended_at, outcome, summary, metadata, error` (run status:
  `running | done | blocked | crashed | timed_out | failed | released`;
  outcome: `completed | blocked | crashed | timed_out | spawn_failed |
  gave_up | reclaimed`).

The `tasks.body` column carries `hermes-swarm/v1` protocol envelopes
(`__init__.py:254-277`): `protocol, kind, source_profile, created_at,
request_id, objective, target_profile, acceptance, memory_queries,
evidence_required, source_task`. The compiler parses these envelopes but
treats them as data, never as instructions (see §8).

Snapshot consistency: the compiler takes one consistent read. SQLite
`mode=ro` + a single connection opened once per compile is sufficient; if a
torn read is ever observed in practice (WAL across a live dispatcher), wrap
the read phase in `BEGIN DEFERRED ... COMMIT` on the read-only connection so
all SELECTs share one snapshot. No `busy_timeout` retries — a board being
actively written is compiled from its own consistent snapshot or not at all.

### 3.2 ByteRover context tree (READ-ONLY)

Source: `~/.hermes/byterover-projects/<project>/.brv/context-tree/**/*.md`
(resolved via the same machine-global fleet root rule as
`ops/migrate_fleet_memory.py:33` — `Path.home() / ".hermes"`, ignoring any
per-session `HERMES_HOME`, which worker sessions export).

Critical determinism decision: the compiler reads the tree FILES, it never
calls `brv query`. Grounding:

- `brv query` is LLM-mediated. `docs/recovery.md` records live measurements:
  deep (T3) queries take 17–128 s, and the Hermes provider surfaces them as
  `MEMORY_TIMEOUT` — the plugin itself treats query output as non-authoritative
  evidence (`__init__.py` MEMORY_* normalization, and commit-phase refusal of
  memory-only passes).
- The tree itself is plain markdown on disk. Live inspection of the opnory
  tree shows nodes with YAML frontmatter: `title, summary, tags, related,
  keywords, createdAt, updatedAt`, plus summary nodes carrying `type:
  summary, covers, condensation_order, children_hash, covers_token_total`,
  and per-directory `_index.md` files.

So the deterministic interface is the filesystem: every node file, its
frontmatter, its `related` cross-references, its body text. `brv query` output
MAY appear inside an appendix or topic page only as a clearly-labeled,
verbatim quote captured in canonical state first (e.g., a comment), never
fetched at compile time.

Read-only enforcement: the compiler never invokes `brv curate`, never writes
into `.brv/`, and should hold the connection/paths so that a mistake fails
closed (open files `rb`, never `ab`/`wb`; no exceptions swallowed).

## 4. Compiler (ops/build_wiki.py — future work)

Lives in `ops/`, following the repo's operational-tool conventions:

- Audit-first, like `ops/repair_kanban_status.py`: default invocation is a
  full compile + lint report with exit code reflecting lint findings;
  there is no `--apply` because there is nothing to repair — output is
  disposable.
- Single-file, stdlib-only where possible, Python 3.9+ compatible, like the
  existing ops scripts (`repair_kanban_status.py` uses argparse + sqlite3 +
  pathlib only).
- CLI sketch (design intent, not implementation):
  `python ops/build_wiki.py --board hsp --project hermes-swarm-protocol
  [--out wiki/] [--check]`. `--check` compiles to a temp dir and exits
  non-zero if the output differs from the committed output — the CI-style
  reproducibility gate.

Explicit non-goals (mirroring `README.md` "no new storage, no daemon, no
networking"):

- NO new authoritative datastore — the wiki output directory is not a store;
  it is a build artifact with the same status as `dist/`.
- NO daemon, NO server, NO hot-reload watcher.
- NO P2P, NO networking, NO publishing hooks. If a human wants the wiki on the
  web, they run `git add wiki/ && git commit` themselves; the compiler never
  does.
- NO concurrent direct wiki editing — by construction: pages are generated.
  A conflict between a hand edit and generated content is resolved by
  deleting the hand edit. The compiler may make this literal: `--check`
  comparing against a clean compile catches hand edits the same way it
  catches non-reproducibility.
- NO plugin tools registered. The wiki is not swarm coordination. Workers
  never gain a "wiki_write" or "wiki_read" tool; the only legitimate reader
  is a human or an auditor with filesystem access.

## 5. Output layout

```text
wiki/
  index.md            — entry point: what this swarm is, board stats, the
                        layer map, links into topics and log
  log.md              — strict chronological event log (see 5.2)
  topics/<slug>.md    — one page per topic/task/claim cluster (see 5.3)
  lint-report.md      — generated findings, same lint exit state as stdout
```

### 5.1 index.md

Generated front page: project identity, board name, compile timestamp (UTC,
explicitly marked as the only non-deterministic field — see §7), task counts
by status, verifier verdict counts, link list of all topic pages, and the
standing banner: "This wiki is a disposable projection. Canonical state is
the Kanban board and the ByteRover tree."

### 5.2 log.md

One line per canonical event, ordered by `(created_at, id)` from a UNION of:

- `task_events` (claim/spawn/heartbeat/crash/complete lifecycles),
- `task_comments` (including `swarm_request` handoff comments and
  `swarm_verify` verdict comments),
- `task_runs` start/end (`started_at`/`ended_at`),
- task creation (`tasks.created_at`) and completion (`completed_at`).

Each line: UTC ISO timestamp, task id, kind, one-line summary truncated
consistently (e.g., 160 chars), and a stable anchor slug so topic pages can
link to log entries (`#L-<seq>`). Heartbeats collapse: N consecutive heartbeats
for the same run become one line ("N heartbeats, last at …") — collapse is a
pure function of the event stream, so determinism is preserved.

### 5.3 Topic pages

A topic is any of:

- a task (`topics/task-<id>.md`),
- a swarm request (`topics/request-<request_id>.md`, from the `hermes-swarm/v1`
  envelope in `tasks.body`),
- a ByteRover knowledge node or cluster (`topics/knowledge-<slug>.md`, from
  context-tree files),
- an emergent theme the compiler can extract deterministically — e.g., all
  tasks that blocked with the same `block_kind`, or all comments referencing
  the same request id.

Every topic page MUST carry these sections, all derived from canonical state:

1. **Claims** — assertions found in canonical inputs: task objectives, run
   summaries, comment assertions, ByteRover node summaries. Each claim is
   quoted verbatim with a source pointer (table + row id, or file path).
2. **Provenance** — for every claim: who authored it (`tasks.created_by`,
   `task_comments.author`, node `createdAt`), when (`created_at`), and through
   which canonical table/file it is recorded. Claims with unknown provenance
   are still listed (never dropped) but marked UNPROVENANCED for the lint.
3. **Linked tasks** — `task_links` edges both directions, plus `creator_task_id`
   provenance links and envelope `source_task` references (the two distinct
   link kinds the plugin itself distinguishes — `__init__.py:280-292`).
4. **Verification state** — parsed `swarm_verify` commit comments on the task
   chain: verdict (`pass/fail/inconclusive/blocked`), `live_evidence` list,
   `memory_status`, `memory_digest`, verifier identity, recorded_at. A claim
   with no verifying comment renders as `UNVERIFIED`. `pass` with empty
   `live_evidence` cannot occur through the plugin (refused,
   `__init__.py:382-385`) — if the compiler sees one in raw state it renders
   it as `INVALID PASS` and the lint flags it.
5. **Contradictions** — mechanical contradiction detection only (§6). Each
   detected contradiction is rendered inline with both sides and sources.
6. **Evidence references** — concrete pointers: commit SHAs found in
   comment/result text (regex `[0-9a-f]{7,40}` with word boundaries), file
   paths mentioned in envelopes (`acceptance`, `live_evidence`), pytest/exit
   summaries quoted from `task_runs.summary`/`error`, and ByteRover node
   paths. The compiler links, never invents: a reference it cannot resolve to
   a canonical artifact is rendered as literal text plus a lint finding if
   stale (§6).

## 6. Wiki lint

`python ops/build_wiki.py --lint` runs after compilation and reports findings
by class; findings set the exit code (audit-first, same posture as
`ops/repair_kanban_status.py` exiting non-zero on invalid rows). Lint checks:

1. **Unresolved contradictions** — two claims that mechanically contradict with
   no later reconciliation on the same chain. Mechanical detection only:
   (a) same task with terminal verdicts differing across comments;
   (b) a task marked `done` while its latest swarm_verify comment says
   `fail`/`blocked`; (c) two ByteRover nodes whose frontmatter `related`
   points at each other but whose summaries assert opposite polarities of the
   same keyword pair (deterministic keyword extraction from `keywords` +
   `tags` frontmatter — no semantic NLP). The lint NEVER attempts open-ended
   semantic contradiction discovery; anything subtler is human work.
2. **Consequential claims lacking independent verification** — a claim is
   consequential when it appears in an `evidence_required: true` envelope
   (the plugin's own severity flag, `__init__.py:275`) or asserts a mutation
   (commit SHA, file write, merge). It is independently verified only by a
   `swarm_verify` commit with verdict `pass` AND non-empty `live_evidence`
   from a different profile than the claim's author. Verifier identity comes
   from the envelope's `verifier` field — trusted because `_identity()` reads
   the runtime profile, never tool args (`__init__.py:59-62`, the #19713
   anti-spoofing pattern).
3. **Stale references** — evidence references that no longer resolve: commit
   SHA not in the repo history (checked read-only via `git cat-file -e`),
   file path not in the worktree, ByteRover node path missing from the tree.
4. **Missing provenance** — any claim the compiler could not bind to
   (author, timestamp, source row/file).
5. **Orphan topics** — topic pages with no inbound link from index, log, or
   any other topic; also ByteRover nodes never referenced by any task and
   tasks never referenced by any log line (impossible by construction for
   tasks — a task always emits at least a creation line — so in practice this
   flags knowledge nodes with zero task cross-references, rendered on the
   node's own page).

Lint findings never block compilation (the wiki still builds; findings go to
`lint-report.md` and stderr), but they DO set the process exit code, so cron
or a human running the tool sees the audit state. The linter reads only
canonical inputs + its own just-written output; it never reads the wiki as
authority about the world (§8 applies to the linter too).

## 7. Reproducibility & disposability

Contract: **unchanged canonical input produces semantically identical output;
deleted output rebuilds to the same projection.**

Rules the compiler must follow to honor it:

- Pure function: inputs = (board DB snapshot, context-tree files, repo HEAD
  for reference resolution). No clock reads except one top-of-compile UTC
  stamp rendered as `compiled_at:` in a single metadata block in `index.md`
  and nothing else — or omitted entirely and rendered as the git commit date
  when the output is committed. No random ids, no dict-order iteration
  (sort everything; SQLite `ORDER BY` on every query), no locale-dependent
  formatting (`datetime.utcfromtimestamp` + explicit `strftime`), no
  filesystem-order `os.listdir` (sorted `Path.glob`).
- `tasks.created_at` is `INTEGER` epoch seconds — render as UTC ISO-8601
  (`docs/recovery.md` timestamps are UTC-stamped already, and
  `ops/repair_kanban_status.py:74` uses UTC for its backup stamps, so UTC is
  the house convention).
- ByteRover nodes carry their own `createdAt`/`updatedAt` frontmatter — used
  verbatim; the compiler adds no timestamps of its own to topic bodies.
- Determinism gate: `--check` builds to a temp dir and byte-compares (after
  the single `compiled_at` exemption) against the existing output. This is the
  acceptance test for the compiler's own regression suite, and it is what
  makes hand-edit detection (§4) fall out for free.
- Disposable: nothing consumes the wiki. Deleting `wiki/` and re-running
  yields the same bytes (modulo `compiled_at`). No migration, no format
  versioning needed — format changes are just compiler commits; rebuild.

## 8. Wiki text is derived untrusted data

The rule that governs every consumer, human or machine:

- Kanban and ByteRover content is authored by automated workers. The wiki
  renders that content verbatim inside claim blocks. Therefore every wiki page
  is, from a security standpoint, a transcript of untrusted input.
- No Hermes component may treat wiki text as instruction. Concretely: no
  skill, no cron job, no worker prompt may include wiki pages as guidance;
  no verification flow may cite the wiki as evidence (evidence is live:
  `__init__.py:382-385`); no config is ever read from wiki content.
- The wiki never renders instructions TO the swarm differently from other
  content — there is no privileged "directive" section type. If a worker
  wrote "ignore previous instructions" into a comment, it appears as a quoted
  claim with provenance, exactly like every other string.
- Prompt-injection surface is acknowledged, not solved: the wiki is for
  humans. A human reading a page and being fooled by content is the threat
  model; the mitigation is provenance-on-every-claim (§5.3.2) and the
  verification-state section that shows which claims have independent
  live-evidence backing.

## 9. Test baseline for this design (Phase 0 evidence)

Recorded 2026-10-05 on the hsp board, run 2 of task t_981997dd:

- Command per card:
  `SWARM_PROTOCOL_PLUGIN_DIR="$PWD/hermes_swarm_protocol"
  PYTHONPATH=/Users/raelldottin/.hermes/hermes-agent
  /Users/raelldottin/.hermes/hermes-agent/venv/bin/python -m pytest tests/ -q`
- Result inside this delegated-child worker context: `8 passed, 12 errors` —
  all 12 errors are the same PermissionError at
  `hermes_cli/kanban_db.py:150` ("delegate_task child contexts cannot mutate
  Kanban tasks or boards"). Cause: the dispatcher pins
  `HERMES_KANBAN_DB`/`HERMES_KANBAN_BOARD` in the child env; the test fixture
  (`tests/test_swarm_protocol.py:30-46`) isolates via `HERMES_HOME=tmp_path`,
  but the pinned board var overrides that isolation, so fixture board writes
  hit the live-board fence, which correctly denies them. The repo's tests and
  the fence are both behaving as designed; the pinned env is the artifact.
- Result with the routing pins unset for the subprocess
  (`env -u HERMES_KANBAN_DB -u HERMES_KANBAN_BOARD -u HERMES_KANBAN_WORKSPACE
  -u HERMES_KANBAN_WORKSPACES_ROOT … pytest tests/ -q`):
  **`20 passed in 4.67s`** — the expected baseline.
- Implication for CI: a dispatcher-spawned or delegated worker that runs this
  suite must strip the kanban routing env pins for the test subprocess (they
  are routing config, not fixtures) — the fixture's `HERMES_HOME` isolation
  then works as intended. This is worth a follow-up note in the repo's test
  docs when the wiki compiler's own tests land, since they will use the same
  fixture pattern.

## 10. Open design decisions (deferred to implementation cards)

1. Do heartbeats enter log.md collapsed or behind a `--verbose` flag? (§5.2
   currently says collapsed.)
2. Should `--check`'s byte-comparison exempt only `compiled_at`, or should
   the compiler accept `--stamp` to fix the stamp for CI runs? (Either
   satisfies §7; `--stamp` makes the gate byte-exact.)
3. Cross-board topics: the fleet has per-project boards (hsp is one). This
   design compiles ONE board per invocation; a fleet-wide index would just be
   a directory of per-board outputs. Confirmed as out of scope for v1.
4. Whether `brv vc` history (context-tree git) becomes an evidence source —
   deferred; v1 reads only the working tree files.

## Appendix A — Source-file anchors for every claim in this document

- Plugin semantics, receipts, MEMORY_* states, live-evidence refusal, identity
  anti-spoofing, no-edge provenance: `hermes_swarm_protocol/__init__.py`
  (lines 16-17, 36-39, 47-62, 128, 254-300, 338-405, 433-460; file is 460
  lines total, read in full).
- Tool surface + version: `hermes_swarm_protocol/plugin.yaml` (v1.0.1,
  provides_tools: swarm_request, swarm_verify, swarm_route).
- Ownership map, install model (symlink, no daemon), test command:
  `README.md` (lines 8-15, 44-97, 99-111).
- Status-integrity triggers and evidence-gated repair:
  `docs/kanban-worker-safety.md` (lines 23-71) and
  `ops/repair_kanban_status.py` (audit-first default, `--apply` narrowness,
  backup-before-mutation, `VALID_STATUSES`).
- Fleet memory policy, tree paths, auto_extract gating, brv query latency:
  `docs/recovery.md` (lines 7-33, 93-101) and `ops/migrate_fleet_memory.py`
  (lines 30-71: machine-global root, PROJECT_MEMORY, audit/apply modes).
- Kanban schema: live `.schema` dump of the hsp board (tasks, task_links,
  task_comments, task_events, task_runs) captured 2026-10-05; row counts at
  capture: 1 task, 0 links, 0 comments, 121 events, 2 runs.
- ByteRover tree format: live reads of
  `~/.hermes/byterover-projects/opnory/.brv/context-tree/**` (node frontmatter
  fields, summary nodes, `_index.md`) and this project's fresh tree
  (`~/.hermes/byterover-projects/hermes-swarm-protocol/.brv/`, created
  2026-10-05T23:41:42Z, empty).
- Test baseline: live pytest runs, §9.
