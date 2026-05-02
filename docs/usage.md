# Usage Notes

## Focused Audit

Use repeated `--focus` flags to reduce a large workstation scan to one workflow family.

```bash
service-cartographer scan \
  --repo-root ~/work \
  --wrapper-dir ~/bin \
  --focus ingest \
  --focus worker \
  --format markdown
```

## Local-Only Fixture Scan

Use this shape in tests, CI, and examples where systemd or cron should not be queried.

```bash
service-cartographer scan --systemd-scope off --no-cron --repo-root .
```

## Classification Limits

The classifier is intentionally conservative. It can identify keep candidates and retirement candidates, but it does not know organizational ownership. Treat `review` as a useful result, not a failure.

