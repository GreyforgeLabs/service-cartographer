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
