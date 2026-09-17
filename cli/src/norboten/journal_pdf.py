"""A journal as a PDF: `e` in the TUI's Journals section, or on a journal's own screen.

The site renders journals dark, because that is what the site is. Paper is the other way round, so
the print stylesheet (site/static/print.css) inverts the palette and keeps the green only as an
accent. Rendering is WeasyPrint, which is the one pure-Python engine that gets `@page` right —
running headers, page numbers and `break-inside: avoid` on a code block all matter in a document
someone is going to print and annotate.

WeasyPrint is an extra (`NORBOTEN_EXTRAS=pdf` for install.sh), because it needs Pango and cairo on
the system and most people only ever read journals in a browser.
"""

from __future__ import annotations

import html
from pathlib import Path

from norboten.journal import Journal
from norboten.paths import repo_root

STYLE_FILE = "print.css"
_INSTALL_PDF = "curl -fsSL https://norboten.org/install.sh | NORBOTEN_EXTRAS=pdf sh"


class PdfUnavailable(RuntimeError):
    pass


def _markdown() -> object:
    try:
        from markdown_it import MarkdownIt
    except ModuleNotFoundError as e:  # pragma: no cover - the extra is not installed
        raise PdfUnavailable(f"markdown-it-py is missing: {_INSTALL_PDF}") from e
    return MarkdownIt("commonmark", {"typographer": True}).enable(["table", "smartquotes"])


def stylesheet() -> str:
    root = repo_root()
    if root is not None:
        path = root / "site" / "static" / STYLE_FILE
        if path.is_file():
            return path.read_text()
    from importlib import resources

    return (resources.files("norboten") / "data" / STYLE_FILE).read_text()


#: A print view opened as `…#print` asks the browser to print it once loaded: on the site, "Save as
#: PDF" is the browser's own print dialog, laid out by the same stylesheet as the TUI's export.
PRINT_ON_OPEN = (
    '<script>if (location.hash === "#print") addEventListener("load", function () { print(); });'
    "</script>"
)


def to_html(journal: Journal, *, cheat_sheet: bool = False, script: str = "") -> str:
    """One self-contained document: the print stylesheet inlined, no network at render time.
    `cheat_sheet` keeps only that section, under the journal's title — one or two pages.
    """
    md = _markdown()
    if cheat_sheet:
        body = md.render(journal.cheat_sheet)
        title = f"{journal.title} — cheat sheet"
        meta = ", ".join(journal.topics)
    else:
        body = md.render(journal.body)
        title = journal.title
        topics = ", ".join(journal.topics)
        minutes = f"{journal.minutes} minutes" if journal.minutes else ""
        meta = " · ".join(p for p in (topics, minutes, f"{journal.words} words") if p)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{stylesheet()}</style>{script}
</head><body>
<header class="journal">
  <div class="brand">norboten · {"cheat sheet" if cheat_sheet else "journal"}</div>
  <h1>{html.escape(title)}</h1>
  <div class="meta">{html.escape(meta)}</div>
</header>
{body}
<footer class="journal">
  norboten.org · this journal accompanies the lab of the same name, where the machine is real and
  the grading is done on its state.
</footer>
</body></html>
"""


def write_pdf(journal: Journal, out: Path) -> Path:
    try:
        from weasyprint import HTML
    except ModuleNotFoundError as e:
        raise PdfUnavailable(
            f"weasyprint is missing: {_INSTALL_PDF} (it needs pango and cairo on the system)"
        ) from e
    out.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=to_html(journal), base_url=str(journal.path.parent)).write_pdf(str(out))
    return out
