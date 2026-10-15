"""P7 report as LaTeX for Overleaf: the Markdown chapters of docs/report/ -> an Overleaf project.

    make report-latex       # -> docs/report/build/overleaf/ (main.tex + figures/) and overleaf.zip
    make report-latex-pdf   # the same, then compiled with Tectonic -> report-latex.pdf

The chapters go through the Word build's own conversion (experiments/report.py), then pandoc
writes LaTeX. The title page and the preamble are in docs/report/latex/.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pypandoc

from experiments import report, shell

LATEX = report.REPORT / "latex"  # preamble.tex and titlepage.tex
OUT = report.REPORT / "build" / "overleaf"  # the project; the zip is overleaf.zip beside it
PDF = report.REPORT / "build" / "report-latex.pdf"
COMPILE_TIMEOUT_S = 600  # Tectonic's first run downloads its TeX bundle
# The architecture and flow diagrams, framed, each at a size that suits its shape (the frame
# and its padding take ~5% of the width). The results charts keep pandoc's fit-to-the-page.
DIAGRAMS = {
    "fig-3-1": r"width=0.94\linewidth,height=0.8\textheight,keepaspectratio",  # tall layers
    "fig-3-2": r"width=0.94\linewidth",
    "fig-3-3": r"width=0.55\linewidth",  # a small flow, huge at full width
    "fig-5-1": r"width=0.94\linewidth,height=0.7\textheight,keepaspectratio",
}
PANDOC_ARGS = [
    "--standalone",
    "-V", "documentclass=article",
    "-V", "fontsize=11pt",
    "-V", "geometry:a4paper,margin=2.5cm",
    "-V", "colorlinks=true",
    "-V", "linkcolor=black",
    "-V", "urlcolor=blue",
    # the PDF's title; the printed title is on the LaTeX title page
    "-V", "title-meta=GenAI-Driven Digital Twin for Intelligent SDN-Based Wireless Network "
    "Optimization",
    "--metadata", "lang=en-GB",
]  # fmt: skip
# After the title page and the abstract: the contents (to subsections) in a smaller font, on
# their own page; the chapters are numbered from 1 after them
CONTENTS = (
    "{\\setcounter{tocdepth}{2}\\small\\tableofcontents}\n\\clearpage\n\\pagenumbering{arabic}\n"
)
_FIGURE_PATH = re.compile(r"\((?:[^()\s]*/)?(fig-[\w-]+\.png)\)")

# A pandoc table (uncaptioned, so in a group that keeps the table counter still), with the
# chapters' "Table X.Y: ..." paragraph: bold above it or italic below it, when there is one
_TABLE = re.compile(
    r"(?:(?P<title>\\textbf\{Table \d+\.\d+:[^}]*\})\n\n)?"
    r"(?P<group>\{\\def\\LTcaptype\{none\} % do not increment counter\n)"
    r"\\begin\{longtable\}\[\]\{(?P<spec>.*?)\}\n(?=\\toprule)(?P<body>.*?)\\end\{longtable\}"
    r"(?P<close>\n\}\n)(?:\n(?P<caption>\\emph\{Table \d+\.\d+:[^}]*\})\n)?",
    re.DOTALL,
)
_P_COLUMN = re.compile(r">\{[^{}]*\}p\{\(\\linewidth - \d+\\tabcolsep\) \* \\real\{[\d.]+\}\}")
_P_WIDTH = re.compile(r"\(\\linewidth - \d+\\tabcolsep\)")


def framed_diagrams(tex: str, sizes: Mapping[str, str]) -> str:
    """Each named diagram (fig-X-Y) in a frame, at its own size (\\includegraphics keys) in
    place of pandoc's fit-to-the-page; other figures stay as they are. ValueError if a named
    diagram is not in the text exactly once."""
    for fig, size in sizes.items():
        pattern = r"\\pandocbounded\{\\includegraphics\[[^\]]*\]\{figures/" + fig + r"\.png\}\}"
        frame = rf"\diagramframe{{\includegraphics[{size}]{{figures/{fig}.png}}}}"
        tex, n = re.subn(pattern, frame.replace("\\", "\\\\"), tex)  # a literal replacement
        if n != 1:
            raise ValueError(f"{fig}: found {n} times, expected once")
    return tex


def boxed_tables(tex: str) -> str:
    """pandoc's open booktabs tables, boxed: an outer border, lines between columns and rows,
    and a shaded header row. A table's bold title becomes its first row and an italic caption
    below it its last, so neither is split from the table across pages."""
    return _TABLE.sub(_boxed, tex)


def _boxed(m: re.Match[str]) -> str:
    columns = _P_COLUMN.findall(m["spec"])
    if columns:  # widths give back the outer padding and the n + 1 rules the box adds
        n = len(columns)
        width = rf"(\\linewidth - {2 * n}\\tabcolsep - {n + 1}\\arrayrulewidth)"
        columns = [_P_WIDTH.sub(width, c) for c in columns]
    else:
        columns = list(re.sub(r"@\{\}|\s", "", m["spec"]))
    head, sep, rows = m["body"].partition("\\endlastfoot\n")
    head = head.replace("\\toprule\\noalign{}\n", "\\hline\n\\rowcolor{tablehead}\n")
    head = head.replace("\\midrule\\noalign{}\n", "\\hline\n")
    head = head.replace("\\bottomrule\\noalign{}\n", "")  # each row closes itself below
    rows = rows.replace("\\\\\n", "\\\\ \\hline\n")
    across = f"\\multicolumn{{{len(columns)}}}"  # a row across the table, outside the box
    if m["title"]:
        title = " ".join(m["title"].split())
        head = f"{across}{{@{{}}l@{{}}}}{{{title}}} \\\\[2pt]\n{head}"
    if m["caption"]:  # the last foot, which longtable keeps with the last row
        caption = " ".join(m["caption"].split())
        head += f"{across}{{@{{}}p{{\\linewidth}}@{{}}}}{{\\small{caption}}} \\\\\n"
    spec = "|" + "|".join(columns) + "|"
    return (
        f"{m['group']}\\begin{{longtable}}[]{{{spec}}}\n{head}{sep}{rows}\\end{{longtable}}"
        f"{m['close']}"
    )


def build(
    chapters: Sequence[Path],
    out: Path = OUT,
    figures: Path = report.FIGURES,
    diagrams: Mapping[str, str] = DIAGRAMS,
) -> Path:
    """Write the Overleaf project (main.tex and the figures it uses) to `out` and zip it beside
    `out`; return the zip. The first chapter is the title-page file: only its abstract is used,
    after the LaTeX title page. ValueError if a diagram is not rendered or has no caption."""
    title_page, *rest = chapters
    abstract, _ = report.chapter_markdown(
        title_page.read_text().split("## Abstract", 1)[1], figures
    )
    texts, problems = [], []
    for chapter in rest:
        text, found = report.chapter_markdown(chapter.read_text(), figures)
        texts.append(text.strip())
        problems += [f"{chapter.name}: {p}" for p in found]
    if problems:  # a diagram left as Mermaid source would print as a code listing
        raise ValueError("; ".join(problems))
    body = _FIGURE_PATH.sub(r"(figures/\1)", "\n\n".join(texts) + "\n")

    tex = pypandoc.convert_text(
        body,
        "latex",
        format="markdown",
        extra_args=[*PANDOC_ARGS, f"--include-in-header={LATEX / 'preamble.tex'}"],
    )
    front = (
        (LATEX / "titlepage.tex").read_text()
        + "\n\\section*{Abstract}\n"
        + pypandoc.convert_text(abstract, "latex", format="markdown")
        + "\n\\clearpage\n"
        + CONTENTS
    )
    tex = tex.replace("\\begin{document}\n", "\\begin{document}\n" + front, 1)
    tex = boxed_tables(framed_diagrams(tex, diagrams))
    if "\\toprule" in tex:
        raise ValueError("a table was left open (pandoc's table layout changed?)")

    if out.exists():
        shutil.rmtree(out)
    (out / "figures").mkdir(parents=True)
    (out / "main.tex").write_text(tex)
    for name in sorted(set(_FIGURE_PATH.findall(body))):
        shutil.copy(figures / name, out / "figures" / name)
    project = out.with_suffix(".zip")
    with zipfile.ZipFile(project, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(out).as_posix())
    return project


def compile_pdf(out: Path = OUT, pdf: Path = PDF) -> Path:
    """Compile the project with Tectonic (XeTeX, as on Overleaf's XeLaTeX) into `pdf`."""
    shell.run(
        ["tectonic", "-X", "compile", "main.tex"],  # writes main.pdf beside it
        check=True,
        cwd=out,
        timeout=COMPILE_TIMEOUT_S,
    )
    shutil.move(out / "main.pdf", pdf)
    return pdf


def main(argv: list[str] | None = None) -> int:
    """Build the Overleaf project (and, with --pdf, compile it)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", action="store_true", help="compile it with Tectonic")
    args = parser.parse_args(argv)
    project = build(report._chapters())
    print(f"REPORT_LATEX {project.relative_to(report.ROOT)}")
    if args.pdf:
        print(f"REPORT_LATEX {compile_pdf().relative_to(report.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
