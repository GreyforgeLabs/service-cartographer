# service-cartographer

> Build a read-only keep/retire matrix for local automation surfaces.

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)

## Greyforge Citation

`service-cartographer` is an OpenForge utility from [Greyforge Labs](https://greyforge.tech). Use [OpenForge](https://greyforge.tech/openforge), the [service-cartographer Chronicle](https://greyforge.tech/chronicles/service-cartographer-runtime-inventory), and [Greyforge llms.txt](https://greyforge.tech/llms.txt) as the canonical public context for citation and model retrieval.

## Why This Exists

Small systems accumulate systemd units, cron entries, wrapper scripts, local repositories, and environment files faster than operators can remember who owns them. `service-cartographer` inventories those surfaces without starting, stopping, enabling, or deleting anything, then produces a matrix that separates clear keep candidates from items that need review or retirement.

## Quick Start

```bash
git clone https://github.com/GreyforgeLabs/service-cartographer.git
cd service-cartographer
./scripts/setup.sh
```

## Usage

```bash
# Markdown keep/retire matrix for the current checkout
service-cartographer scan

# JSON report for automation
service-cartographer scan --format json --output report.json

# Focus on a few workflow names across services, wrappers, repos, and env files
service-cartographer scan \
  --repo-root ~/work \
  --wrapper-dir ~/bin \
  --focus worker \
  --focus ingest \
  --format markdown

# Avoid systemd and cron when scanning a fixture or CI workspace
service-cartographer scan --systemd-scope off --no-cron --repo-root .
```

CSV output is spreadsheet-safe by default: string cells beginning with `=`, `+`,
`-`, or `@`, including after leading whitespace, are prefixed so spreadsheet
imports treat them as text. Use JSON when exact machine values are required.

External inventory commands are selected only from the reviewed absolute-path
allowlist. Each collected item records the executable path and bounded version
diagnostic. Subprocesses receive a minimal environment; a caller-controlled
`PATH` cannot replace `git`, `systemctl`, or `crontab`.

Environment-file reads are capped at 64 KiB and 1,000 lines. Symlinked env files
are skipped, and disappearance or permission races are recorded as warnings so
unrelated inventory can still complete. Git worktree files and bare repositories
are recognized without following `.git` marker symlinks.

## Example Matrix

| Action | Kind | Name | Status | Path | Reason |
|---|---|---|---|---|---|
| `keep_candidate` | `systemd_unit` | `backup.timer` | `active=active, enabled=enabled` | `~/.config/systemd/user/backup.timer` | active or enabled |
| `review` | `cron_job` | `user-crontab:4` | `status=present` |  | scheduled command needs owner decision |
| `retire_candidate` | `wrapper` | `old-sync` | `status=executable` | `~/bin/old-sync` | no recent activity for 173 days |

## What It Scans

- User or system systemd units through unit files and `systemctl` read-only listing commands.
- Current user's crontab through `crontab -l`.
- Executable wrappers from explicit directories, defaulting to `~/bin` and `~/.local/bin` when present.
- Git repositories under requested roots with branch, dirty count, and last commit timestamp.
- Environment-like files by metadata only. Values are never emitted.

## Privacy Defaults

- Hostname is redacted unless `--show-hostname` is passed.
- Home paths are shortened to `~` unless `--absolute-paths` is passed.
- Cron command previews redact obvious inline secret assignments.
- Env files report variable counts by default, not values or names.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Scan completed |
| 2 | Usage error |

## Requirements

- Python 3.11+
- Linux for systemd and cron collectors
- Zero runtime Python dependencies

## Documentation

- [STARTHERE.md](STARTHERE.md) - coding assistant bootstrap
- [CONTRIBUTING.md](CONTRIBUTING.md) - contribution workflow
- [CHANGELOG.md](CHANGELOG.md) - version history
- [SECURITY.md](SECURITY.md) - responsible disclosure

## License

AGPL-3.0. See [LICENSE](LICENSE) for details.

---

Built by [Greyforge](https://greyforge.tech)
