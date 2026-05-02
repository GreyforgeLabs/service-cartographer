# Security Policy

## Supported Versions

Security fixes target the latest released version.

## Reporting a Vulnerability

Report vulnerabilities through GitHub security advisories or by contacting Greyforge through the public site at <https://greyforge.tech>.

## Threat Model

`service-cartographer` is a local read-only scanner. It must not start, stop, enable, disable, delete, or modify services. Reports may still describe sensitive local structure, so users should review output before sharing it.

## Privacy Commitments

- Env file values are never emitted.
- Hostname is hidden by default.
- Home paths are shortened by default.
- Inline secret-looking command assignments are redacted in cron previews.

