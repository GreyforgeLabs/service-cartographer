# Contributing

Thanks for improving `service-cartographer`.

## Local Setup

```bash
./scripts/setup.sh
```

## Development Checks

```bash
ruff check src/service_cartographer/*.py tests/*.py
pytest
service-cartographer scan --systemd-scope off --no-cron --repo-root . --format json
```

## Standards

- Keep collectors read-only.
- Use `subprocess.run()` with argument lists, never shell-form commands.
- Do not emit secret values from env files or cron entries.
- Add focused tests for new parsing or classification behavior.
- Keep runtime dependencies at zero unless a dependency removes meaningful risk.

## Pull Requests

Open a PR with:

- a short summary of behavior changed
- validation commands run
- any privacy or security tradeoffs introduced
