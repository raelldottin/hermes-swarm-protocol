# Swarm Wiki fleet rollout gates

This follow-up closes the curation configuration, immutable plugin release,
and project/profile canary gates left after PR #5. The scope is all existing
swarm project fleets. Existing board history, source knowledge, profile roles,
and the original authored checkout must be preserved.

## Research and plan

The initial inventory found eight boards and 42 named profiles plus default.
Only default and the four HSP worker profiles had explicit Wiki mappings and the
600-second curation deadline. The global plugin symlink still pointed into
the authored checkout. ByteRover's active model was `z-ai/glm-5.3`; earlier
accepted synthesis used `openai/gpt-oss-20b` temporarily before restoring it.

1. Resolve each existing board, project, profile, knowledge tree, repository,
   task workspace root, maintainer and maintenance task owner from live
   configuration. Report ambiguous mappings rather than infer authority.
2. Produce a reviewable configuration plan that adds explicit Wiki mappings
   and deadline settings while preserving every unrelated configuration key.
3. Validate the plan and rollback behavior with isolated fixtures, then apply
   it with private backups and compare the actual result with the plan.
4. Select `openai/gpt-oss-20b` persistently through the public ByteRover CLI.
   Verify the selection in new processes and prove reviewed stored synthesis
   and source-grounded recall. Exit code alone is not acceptance.
5. Install a complete clean Git commit into a dedicated release directory;
   verify its tree and tests, then atomically switch the plugin symlink.
6. Register the plugin under every configured profile in new processes.
   Check effective deadlines, membership, routing and authorization failures.
7. Run a bounded maintenance canary for every fleet using public Kanban and
   registered Swarm tools. Preserve pre-existing board rows and require an
   idempotent retry, cross-project denial and a current compiler check.
8. Repeat acceptance after corrections, merge the validated PR, and record
   the tested release identity, canonical receipts and remaining limitations.

## Design

Configuration changes are additive to each profile's existing plugin
settings. Default can maintain all configured projects; a fleet-specific
maintainer is chosen only from existing authorized profiles. Knowledge roots
and task roots remain explicit and project-specific. The compiler never
treats generated prose as independent proof or invents historical actors.

The installed release is addressed by its full Git commit, independent of
mutable branches or worktrees. Installation verifies a clean committed tree
and preserves the previous symlink target for rollback. No release claims
include uncommitted changes or the original checkout's authored state.

Canary tasks are created blocked to prevent automatic dispatch, remain
bounded to configuration and plugin evidence, and are completed through
public APIs after verification. Existing unresolved historical findings in
other fleets are reported separately from successful deployment canaries.
A clean canary does not resolve unrelated source history or establish fleet
workload success. Future curation may change indexes and reopen findings;
source preflight remains required before each rollout.

## QA and iteration results

### Durable curation configuration

ByteRover now persistently selects `openai/gpt-oss-20b` through its public
model-switch command. Fresh model queries in all six effective knowledge
contexts confirm the same model and provider. These contexts serve eight
boards because Home Lab and Opnory IaC share Opnory's existing knowledge tree.

The accepted input mode is inline content, matching Hermes's memory adapter.
An external-file attempt was rejected, a file-mode GPT attempt returned a
processing error, and a DeepSeek attempt returned an empty response. None
was accepted as storage. The inline GPT run actually upserted a dedicated
planned-contract node. Task `7af01251-6d7c-414d-a9b9-5de20d25c231` was reviewed
and approved. Independent recall task `c72cb888-8e7f-4d4f-8b58-1bb601339211`
retrieved `curated_content/general/generated_extracted.md` and correctly
identified marker `HSP-FLEET-CURATION-20261009`, the model, 600-second deadline,
and the planned status. This verifies source-supported recall of a deployment
contract. It does not establish production workload acceptance.

Automatic related-node/index maintenance subsequently produced additional
context revisions. Canonical task `t_ff9e34cd` captured eleven reviewed
revisions and published their provenance without rewriting any source prose.
Its 33 initial replies and three historical synthesis correction replies
returned only duplicates when repeated. All earlier board rows and captures
were retained. The historical synthesis body was unchanged; its related-node
metadata was reviewed separately, with no claim of a new model inference.

### Configuration and release design QA

The reviewed plan adds explicit board, repository, workspace, knowledge,
task-root, profile and maintainer mappings across all eight fleets. Default
has explicit maintenance authority. Existing cross-fleet role routing remains
authorized, and every original role map and extraction policy is preserved.
All 43 original configuration files have private mode-0600 backups. Applying
the reviewed plan a second time changes no files. Both the configured and
instantiated curation deadlines are 600 seconds in every profile; coordinator
automatic extraction remains disabled.

Fixture-first QA caught and corrected omitted repository mappings, a failure
after symlink activation, immutable permission checks, duplicate YAML keys,
and hidden release modifications. Release acceptance compares raw committed
blobs and permissions, rejects extra paths and ignores no index flags. A
failed post-activation directory sync restores the prior symlink target.

### Broader compiler iteration

Alepes stores opaque binary cells in `tasks.result` and `task_runs.summary`;
Tachikoma stores them in `task_comments.body` and `task_runs.metadata`, despite
their declared TEXT types. Reproducing fixtures exposed serialization and
prose concatenation failures. The compiler retains those SQLite bytes,
hashes them with typed lossless encoding, and renders only byte length and
SHA256. Binary payloads cannot become prose, inferred passes, publication
records or commit references. Text-only snapshot hashes remain compatible.

Source freshness also exposed historical synthesis retirement: a valid
current successor must retire only its same-author, same-topic historical
knowledge revision. Lost captures and unrelated evidence must remain findings.
The scoped regression and cycle/source-freshness checks govern that correction.

### Final operational acceptance (2026-10-09)

All three operational gates passed across eight boards, 43 identities and six
knowledge trees. The active immutable release is
`f341d77d5a1acdc52a9aefdf1571ac0e215eb558`. Installation checks committed blob
identity, Git modes, unexpected paths, symlinks, hardlinks and read-only
permissions. The global plugin points to that immutable release; the original
authored checkout was preserved. Configuration backups remain private under
`~/.hermes/backups/swarm-wiki-fleet-20261009/configs`.

The exact release passed 154 tests with zero failures, errors or skips. All 43
fresh profiles loaded its actual plugin origin, authenticated identity, five
registered tools, expected project mappings and 600-second curation deadlines.
The reviewed configuration apply was idempotent, changing zero files on retry.

Each of the eight live canaries observed a newly created task as blocked with
zero runs before publishing. A distinct existing fleet profile independently
read the fixture, raw capture and a fresh default-runtime probe. Capture, claim
and verification retries returned duplicates. Wrong-board and outsider calls
were rejected, with immediately adjacent equality checks across all eight
database schemas, tables and counters and every raw tree. Pre-existing rows
were preserved, and each canary task completed through the public Kanban API.
These bounded fixtures establish protocol operation; they do not establish
production workload performance or verify historical source assertions.

Iteration QA corrected the runner's treatment of Hermes's standard `error`
rejection envelope, rejected ambiguous mixed success/error responses, and
required an observed blocked state. Completed reuse is allowed only when the
same task existed before creation. The interrupted HSP attempt `t_2ee33420`
completed on its original release after the harness correction; failed and
successful retry receipts were retained separately. The final eight canaries
used fresh release-specific tasks, rather than reusing that attempt.

All eight generated projections passed reproducibility checks. Every manifest
file digest and local Markdown link was verified. The compiler's `--check`
returns 1 on the seven fleets retaining source findings even when output
matches; HSP returned 0 with no unresolved findings.

The frozen baseline's 7,546 unresolved source findings were all preserved.
During validation, 45 additional `respawn_guarded` events on five pre-existing
tasks produced missing-provenance findings. None was linked to a final canary
task, and no canary source finding was added. These lifecycle findings remain
visible and unresolved; the current source total is 7,591. No historical
assertion was adopted or independently verified to pass operational gates.

| Project | Baseline unresolved | Current unresolved | Live canary |
| --- | ---: | ---: | --- |
| HSP | 0 | 0 | passed |
| Alepes | 409 | 409 | passed |
| Home Lab | 489 | 498 | passed |
| Life Achievements | 2,359 | 2,377 | passed |
| Opnory | 909 | 918 | passed |
| Opnory IaC | 307 | 307 | passed |
| Tachikoma | 494 | 494 | passed |
| Tunory | 2,579 | 2,588 | passed |

The sanitized, reviewable results are in
[`swarm-wiki-fleet-acceptance.json`](swarm-wiki-fleet-acceptance.json). Detailed
receipts remain private in the isolated rollout worktree's
`.swarm/maintenance/`, including original failed attempts, release installs,
43-profile checks, eight final canaries, audit baselines and exact-release test
results. Existing long-lived Hermes processes must restart before they use the
new plugin; fresh-process loading was verified for every configured identity.
