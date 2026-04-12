# Contributing to Whisper

## Development Setup

```bash
# Clone and enter the repo
git clone https://github.com/viyh/whisper.git
cd whisper

# Create a virtualenv and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r src/requirements.txt -r src/requirements-dev.txt

# Copy the default config
cp src/config.default.yaml src/config.yaml
# Edit src/config.yaml — at minimum, set a random secret_key (32+ chars)
```

## Running Locally

See the [Quick Start](README.md#quick-start) section in the README for
Docker-based usage. To run the Flask dev server directly:

```bash
cd src
python app.py
```

## Running Tests

```bash
cd src
pytest tests/ -v
```

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting. CI
will fail on any finding. You can check locally with:

```bash
ruff check src/
```

## Pull Requests

- Branch from the latest `release/*` or `master` branch.
- CI must pass (lint, tests, Docker build).
- Keep commits focused — one logical change per PR.
- Write a clear PR description explaining *what* and *why*.

## Security Issues

Please do **not** open a public issue for security vulnerabilities.
See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.
