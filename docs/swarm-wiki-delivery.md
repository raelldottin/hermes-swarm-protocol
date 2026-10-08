# Swarm Wiki v1.2 delivery evidence

Reviewed 2026-10-08. The research, design review, implementation, source
remediation, deployment and iteration QA are applied. The generated wiki is
an untrusted projection; Kanban, ByteRover and original evidence retain their
own authority. All original findings remain visible with canonical outcomes.

## Latest source preflight after delayed indexing

The initial generation below was later invalidated by asynchronous ByteRover
index writes. Maintenance task `t_72e2b34b` reviewed and captured all three
affected indexes, published six canonical corrections and retained the two
old root annotations as superseded history. All eight reopened findings have
outcomes. Repeating the reviewed plan returned only duplicate receipts.

Current recorded acceptance: 94 passing tests; 55 retained outcomes and zero
unresolved findings; 129 generated files with byte-identical independent
rebuild and matching manifest hashes; 1,244 valid local links and no broken
targets. Existing board rows and knowledge bytes were unchanged by maintenance
and compilation. See [research, plan, design and iteration QA](swarm-wiki-index-reconciliation.md).

Before fleet rollout, repeat preflight against the current source inventory.
Durable curation model configuration, an immutable deployed release and
validation of additional fleet projects remain rollout gates.

## Initial pilot acceptance

| Gate | Applied evidence |
| --- | --- |
| Canonical publication/evidence | Five registered tools, authenticated runtime provenance, compatible v1 plus strict v2 records, immutable captures, source-workspace boundaries and idempotency |
| Read-only compiler | Atomic generations, deterministic manifest and pages; fresh independent rebuild matches all 115 files byte for byte |
| Synthesis/reconciliation | Live ByteRover curation persisted a reviewed topic; explicit review approval and maintainer synthesis event `swe_13bfaf641cf6bf0242424408055da159` bind its exact hash and active source digests |
| Lint/publication | 49 retained current audit outcomes, zero unresolved findings; build and matching check both exit 0; all manifest hashes match and 1,118 local links resolve |
| Deployment/navigation | Default, builder, researcher, security and verifier fresh profiles each register all five tools; effective ByteRover curate timeout is 600 seconds; explicit single-project access roots and maintainer membership |

The 92-test regression suite covers source loss/change, unknown identity,
independence and exact criterion scope, conflicting verdicts, supersession,
untrusted prose, producer workspaces, stale output, symlinks and concurrent
publication. Iteration QA added task-creator disclosures, retirement of stale
annotations only through valid successors, the native `kind: standalone`
manifest declaration, and real audit CLI exit policy tests.

## Source audit outcomes

The original 39 findings on 27 subjects are addressed by 11 exact-revision
adoptions, 11 reviewed work links, two independent request outcomes and 15
unknown-actor disclosures. Adoption does not invent authors or verify all
memory assertions. Historical actors remain unknown. At initial pilot QA, the original 11
knowledge nodes and all pre-existing canonical rows were preserved: seven
tasks, 317 lifecycle events, 12 runs, seven links and six comments.

Maintenance tasks `t_44e964c2` and `t_84d5b601` are complete. Six additional
creator/event gaps on those tasks are disclosed. Four additional findings on
the new curated context/companions have reviewed adoption and work-link
outcomes. The initial 49 outcomes are 13 adopted revisions, 13 work links, two
verified request gaps and 21 disclosed identity findings. The full
[finding register](swarm-wiki-audit-findings.json) retains original source
hashes and correction event IDs separately from later operational findings.

The archived request assessment `swe_9b13ad8a287c3bb978559bfa1a78a9e1` binds
all five original criteria to `855a0194e25c8316f6e460bf708805a4f0d971fc`.
A fresh hsp-verifier run against an independent Git export passed 20 tests,
with zero failures, errors or skips. The exact original document and JUnit
result are captured. This verifies Phase 0 design scope only.

## Live provider iteration

The original `z-ai/glm-5.3` curation returned a response parsing failure
despite CLI exit 0. A flash-model attempt reported completion but stored
nothing and emitted tool-call text. A Kimi attempt returned `Not Found`.
None was accepted as synthesis. The compatibility guard now converts the
observed parse and provider failures into tool errors.

The available `openai/gpt-oss-20b` model persisted the new topic under
`curated_content/general/general_knowledge_extracted.md`. The curator trace
records task `29d63bed-3a3e-4aa9-9a16-bc89997758c9`, one successful upsert,
and explicit review approval. The maintainer reviewed its scope, source IDs,
historical counts and uncertainty, captured the persisted bytes and accepted
the synthesis. Its “45 outcomes” count describes the pre-curation generation;
the current projection includes the new topic and has 49 outcomes.

The original model was restored after the bounded maintenance run. For future
curation, use a compatible tested model and require a persisted, reviewed
node before publishing synthesis. The wiki compiler does not depend on a
model call; provider failures leave earlier accepted knowledge intact.

## Reproducibility and integration

Build, matching check and independent rebuild left the canonical board,
knowledge inventory, immutable raw inventory and rules unchanged. The
source fingerprints are recorded in the finding register. Private config
and database backups are retained under the local Hermes backup directory.
Coordinator automatic extraction remains disabled; worker extraction and
unrelated configuration are preserved.

PR 2 was validated at `6a56d76d118868c180b8a48d394ae24437daf3b4`
(23 tests) and merged as `d4b109457874c186e53a5cf74c32ebb59574a06a`.
PR 3 was validated at `855a0194e25c8316f6e460bf708805a4f0d971fc`
(20 tests) and merged as `5dfdefec0d6866933a61232df7dae5cbf1202267`.
The combined integration uses an isolated checkout of merged main, preserving
the original dirty checkout and `.serena/`. The final integration PR records
the exact tested head and GitHub merge result, avoiding a self-referential
commit hash in this document.

Optional scheduled lint should run the documented compiler command with
`--check` in the authorized project context. It must report unresolved
findings or stale output as failure and retain disclosed historical findings.
Git/Obsidian navigation is optional; it creates no new runtime authority.
