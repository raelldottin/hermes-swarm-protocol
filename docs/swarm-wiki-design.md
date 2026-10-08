# Swarm Wiki — Design Contract

Status: **implemented and deployed in plugin v1.2.0** after research, design QA and
implementation QA. `swarm_publish` and `swarm_capture` add canonical comment
publications and immutable evidence. `ops/build_wiki.py` provides the independent
compiler/linter. Existing request/verify/route behavior remains compatible.
See [operations](swarm-wiki-usage.md) and [QA evidence](swarm-wiki-implementation.md).
Worker deployment requires explicit project/member/maintainer configuration.

Task workspaces may be Hermes scratch directories outside the checkout. Every
new publication includes a runtime-derived absolute `workspace` field, taken
from canonical task metadata rather than caller arguments. Project configuration
explicitly authorizes additional `task_workspaces` roots; the compiler takes the
same roots through `--task-workspace-root` and persists them in the manifest.
Typed file evidence and its cache keys bind to the producing publication's
workspace, including when a different maintainer accepts synthesis. Immutable
captures live in shared project `.swarm/raw`, independently of their source root.
Knowledge captures record their origin and remain contextual snapshots after
curation; they cannot supply sole live evidence through an artifact or file alias.

The wiki is the swarm's readable memory and audit surface: compiled knowledge,
cross-references, visible uncertainty, and a history of changing conclusions.
It is a projection of canonical records and immutable evidence, never a competing
task database, coordination bus, or verification authority.

## 1. Architecture and ownership

Collusion's architectural lesson is durable, discoverable shared state, not a
requirement to run MediaWiki. Karpathy's LLM Wiki pattern contributes immutable
sources, accumulated synthesis, an index, chronological log, maintenance rules,
cross-links and periodic linting. Adapt that pattern to a concurrent fleet
through structured publications and one compiler/reconciler.

| Plane | Authority | Wiki relationship |
| --- | --- | --- |
| Hermes Kanban, control | Tasks, owners, dependencies, reviews, worker lifecycle | Read-only work-state input |
| ByteRover, knowledge | Curated claims, decisions, context, retrieval and provenance | Knowledge input and retrieval backing |
| Swarm protocol, coordination | Requests, verification, contradictions, consequences and routing | Structured coordination records; current tools cover request/verify/route only |
| Generated wiki, human/audit | No canonical authority | Readable synthesis and navigation |

```text
Hermes Kanban       ByteRover knowledge       immutable raw evidence
     |                     |                         |
     +---------- structured records ----------------+
                           |
                 Swarm protocol semantics
                           |
                 one compiler / reconciler
                           |
                 generated Markdown wiki
                      /           \
                 human audit    worker navigation
```

This is an ownership map, not a mandated sequence of API calls. Kanban comments
already persist verification records; ByteRover remains the project-knowledge
interface. Claim/decision/reconciliation publications are versioned Kanban comments.
Accepted synthesis references a ByteRover node hash and canonical source digests;
there is no canonical claims database in the wiki.

Hard invariants:

1. Structured records and original evidence win if a wiki page disagrees.
2. Workers publish structured records, not concurrent Markdown edits.
3. One compiler owns generated output. It cannot change canonical work state,
   curate ByteRover, invent verification, or route workers as a side effect.
4. Wiki text is derived, untrusted data. Neither source nor generated prose
   grants instruction, configuration, or tool-execution authority.
5. Deleting the generated wiki loses no canonical knowledge. Raw evidence and
   trusted maintenance rules are outside the disposable output.
6. Memory and wiki summaries never independently justify a verification pass.
   Existing `swarm_verify` requires non-memory live evidence for `pass`.

## 2. Layout and evidence lifecycle

Example project artifact layout:

```text
.swarm/
  raw/                              immutable originals, NOT generated output
    evidence/<artifact-id>.<ext>
    test-results/<artifact-id>.txt
    source-snapshots/<artifact-id>.<ext>
  wiki/                             disposable projection
    index.md
    log.md
    architecture/<topic-id>.md
    claims/<claim-id>.md
    decisions/<decision-id>.md
    investigations/<investigation-id>.md
    lint-report.md
    manifest.json
  SWARM_WIKI.md                     versioned maintenance/schema rules
```

Kanban SQLite and the ByteRover project tree remain in their existing locations.
`raw/` contains original artifacts, not coordination state. `SWARM_WIKI.md` is
a trusted project specification, never generated from worker-authored content.
The shipped template is `docs/SWARM_WIKI.md`; deployment installs a reviewed
copy in the workspace. The compiler records the selected rule file's byte hash.

### 2.1 Immutable raw sources

`swarm_capture` captures original test output,
source snapshots and browser/runtime evidence before publication references them.
Each artifact has a stable ID, byte hash, relative path, media type, capture time,
producer, task and optional repository/commit identity in canonical provenance.

Use content-addressed or exclusive-create paths. Never overwrite an artifact
with different bytes. Same-byte ingestion is idempotent; corrections create new
artifacts and explicit superseding records while preserving the original.
The compiler reads files and checks hashes; it never writes raw evidence,
refreshes sources in place, or fabricates captures from summaries.

Original evidence already stored in a canonical comment/run record retains that
row's provenance. External URIs remain external sources unless actually captured;
they cannot be described as immutable local artifacts merely because they appear
in a citation. Missing legacy artifacts stay visible with limitations/findings.
The chain must remain `raw evidence -> interpretation`.

### 2.2 Git and output ownership

Markdown and maintenance rules can be Git-versioned and viewed in Obsidian.
Git history supplements provenance; it does not make generated prose canonical.
Define artifact retention/access policy before committing captures; versioning
a projection must not make restricted evidence public.

The compiler writes only the designated wiki output. Reject overlapping
source/output paths, including symlink aliases. Rebuild/check/cleanup must never
remove `raw/`, `SWARM_WIKI.md`, `.brv/`, board databases or unrelated user files.

## 3. Canonical inputs and structured publications

### 3.1 Existing stores

Read the selected board with Python SQLite `mode=ro` and one explicit read
transaction spanning all table reads. A connection alone is insufficient for a
consistent multi-table snapshot during dispatcher writes. Use `query_only` as
defense in depth. Never initialize/migrate a board at compile time. Missing
required schema is an explicit error.

Consume needed fields from `tasks`, `task_links`, `task_comments`,
`task_events` and `task_runs`: identity, objective/body, creator, status,
lifecycle times, result, workspace context, block state, authored publications,
run summaries and events. Dependency edges remain distinct from source-task
provenance. `creator_task_id` where available and envelope `source_task` are
provenance, not proof that a request depends on source-task completion.

Read valid task statuses from installed Hermes `kanban_db.VALID_STATUSES`
without a mutating connection path. Fail if unavailable; do not guess an enum.
Unknown stored statuses are integrity findings, not silent remappings.

Read project `.brv/context-tree/**/*.md` files, frontmatter, summary nodes,
indexes and `related` links. Do not call LLM-mediated `brv query` during
compilation. Canonically captured query output may be quoted as a memory
observation; a timeout does not mean a claim is false or absent.

Default fleet root is `Path.home() / ".hermes"`, matching migration tooling's
machine-global rule rather than worker-session `HERMES_HOME`. Support explicit
DB/tree/raw/repo paths for fixtures and deployments. Compile one board/project
per invocation, document source locations, and never infer cross-project access.

Capture a stable knowledge-tree/raw read: sorted inventory, content hashes,
before/after validation, retry-or-fail on changes, including atomic replacement.
SQLite and the tree have no distributed transaction. Record their snapshot
fingerprints and dangling references instead of claiming an atomic cross-store
capture.

### 3.2 Versioned publications and legacy compatibility

Plugin v1.2 retains all v1 records and adds `hermes-swarm/wiki-v2` records
for `provenance` and `request_assessment`. The prefix and schema version must
agree. Maintainer provenance binds exact knowledge bytes or canonical board
task/event row digests. Adoption records reviewed responsibility,
never original authorship or factual verification. Work links and derivation
have separate meanings; cyclic or changed-revision lineage is invalid.
Canonical identity evidence is required for historical attribution. Unknown
creator/caller disclosures preserve missing identity for task and event rows.

An independent request assessment binds the exact archived request envelope,
every acceptance criterion index/digest, full frozen commit and explicit
request scope. A PASS requires complete passing criterion coverage and
available non-memory evidence. Request creators, assignees and target profiles
cannot self-verify. Opposing active verdicts preserve uncertainty. The compiler
retains original findings with correction IDs and reports unresolved findings
separately from adopted, linked, verified, attributed or disclosed history.
Source change, source loss or supersession invalidates current annotations.

Workers submit structured publications to an authenticated canonical path.
The publisher supplies event identity, runtime profile identity, task, time and
source provenance. Identity never comes from model-controlled `worker` fields.
Same-ID/same-payload retries are idempotent; same-ID/different-payload is rejected.
Publications are append-only; revisions link to superseded records. User-written
JSON alone is not an authenticated publication.

Envelope fields: `protocol`, `schema_version`, `event_id`, `type`, `project`,
`topic`, `task_id`, `actor`, `publication_key`, `recorded_at`, `data` and
`payload_digest`. Evidence is typed inside `data`. Canonical source provenance
comes from the board/comment row, author and timestamp, not caller-supplied JSON.
Local references carry hashes. Exact payloads are documented in the operations guide.

| Type | Additional fields / meaning |
| --- | --- |
| claim | Claim ID, assertion, scope, optional confidence, consequential flag |
| verification | Target claim/request, verdict, verifier, scope, live evidence, rationale |
| contradiction | Conflicting claim IDs, scope and supporting evidence |
| reconciliation | Contradiction ID, disposition, scoped conclusion, supporting record IDs |
| decision | Decision ID, rationale, claim/evidence links, superseded decision if any |
| consequence | Finding/claim IDs, affected task IDs, recorded impact |
| route | Requested role, resolved profile or unresolved outcome, associated task |

Illustrative model-controlled `data` payloads are below; common fields are
supplied by `swarm_publish`. The returned event ID serves as the claim ID:

```json
{"assertion":"Tenant-specific issuer is lost during initialization.","scope":"tenant-specific path","confidence":0.91,"evidence":[{"kind":"runtime","text":"Original reproduction output"}]}
{"claim_id":"<returned-event-id>","verdict":"partial","scope":"default path unaffected","rationale":"Independent scope assessment","live_evidence":[{"kind":"runtime","text":"Original independent observation"}]}
```

Compatibility is explicit: preserve existing `hermes-swarm/v1` request bodies
and `swarm_verify` comment envelopes. Current verdicts are `pass`, `fail`,
`inconclusive`, `blocked`. `partial` is supported only by new structured `swarm_publish` assessments,
not the existing `swarm_verify` tool. It records a scoped observation and never
becomes a pass for the original broader claim.

Objectives, comments, run summaries and ByteRover prose also contain assertions.
Preserve these as legacy/unstructured claims with row/file pointers. Never invent
authenticated claim IDs, authors or verification from prose. A node timestamp
is not an author identity; missing provenance renders unknown and triggers lint.

Publication mapping is pinned: structured envelopes live in authenticated
Kanban comments. Existing `brv_curate` maintains ByteRover prose; configured
maintainers accept exact node/source revisions through synthesis publications.

## 4. One compiler/reconciler and accumulated synthesis

Entry point: `ops/build_wiki.py`, a batch operational tool, not a daemon or
worker write API. Interface:

```text
python ops/build_wiki.py --board hsp --project hermes-swarm-protocol
  [--out .swarm/wiki] [--check] [--lint]
```

Support explicit input paths and repo identity. Compilation always produces lint;
`--lint` emphasizes audit output. Findings set a non-zero exit status but do
not suppress readable pages. Operational/schema failures use a distinct status
and never publish partial output. Clean compilation/check exits 0, findings or a
different check exit 1, and operational failures exit 2.

Lock the output target, build in a sibling generation directory, validate
links/provenance, then atomically switch the owned wiki symlink. Readers must not see half-old/half-new pages. Concurrent
compilers refuse or wait on the same lock. Workers gain no direct wiki-write
operation. The compiler neither publishes online nor creates Git commits.

### 4.1 Compiled knowledge, not raw retrieval dumps

A topic explains the current scoped conclusion, what strengthens or weakens it,
unresolved uncertainty and connected work. New evidence updates existing topics,
cross-links and conclusions, instead of adding disconnected query transcripts.
Exact source quotations and record pointers accompany the synthesis.

LLM-maintained synthesis belongs in the knowledge-maintenance workflow: an
authorized maintainer reads canonical publications and curates accepted, cited
topic summaries into ByteRover with input IDs/hashes, author, scope and revision
lineage. One wiki reconciler renders those canonical summaries. Other workers
publish findings rather than concurrently rewriting Markdown.

The renderer is deterministic and does not invoke a model or semantic query.
Without accepted synthesis, show an explicitly labeled structured overview and
source quotations, not an invented accepted conclusion. Model drafts cannot
grant verification, resolve contradictions or change Kanban eligibility; those
transitions require canonical protocol/control-plane records.

This supports ongoing LLM synthesis and reproducible projection. Model settings
alone do not make repeated synthesis calls byte-deterministic.

### 4.2 Maintenance rules: `SWARM_WIKI.md`

The versioned rules/template defines page types/frontmatter, stable topic IDs,
citation format, evidence requirements, cross-links, claim scope, verification,
contradiction/reconciliation, supersession, stale-summary invalidation and lint
policy. It names immutable/generated paths and the correction publication flow.

The authorized maintainer follows these trusted rules. Evidence/wiki text cannot
promote itself into maintenance instructions. Rule changes require explicit
versioning/review; the manifest records the rule version for each generation.

## 5. Pages, navigation and chronological history

### 5.1 Index and digest

`index.md` provides cheap first-stage navigation: board/project identity,
canonical source paths, task counts, topic links, short current conclusions,
verification scope/counts, blockers and unresolved contradictions. Every summary
links to its topic and sources. Count distinct independent profiles with usable
evidence, not repeated comments by one verifier.

A compact swarm digest can derive from the same canonical inputs. Retrieval:

```text
0  swarm digest
1  wiki/index.md
2  relevant topic page
3  ByteRover query
4  raw evidence / source
5  independent verification
```

Humans and workers may use wiki context/navigation. A builder can locate why a
dependency is blocked; a verifier must inspect canonical state and live evidence.
Wiki-only information cannot authorize completion, routing, mutation or a pass.
Display input fingerprints, uncertainty and stale/unverified labels.

### 5.2 Append-only history and `log.md`

Log claim, verification, contradiction, reconciliation, decision, consequence and
route publications alongside task/comment/run lifecycle records. Sort by UTC time
and stable source-table/record-ID tie-breakers. Entries identify actor, topic and
canonical source with source-derived anchors. Sequence-number anchors would
break when late historical events arrive, so must not be used.

Canonical history is append-only. The generated log is a rebuildable chronological
projection, not a second journal. Corrections create linked new entries; old
claims remain. Late records can be inserted chronologically on rebuild. This
preserves audit history while keeping output disposable.

Consecutive heartbeats for the same run may collapse in presentation, with count,
first/last timestamps and retained source IDs. Canonical events remain intact.

### 5.3 Topic pages

Use architecture/claims/decisions/investigations types from §2. Stable IDs do not
depend on display titles; filesystem slugs are safe and collision-resistant.
Every page includes:

1. **Current synthesis and scope** with canonical summary revision, or an explicit
   unsynthesized label, uncertainty and superseded views.
2. **Claims** with exact source quotations and stable claim/legacy record IDs.
3. **Provenance** for every assertion: author or unknown, time, canonical row/file,
   revision and original evidence where available.
4. **Linked work/knowledge**, distinguishing dependencies, source-task provenance
   and topic cross-references.
5. **Verification state**: verifier, verdict, scope, rationale, live evidence,
   memory status/digest and time. Absence is `UNVERIFIED`; an unsupported pass
   is `INVALID PASS`.
6. **Contradictions**, both sides and sources, disposition and supported canonical
   reconciliation if resolved.
7. **Evidence references** to originals, source/test/runtime/commit and ByteRover
   records. Unavailable references stay visible with findings, never invented links.

Quote/escape source Markdown and HTML, delimit multiline input and validate link
schemes so untrusted prose cannot impersonate metadata, verification badges or
rules. Preserve original bytes in raw artifacts; display escaping is not a change
to original evidence.

## 6. Periodic lint and contradiction semantics

Lint audits canonical inputs and just-built output, both per-generation and via
scheduled batch invocation. `swarm_lint` is a candidate later primitive, not
an existing plugin tool. No daemon is required.

| Finding | Required check |
| --- | --- |
| Missing provenance | Assertion lacks author, time or canonical source; retain visibly |
| Insufficient sources | Single-source consequential claim, copied observations, non-independent identities |
| Missing independent verification | No scoped pass/live evidence from a different authenticated profile |
| Invalid verification | Unsupported pass, unknown identity, malformed record, scope mismatch |
| Unresolved contradiction | Explicit conflict without supported reconciliation or mechanical state/verdict conflict |
| Stale knowledge | Summary cites changed/superseded records, old scoped commit, missing/changed evidence |
| Stale references | Absent commit/file/node, broken evidence pointer, hash mismatch |
| Orphans / missing cross-links | Unindexed page, broken related link, knowledge with no work/topic connection |
| Knowledge gaps | Explicit required topic/acceptance question lacks cited claim/evidence |

Consequential means existing `evidence_required: true`, an explicit new-schema
flag or a recorded mutation assertion. Independence derives from authenticated
identity and target/scope links, never prose labeling a source independent.
Legacy records missing those bindings cannot be upgraded automatically.

Mechanical contradictions include differing terminal assessments for the same
claim/scope and a `done` task whose latest applicable verification is
`fail`/`blocked`. A later comment does not erase conflict; reconciliation
links both sides, evidence, scope and disposition. Superseded claims stay in
history. Opposite-polarity ByteRover summaries may produce candidate findings
only under defined keyword/scope rules; open-ended semantic detection is not
promised. Subtle contradictions need worker publication or human review.

Check commits read-only in the identified repo, not inherited CWD. Distinguish
missing commits from historical commits that exist but no longer support
current-state claims. Prefer typed references; legacy extraction is labeled
heuristic. Do not treat every hex token as a commit or every string as a path,
fetch arbitrary URIs, execute evidence text or follow paths beyond allowed roots.

Report class, severity, topic, canonical record and remediation target. Repair
canonical evidence/knowledge or compiler rules, never generated text. Pin policy
thresholds and exact exit codes in implementation tests.

## 7. Reproducibility, freshness and safety

Unchanged canonical input, rules and reference-resolution state produces identical
bytes. The manifest records sorted input hashes, schema/rule/compiler versions,
board/project identity and reference context. Omit wall-clock stamps; source times
and fingerprints identify a generation. Use UTC, stable IDs and sorted traversal.

`--check` builds in a temporary directory and compares complete expected file
sets/bytes, including unexpected/stale pages. It changes neither sources nor
existing output. Normal publication removes obsolete generated pages only within
owned output; unknown user files cause refusal, not silent deletion.

Delete/rebuild `.swarm/wiki/` must reproduce output. Raw evidence deletion is
never part of cleanup. Source/hash/schema failures cannot produce a falsely fresh
manifest. Each page displays:

> Generated, untrusted projection. Kanban owns work state; ByteRover owns
> knowledge; original records and evidence govern.

Generated-page access cannot broaden access to restricted evidence. Compile from
an authorized source set into an equally authorized destination. Sharing/access
integration is a deployment gate, not a property guaranteed by Markdown or Git.

## 8. Implementation sequence and acceptance gates

Implementation follows these gates. Current evidence is recorded in
`swarm-wiki-implementation.md`; fixtures and the read-only real-source build
establish compiler behavior. Applied source outcomes and live deployment are recorded in
`swarm-wiki-delivery.md`; disclosed historical unknowns remain visible.

1. **Canonical publication/evidence:** finalize/version schema, store mapping,
   authenticated identity, idempotency, ingestion and maintenance rules. Prove
   concurrent publication, preserved corrections and existing-tool compatibility.
2. **Read-only compiler:** implement snapshot readers, typed citations, topic
   pages, overview/digest/index/log and manifest. Prove DB snapshot consistency,
   tree replacement detection, schema failures and canonical/raw byte preservation.
3. **Synthesis/reconciliation:** add authorized ByteRover maintenance, accumulated
   topic updates, scoped reconciliation, decisions and consequence links. Show
   strengthening, narrowing and supersession without inventing verification or
   changing control-plane state.
4. **Lint/publication:** cover every §6 class, locking, coherent generations, safe
   paths/symlinks, escaping, stale-page cleanup, check mode and identical rebuilds.
5. **Deployment/navigation:** demonstrate the retrieval ladder on a real project,
   trace index claims to originals, validate access boundaries, document scheduled
   lint and optional Git/Obsidian use.

Fixtures must cover opposing verdicts, self-verification, partial/narrowed scope,
unsupported passes, unknown authors, malformed/duplicate events, late records,
repeated heartbeats, historical but stale commits, changed hashes, broken links,
injection prose, unknown output files and concurrent compilers. Prove no canonical
mutation and no runtime wiki dependency. Formatting snapshots alone are inadequate.

No new server, daemon, network bus, authoritative wiki datastore, unrestricted
worker Markdown writes or automatic publishing is required. Fleet-wide indexes
and ByteRover version-control history ingestion are deferred beyond the first
single-project implementation.

## 9. Current grounding and review evidence

Repository grounding:

- `README.md`: Kanban work state, ByteRover knowledge, worker authors,
  coordinator roles and request/verify/route semantics.
- `hermes_swarm_protocol/plugin.yaml` v1.2.0: request, verify, route, publish and capture.
- `hermes_swarm_protocol/__init__.py`: runtime identity, request task bodies,
  verification comment envelopes, memory outcomes, live-evidence pass requirement
  and request provenance without a dependency edge.
- `ops/migrate_fleet_memory.py` / `docs/recovery.md`: project knowledge trees
  and machine-global root independent of worker `HERMES_HOME`.
- `ops/repair_kanban_status.py` / `docs/kanban-worker-safety.md`: audit-first
  operational conventions and status-integrity boundaries.

This revision inspected hsp schema read-only: all five input tables exist; the
project tree contains 11 Markdown nodes. These are inspection observations, not
compiler acceptance. Validate required columns at implementation time, tolerate
additive Hermes schema changes, and do not freeze a dated full schema dump.

Pre-implementation baseline: **20 passed** using the Hermes virtualenv and this checkout's
plugin, with Kanban routing pins removed only in the isolated test subprocess.
From repository root:

```bash
env -u HERMES_KANBAN_DB -u HERMES_KANBAN_BOARD \
  -u HERMES_KANBAN_WORKSPACE -u HERMES_KANBAN_WORKSPACES_ROOT \
  -u HERMES_KANBAN_TASK \
  SWARM_PROTOCOL_PLUGIN_DIR="$PWD/hermes_swarm_protocol" \
  PYTHONPATH=/Users/raelldottin/.hermes/hermes-agent \
  /Users/raelldottin/.hermes/hermes-agent/venv/bin/python -m pytest tests/ -q
```

The extended suite also covers wiki compiler/publication behavior; see the QA
record for the final result. Removing subprocess routing pins lets fixtures avoid
a live dispatcher board.

Task-supplied inspirations (not evidence of shipped repository features):

- [Collusion](https://collusion.wiki/): durable shared surfaces and discovery.
- [Karpathy's LLM Wiki idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
  immutable sources, maintained synthesis, rules, index/log and lint.
- [Hermes memory providers](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers/)
  and [ByteRover](https://www.byterover.dev/): retrieval and sharing.

Verify current external APIs and deployment-specific access behavior when
implementing adapters.
