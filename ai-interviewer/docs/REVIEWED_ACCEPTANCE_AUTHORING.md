# Reviewed Acceptance Authoring

P3-A treats `reviewed_acceptance_checks` as a YAML evaluation asset.
The YAML question seed files are the source of truth; the database is only the
runtime copy populated by the existing question seed import flow.

## Author Draft Checks

Use the authoring script with an explicit seed file or seed directory path:

```bash
cd ai-interviewer/backend
python -m app.scripts.author_reviewed_acceptance_checks knowledge/question_seeds
```

The default mode is dry-run. It prints a JSON summary with scanned seeds,
scanned variants, existing reviewed-check coverage, generated draft counts,
stale checks, and skipped reasons. It does not mutate files.

To append missing draft checks to YAML, pass `--write`:

```bash
cd ai-interviewer/backend
python -m app.scripts.author_reviewed_acceptance_checks knowledge/question_seeds/system_design.yaml --write
```

The script only appends missing drafts. Existing `reviewed`, `draft`, and
`deprecated` checks are preserved and never overwritten.

## Review Workflow

Generated checks are always drafts:

```yaml
review_status: draft
reviewed_by: ""
reviewed_at: ""
```

Human review is required before runtime can consume a check. To promote a
draft, edit YAML and set:

```yaml
review_status: reviewed
reviewed_by: qa-lead
reviewed_at: "2026-06-01"
```

Runtime modes `reviewed_shadow` and `reviewed_append` only consume checks with
`review_status: reviewed`.

## DB Sync

After editing YAML, run the existing importer:

```bash
cd ai-interviewer/backend
python -m app.scripts.import_question_seeds
```

The importer copies `reviewed_acceptance_checks` into
`question_variants.reviewed_acceptance_checks` for selector and runtime use.
There is no DB-to-YAML reverse sync, and admin surfaces should not directly edit
the DB copy.

Existing deployed databases need an equivalent migration before importing P2/P3
YAML:

```sql
ALTER TABLE question_variants
ADD COLUMN reviewed_acceptance_checks JSON DEFAULT '[]';
```

## Stale Checks

If a seed or variant version increases, existing reviewed checks may become
stale. The authoring script reports stale checks when
`reviewed_seed_version` or `reviewed_variant_version` is behind the current YAML
version. It does not auto-upgrade them; a human reviewer must re-check and
update the version fields.
