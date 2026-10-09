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

Final immutable release identity, fresh-profile canaries, board receipts and
compiler iteration acceptance are recorded after final validation below.
