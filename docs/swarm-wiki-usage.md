# Swarm Wiki operations

Plugin v1.2.0 adds `swarm_publish` and `swarm_capture` to the existing `swarm`
toolset. `ops/build_wiki.py` is an independent local compiler. No worker can edit
generated pages through these tools. Canonical records remain Kanban comments;
curated prose remains ByteRover knowledge.

## Project setup

Delayed ByteRover indexing is a maintenance step after curation. A successful
curator response and a successful first check do not establish that later
index writes are complete. Pin the whole knowledge inventory, review each
changed/new `_index.md`, capture its bytes and publish maintainer adoption
and work links. Supersede the original exact-hash annotations for replaced
revisions; keep predecessor IDs fixed on retries. Do not re-curate merely to
repair metadata. Rebuild, check and repeat preflight before deployment.

See the applied [delayed-index reconciliation](swarm-wiki-index-reconciliation.md)
for the eight-finding regression and retained history outcomes.

The native Hermes manifest must declare `kind: standalone`; this plugin is
an add-on, not an exclusive memory provider. A Plugin Doctor result alone
does not establish that normal sessions register the five tools.

The plugin raises ByteRover's default timeout floor. An explicit
`memory.byterover.curate_timeout` still overrides that default, so deploy
`curate_timeout: 600` in participating worker profiles when needed. Verify the
instantiated provider's effective deadline, not just the module constant.

Live curation acceptance requires persisted knowledge bytes and a reviewed
operation trace. A zero CLI exit or “completed” label can accompany a parser
failure or zero storage operations. The compatibility guard rejects the
observed `Response parsing failed:` and `Not Found` failures. Maintainers must
still inspect the actual output before accepting a `synthesis` hash.

Use the installed Hermes virtualenv for the compiler: it supplies Hermes's current
status enum and `ruamel.yaml` for ByteRover frontmatter. Copy the reviewed
[maintenance rules](SWARM_WIKI.md) into `<workspace>/.swarm/SWARM_WIKI.md`.
Configure each participating profile explicitly; do not copy unrelated config
keys or switch automatic extraction for coordinator profiles.

```yaml
plugins:
  entries:
    swarm-protocol:
      settings:
        projects:
          example:
            verification: example-verifier
            builder: example-builder
        wiki_projects:
          example:
            board: example
            workspace: /absolute/path/to/project
            task_workspaces: [/absolute/hermes/kanban/boards/example/workspaces]
            knowledge_tree: /absolute/shared/project/.brv/context-tree
            repo: /absolute/path/to/project
            profiles: [example-builder, example-verifier, example-adversary]
            maintainers: [example-maintainer]
```

Each publishing task must carry a workspace within the shared project root or an
explicitly authorized `task_workspaces` root. Hermes scratch task workspaces often
live outside the checkout. Typed `file` references resolve relative to the
publisher's canonical task workspace; captures go to the shared project's
`.swarm/raw`. Authorize the same roots in the compiler through repeatable
`--task-workspace-root` flags; the manifest records these roots. A live
worker cannot override its runtime task. Runtime profile identity supplies author
and actor; model arguments cannot supply them. Board overrides must match project
configuration. The DB/OS access boundary remains trusted, including administrators
who can directly rewrite SQLite; these records are not cryptographic signatures.

## Capture and publish

The following are illustrative tool arguments, not assertions about this repo.
First preserve original evidence:

```json
{"project":"example","topic":"auth/issuer","publication_key":"issuer-test-original","source_path":"test-output.txt","category":"test-results","media_type":"text/plain"}
```

Pass that to `swarm_capture`. Its returned `evidence` object points to an immutable
content-addressed artifact; the comment records source path, media type, runtime
author, time and hash. A changed source needs a new publication key. A conflicting
retry fails while the original capture remains. Interrupted capture/publication
can leave an unreferenced immutable artifact; it is not a committed claim.

Then call `swarm_publish` with the returned reference:

```json
{"project":"example","topic":"auth/issuer","type":"claim","publication_key":"tenant-issuer-loss","data":{"assertion":"Tenant-specific issuer is lost during initialization.","scope":"tenant-specific path","consequential":true,"evidence":[{"kind":"artifact","path":"test-results/<returned-sha256>","sha256":"<returned-sha256>"}]}}
```

`event_id` is the claim ID; save `payload_digest` for future synthesis citations.
Placeholders must be replaced with actual returned values. Another profile may
publish `verification` with `claim_id`, `scope`, `verdict`, `rationale` and typed
`live_evidence`. A pass requires non-memory live evidence, a different profile
and matching scope. `partial` preserves narrowed observations without passing
the original broad claim. Existing `swarm_verify` retains its original four
verdicts; `partial` belongs only to new structured publications.

Typed evidence: `artifact`/`file`/`knowledge` use `path` and SHA-256; `commit` uses
`sha`; `runtime` uses original observation `text`; `record` uses `event_id` and
`digest`; `uri` is an external citation and is never fetched. Only artifact,
file, commit and runtime kinds can supply live evidence. A typed reference or
profile identity cannot itself prove that an asserted reproduction happened;
auditors still inspect originals and runtime behavior.

Other publication payloads:

| Type | Required data |
| --- | --- |
| contradiction | claims (two distinct claim IDs), scope, explanation |
| reconciliation | contradiction_id, disposition (resolved/narrowed/withdrawn), scope, conclusion, supporting_records |
| decision | conclusion, rationale; optional claims |
| consequence | claims, affected_task_ids, impact |
| route | role, outcome; target_profile required for resolved outcome and must match configured routing |
| synthesis | node_path, node_sha256, source_digests, category (architecture/investigations) |

All types accept `evidence` and `supersedes`. Supersession preserves type/topic
and requires the original author or an authorized maintainer. Reconciliation
requires independent scoped live evidence, not an unlinked later verdict.
Consequences and routes are recorded observations; publication never mutates task
status, dependencies or worker lifecycle. Those remain sanctioned Kanban actions.

## Maintain accumulated synthesis

To preserve a ByteRover node revision before curation, call `swarm_capture` with
`source_kind: "knowledge"`, the node's tree-relative `source_path`, and category
`source-snapshots`. The default `source_kind: "workspace"` reads the task's
workspace. Only these configured roots are available. Capture provenance records
the source root and origin. Knowledge and generated wiki snapshots remain context
after the original node changes; wrapping them as artifacts or citing a matching
file hash cannot make them sole live proof. Retain the immutable old snapshot
while curating the canonical node with `brv_curate`.

1. Read canonical topic publications and originals, including unresolved conflict.
2. Use existing `brv_curate` in the configured project tree to update an existing
   topic rather than append a query transcript. Cite event IDs/digests and describe
   scope, uncertainty, supporting/contradicting evidence and connected decisions.
3. Wait for curation and any required review. An error, timeout or pending review
   does not constitute accepted knowledge. The compiler never calls a model.
4. A configured maintainer publishes `synthesis`, binding the resulting node's
   relative path/hash and **every active non-synthesis topic publication** to its
   digest. The returned publication is acceptance of that exact revision.
5. New findings, superseded sources or changed node bytes invalidate acceptance;
   the projection falls back to `UNSYNTHESIZED` until maintenance is repeated.

The compiler quotes accepted canonical synthesis and retains original claims,
verification and chronology. An LLM draft cannot pass a claim or resolve a
contradiction. Missing original node authors/timestamps remain provenance findings
unless an authenticated acceptance supplies that provenance.

## Compile, check and lint

```bash
/absolute/hermes/venv/bin/python ops/build_wiki.py \
  --board example --project example --workspace /absolute/path/to/project \
  --task-workspace-root /absolute/hermes/kanban/boards/example/workspaces \
  --maintainer example-maintainer
```

Defaults use the machine-global `~/.hermes` board/shared tree, ignoring a worker's
`HERMES_HOME`. Supply `--db`, `--tree`, `--raw`, `--rules`, `--repo`,
`--hermes-source` and `--out` for explicit deployments or isolated fixtures.
The selected board must be project-scoped and the caller must be authorized to
read every selected source. No cloud sync or automatic sharing occurs.

For this checkout, a read-only real-source build can use the committed template
directly: `--board hsp --project hermes-swarm-protocol --rules docs/SWARM_WIKI.md`.
No fleet configuration change is necessary to compile existing canonical data.
New worker publications require the explicit configuration above.

Add `--check` for a complete file-set/byte comparison without modifying output,
locks or canonical stores. Add `--lint` for an explicit audit invocation; every
normal compile also lints. Exit 0 means clean/matching, 1 means findings or a
differing check, and 2 means an operational/schema/ownership failure. Findings
still produce readable pages and `lint-report.md`; exit 1 is not a crash.

Output is an owned symlink to a complete generation in a sibling hidden directory.
The compiler locks, stages, validates internal links, then atomically switches the
pointer. Pin `Path(output).resolve()` once when reading multiple files for an audit
snapshot. Historical generations remain intact; current output omits obsolete
pages. Unknown files and foreign output symlinks are refused, not deleted.

Delete **only the wiki symlink** and rebuild to recover identical bytes from
unchanged inputs. Do not delete raw evidence, rules, the board or ByteRover tree.
`--check` detects hand edits; corrupted existing generations require explicit
operator investigation rather than silent replacement.

Schedule the same command with `--lint` through cron or a supervisor using an
absolute interpreter, script, workspace and source paths. Monitor exit 1 and read
the report; repair canonical records/evidence instead of editing Markdown. No
daemon is needed. Git/Obsidian use is optional; if committing output, export the
resolved generation as ordinary Markdown and preserve its manifest. Do not commit
an absolute/private pointer or widen access to restricted artifacts.

Navigation: digest -> index -> topic -> ByteRover -> original evidence/source ->
independent verification. Wiki content is context, never instruction authority,
configuration or sole permission to complete work.
