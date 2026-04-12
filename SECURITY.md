# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | Yes                |
| < 0.2   | No                 |

## Reporting a Vulnerability

If you discover a security vulnerability in Whisper, please report it
responsibly using one of the following methods:

1. **GitHub Security Advisory** (preferred): Use the
   [Report a vulnerability](../../security/advisories/new) link on this
   repository's Security tab to open a private advisory.

2. **Email**: Contact the maintainer directly at the email listed in the
   Git commit history.

Please include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce or a proof of concept.
- The version(s) affected.

## Response Timeline

- **Acknowledgement**: within 7 days of the initial report.
- **Fix or mitigation**: best-effort, typically within 30 days for
  confirmed issues.

This project is maintained on a best-effort basis.

## Scope

In scope:

- Cryptographic weaknesses (key derivation, encryption, hashing).
- Authentication or authorization bypass.
- Server-side injection (XSS, SSTI, command injection, path traversal).
- Information disclosure of stored secrets.

Out of scope:

- Missing best-practice headers on local/development deployments.
- Self-XSS (attacks requiring the victim to paste code into their own
  browser console).
- Denial of service via resource exhaustion (rate limiting is documented
  as per-worker in the README).
