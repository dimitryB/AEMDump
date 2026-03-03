# Security Policy

## Supported Versions

Security fixes are applied on the `main` branch.

## Reporting a Vulnerability

Please do not open public issues for potential vulnerabilities.

Report privately to the maintainer with:

- A description of the issue
- Reproduction steps or proof of concept
- Potential impact

The maintainer will acknowledge receipt and follow up with remediation status.

## Credential Handling

- Prefer `--password-env` over `--password` to avoid exposing secrets in shell history.
- Avoid using `--insecure` outside controlled environments.
