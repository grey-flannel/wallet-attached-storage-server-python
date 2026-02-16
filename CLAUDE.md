# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python server implementation for the [Wallet Attached Storage](https://wallet.storage/spec) specification. Built with FastAPI, providing HTTP Signature verification, space/resource CRUD, and pluggable storage backends (in-memory first).

## Commands

All commands use `uv run` (no activating `.venv` directly).

```bash
# Lint & security
uv run ruff check                                    # ruff (primary linter)
uv run flake8 src tests                              # flake8
uv run bandit -r src                                 # security scan (src)
uv run bandit -r tests -s B101                       # security scan (tests, allow assert)
uv run safety scan                                   # dependency vulnerability scan

# Test
uv run -m pytest -vv --cov=src --cov-report=term     # full suite with coverage
uv run -m pytest tests/test_foo.py -k "test_name"    # single test

# Run server locally
uv run uvicorn was_server:app --reload --port 8080

# Build & publish
rm -rf dist && uv build
uv publish -t $(keyring get https://upload.pypi.org/legacy/ __token__)
```

## Project Configuration

Matches the companion client library conventions:

- **Build**: hatchling
- **Python**: >=3.11
- **Ruff**: line-length 120, target py311, rules E/F/N/S (S101 ignored in tests)
- **Pytest**: `--import-mode=importlib`, marker `live` for integration tests
- **Runtime deps**: base58, cryptography, fastapi, uvicorn
- **Dev deps**: bandit, flake8, httpx, keyring, pytest, pytest-cov, ruff, safety

## Architecture

- **`_http_signature.py`** — Cavage draft-12 signature verification (the inverse of the client's signing logic). Parses Authorization headers, extracts Ed25519 public keys from `did:key` identifiers, and verifies signatures.
- **Storage backend** — abstracted behind a protocol; in-memory dict implementation first, designed for file/DB/S3 substitution later.
- **Authorization** — space `controller` field is a DID; the signing DID extracted from the request's `keyId` must match. All writes require a valid signature.
- **Errors** — `application/problem+json` format per spec.

## Companion Client Library

Located at `../wallet-attached-storage-client-python/`. The client's `tests/test_live.py` is the acceptance test suite for this server (runs against `localhost:8080`).

## Issue Tracking

Uses **bd (beads)** — not TodoWrite/TaskCreate/markdown files. See `AGENTS.md` for quick reference.
