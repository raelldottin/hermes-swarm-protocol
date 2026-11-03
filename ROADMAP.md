# Hermes Swarm Protocol — Product Roadmap

**Planning baseline:** 2026-11-03  
**Status:** Proposed roadmap for review; not an authorization to deploy or mutate a fleet  
**Repository:** `raelldottin/hermes-swarm-protocol`  
**Current plugin manifest:** `swarm-protocol` v1.2.0  
**Scope:** Swarm coordination, evidence-backed knowledge, generated Swarm Wiki, and fleet operational safety — **not** the Hermes Agent core, a replacement Kanban, or a new memory service  
**License:** GPL-2.0-only (see `COPYING`)

> **How to read this document.** “Shipped/recorded” means a capability or historical acceptance evidenced in this repository. “Proposed” means future work; its dates and metrics are planning targets, not promises or claims about the presently running fleet. Historical acceptance receipts do not prove that a current fleet is still configured identically. Verify current state before acting.

## 1. Executive direction

**Product vision:** make a multi-agent Hermes fleet accountable: workers request work, publish traceable claims and evidence, independently verify results, reconcile disagreements, and retrieve current shared knowledge without confusing memory with proof or human-readable wiki output with canonical state.

**Positioning:** a **thin, auditable protocol** over existing Hermes Kanban and shared project knowledge, with a reproducible, non-authoritative Swarm Wiki. The product should be useful to a maintainer of one project and repeatably safe across many isolated project boards.

**Product promises**

1. **One work authority:** Hermes Kanban retains tasks, ownership, dependencies, run history and review lifecycle.
2. **One existing knowledge authority:** per-project ByteRover trees retain curated knowledge; optional Hindsight exports can be *read as explicitly authorized, unverified contextual snapshots*.
3. **Authenticated, append-only coordination:** requests, verification, publications and corrections bind runtime identity and exact source revisions in Kanban records.
4. **Evidence is inspectable:** original captures are immutable; verification PASS requires available independent non-memory evidence for the stated scope.
5. **Wiki is disposable:** Markdown, index, digest, chronology and findings regenerate deterministically from canonical inputs; generated prose never authorizes actions.
6. **Failure is visible and bounded:** uncertainty, stale source references, incomplete snapshots, contradictory verdicts, identity gaps and permission denials are surfaced, not silently repaired.
7. **Operations do not depend on upstream acceptance:** versioned, tested releases and rollback are possible without changing Hermes core or creating a new daemon/database.

**Primary users and jobs to be done**

| Persona | Job | Observable outcome |
| --- | --- | --- |
| Project owner / operator | Know what the swarm did, who approved it, and what needs attention | One reviewable status and finding trail tied to exact canonical records |
| Orchestrator | Request and route work across named roles without guessing | Linked Kanban request; unresolved routes fail closed |
| Worker / builder | Publish reproducible outputs and evidence | Immutable captures, typed references, idempotent publication |
| Independent verifier | Assess the actual deliverable and scope, not an LLM summary | Explicit PASS/FAIL/INCONCLUSIVE/BLOCKED plus source-bound live evidence |
| Knowledge maintainer | Curate, supersede and reconcile shared knowledge | Hash-bound accepted revision with retained contradictions and history |
| Auditor / future worker | Trace current claims back to originals | Navigable wiki and reproducible manifest; unknowns remain visible |

## 2. Current product baseline: what exists

### Recorded shipped capabilities

- Five plugin tools: `swarm_request`, `swarm_verify`, `swarm_route`, `swarm_publish` and `swarm_capture`; `hermes-swarm/v1` requests and compatible `hermes-swarm/wiki-v1` / `wiki-v2` publications.
- Runtime-derived identity, deterministic routing, two-stage verification, typed evidence, immutable hashed capture, idempotent publication, contradiction/reconciliation records, source-bound synthesis and strict legacy compatibility.
- Read-only, single-project wiki compiler with consistent SQLite reads, stable tree/raw snapshots, source hashes, lint, atomic generation publication and a no-write `--check` path. The generated wiki is never a system of record.
- Optional Hindsight **snapshot ingestion**: explicit memory-bank allowlist; content-addressed files; provenance/source checks; incomplete-page detection using the captured `total`; labels for unverified, invalidated and generated memories. Compilation does **not** query Hindsight.
- Fleet memory audit/migration; monotonic ByteRover curate timeout compatibility; task-status SQLite guard and conservative status-repair utility; isolated fleet release/canary tooling.
- GPL-2.0-only licensing with tracked `COPYING` and a release-contents regression test.

### Historical acceptance evidence (not a current-state assertion)

The repository's 2026-10-09 fleet-rollout record documents **eight boards, 43 identities and six ByteRover trees**, 154 tests passing for the pinned release, all 43 fresh-profile checks, eight serial live canaries, and matching reproducible wiki projections. The HSP pilot's delayed-index maintenance record documents 55 retained audit outcomes, zero then-unresolved findings, 129 generated files and 1,244 valid local links. Other fleets retained 7,591 unresolved historical/source findings at the recorded rollout; these must **not** be relabeled as verified or resolved by a clean operational canary.

### Gaps and constraints that motivate the roadmap

- No `.github/workflows` directory is present on the roadmap baseline. Local test instructions exist; repeatable GitHub CI and release gates are a proposed addition.
- Hindsight snapshot **reader exists**, but the PR #8 description says there was not yet a producer of complete, paginated snapshots. An approved producer/integration is future work, not a shipped live connector.
- No user-facing `swarm_lint` tool is registered; scheduled lint currently uses the compiler/CLI. An API is optional and needs security review.
- The release and fleet canary tooling exists, but continuous evidence freshness, performance/cost baselines, compatibility policy and a low-friction operator experience need productization.
- Current historical attribution cannot be reconstructed from missing evidence. A new future-writer guarantee can improve new records but must not fabricate old actor identities.
- Reconciliation across several projects is **not** permission to create cross-board read access or a global authority.
- The Swarm Protocol must evolve independently from Hermes core PRs, including the distinct Kanban respawn-guard work in another repository.

### Release naming and status

- Treat **v1.2.0** as the recorded plugin feature baseline, not a claim of a new version being released by this roadmap.
- Future names below (v1.2.x, v1.3, v1.4, v2 candidate) are **proposed targets**. Version bumping, tagging, installing and fleet deployment each require independent review.
- A release's evidence must name its full commit SHA, plugin version, compatible Hermes revision, test environment and provenance of its acceptance receipts.

## 3. Prioritization and delivery schedule

The schedule is directional. Sequence follows dependencies and acceptance gates; no team-size or delivery-capacity assumptions have been made.

| Horizon | Proposed window | Priority | Milestone / customer outcome | Exit gate |
| --- | --- | --- | --- | --- |
| **M0 — Trusted delivery baseline** | Nov–Dec 2026 | P0 | Contributor can test, audit and package a precise revision repeatably | Hermetic CI, permissions review, pinned compatibility, release checklist |
| **M1 — Freshness and audit operability** | Dec 2026–Jan 2027 | P0 | Operator can identify stale or unresolved sources before using an index | Source preflight, alerts/reports, deterministic and no-write proofs |
| **M2 — Complete Hindsight snapshot pipeline** | Jan–Mar 2027 | P1 | Authorized memory snapshots reach the wiki without becoming proof | Tested paginated producer, bank isolation, provenance and failure semantics |
| **M3 — Independent evidence workflow** | Mar–May 2027 | P1 | Verification/reconciliation becomes easier and harder to misuse | Guarded actions, explicit scope, conflicts and review UX validated |
| **M4 — Repeatable fleet lifecycle** | May–Jul 2027 | P1 | Maintainers upgrade, canary and roll back safely | Immutable releases, fleet receipts, staged rollout/rollback rehearsal |
| **M5 — Interoperability and adoption** | Jul–Oct 2027 | P2 | New project fleets adopt the protocol with fewer custom steps | Compatibility matrix, reference fixtures, install/upgrade guidance |
| **M6 — Optional next-generation exploration** | After M5 gates | P3 | Scale navigation without compromising single-project authorization | Separate threat model and ADR; no production feature commitment |

**Prioritization rule:** security/provenance correctness > durable state safety > independent verification > source freshness > operating ergonomics > performance optimization > optional integrations.

## 4. M0 — Trusted delivery baseline (P0)

**Outcome:** every proposed change is testable, reproducible and attributable before merging or installation.

| ID | Deliverable | Acceptance criteria |
| --- | --- | --- |
| HSP-001 | Baseline and compatibility inventory | Pin tested Hermes Python/API revision(s), plugin loading mode, SQLite schema, ByteRover format and Hindsight export contract; clearly label untested versions |
| HSP-002 | GitHub CI | Add a minimal least-privilege workflow for syntax/lint, GPL/license checks, unit tests and isolated protocol/SQLite integration; report separate Hermes-dependent tests rather than skipping them silently |
| HSP-003 | Repeatability and adversarial tests | Run fixtures for spoofed identity, wrong board, unauthorized paths/banks, symlinks, forged verification, duplicate IDs, changed bytes, stale commits, conflict and publisher concurrency |
| HSP-004 | Release provenance | Document one tested-commit release manifest, test receipts, source/build hashes, compatibility, rollback and named review/approval gates; retain the existing `ops/fleet_release.py` flow |
| HSP-005 | Maintainer governance | Add contribution and security-reporting guidance, decision ownership, change log conventions, version policy and roadmap issue/PR templates; keep GPL notice/distribution compliance |

**Gate:** CI and local reproduction agree at the **same** revision; tests never write real Hermes home/boards; no workflow exposes private credentials to pull-request code. Track external Hermes-dependent tests distinctly from a minimal self-contained suite. Do not turn historical test counts into current CI claims.

**Proposed release:** v1.2.x reliability baseline after passing these checks.

## 5. M1 — Source freshness and actionable audit (P0)

**Outcome:** a green wiki means the current authorized inputs are checked, not that a historically green generation was once reviewed.

| ID | Deliverable | Acceptance criteria |
| --- | --- | --- |
| HSP-101 | Source preflight operator command | Deterministically inventory current board, ByteRover indexes, captured artifacts, trusted rules and authorized snapshots; report revision drift and missing provenance before rollout |
| HSP-102 | Change-aware synthesis invalidation | Changed root/child index bytes, source supersession or delayed writes invalidate affected acceptance; explicit exact-hash successor publications are required |
| HSP-103 | Finding ownership and triage | Render finding class, severity, canonical source, revision, responsible role and suggested canonical remediation; distinguish unresolved current gaps, disclosed historical unknowns and superseded outcomes |
| HSP-104 | Scheduled read-only audit | Document cron/supervisor invocation of `ops/build_wiki.py --check --lint` with output snapshot pinning, exit-code semantics and bounded retries; optional notification integration is not a new daemon |
| HSP-105 | Report format | Publish a stable machine-readable lint/manifest summary with source fingerprint, finding counts by class, checked revision and whether the generated output matches |

**Gate:** repeatable changed-index fixture; byte-identical independent rebuild and local-link validation; all denied/malformed inputs leave **all** canonical stores unchanged. A source change must turn the relevant prior acceptance stale. Historical unknowns cannot silently disappear.

**Proposed release:** v1.3 audit/freshness usability.

## 6. M2 — Authorized Hindsight snapshot production (P1)

**Outcome:** optionally ingest Hindsight memory as *context* while preserving ByteRover authority and the offline compiler contract.

| ID | Deliverable | Acceptance criteria |
| --- | --- | --- |
| HSP-201 | Snapshot producer contract | Define opt-in adapter/companion invocation with explicit project, approved bank, API endpoint/revision, capture identity, destination and source/evidence metadata; never embed credentials in snapshot files |
| HSP-202 | Complete pagination and consistency | Fetch every unfiltered page for one authorized bank, track `total`, reject duplicate IDs or inconsistent totals, detect changes during capture and fail closed or mark a snapshot incomplete |
| HSP-203 | Immutable materialization | Write content-addressed `hindsight-snapshot/v1` JSON by exclusive/atomic creation; preserve original capture and provenance; no in-place edits or partial file promoted as complete |
| HSP-204 | Strong source and bank boundary | Reject unauthorized project/bank, out-of-root paths, symlinks, altered source hash, stale evidence and invalid metadata; support explicit bank rotation/revocation without erasing historical captures |
| HSP-205 | Projection and recovery tests | Test complete, missing-page, changed-total, interrupted, invalidated and generated-consolidation fixtures; retain `UNVERIFIED` labeling and unchanged ByteRover-only output when memory is omitted |

**Dependencies:** clarify which component owns the producer with the repo-automation RA-CP-004 / RA-CP-003 memory-adapter work. This repository should own the **schema and consumer compatibility**; a producer can live in a separately authorized integration if that avoids unnecessary credential or network authority in the plugin.

**Gate:** no Hindsight server call during compilation; absent/incomplete banks never appear empty or verified; memory-only evidence cannot satisfy `swarm_verify` PASS; source fingerprint and full bank identity are reproducible. No public or cross-project export of restricted memories.

**Proposed release:** v1.3.x optional integration after M1.

## 7. M3 — Evidence-first verification and reconciliation (P1)

**Outcome:** operators see exactly why a request or claim passed and what remains disputed; unsafe shortcuts are denied at the protocol boundary.

| ID | Deliverable | Acceptance criteria |
| --- | --- | --- |
| HSP-301 | Structured verification checklist | Present criterion index/digest, exact request scope and commit, independent verifier, live-evidence type/hash, verdict and exclusions; no implicit carryover from another task |
| HSP-302 | Scoped pre-action safety | Research a **narrow, explicit** guard for sensitive protocol operations (publishing PASS, accepting synthesis, resolving contradiction); block unsupported evidence/identity, not routine reads or model reasoning |
| HSP-303 | Contradiction resolution workflow | Surface both active positions and their original sources; require authenticated, evidence-linked, scoped reconciliation and explicit supersession; retain chronology |
| HSP-304 | Maintainer review of synthesis | Make source digest coverage, node revision, stale dependency, approval identity and uncertainty legible before `synthesis` publication; never equate curator completion with approval |
| HSP-305 | Optional `swarm_lint` surface | After an ADR and threat model, consider a strictly read-only tool exposing existing compiler findings. It must not edit boards, synthesize, fetch arbitrary URLs, or enlarge permissions |

**Gate:** integration scenarios for self-verification, same actor under multiple roles, partial criteria, contradictory verdicts, later revocation and stale source; independent live proof required. No source-prose instruction injection can authorize a publication or action.

**Proposed release:** v1.4 workflow/assurance.

## 8. M4 — Fleet release, migration and observability (P1)

**Outcome:** the protocol can be safely adopted and updated across fleets without confusing release installation with active-process loading.

| ID | Deliverable | Acceptance criteria |
| --- | --- | --- |
| HSP-401 | Release pinning and integrity | Extend existing worktree-based release procedure to verify full commit, tracked files, permissions/modes, plugin origin, version, signed/recorded manifest if adopted, and rollback target |
| HSP-402 | Config drift and policy audit | Read-only comparison of per-profile plugin enablement, project-role routing, ByteRover workdir, `auto_extract` policy and curator timeout; preserve unknown configuration keys |
| HSP-403 | Safe staged rollout | Preflight -> private backup -> fresh-profile import -> isolated board canary -> review gate -> limited fleet cohort -> expanded cohort; each phase emits evidence and can abort |
| HSP-404 | Fleet health report | Per-board compiler freshness, unresolved vs historical findings, active plugin revision, failed tools/curation, last canary and backup status; avoid a new always-on store or daemon |
| HSP-405 | Recovery rehearsal | Prove rollback of plugin selection and compatible config/DB state; detect unsupported downgrade/schema changes; audit original source preservation and leftover processes |
| HSP-406 | Upstream compatibility retirement | On newer Hermes builds, test whether native task-status constraints supersede local SQLite triggers; remove compatibility shim **only** after equivalent safety is verified |

**Gate:** successful small-cohort and full-cohort dry runs with named operator approval, restored source-state checksums and no unauthorized cross-board writes. No automatic production apply on tag push or PR merge without a separately approved deployment gate.

**Proposed release:** v1.4.x operational readiness.

## 9. M5 — Developer experience and interoperability (P2)

**Outcome:** an operator can understand and adopt the project without reconstructing a historical fleet incident.

| ID | Deliverable | Acceptance criteria |
| --- | --- | --- |
| HSP-501 | First-project tutorial | Setup from clean Hermes profile; create linked request; capture original artifact; independently verify; publish/curate; generate/check wiki; inspect original; roll back |
| HSP-502 | API/schema reference | Document `hermes-swarm/v1` and `wiki-v1/v2` records, strict decoding, typed evidence, idempotent retry, source-identity rules, error/exit codes and version compatibility |
| HSP-503 | Migration tooling UX | Dry-run by default, JSON reporting, explicit apply approval, private checksum-verified backups, retained unknown keys and reversible profile settings |
| HSP-504 | Compatibility matrix | Document tested combinations of Hermes release, Python, platform, Kanban schema, ByteRover, optional Hindsight snapshot schema and future plugin manifests |
| HSP-505 | Onboarding and support | Contributor guide, architecture decisions (ADRs), troubleshooting cookbook, release notes, issue labels, triage expectations, minimal examples and security boundaries |
| HSP-506 | Static audit export | Reviewable sanitized wiki/evidence report for stakeholders, with redaction and source-access controls; never include secret/private original artifacts by default |

**Gate:** a fresh operator completes an end-to-end sandbox walkthrough using only documented commands; each step has independently checkable output and a safe undo path. Untrusted pages and memory do not gain execution or verification authority.

**Proposed release:** v1.5 adoption experience.

## 10. M6 — Research backlog, not committed work (P3)

These require separate design records, threat models and cost/benefit analysis:

- **HSP-601 — Federated navigation:** link *summaries* across explicitly authorized projects without creating cross-board read access, a global claims database, or a second task authority.
- **HSP-602 — Longitudinal provenance:** investigate read-only import of ByteRover revision history where a stable format and source identity exist; never infer original author from timestamps.
- **HSP-603 — Scale and latency:** incremental compilation or caching only if benchmarked source sizes warrant it; cache keys must include full input/provenance/rules fingerprints.
- **HSP-604 — Optional integrations:** static dashboards, Obsidian/Git exports, additional memory providers or notifications, subject to independent access and disclosure review.
- **HSP-605 — Future schema revision:** versioned protocol evolution only when backward-compatible extensions are inadequate; ship old-reader denial and migration fixtures first.

**Explicit non-goals:** replacing Hermes Kanban, building an autonomous orchestration daemon, accepting LLM-written wiki pages as truth, making memory a verification authority, continuous unapproved curation, silent historical identity reconstruction, unrestricted cross-project search, hidden automatic recovery, or deploying to a live fleet as a side effect of documentation or CI.

## 11. Engineering architecture and quality bar

### Canonical data flow

`Hermes Kanban (tasks/runs/comments/events) + ByteRover project tree + immutable .swarm/raw + optional authorized Hindsight export -> deterministic compiler/linter -> disposable .swarm/wiki -> human/agent read-only navigation`

- A worker writes only via authenticated protocol tools; model-authored data cannot supply effective identity, privileges or timestamp.
- A compiler opens board data read-only with one consistent read transaction; it snapshots file inventories and detects mid-read drift. Cross-store snapshots record their fingerprints rather than claiming impossible distributed atomicity.
- Paths are normalized and confined; reject traversal, unexpected symlinks, overlapping source/output, foreign output ownership, altered hashes and unauthorized bank or project names.
- Evidence access obeys source ACLs; a public Git repo or rendered wiki must never automatically publish private captured data.
- Record updates are append-only, explicit supersession; same-key/same-payload retries are idempotent, different-payload collisions fail.
- Persist uncertainty: `UNKNOWN` historical actors, `UNVERIFIED` memory and claims, `INCOMPLETE` or changed Hindsight captures, and contradictory verdicts remain distinguishable.

### Required test layers

| Layer | Core scenarios |
| --- | --- |
| Unit / schema | Envelope validity, version compatibility, typed sources, permissions, status enums, stable IDs, collisions |
| Integration | Real Hermes plugin discovery; Kanban lifecycle; ByteRover data paths; capture/publish/verify/route; denial does not write |
| Adversarial | Symlink/traversal; malicious source prose; forged actor; wrong board/bank; stale hash; conflicting verdict; corrupt/incomplete snapshots |
| Determinism | Two independent compiles same bytes/manifest/links; input drift invalidates output; `--check` never writes |
| Process / rollout | Fresh profiles, immutable commit loading, isolated kanban canary, rollback, source-preservation hashes and crash recovery |
| Compatibility | Supported Hermes/Python/platform matrix and memory/schema revisions; no unexamined upstream assumptions |
| Performance | Fixture sizes and source counts pinned; measure compile time, peak memory, index freshness lag, publication latency and error rate before setting SLOs |

## 12. Proposed product KPIs and acceptance thresholds

**These are target definitions, not measured current performance.** Record baseline measurements during M0/M1 and adjust targets in a reviewed ADR.

| Measure | Proposed target / policy | Measurement |
| --- | --- | --- |
| Unauthorized canonical writes | **0 tolerated** | Before/after DB, ByteRover/raw and config fingerprints on denied actions |
| Verification integrity | **100% of PASS verdicts** have exact scope, independent runtime identity and available non-memory live evidence | Publication audit and adversarial fixtures |
| Snapshot completeness | **100% of projected Hindsight banks** are authorized and disclose whether `count == total` | Snapshot manifest and lint |
| Deterministic output | **100% byte match** under identical input and rules | Paired independent build/check |
| Source freshness | **100% of production promotions** use a fresh preflight after last source/knowledge change | Deployment receipts with fingerprints |
| Finding integrity | **0 silent drops or invented attributions** | Finding-ID audit and supersession fixtures |
| Release provenance | **100% of releases** bind full commit, manifest, tests, compatibility and rollback | Release receipts |
| Canary containment | **0 unauthorized cross-board/profile writes**; no orphaned processes in isolated canary | Runtime snapshots and cleanup checks |
| Operator adoption | Sandbox first-project flow succeeds without undocumented manual database edits | Follow-the-docs test |
| Performance | Establish p50/p95 compile and freshness baselines first; set capacity targets by workload and platform | Benchmark fixtures, time/memory and source counts |

A zero unresolved-finding number on one board is **not** the north-star metric: legitimate unknown historical actors may remain. Prefer traceability, honest uncertainty, freshness, useful verified outcomes and safe repeated operations.

## 13. Dependencies, risks and mitigations

| Risk / dependency | Consequence | Mitigation / decision gate |
| --- | --- | --- |
| Hermes core changes its plugin API or Kanban schema | Tool/trigger breakage or unsafe assumptions | Pin tested revisions, maintain compatibility matrix and fail closed on unknown schema |
| ByteRover delayed index writes | Previously accepted synthesis becomes stale | Whole-inventory final preflight, exact-byte successor review, no silent reacceptance |
| Hindsight paging, changing banks or authorization | Missing memory falsely appears absent/complete | Explicit bank authorization, complete pagination, `total` and stable capture checks |
| Memory summarized as factual proof | False verification or unsafe action | Non-memory live evidence requirement, visible `UNVERIFIED` and typed reference checks |
| Source injection or path escape | Privilege escalation/data leak | Trust boundary tests, output escaping, no arbitrary fetch/execute, constrained roots |
| Accidental publication of fleet secrets or raw captures | Confidentiality breach | Private backups, redaction and access review; no automatic public artifact export |
| Historical missing identities | Misleading attribution or audit | Explicit unknown disclosure; new writers improve future records only |
| Unreviewed multi-profile configuration rewrite | Routing/provider regressions | Strict audit, preserve unknown keys, detect duplicate YAML blocks, backup and compare |
| Release/auto-update triggers | Unexpected live gateway changes | Non-deploying CI, immutable tags, manual promotion gates and staged canaries |
| Different machines/environments | Non-reproducible test/curation behavior | Record OS/Python/Hermes/provider version, locked dependencies and baseline failures |
| Scope creep into new central services | Multiple authorities, bigger failure domain | ADR before architectural changes; default to existing Kanban and ByteRover |

## 14. Delivery governance and decision records

**Ownership by role:** protocol maintainer owns schemas/tool policy; project maintainer owns source approval and accepted synthesis; independent verifier owns acceptance decisions; operations owner owns fleet credentials/backups/release; security reviewer owns permissions/secret exposure; documentation owner owns usability. One identity may perform several jobs in different contexts **except** the same work cannot self-verify.

**Definition of ready for an implementation issue:** user problem, exact current source reference, affected protocol boundary, acceptance tests, denied/legacy cases, dependency owner, rollback and privacy impact, measurable exit signal.

**Definition of done:** implementation + regression + negative/adversarial tests; exact SHA; all relevant CI results classified; docs and compatibility updated; non-mutation proof where applicable; independent review; changelog; no production change unless separately authorized.

**Promotion model:** issue/ADR -> branch -> draft PR -> independent review -> clean CI and fixed baseline -> immutable test release -> isolated canary -> explicit deployment approval -> staged rollout -> final source preflight -> audit receipt. A documentation merge, release tag or passing test is never implicit authorization for a live-fleet update.

**External coordination:** the Hermes fork handles core dispatcher/runtime fixes; repo-automation may produce the separately authorized memory snapshots; this repository owns the swarm protocol plugin, wiki contracts and their safety tests. Mirror only explicit, reviewed integration contracts. Retire compatibility patches after equivalent upstream behavior is independently demonstrated.

## 15. First actionable backlog (next 30–60 days)

Deliver in dependency order. The suggested owner is a **role**, not an assignment of a specific person or autonomous agent.

| Order | Issue seed | Priority | Suggested owner | Evidence required |
| --- | --- | --- | --- | --- |
| 1 | HSP-001 inventory current source, API and runtime revision | P0 | Protocol maintainer | Version matrix, integration probes, pinned HEAD |
| 2 | HSP-002 establish isolated least-privilege CI | P0 | Build/CI maintainer | Workflow run URL, tests, denied secrets, baseline table |
| 3 | HSP-003 release manifest and dry-run promotion contract | P0 | Release operator | Exact release artifact, verification, rollback rehearsal |
| 4 | HSP-101 source freshness preflight | P0 | Wiki maintainer | Delayed-index changed-hash fixture, stable audit output |
| 5 | HSP-103 finding ownership and usable classifications | P0 | Auditor | Historical disclosures kept distinct from open remediation |
| 6 | HSP-201 agree Hindsight producer ownership and schema | P1 | Protocol + integration owners | ADR, authenticated bank permission and pagination design |
| 7 | HSP-202 end-to-end complete snapshot producer test | P1 | Integration owner | Fake paged provider, changed-total and interruption fixtures |
| 8 | HSP-301 scoped verification reporting prototype | P1 | Verifier | Criteria-to-evidence trace, fail-closed self-verification |
| 9 | HSP-401 immutable release/canary matrix | P1 | Operations owner | No-write production proof and safe recovery evidence |
| 10 | HSP-501 documented first-project walkthrough | P2 | Documentation owner | Clean sandbox end-to-end completion |

Create implementation issues only after reviewing overlap with existing branches and linked repo-automation work. Do not create duplicate background swarms or switch production configuration to satisfy roadmap checkboxes.

## 16. Change management and references

Review this roadmap at least once per release candidate or quarterly, whichever is sooner. Update each milestone with **planned / active / validated / released / deferred / rejected**, the exact PR/commit, acceptance evidence and material changes to dependencies. Never rewrite historical acceptance as if it represented the current live environment.

**Source-of-truth documents inside this repository:**

- [README](README.md) — product semantics, five tools, install and current documented deployment.
- [Swarm Wiki design contract](docs/swarm-wiki-design.md) — architecture, record trust, typed evidence, compiler and QA gates.
- [Swarm Wiki operations](docs/swarm-wiki-usage.md) — live commands, output/check semantics, Hindsight snapshot format and incomplete capture handling.
- [Swarm Wiki maintenance rules](docs/SWARM_WIKI.md) — retained unknowns, exact revisions and source preflight.
- [Fleet rollout and receipts](docs/swarm-wiki-fleet-rollout.md) and [acceptance JSON](docs/swarm-wiki-fleet-acceptance.json) — historical eight-board, 43-identity, six-tree evidence.
- [Delivery and integration QA](docs/swarm-wiki-delivery.md) — v1.2 pilot and source remediation evidence.
- [Index reconciliation](docs/swarm-wiki-index-reconciliation.md) — delayed-index invalidation and correction.
- [Fleet memory recovery](docs/recovery.md) — ownership, ByteRover policy, backups and configuration safety.
- [Worker safety](docs/kanban-worker-safety.md) — status-enum compatibility and conservative repair.
- [Merged Hindsight snapshot PR #7](https://github.com/raelldottin/hermes-swarm-protocol/pull/7) and [completeness PR #8](https://github.com/raelldottin/hermes-swarm-protocol/pull/8) — current optional reader and producer gap.

**North star:** a maintainer can answer “What work was requested, what evidence supports the result, who independently verified it, what is still uncertain, and can I reproduce the current view?” without trusting a worker's prose or editing canonical history.
