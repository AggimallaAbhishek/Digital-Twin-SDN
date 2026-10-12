"""P7 report build: the Markdown chapters of docs/report/ -> one Word document (decision P7-A).

    make report-figures   # after a diagram changes: Mermaid -> docs/report/figures/*.png
    make report           # -> docs/report/build/report.docx

Chapters `NN_*.md` are joined in order; the editorial `<!-- ... -->` notes are left out. A
```mermaid block followed by its `*Figure X.Y: ...*` caption becomes a numbered figure from
docs/report/figures/fig-X-Y.png, rendered with the Mermaid CLI. That needs Node and the npm
registry, so the PNGs (and the .mmd source each was rendered from) are committed and the build
needs neither. Pandoc comes bundled with the `pypandoc-binary` dev dependency. Its default Word
styles get table borders, a bold header row and a page break before every chapter.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pypandoc

from experiments import shell

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "report"
FIGURES = REPORT / "figures"
OUT = REPORT / "build" / "report.docx"
REFERENCE = REPORT / "build" / "reference.docx"
TEMPLATE = REPORT / "template.docx"  # a department template, used as it is when present (Q4b)
MERMAID_CLI = "@mermaid-js/mermaid-cli@11"
RENDER_TIMEOUT_S = 600  # the first npx run downloads the CLI and a headless Chromium
TOC = (  # after the title page, on a page of its own: a "Contents" title and a Word contents
    # field marked dirty, so Word offers to fill it in when the document opens
    "```{=openxml}\n"
    '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    '<w:p><w:pPr><w:spacing w:after="240"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr>'
    "<w:t>Contents</w:t></w:r></w:p>"
    '<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-2" \\h \\z \\u </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    "<w:r><w:t>Open in Word and choose Yes to update the contents (or right-click, Update"
    " Field).</w:t></w:r>"
    '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>\n```'
)
_DIAGRAM = re.compile(
    r"```mermaid\n(?P<source>.*?)\n```\s*\n\*(?P<caption>Figure (?P<n>\d+)\.(?P<m>\d+): [^\n]*?)\*",
    re.DOTALL,
)
_COMMENT = re.compile(r"<!--.*?-->\n?", re.DOTALL)
_BORDER = '<w:{side} w:val="single" w:sz="4" w:space="0" w:color="A6A6A6" />'
# (anchor, what to add after it, the style it belongs to) in pandoc's default styles.xml
_STYLE_EDITS = (
    ("<w:keepLines />", "\n      <w:pageBreakBefore />", "Heading1"),
    (
        '<w:tblInd w:w="0" w:type="dxa" />',
        "<w:tblBorders>"
        + "".join(_BORDER.format(side=s) for s in ("top", "bottom", "insideH"))
        + "</w:tblBorders>",
        "Table",
    ),
    ('<w:tblStylePr w:type="firstRow">', "<w:rPr><w:b /></w:rPr>", "Table"),
)


@dataclass(frozen=True)
class Diagram:
    """A Mermaid diagram of a chapter, with the caption that follows it."""

    number: str  # "3.1"
    caption: str  # "Figure 3.1: ..."
    source: str

    @property
    def png(self) -> str:
        """The rendered figure's file name."""
        return f"fig-{self.number.replace('.', '-')}.png"

    @property
    def mmd(self) -> str:
        """The file recording the source the PNG was rendered from."""
        return f"fig-{self.number.replace('.', '-')}.mmd"


def _diagram(match: re.Match[str]) -> Diagram:
    return Diagram(f"{match['n']}.{match['m']}", match["caption"], match["source"])


def diagrams(text: str) -> list[Diagram]:
    """The captioned Mermaid diagrams of a chapter, in order."""
    return [_diagram(m) for m in _DIAGRAM.finditer(text)]


def chapter_markdown(text: str, figures: Path) -> tuple[str, list[str]]:
    """A chapter as the report shows it: without editorial `<!-- -->` notes, each rendered
    diagram as a figure (its caption becomes the figure's caption). Also what is wrong:
    diagrams not rendered yet (left as source) and diagrams without a caption."""
    text = _COMMENT.sub("", text)
    found = diagrams(text)
    problems = [
        f"{d.png} not rendered (make report-figures)"
        for d in found
        if not (figures / d.png).exists()
    ]
    uncaptioned = text.count("```mermaid") - len(found)
    if uncaptioned:
        problems.append(f"{uncaptioned} diagram without a *Figure X.Y: ...* caption")

    def figure(match: re.Match[str]) -> str:
        path = figures / _diagram(match).png
        return f"![{match['caption']}]({path})" if path.exists() else match.group(0)

    return _DIAGRAM.sub(figure, text), problems


def assemble(chapters: list[str]) -> str:
    """The chapters in order, the contents after the first (the title page). Each chapter
    starts a page through its Heading 1 style."""
    parts = [c.strip() for c in chapters]
    return "\n\n".join([*parts[:1], TOC, *parts[1:]]) + "\n"


def style_reference(styles: str) -> str:
    """pandoc's default styles.xml with table borders, a bold header row and a page break
    before each chapter; ValueError if pandoc's styles no longer have what is edited."""
    for anchor, addition, style in _STYLE_EDITS:
        start = styles.find(f'w:styleId="{style}"')
        at = styles.find(anchor, start) if start >= 0 else -1
        end = styles.find("</w:style>", start)
        if at < 0 or at > end:
            raise ValueError(f"pandoc's reference styles changed: no {anchor} in {style}")
        at += len(anchor)
        styles = styles[:at] + addition + styles[at:]
    return styles


def reference_doc(out: Path = REFERENCE, template: Path = TEMPLATE) -> Path:
    """The Word styles of the report: a department template as it is, if there is one (Q4b),
    else pandoc's default reference.docx with style_reference() applied."""
    if template.exists():
        return template
    out.parent.mkdir(parents=True, exist_ok=True)
    default = out.with_name("default-reference.docx")
    pandoc = pypandoc.get_pandoc_path()
    shell.run(
        [pandoc, "-o", str(default), "--print-default-data-file", "reference.docx"], check=True
    )
    with zipfile.ZipFile(default) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item)
            if item.filename == "word/styles.xml":
                data = style_reference(data.decode()).encode()
            dst.writestr(item, data)
    default.unlink()
    return out


def render(chapters: Sequence[Path], figures: Path = FIGURES) -> list[Path]:
    """Render the chapters' Mermaid diagrams to PNG (neutral theme, white, 2x). A diagram whose
    .mmd records the same source is skipped (no churn in git); the .mmd is written only after
    its PNG, so a failed render is tried again next time."""
    figures.mkdir(parents=True, exist_ok=True)
    written = []
    for chapter in chapters:
        for d in diagrams(chapter.read_text()):
            png, record, source = figures / d.png, figures / d.mmd, d.source + "\n"
            if png.exists() and record.exists() and record.read_text() == source:
                continue
            pending = figures / f"{d.mmd}.pending"
            pending.write_text(source)
            try:
                argv = ["npx", "-y", MERMAID_CLI, "-i", str(pending), "-o", str(png)]
                shell.run(
                    [*argv, "-t", "neutral", "-b", "white", "-s", "2"],
                    check=True,
                    timeout=RENDER_TIMEOUT_S,
                )
            finally:
                pending.unlink()
            record.write_text(source)
            written.append(png)
    return written


def build(out: Path = OUT) -> list[str]:
    """Write the Word document; return what is wrong with its diagrams (empty when nothing)."""
    problems: list[str] = []
    texts = []
    for chapter in _chapters():
        text, found = chapter_markdown(chapter.read_text(), FIGURES)
        texts.append(text)
        problems += [f"{chapter.name}: {p}" for p in found]
    out.parent.mkdir(parents=True, exist_ok=True)
    pypandoc.convert_text(
        assemble(texts),
        "docx",
        format="markdown",
        outputfile=str(out),
        extra_args=[f"--resource-path={REPORT}", f"--reference-doc={reference_doc()}"],
    )
    return problems


def _chapters() -> list[Path]:
    return sorted(REPORT.glob("[0-9][0-9]_*.md"))


def main(argv: list[str] | None = None) -> int:
    """Build the report (or, with --figures, render its diagrams); 1 if a diagram is wrong."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--figures", action="store_true", help="render the Mermaid diagrams")
    args = parser.parse_args(argv)
    if args.figures:
        for path in render(_chapters()):
            print(f"REPORT_FIGURE {path.relative_to(ROOT)}")
        return 0
    problems = build()
    print(f"REPORT {OUT.relative_to(ROOT)}")
    for problem in problems:
        print(f"REPORT problem (the docx was still written): {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
