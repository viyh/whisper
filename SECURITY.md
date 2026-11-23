# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.5.x   | Yes                |
| < 0.5   | No                 |

## Reporting a Vulnerability

If you discover a security vulnerability in Whisper, please report it
responsibly using one of the following methods:

1. **GitHub Security Advisory** (preferred): Use the
   [Report a vulnerability](../../security/advisories/new) link on this
   repository's Security tab to open a private advisory.

2. **GitHub issue or pull request**: Open an [issue](../../issues) or a
   [pull request](../../pulls) on this repository.

Please include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce or a proof of concept.
- The version(s) affected.

## Response Timeline

- **Acknowledgement**: within 7 days of the initial report.
- **Fix or mitigation**: best-effort, typically within 30 days for
  confirmed issues.

This project is maintained on a best-effort basis.

## What Whisper Can't Protect Against

Whisper encrypts and decrypts in the browser, so the server, its storage and
its logs never see a secret, its password or its link token. That protection
depends on the page itself, which the server sends on every visit. Someone who
controls the running server, the container image, or a proxy in front of it
can serve modified JavaScript that reads secrets and passwords as they are
typed or opened. Keep the host and image up to date, deploy a pinned image
version, and terminate TLS at a proxy you trust.

Also outside what Whisper can protect:

- **The sender's and recipient's devices**: malware, a browser extension with
  access to the page, or a clipboard manager can read a secret there.
- **Someone with both the link and the password**: that is everything needed
  to open the secret.
- **Rate limits across restarts and instances**: the per-IP limits are kept in
  memory, so a restart (including a Cloud Run cold start) resets them, and
  each instance counts separately. The per-secret lock after
  `max_failed_attempts` wrong passwords is stored with the secret and isn't
  affected.

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
