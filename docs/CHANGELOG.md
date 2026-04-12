# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-04-11

### Security
* Argon2id password hashing - Replaced bcrypt (server-side) and PBKDF2 (client-side) with Argon2id for both. Argon2id is memory-hard and resistant to GPU/ASIC brute-force attacks.
* AES-256-GCM encryption - Replaced CryptoJS AES-CBC with Web Crypto API AES-256-GCM (authenticated encryption). Eliminates padding oracle attack surface.
* Rate limiting - Added Flask-Limiter (10 requests/minute per IP) on the secret retrieval endpoint to prevent brute-force attacks.
* Per-secret lockout - Secrets lock after 10 failed password attempts.
* One-time secret race condition fix - Atomic claim pattern prevents concurrent requests from both retrieving a one-time secret. Uses file rename (local), dict lock (memory), head+delete (S3), and generation-match delete (GCS).
* Security headers - Added Content-Security-Policy, X-Frame-Options (DENY), X-Content-Type-Options (nosniff), Referrer-Policy (no-referrer), and Permissions-Policy via nginx.
* Strict CSP - No `'unsafe-inline'` in `script-src`. All inline scripts and event handlers moved to external JS files. All third-party scripts consolidated to a single CDN (jsdelivr). Inline styles replaced with the `hidden` HTML attribute where possible.
* Input validation - All POST endpoints validate JSON fields, types, and allowed values. Returns 400 on invalid input. Unsupported version values are strictly rejected (400).
* ProxyFix hardened - Changed from `x_host=1` to `x_for=1, x_proto=1, x_host=0` to prevent host header injection.
* Nginx body size - Reduced `client_max_body_size` from 1G to 2m to match application limits.
* Config key warning - Startup warning if `secret_key` appears to be a default or is too short.
* PBKDF2 iteration count - Increased client-side PBKDF2-SHA256 key derivation from 210,000 to 600,000 iterations per OWASP recommendations.
* Modulo bias fix - Random password generation now uses rejection sampling to eliminate bias.
* Password visibility toggle - Password fields default to hidden (`type="password"`) with eye icon toggle on both create and retrieve pages.
* HSTS enabled by default in nginx config (2-year max-age, includeSubDomains, preload).
* Flask debug mode decoupled from LOG_LEVEL to prevent accidental Werkzeug debugger exposure in containers.

### Added
* `argon2-cffi` - Server-side Argon2id hashing.
* `argon2-browser` - Client-side Argon2id hashing via WASM (CDN).
* `Flask-Limiter` - Rate limiting middleware.
* `init-index.js` / `init-show.js` - Extracted page initialization scripts.
* Version marker system - Secrets store a `version` field as a protocol marker for future format migrations. Currently only version 2 is supported.
* Configurable Argon2id parameters via config.yaml (`argon2_time_cost`, `argon2_memory_cost`, `argon2_parallelism`). Server passes params to client so they stay in sync.
* SRI integrity hashes on all CDN script and stylesheet tags.
* Test suite (pytest) covering secret class, config loading, memory storage backend, and all Flask routes (41 tests).
* GitHub Actions CI: lint (ruff + bandit), test, Docker build, dependency audit.
* `SECURITY.md` - Responsible disclosure policy.
* `CONTRIBUTING.md` - Development setup and contribution guidelines.

### Changed
* Upgrade to Python 3.12 + Debian Slim (from Python 3.10 Alpine) for better glibc compatibility, CVE tracking, and package support.
* Upgrade Flask 2.2.3 to 3.1.3
* Upgrade Gunicorn 20.1.0 to 23.0.0
* Upgrade all Python dependencies to latest versions
* Upgrade Bootstrap to 5.3.3 (standardized both pages, was 5.0.2 / 5.2.0-beta1)
* Upgrade clipboard.js 2.0.10 to 2.0.11 (now served from jsdelivr instead of cdnjs)
* Changed `max_data_size_mb` to `max_data_size_kb` for finer-grained upload size control (default: 100 KB). Server-side limit accounts for base64 encoding overhead.

### Removed
* v1 crypto compatibility - CryptoJS, PBKDF2 (client-side), and bcrypt (server-side) are removed. For decrypting pre-0.2.0 v1 secrets, use the `release/0.1.0_to_0.2.0` branch.
* `bcrypt` Python dependency.
* `crypto-js` CDN script tag.
* `cdnjs.cloudflare.com` from CSP `script-src` (all third-party assets now served from jsdelivr).
* jQuery - Replaced with vanilla JS (fetch API, native DOM, Bootstrap 5 native tooltips).
* Flask-Cors - Was imported but never used.
* Dead argon2.js script tag - Referenced a non-existent file; replaced with proper argon2-browser WASM library.
* All inline JavaScript - Extracted to external JS files.

### Fixed
* Config loader bug - `load_config` mutated the default config dict in-place, preventing `check_config` from detecting unknown configuration keys. Typos in config.yaml were silently accepted.
* Config exception hierarchy - `ConfigMissingError` and `ConfigUnknownError` failed at construction time due to incorrect super().__init__() calls. `ConfigUnknownError` now correctly inherits from `ConfigError`.

## [0.1.0] - 2022-05-25

### Added
* Complete rewrite for pluggable storage backends
* Add storage backends: S3, GCS, local, memory
* Add file sharing support
* Add size limit for files
* Support web URL sub paths

### Changed
* Storage cleaner runs periodically in background
* Better logging and debugging
* Run as unprivileged user
* Use SHA256 hashes for item paths
* Upgrade to python 3.10
* Upgrade JS libs: jquery@3.6.0, bootstrap@5.0.2, clipboard.js@2.0.10, crypto-js@4.1.1
* Use CDN JS libs
* Use config files for configuration
* Update look and feel for Bootstrap 5
* Improved user flow (such as focus on load, clipboard buttons, order of fields, etc.)
* Generate random password by default
* Better config parsing. Check for default config parameters or extra keys.
* Updated documentation: README, in-line code

### Removed
* DynamoDB support/dependency. DynamoDB stores a max of 400 kB items, so unfeasible for backend with new file support.

### Fixed
* Fix grid support for mobile responsiveness ([PR #4](https://github.com/viyh/whisper/pull/4)), by @kdeenanauth

### Security
* Use PBKDF2 (salted SHA512, 10000 rounds) for client-side password hashing
* Use bcrypt for server-side password hashing
* Simplify crypto

## [0.0.4] - 2016-11-05

Initial Release
