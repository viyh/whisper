# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.2] - Unreleased

### Security
* Close the remaining ways full secret IDs could reach logs, found in code review of 0.3.1. Flask's own `Exception on /<path>` error lines, exception tracebacks (file paths, GCS object names), and gunicorn tracebacks and `critical` messages were not redacted. Redaction now happens once, in a logging filter on the shared gunicorn/app log handlers, so every line they write is covered, including tracebacks and stack info. `short_id()` at call sites remains as a first layer.
* Redaction now also matches uppercase IDs and IDs not separated by a slash, e.g. with an `app_url_base` that has no trailing slash or next to percent-encoding.

### Fixed
* The log-injection test could never fail (its payload was past the 8 characters `short_id` keeps); it now places the newline and payload inside them.
* Local backend errors without an OS error reason logged `None`; they now log the error type.
* The Dockerfile now removes pip, setuptools, and wheel from the base image by name, instead of everything in `/usr/lib/python3/dist-packages`, so a future base image change can't silently remove something needed.

### Changed
* `whisper.gunicorn_logging.RedactingLogger` only installs the filter; its per-method overrides are gone, which also removes per-request formatting work at the default log level.
* Tests force the error paths (failing request, cleaner traceback, gunicorn access/error logs) and check that no full ID is written (98 tests).

## [0.3.1] - 2026-11-17

### Security
* Logs no longer contain full secret IDs. A secret ID is the random part of the share link, so anyone who could read the logs could see every live link, then try passwords against it or trip its failed-attempt lockout. Logs now show the first 8 characters (enough to correlate lines for one secret), and storage backends no longer log file paths or object keys that contain the full ID. IDs taken from the URL are also stripped of non-hex characters before logging, so they can't inject log lines.
* Gunicorn's access log (request path and Referer) and its DEBUG request lines also showed full secret IDs. A custom gunicorn logger now shortens any secret ID in its output the same way. Platform request logs outside the container (Cloud Run, ALB access logs) still record full URLs.
* Removed the base image's unused system pip, setuptools, and wheel from the runtime image. pip's vendored setuptools metadata (70.3.0, CVE-2025-47273) was the only fixable finding in Docker Scout; it was not exploitable, as pip only vendors `pkg_resources` and nothing runs pip at runtime.

### Fixed
* CodeQL `py/reflective-xss` alert in a test-only helper (`test_proxy.py`), which now returns JSON.

### Added
* Tests that full secret IDs never appear in app or gunicorn logs and that URL input can't inject log lines (94 tests).

## [0.3.0] - 2026-11-17

### Changed
* Container rebuilt on [Docker Hardened Images](https://dhi.io) (`dhi.io/python:3.14-debian13`) with a two-stage build. The runtime image has no shell or package manager, pip is removed from the app's virtualenv, and tests are no longer shipped. The image is 232 MB (was 420 MB) with roughly a third of the previously reported OS-level CVEs and none with an available fix.
* nginx removed. Gunicorn now serves requests directly with threaded workers (`WEB_THREADS`, default 2), request timeouts, and request line/header limits. Security headers (CSP, HSTS, X-Frame-Options, etc.) and the `/elb-status` health check moved into Flask, unchanged. Whisper must run behind a TLS-terminating proxy, which the README now documents under "Deploying".
* `trusted_proxy_count` keeps its meaning (number of `X-Forwarded-For` entries added by proxies in front of the container); existing values stay correct.
* Building from source needs `docker login dhi.io` (free Docker account). CI logs in using the `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` repository secrets and skips the image build when they are not set.

### Added
* `WHISPER_CONFIG` environment variable: the config YAML itself, used instead of `CONFIG_FILE` when set. For platforms that inject secrets as environment variables but not files (e.g. ECS).
* Terraform examples for GCP (Cloud Run, GCS, Secret Manager, domain mapping) and AWS (ECS Fargate, ALB, ACM, S3, Secrets Manager) in `examples/terraform`.
* README "Deploying" section and Cloud Run guidance for `trusted_proxy_count`.

### Removed
* nginx, `scripts/run.sh`, and `src/nginx.template.conf`.
* The outdated CloudFormation example, replaced by the Terraform examples.

### Fixed
* An empty or non-mapping config file now gives a clear configuration error instead of a crash.

### Upgrading from 0.2.x
* Drop-in for config, ports (`WEB_PORT`, default 8000), health check path, and file ownership (still runs as uid 65534).
* There is no shell in the image: `docker exec ... sh` and custom entrypoints or command overrides that use `/run.sh` no longer work.
* Up to `WEB_THREADS` password hashes run at once (0.2.x ran one), each using `argon2_memory_cost` of RAM. The default of 2 fits a 512 MB container.

## [0.2.2] - 2026-11-17

### Security
* Rate limiting behind a load balancer was effectively global. nginx inside the container appends the address of whatever connected to it, so behind an ALB or other proxy every client appeared to come from the proxy's IP and shared one 10/min limit, letting a single client block secret retrieval for everyone. New `trusted_proxy_count` setting (default `0`, the previous behavior) tells Whisper how many extra `X-Forwarded-For` entries upstream proxies add, so the real client IP is used for rate limiting and logs.

### Added
* `trusted_proxy_count` config option, validated as a non-negative integer at startup.
* README "Running Behind a Proxy" section with recommended values per deployment.
* Tests for client IP resolution and spoofing resistance (83 tests).

### Changed
* README: document the 30-day retention for unread one-time secrets, add `update_secret` to the storage backend method table, and correct the client-side PBKDF2 iteration count (600,000).

## [0.2.1] - 2026-11-17

### Security
* eMudhra CA compromise - Pin `certifi==2026.10.23` (fixed in >= 2026.10.19, GHSA-6q48-6c7w-9gw2) so the Python HTTP clients (requests, boto3, google-cloud-storage) no longer trust the affected roots. The Debian base image already ships the fixed `ca-certificates` (20250419+deb13u1).
* Expired secrets were retrievable until the next cleaner run. Expiry is now checked on every read.
* The storage cleaner thread exited permanently on any backend error, so expired secrets were never purged afterwards. Errors are now logged and the cleaner keeps running.
* S3 one-time secrets could be retrieved by multiple concurrent requests, because S3 deletes are idempotent. Claims now use a conditional delete on the object's ETag.
* A wrong-password request racing a successful retrieval could write a just-claimed one-time secret back into storage. Failed-attempt counts now use a new `update_secret` operation that never recreates a deleted secret (conditional writes on S3/GCS, no-create open on local disk).
* Local-disk secret files are now created with owner-only (0600) permissions.
* The memory backend no longer logs password hashes and encrypted data at DEBUG level.
* Docker image runs `apt-get upgrade` at build time to pick up pending Debian security updates, and `build.sh` always pulls the latest base image.

### Changed
* Upgrade to Python 3.14 (python:3.14-slim, Debian trixie). CI updated to match.
* Upgrade Python dependencies to latest, including Flask-Limiter 4, Gunicorn 27, protobuf 7, boto3 1.44, google-cloud-storage 3.17, requests 2.34, urllib3 2.8.
* Upgrade dev tooling: pytest 9, pytest-cov 7, ruff 0.17, bandit 1.9, pip-audit 2.10. CI audit job uses the pinned pip-audit.
* Rewrote the GCS and S3 storage backends with a shared structure. Dates are uploaded with the object in one request (GCS), listings are paginated (S3 previously stopped at 1000 objects), only `<bucket_path>/<id>.json` objects are touched, and objects missing date metadata fall back to the stored secret instead of never expiring.
* `build.sh` tags `0.2.1`, `0.2.1.<timestamp>`, and `latest`.

### Fixed
* GCS cleaner crashed on connection errors (referenced an undefined variable and a non-existent `_connect` method).
* Lint cleanups for ruff 0.17 (mutable defaults, blind exceptions, legacy `super()` calls).

### Added
* Tests for the local, S3 (botocore Stubber), and GCS (mocked) backends, the cleaner, and expiry/claim races (72 tests).

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
