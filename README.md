# kinox

> A local-first, governed, cost-efficient workspace for running coding agents.
> Cheap local intelligence does the groundwork; expensive frontier models do only
> the high-value reasoning; everything an agent does is observable, reversible, and
> fails in a known direction.

The full vision is in [`vision.md`](vision.md); the immutable core in
[`alignment/CONSTITUTION.md`](alignment/CONSTITUTION.md).

## Layout

```
kinox/
├── kx                  # entrypoint (banner+menu · doctor · new)
├── install.sh          # idempotent setup (uv sync)
├── pyproject.toml      # uv + strict tooling (ruff, pyright, pytest)
├── alignment/          # CONSTITUTION.md (the three theses, immutable)
├── kernel/             # the constant: contracts, manifest, router, metrics (100% tested)
├── products/groom/     # first product: the squire grooming pipeline
├── adapters/           # claude_code.py — the only Claude-specific wiring
├── daemon/             # the Model Control Plane broker (minimal for now)
├── projects/           # user projects (gitignored)
├── docs/ · tests/ · .github/workflows/
```

## Develop

```sh
uv sync                 # create the env from the lockfile
uv run pytest           # run the suite (incl. the architecture guardrail)
uv run ruff check .     # lint
uv run pyright          # type-check
./kx                    # banner + menu
```

The kernel imports nothing from `products/` or `adapters/` — enforced by
`tests/test_architecture.py` from commit #1.
