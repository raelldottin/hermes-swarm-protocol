# Delayed index reconciliation: research, plan, design and QA

Scope: the eight unresolved findings discovered after the v1.2 pilot's
point-in-time acceptance. This correction does not expand fleet membership
or change the selected model/provider.

## Research

The accepted generation was written at 2026-10-08 08:31:45 UTC. ByteRover
subsequently wrote `curated_content/general/_index.md` at 08:47:28,
`curated_content/_index.md` at 08:48:14, and `_index.md` at 08:48:27.
The indexes arrived after the successful curator response, review approval,
and first build/check. The prior acceptance was valid for its source snapshot;
it did not prove that asynchronous indexing had finished.

The current check reports stale output and eight unresolved findings:

| Source | Findings | Cause |
| --- | ---: | --- |
| `_index.md` | 4 | Two previous annotations no longer bind the changed bytes; current revision has no valid adoption or work link |
| `curated_content/_index.md` | 2 | New index lacks reviewed adoption and canonical work links |
| `curated_content/general/_index.md` | 2 | New index lacks reviewed adoption and canonical work links |

The prose summarizes historical project and source-audit context. Its earlier
45-outcome count refers to the pre-curation generation. Neither index prose,
opaque `children_hash` metadata nor a source timestamp proves factual truth,
original authorship or completion of future indexing. Original captured
revisions and independent request assessment remain available.

## Plan and design

1. Preserve a private board backup and pin the complete knowledge inventory,
   not only the three affected files. Save a reviewed plan with exact hashes,
   original successor targets and explicit contextual task links.
2. Create a maintenance task through the public Kanban API, supplying the
   authenticated creator and `workspace_kind: dir`. Keep it blocked while
   doing this bounded maintenance to avoid automatic worker dispatch.
3. Capture each affected file unchanged. Publish maintainer adoption and
   work-link records through the registered tool handlers. The root records
   explicitly supersede their original annotations. New index records have
   no invented predecessor or author.
4. Reuse stable keys based on path, revision and relation. Resume using the
   same pinned plan; never derive a retry's predecessor from its own newly
   published record. Abort if the reviewed inventory changes. Partial valid
   publications remain canonical and cannot imply whole-plan completion.
5. Complete the maintenance task, inspect any newly emitted lifecycle
   provenance, then rebuild and check the complete wiki. Independently
   reproduce files, verify hashes and links, and confirm source preservation.

Adoption expresses reviewed responsibility for this historical context.
Work links connect it to inspected tasks; they do not verify every sentence.
No source text is executed and no knowledge node is rewritten. Do not call
`brv_curate` just to repair index metadata: that would begin another indexing
cycle. The read-only compiler already invalidates changed sources correctly.

## QA pass and iteration

Regression coverage must reproduce a successful initial build/check followed
by a changed root index and two late child indexes. Check must then fail.
Six exact-revision corrections must retain all eight findings with outcomes:
six current adoption/link outcomes and two retired annotation histories.
The compiler must reject a changed reviewed revision and an invalid successor.
It must support repeated source revisions without erasing prior records.

The operational completion gate is a final source-preserving build/check
after all reviewed index writes are present. A finite quiet interval does not
guarantee that later writers will never change sources. Record the inventory
fingerprint and run preflight again immediately before any rollout; future
source changes reopen the appropriate findings.

## Applied results and QA loop

Task `t_72e2b34b` is complete. All three reviewed files were captured unchanged.
Six canonical corrections retired the two stale root annotations and provided
current adoption/work links for the root and two new indexes:

| Index | Adoption event | Work-link event |
| --- | --- | --- |
| `_index.md` | `swe_bca09b62a4d183484f8df535c2b8f3fb` | `swe_5ff067816993204143e9dd07941693b0` |
| `curated_content/_index.md` | `swe_cdfcdc0a68a3933a8ebafc55170fb1a4` | `swe_35fdeaf731a54033b1acc59a21156ee7` |
| `curated_content/general/_index.md` | `swe_269c5ec7327faa779816b925e669c9da` | `swe_6d6de2871e49e08af0ab084e4edd5d87` |

The frozen plan was executed twice; the second execution returned duplicate
receipts for all six corrections. No curation call was made and no knowledge
bytes were rewritten. All pre-existing board rows were retained: nine tasks,
392 events, 14 runs, 75 comments and seven dependency links. The new maintenance
task's explicit creator and directory workspace avoided further actor gaps.

Iteration QA passes the full 94-test suite, including the exact eight-finding
late-index regression and repeated supersession chains. The live generation
has 55 retained outcomes: 15 adopted revisions, 15 work links, two independently
verified request gaps, 21 disclosed identity findings and two superseded
annotation histories. Zero findings remain unresolved.

Build and check exit 0. An independent rebuild reproduces all 129 files byte
for byte; manifest hashes match and all 1,244 local links resolve. The build,
check and rebuild leave the board, knowledge, raw evidence and trusted rule
fingerprints unchanged. Updated maintenance rules require whole-inventory
review and another preflight before rollout. The finding register preserves
baseline hashes separately from the root index's newly reviewed revision.

The follow-up PR records its exact tested head and merge result. This scoped
correction leaves the remaining fleet rollout gates recorded in delivery.
