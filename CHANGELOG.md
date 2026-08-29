# Changelog

## 0.2.0 - 2026-08-28

- Resolve external inventory tools only from reviewed absolute paths and record versions.
- Run probes with a minimal environment and distinct timeout, execution-error, and nonzero states.
- Neutralize spreadsheet-formula prefixes in every CSV string cell while keeping JSON exact.
- Recognize worktree and bare Git layouts without following marker symlinks.
- Bound env reads, reject env symlinks, and record disappearance/permission races without aborting.

## 0.1.0 - 2026-05-02

- Initial public release candidate.
- Added read-only collectors for systemd units, crontab entries, executable wrappers, Git repositories, and env-file metadata.
- Added Markdown, JSON, and CSV report formats.
- Added privacy defaults for hostname, home paths, cron previews, and env files.
- Added test suite, CI workflow, setup script, and release documentation.
