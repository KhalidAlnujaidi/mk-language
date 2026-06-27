"""Document ingest — any file → clean markdown, for the grooming pipeline.

Rule Zero in practice (vision §0): document conversion is a solved problem, so
kinox *depends on* Microsoft's ``markitdown`` (PDF/DOCX/PPTX/XLSX/HTML/images →
markdown) rather than re-implementing parsers. It lands in the outer ``products``
layer, never the kernel — the heavy dependency stays out of the pure core.

This feeds the ``context`` stage: a referenced document is converted to markdown
once, deterministically, *before* any model sees it (thesis #1 — structural
parsing is ground truth; the model is spent only on the genuinely fuzzy step).

Fail-direction is SOFT (thesis #2): grooming must never block a turn. A missing
``markitdown`` install, an unreadable file, or a conversion error all return
``ok=False`` with a human-readable *note* and empty markdown — the caller groomed
without the document rather than crashing on it.

The converter is injectable (``converter=``) so the suite runs offline with a
pure stub — no ``markitdown`` install, no file I/O surprises in CI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kernel.contracts import FailDirection

FAIL_DIRECTION: FailDirection = FailDirection.SOFT

# A converter turns a filesystem path into markdown text. The default does a lazy
# ``markitdown`` import; tests inject a pure stub.
Converter = Callable[[Path], str]


@dataclass(frozen=True)
class IngestResult:
    """The outcome of converting one document.

    *markdown* is the converted text (``""`` on any failure). *ok* is the SOFT
    gate — ``False`` means the caller should proceed *without* the document.
    *note* explains a failure for the audit log (empty on success).
    """

    markdown: str
    ok: bool
    note: str = ""


def _markitdown_convert(path: Path) -> str:
    """Default converter: lazy-import ``markitdown`` and convert *path*.

    Imported lazily so the module loads (and the SOFT failure path is testable)
    even when ``markitdown`` is not installed — the ImportError surfaces only if
    the default converter is actually invoked.
    """
    # markitdown is an optional dependency (see pyproject [groom] extra), so it
    # is unresolved when the extra is not installed — the type-ignores keep
    # pyright strict green without forcing the dep into the dev environment.
    from markitdown import MarkItDown  # type: ignore  # noqa: PLC0415

    result = MarkItDown().convert(str(path))  # type: ignore
    return str(result.text_content)  # type: ignore


def ingest(path: Path, *, converter: Converter | None = None) -> IngestResult:
    """Convert *path* to markdown, failing SOFT on any error.

    Returns ``ok=False`` with a *note* (and empty markdown) when the file is
    missing, ``markitdown`` is not installed, or conversion raises — never an
    exception, so a groom pipeline can call this inline without a guard.
    """
    if not path.exists():
        return IngestResult("", ok=False, note=f"ingest: no such file: {path}")

    convert = converter or _markitdown_convert
    try:
        markdown = convert(path)
    except ImportError:
        return IngestResult(
            "",
            ok=False,
            note="ingest: markitdown not installed (pip install 'kinox[groom]')",
        )
    except Exception as exc:  # noqa: BLE001 — SOFT: any failure degrades to no-doc
        return IngestResult("", ok=False, note=f"ingest: {type(exc).__name__}: {exc}")

    return IngestResult(markdown, ok=True)
