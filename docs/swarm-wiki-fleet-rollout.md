# Swarm Wiki fleet rollout gates

This follow-up closes the curation configuration, immutable plugin release,
and project/profile canary gates left after PR #5. The scope is all existing
swarm project fleets. Existing board history, source knowledge, profile roles,
and the original authored checkout must be preserved.

## Research and plan

The initial inventory found eight boards and 42 named profiles plus default. Only default
and the four HSP worker profiles had explicit Wiki project mappings and the
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

Pending implementation and live acceptance.
