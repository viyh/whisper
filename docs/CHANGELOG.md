# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2022-05-25

### Added
* Complete rewrite for pluggable storage backends
* Add storage backends: S3, GCS, local, memory
* Add file sharing support
* Add size limit for files

### Changed
* Storage cleaner runs periodically in background
* Better logging and debugging
* Run as unprivileged user
* Use SHA256 hashes for item paths
* Upgrade to python 3.10
* Upgrade JS libs: jquery@3.6.0, bootstrap@5.0.2, clipboard.js@2.0.10, crypto-js@4.1.1
* Use CDN JS libs
* Use config files for configuration
* Update look and feel
* Update look and feel for Bootstrap 5
* Improved user flow (such as focus on load, clipboard buttons, order of fields, etc.)
* Generate random password by default

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
