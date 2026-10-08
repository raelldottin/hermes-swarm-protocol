# Swarm Wiki source audit: research, plan, design and QA

Status: **implemented, QA validated and applied through canonical publications**. Reviewed 2026-10-08.

## Applied results

All original 39 findings now have exact-source canonical outcomes: 11 adopted
knowledge revisions, 11 explicit work links, two independently verified
request gaps, and 15 disclosed historical actor gaps. The original actors
remain unknown. Eleven original knowledge nodes and the original Phase 0
design/test evidence were captured unchanged. Existing seven task records and
their lifecycle rows were preserved.

Maintenance tasks `t_44e964c2` and `t_84d5b601` are complete. Their six new
creator/event gaps are retained with explicit disclosures, bringing the live
audit to 45 outcomes before synthesis curation. The finding register links
original source digests to canonical correction event IDs. Current deployment,
synthesis acceptance, reproducibility and final integration QA are recorded in
[delivery](swarm-wiki-delivery.md).
This document covers all 39 findings in the current hsp wiki. The
[finding register](swarm-wiki-audit-findings.json) assigns every finding a stable
ID, a source revision hash, a workstream and an unresolved status. It is a review
artifact, not canonical provenance or verification authority.

## Research

The current read-only `--check` reports `matches: true`, 23 generated files and
39 findings. Counts below are reproduced from compiler output, not inferred from
the rendered prose. Source fingerprints are pinned in the finding register.

| Workstream | Finding class | Count | Actual source problem |
| --- | --- | ---: | --- |
| A1 | missing-provenance | 15 | Lifecycle rows contain no actor or linked run |
| A2 | missing-provenance | 11 | Knowledge files lack an assertion author |
| A2 | orphan-topic | 11 | No structured publication links those files to work |
| A3 | missing-independent-verification | 1 | Archived request lacks an attached, scoped independent assessment |
| A3 | knowledge-gap | 1 | Its acceptance criteria have no recognized independent answers |
| Total | | 39 | 27 distinct source subjects; some have two findings |

### A1: lifecycle provenance

All 15 flagged rows have `run_id: null`, no recoverable run profile and no
`author`, `actor`, `by` or `profile` in their payloads. Their exact row hashes and
task IDs are in the register.

| Kind | Event IDs | Count | Installed Hermes writer |
| --- | --- | ---: | --- |
| dependency_wait | 207, 209, 211, 213, 215 | 5 | `kanban_db.create_task`, line 1487; other call paths also exist |
| promoted | 218, 219, 220, 292, 299 | 5 | `kanban_db.recompute_ready`, line 2260 |
| respawn_guarded | 267, 272, 277, 282 | 4 | `kanban_db_dispatch._dispatch_lane_task`, line 2085 |
| archived | 203 | 1 | `kanban_db.archive_task`, line 3991 |

Installed Hermes checkout: `1298c8e74baa73e1a2b90124228d017261ac6bc4`.
Writer inspection establishes that 14 events can be emitted by operational
machinery without recording an initiator. It does **not** establish which binary
or caller emitted a historical row. Promotion can also result from a human-driven
readiness computation. The archive initiator is unknown. Current assignees,
task creators and nearby comments cannot fill these historical identity gaps.

### A2: knowledge provenance and links

Installed provider: `byterover-cli/3.16.1`, Darwin arm64. The local tree contains:

| Observed role | Files | Count | Provenance available |
| --- | --- | ---: | --- |
| Declared structural summaries | Three `_index.md` files | 3 | `type: summary`, `covers`, `children_hash`; no author/time |
| Context prose | Two `context.md` files | 2 | No frontmatter provenance |
| Candidate derived summaries | Two `.abstract.md`, two `.overview.md` | 4 | No frontmatter provenance; filename suggests a relationship only |
| Knowledge assertions | Two main task nodes | 2 | `createdAt`/`updatedAt` and explicit task/commit mentions; no author |

The main nodes describe `t_6ce34613` and `t_7747c2f0`, and mention related
`t_9d3e6f3d`/`t_d9e4657d` work. These are candidate lineage links, not authenticated
assertion authorship. A filesystem timestamp, Git commit author, task filename,
or current profile does not establish who curated a ByteRover assertion.
One main node has a `related` link to the other; that knowledge link does not
constitute a canonical work publication. Index navigation is distinct from
canonical work linkage.

Three live external references informed the design:

- [Hermes memory providers](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers/): retrieval and curation are separate provider operations.
- [ByteRover documentation](https://docs.byterover.dev/) and its [index](https://docs.byterover.dev/llms.txt): current public documentation primarily describes V4. V4 behavior is not used to infer this V3 tree's generation or author metadata.
- [W3C PROV-DM](https://www.w3.org/TR/prov-dm/): generation, derivation, attribution and the responsible agent are distinct relations. This supports separating producer metadata, historical authorship and current adoption; it does not authenticate these particular files.

### A3: archived Phase 0 request

Subject: `t_981997dd`, request `swreq_1d468c5ac8e0`, created by `default` for
`hsp-builder`. It is archived, with two runs and **no task comments**. Run 2
reports a completed design-only deliverable and a 20-test baseline.

The claimed commit exists locally:
`855a0194e25c8316f6e460bf708805a4f0d971fc`. Its only added file is the 440-line
Phase 0 `docs/swarm-wiki-design.md`; that tree has no `wiki_compiler` or
`build_wiki` file. The design file's SHA-256 is
`4549026bc6d5d36c9839b2d6bd16c0c61b25e29597f049bb9fa69fc8f52e6d0e`.

Fresh research QA exported that exact commit into a temporary directory, removed
the Kanban routing pins for the isolated subprocess, and ran its test suite.
The JUnit result confirmed **20 tests, zero failures/errors/skips**, exit 0, in
4.763 seconds. The exported Git archive SHA-256 was
`ff2d5f5acb75f238b4aa0c6d672eb996367824af64bbacb22808e041dff51255`.
This corroborates the historical baseline; it is not an authenticated Kanban
request assessment or evidence that the PR was merged. The temporary tree was
removed after the run.

Canonical comment 5, authored by `hsp-verifier` on `t_9d3e6f3d`, records a
blackboard `verifier_gate` PASS for `t_d9e4657d`. It reports an independent
inspection of the same commit, a live exported-tree result of 20 passed in
4.27 seconds, and the read-only/untrusted-data sections. This is useful existing
evidence, but it is neither a `swarm_verify` comment on the archived request nor
an assessment explicitly binding all its acceptance criteria. The compiler
correctly does not silently transfer that PASS to another task.

[PR #3](https://github.com/raelldottin/hermes-swarm-protocol/pull/3) was fetched
live during this review. Its head matches the full commit above; its state is
**open**, `merged: false`. Existence of a commit, successful tests or a mergeable
PR must not be reported as a merge. Merge was not an acceptance criterion here.

The original request requires a design-only snapshot. Its assessment must use
the frozen Phase 0 commit, not today's worktree, which now contains the compiler.

## Plan

| Order | Workstream / owner | Concrete deliverable | Completion evidence |
| --- | --- | --- | --- |
| 1 | Protocol maintainer | Add revision-bound provenance annotations and legacy request assessments, with strict compatibility handling | Positive and adversarial fixture tests; old publication behavior preserved |
| 2 | A1 / operations maintainer | Record confirmed producer semantics separately from unknown historical initiators; enrich future writers with runtime actor/origin where available | All 15 rows accounted for; source hashes unchanged; unsupported actor attribution rejected |
| 3 | A2 / knowledge maintainer | Capture all 11 original revisions; review explicit source-task/derivation links; adopt current bytes or curate corrections | 11 reviewed hash-bound adoptions/work links, with originals retained and current adopter identified |
| 4 | A3 / independent verifier | Assess each original acceptance criterion at the frozen commit in a new maintenance task | Exact request/commit binding, full criterion coverage and live original-artifact evidence |
| 5 | Auditor | Recompile, compare manifests and review outcome transitions | No finding silently deleted; every changed outcome links to its canonical corrective record |

This sequence is ready for a separate implementation pass. It does not require
rewriting old task events, manufacturing original authors or reopening archived
work. Create follow-up maintenance work through sanctioned Kanban operations;
the compiler remains read-only. Deploy consumers that understand the new record
schema before enabling producers. Provider migration is outside this remediation.

## Design

### Canonical metadata corrections

Propose a versioned `provenance` publication, authored through runtime identity
on a maintenance task. Use a new schema/protocol version with strict decoding;
continue to decode existing v1 publications unchanged. Older readers must fail
closed on unsupported new records. Proposed data contract:

| Field | Meaning / validation |
| --- | --- |
| subject | Board/project plus typed task-event ID and canonical row hash, or knowledge path and exact byte hash |
| relation | `adoption`, `work_link`, `derivation`, `producer_observation`, `actor_attribution`, or `unknown_disclosure` |
| rationale | Reviewed explanation, rendered as data |
| evidence | Existing typed evidence references; originals must be available |
| source_task_ids | Optional same-board task IDs, all required to exist; never dependencies or completion authority |
| parent_revisions | Optional explicit path/hash pairs for reviewed derivation; reject cycles and path escapes |
| attributed_actor | Allowed only for evidence-supported historical attribution; never inferred from the annotator |

Only configured maintainers may publish these annotations. Subject IDs and hashes
are checked against canonical snapshots inside the publication transaction and
again during compilation. Recheck file hashes during read snapshots. Conflicting
attributions remain visible; a newer annotation does not win simply because it
is newer. Corrections use explicit authorized supersession and keep old records.

An adoption establishes **who reviewed/adopted these bytes now**. It does not
replace an unknown historical author or verify the node's factual assertions.
Each knowledge node is reviewed individually; neither a suffix nor `type:
summary` grants an exemption. The opaque provider `children_hash` is retained
but not independently validated without its version-specific algorithm.
Explicit parent/child byte hashes bind reviewed derivation instead.

Work links must reflect inspected canonical task/run/comment evidence. A filename
match is only a suggestion. They provide navigation and provenance, not task
status, task dependency, source independence or claim verification.

For lifecycle rows, record `producer_observation` and/or `unknown_disclosure`
when the historical initiator cannot be recovered. Display an unknown original
actor alongside the annotation author and its evidence. Producer observations
are scoped to the inspected writer revision, not asserted historical execution.
Any future historical `actor_attribution` needs original, independently checked
evidence; a maintainer's assumption or current assignee is insufficient.

### Scoped legacy request assessment

Propose `request_assessment`, published from an independent verifier's current
maintenance task, with these required fields:

- `subject_task_id`, original `request_id`, and `request_digest` binding the
  original request envelope and acceptance text.
- Full `artifact_commit` SHA, scope and rationale. Here the scope is the frozen
  Phase 0 deliverable, not current implementation or PR merge state.
- `acceptance_results`: exactly one result per criterion, bound by index and
  criterion digest; each has a verdict and evidence references. Missing or
  duplicate criteria invalidate aggregate PASS.
- `verdict` and typed `live_evidence`. An aggregate PASS requires every criterion
  to pass, available original evidence and a verifier different from both the
  request creator and the delivering builder. Memory/wiki/blackboard assertions
  alone cannot supply live proof.

The authenticated publication task remains the maintenance task; the subject
request is a separate validated reference. Publication must not change the
archived task's state. A request/body revision, changed artifact, unavailable
evidence, later failure or invalid supersession invalidates the corresponding
current assessment. The compiler connects a valid assessment to both existing
request findings; it never treats a metadata adoption as verification.

| Original criterion | Existing research evidence | Required assessment work |
| --- | --- | --- |
| 20-test baseline | Run 2, comment 5 and fresh exported-tree QA all support 20 passed | Independent verifier reviews the originals and retains live output for the criterion-bound assessment |
| Committed document and required sections | Exact local commit and 440-line file | Map every required section to original artifact lines |
| Grounded in actual repo code | Historical document contains source anchors | Inspect cited code at that commit; distinguish historical from current behavior |
| Design only; no compiler implementation | Single-file delta; historical tree lacks compiler files | Confirm original tool surface and full relevant tree |
| Commit SHA and pytest summary in completion | Builder run 2 summary and verifier record | Bind those exact canonical rows and capture live verification evidence |

### Finding outcomes and invariants

Preserve the 39 baseline IDs and their original evidence. Expose separate outcomes
such as `unresolved`, `adopted_current_revision`, `linked`, `verified`, and
`disclosed_unknown`. A disclosed unknown is not recovered authorship or a verified
claim. Report historical disclosures separately from actionable current gaps;
do not target a misleading zero-finding total. Define exit-policy changes in the
implementation review before deployment and include counts in the manifest.

No prose mutation or record publication occurs during compilation. Immutable
originals remain available. Changing a subject hash invalidates its annotation;
changing a parent invalidates derived coverage. Historical reports remain
historical, especially claims about the now-implemented compiler or PR state.

## QA pass 1: rejected shortcuts

The first review tested candidate shortcuts against actual source records:

| Candidate | QA finding | Design correction |
| --- | --- | --- |
| Use task creator/assignee as historical actor | All 15 rows lack recorded initiators; creator is not event actor | Preserve unknown actor; attach separately scoped evidence |
| Assign `dispatcher` to every operational event | Current source proves an emission path, not historical caller/version | Distinguish writer semantics from observed historical execution |
| Ignore `_index`/summary files | Summaries contain assertions and may be stale or unrelated | Individually review bytes and bind derivation; no suffix exemption |
| Fill ByteRover author from timestamps or task names | No authenticated curation author is present | Current adoption remains separate from original authorship |
| Reuse comment 5's PASS automatically | Its target is another task and has no exact archived-request binding | Require an explicit criterion-bound assessment |
| Skip the archived request | Archival is lifecycle state, not evidence | Assess the historical artifact without changing task state |
| Verify design-only acceptance on today's checkout | The compiler now exists | Pin the original Phase 0 commit |
| Treat PR evidence as proof of merge | Live PR is open and unmerged | Report the observed state and keep merge out of this scope |

## Iteration QA: revised design

The second review traced every original finding through the revised plan. All
39 have one action assignment and a hash-bound subject; no finding is omitted or
declared resolved by this review. Required implementation gates are:

1. Valid current adoption never sets original author or live verification state.
2. Unknown actor disclosure cannot be converted into invented actor attribution.
3. Same-path changed bytes and same-ID changed rows invalidate annotations.
4. Cross-board/task roots, path traversal, symlinks and cyclic derivation fail.
5. Arbitrary filenames/provider metadata cannot grant provenance or work links.
6. Unlinked or memory-only legacy PASS cannot resolve either request finding.
7. Full frozen-request acceptance coverage passes only with independent evidence;
   partial coverage remains partial and current code cannot answer historical scope.
8. Duplicate retries, conflicting supersession and later failure retain history
   and yield the correct current state.
9. v1 request/verify/route and publication compatibility remains tested while new
   unsupported records fail closed.
10. Rebuild/check remains deterministic, with unchanged canonical inputs and
    outcome counts traceable to exact canonical correction IDs.

These are design acceptance requirements, not claims that proposed new record
types have been implemented or passed runtime tests. The final review also checks
the register against a fresh compiler run, validates subject hashes and verifies
the existing regression suite. Final results:

| Check | Result |
| --- | --- |
| Finding register compared with fresh compiler output | Exact 39/39 coverage, unique IDs; 27 distinct subjects |
| Workstream allocation | A1: 15, A2: 22, A3: 2; every finding assigned once |
| Subject hashes | Every task/event row digest and knowledge byte hash matches |
| Source preservation | Database bytes, board tables, knowledge, raw inventory, rules and compiler source match the pinned baseline |
| Generated output | Exact byte match in read-only check; generated cross-links validate |
| Existing architecture regression suite | 59 passed in 6.53 seconds |
| Frozen Phase 0 suite | 20 tests passed; zero errors, failures or skips; 4.763 seconds |
| Proposed new record types / outcome logic (initial review) | Design reviewed; implementation followed in v1.2 |
| Applied canonical corrections (initial review) | 0 at research baseline; see applied results below |

The two QA passes produced a concrete remediation design and an exhaustive source
register. Future implementation and authenticated corrective publications are
required before outcomes can change. Historical unknowns may remain disclosed
unknowns even after current provenance and verification gaps are addressed.
