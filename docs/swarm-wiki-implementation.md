# Swarm Wiki: research, plan, design and QA

## Research

Reviewed 2026-10-08 against the current checkout and installed Hermes sources.

- [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), fetched live: a pattern rather than an implementation; immutable sources, compiled/maintained synthesis, navigation, chronological history and periodic lint are central.
- [Hermes memory providers](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers/), fetched live: ByteRover exposes query, curate and status with profile-scoped defaults. This fleet's existing migration policy supplies shared project trees.
- [Collusion](https://collusion.wiki/), fetched live: supports the durable shared-surface motivation, not a dependency on a wiki service.
- [Python SQLite transaction control](https://docs.python.org/3/library/sqlite3.html), fetched live: SELECTs do not implicitly establish the needed multi-query transaction; an explicit read transaction is required.
- Installed Hermes: `kanban_db.add_comment(conn, task_id, author, body)` persists authenticated-profile publications through the same path as existing swarm tools. Current tables support tasks, comments, events, runs and dependencies. Existing statuses are read from Hermes at runtime.
- Existing plugin: runtime profile identity, explicit memory outcomes, live-evidence pass guard and deterministic routing remain compatible. Test baseline before this work: 20 passed.

## Plan

1. Finalize structured records, evidence capture, synthesis acceptance and maintenance rules.
2. Implement read-only source snapshots, normalization of legacy records, topic synthesis, index/digest/log and manifest.
3. Implement lint, output locking, atomic generation publication and read-only check mode.
4. Integrate publication/capture tools with runtime identity and project access configuration; keep rendering out of worker tools.
5. Test adversarial records, concurrency, regeneration, unchanged sources, real plugin discovery and a read-only real-project compilation. Document deployment and repeat QA after failures/fixes.

## Design decisions

- Structured publications use versioned `hermes-swarm/wiki-v1` envelopes in **Kanban comments**. No new claims database. ByteRover remains canonical for curated topic prose; a maintainer accepts a node revision by publishing its hash and source-record digests.
- `swarm_publish` supplies actor/task/time/ID; payload cannot supply identity. A publication key is scoped to project/task/profile. Same-key retries are idempotent, conflicting payloads fail. A SQLite write transaction serializes competing publishers.
- `swarm_capture` copies an allowed workspace file into `.swarm/raw/<class>/<sha256>` using exclusive creation and records provenance in a comment. It never silently replaces an artifact. Publishers require configured project members and workspace; synthesis acceptance additionally requires a configured maintainer.
- Existing request/verify tools and verdicts remain intact. New typed verification includes `partial` with an explicit scope; it never upgrades broad claims. Compiler authentication checks comment author against envelope actor. Direct database administrators remain trusted; JSON does not provide cryptographic authorship.
- One independent compiler reads a consistent SQLite transaction plus stable tree/raw inventories. It performs no semantic query, curation or work-state mutation.
- LLM/topic maintenance uses existing `brv_curate`, then the maintainer accepts the resulting node hash/source digests. The renderer displays that accepted synthesis, or labels its structured fallback unsynthesized. Curation errors/pending review are not acceptance.
- Output is an owned symlink to immutable generation directories. Build/validate staging, then atomically replace the symlink under a sibling file lock. This avoids a partially updated multi-file directory. Unknown user files/foreign symlinks cause refusal. Sources and rules are outside generations.
- No wall-clock build stamp. Deterministic hashes, UTC source times, stable anchors and complete file-set comparison support disposable rebuild and `--check`.
- Lint always produces readable findings and exit 1; operational failures exit 2; clean compilation/check exits 0. A differing check exits 1 without writing output.

## Design QA pass 1

Review against `swarm-wiki-design.md` before implementation found:

1. Canonical publication placement was deferred: resolved to authenticated Kanban comments, with accepted ByteRover synthesis referenced by hash.
2. Directory-by-directory Markdown writes violate coherent publication: resolved to locked generation directories and atomic symlink replacement.
3. A generic `partial` verdict could erase broader uncertainty: preserve claim/scope binding; only a same-scope independent live-evidence pass verifies a claim.
4. A changed knowledge node could masquerade as accepted synthesis: bind node bytes and cited publication digests, invalidate on change/supersession.
5. A caller-controlled artifact path or output alias could escape roots: validate canonical roots and reject symlink traversal/overlap; never execute/fetch cited data.

## Design QA pass 2 (iteration)

Rechecked those decisions against the original architecture:

- Control/knowledge/coordination/projection ownership remains intact; a compiler cannot mutate the first three planes.
- One publisher transaction prevents competing idempotency records. Runtime author checks preserve existing anti-spoofing conventions.
- Raw bytes survive interpretation/correction. Generated generations are disposable; old source records remain chronological.
- Accepted synthesis is canonical knowledge, not nondeterministic compiler output. Worker navigation remains allowed while verification descends to evidence.
- Cross-project access is explicit configuration, not an inferred profile name. No live fleet config is edited by this implementation.
- Deferred fleet-wide aggregation and ByteRover VC-history ingestion stay deferred; all single-project gates remain in scope.

Implementation QA results follow. Design reviews alone are not runtime proof.

## Implementation QA and iteration

Final isolated Hermes integration and compiler suite: **59 passed** on 2026-10-08
(6.29 seconds), using the command in the design contract. The suite preserves the
existing protocol checks and covers canonical authenticated publications,
transactional concurrent retries, immutable captures, project/task confinement,
synthesis acceptance and invalidation, provenance lint, generated links, coherent
publication, reproducible rebuilds, and read-only checks.

QA led to these implementation corrections, each checked before completion:

- Installed Hermes returns typed tasks, so publication reads canonical workspace
  metadata through SQL instead of assuming a dictionary return value.
- Real hsp task workspaces live outside the checkout. Explicit configured roots
  now authorize scratch workspaces; file evidence and cache keys bind to their
  producer workspace. Shared raw storage is independent of capture source roots.
  Synthesis accepted by a different maintainer still validates producer evidence.
- Idempotent retries return the original committed publication before validating
  current state, including a synthesis retry after its node has changed.
- Lost evidence, changed nodes, new topic publications and superseded sources
  invalidate synthesis. Reconciliation checks currently available independent
  evidence; historical invalid reconciliations remain visible.
- ByteRover snapshots retain their immutable original bytes after curation and
  are identified as memory context. Known memory/wiki capture hashes cannot be
  relabelled as sole live artifact/file proof.
- Confined source reads anchor directory descriptors and reject symlink traversal;
  raw files use exclusive content-addressed creation and read-only permissions.
- Same-author or maintainer corrections preserve type/topic. Superseded
  verification no longer affects current claim state or reconciliation support;
  its historical page remains and is labelled `SUPERSEDED`.
- ByteRover related links support root-relative, node-relative and confined parent
  paths. Lifecycle actor recovery uses available canonical payload/run/task data
  while preserving unresolved unknowns as findings.

Two new test fixtures initially failed because they used an unsupported synthesis
category and expected an unescaped identifier in escaped Markdown. Both fixture
expectations were corrected; the final full suite passed after the code changes.

## Initial real-source acceptance (historical baseline)

Built the current hsp board and shared hermes-swarm-protocol ByteRover tree:

```bash
/Users/raelldottin/.hermes/hermes-agent/venv/bin/python ops/build_wiki.py \
  --board hsp --project hermes-swarm-protocol --rules docs/SWARM_WIKI.md \
  --task-workspace-root /Users/raelldottin/.hermes/kanban/boards/hsp/workspaces
```

The build generated **23 files** at `.swarm/wiki/index.md`, from 7 tasks, 6
comments, 317 lifecycle events, 12 runs, 7 dependency links and 11 knowledge nodes.
The same command with `--check` reported `matches: true`. Generated cross-links
and every manifest file hash validated. Before/after checks confirmed unchanged
database bytes, canonical table contents, tree bytes, raw inventory and rules.
The canonical table snapshot SHA-256 was
`683f63381f111554701d49e6dbebeb29c704a9b0beb90f77ef2603c78f7ff324`;
the knowledge inventory digest was
`432febe55e21246981932d3040479c76c6de569cb59a35da59a6884d18876d77`.

Both build and matching check returned the documented **exit 1** because canonical
inputs retain **39 lint findings**:

| Class | Count |
| --- | ---: |
| missing-provenance | 26 |
| orphan-topic | 11 |
| knowledge-gap | 1 |
| missing-independent-verification | 1 |

These are unresolved input findings, not clean acceptance of the legacy claims.
The real board currently has no new structured wiki publications; their complete
publish/capture/verify/synthesis path was exercised with isolated real Hermes
fixtures. No live fleet configuration, canonical board record or ByteRover node
was edited at this historical baseline. Curation and deployment were then
untested; applied results are recorded in [delivery](swarm-wiki-delivery.md).

The subsequent [source audit remediation review](swarm-wiki-audit-remediation.md)
covers all 39 findings with research, a remediation design and two QA passes.
Its [finding register](swarm-wiki-audit-findings.json) pins every source revision;
that initial review preceded canonical corrections. The subsequent v1.2
delivery applied those corrections, reviewed live synthesis, deployed five
profiles and passed final iteration QA. The initial 39 findings are retained
with explicit outcomes rather than deleted.
