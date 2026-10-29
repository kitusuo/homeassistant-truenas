# homeassistant-truenas (kitusuo fork) — the local gate.
#
# Supply-chain policy: a hash-pinned uv.lock, a 7-day cooldown on every dependency update (`exclude-newer` in
# pyproject.toml, so it binds every resolver, Dependabot included), and an SCA scan (pip-audit) in the gate.
# CI runs the same `make sync` and `make check`.

.PHONY: sync lockcheck lint test audit check lock upgrade

# Install the locked deps into .venv. `--locked`, not `--frozen`: it FAILS when uv.lock no longer matches
# pyproject.toml, where --frozen would install the stale lock and audit it (PR #1 review).
sync:
	uv sync --locked

# The lock matches pyproject.toml (the same check, without installing).
lockcheck:
	uv lock --check

# Formatting, as upstream kept it (black).
lint:
	uv run --frozen black --check custom_components tests

# The suite, with the coverage gate (fail_under in pyproject.toml).
test:
	uv run --frozen pytest --cov=custom_components/truenas --cov-report=term-missing

# SCA: scan the locked deps against the OSV / PyPI advisory DB.
audit:
	uv run --frozen pip-audit

# The full gate — run before committing.
check: lockcheck lint test audit

# Re-resolve uv.lock after a pyproject change. It advances NOTHING on its own, so it cannot clear an audit
# finding: that is `make upgrade`. Both honour the 7-day cooldown from pyproject.toml.
lock:
	uv lock

# Advance pins to the newest versions older than the cooldown; PKG=<name> for one package.
upgrade:
	uv lock $(if $(PKG),--upgrade-package $(PKG),--upgrade)
