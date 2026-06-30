# Contributing to kinox

## Roles & access model

kinox has two roles, chosen at the login layer (`kx` / `kin`):

- **admin** — full repo. Can edit the kernel, daemon, products, configs, and run
  the gates. This is the owner / maintainer.
- **developer** — scoped to `projects/` only. The hub hides the admin scope, and
  the **dev-guard** (a PreToolUse hook) blocks edits to framework code — anything
  under the repo outside `projects/`.

```bash
kx            # pick admin or developer
kx dev        # straight to developer
kx kin        # straight to admin
```

**How access control actually works (read this).** There is *no local password*,
by deliberate decision. On a local machine a passphrase is bypassable friction,
not security — anyone with shell access can edit the launcher or set the role
env. Real access control lives in two places:

1. **The dev-guard** — enforced locally: a developer session cannot edit
   framework code (it covers the file-editing tools; it is a guardrail, not an
   airtight sandbox — it does not police arbitrary `Bash`).
2. **GitHub** — who has push/merge access, branch protection, and PR review. This
   is the meaningful boundary for "only maintainers change the framework."

## Workflow — branch + PR

All changes go through a branch and a pull request (no direct pushes to `main`):

```bash
git checkout -b <type>-<slug> main      # e.g. feat-context-selection
# ... make changes, TDD ...
uv run pytest && uv run ruff check . && uv run pyright   # green gates
git push -u origin <type>-<slug>
gh pr create --fill                      # open a PR for review
```

A maintainer (admin) reviews and merges. CI runs the gates on every PR.

## Green gates (required before merge)

```bash
uv run pytest          # all tests pass
uv run ruff check .    # lint clean
uv run pyright         # types clean (strict)
```

`tests/test_architecture.py` enforces kernel purity: `kernel/` is stdlib-only and
imports nothing from `products/`, `adapters/`, or `daemon/`. Keep it that way.

## Conventions

- TDD: write a failing test first, then the minimal code to pass it.
- Reuse before building (Rule Zero) — search for an existing tool/lib first.
- Keep `kernel/` dependency-light; heavier deps live in the outer layers
  (`daemon`, `products`, `adapters`) behind optional extras.
- Work for a project goes in `projects/<name>/`; the framework itself is for
  admins.
