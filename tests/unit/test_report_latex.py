"""P7 report as LaTeX for Overleaf (experiments/report_latex.py): pandoc's LaTeX, restyled."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from experiments.report_latex import (
    OUT,
    PDF,
    boxed_tables,
    build,
    compile_pdf,
    framed_diagrams,
    main,
)

OUT_ZIP = OUT.with_suffix(".zip")

TITLE_PAGE = """::: {custom-style="Title"}
A Word-only title page
:::

## Abstract

<!-- editorial note -->

We built a twin.
"""

CHAPTER = """# 3. Architecture

Text before.

```mermaid
flowchart LR
    A --> B
```

*Figure 3.1: Two boxes.*

**Table 3.1: Two columns**

| Case | MAPE |
|---|---|
| All | 4.5% |
"""


def _report(tmp_path: Path) -> tuple[list[Path], Path]:
    chapters = [tmp_path / "00_title_page.md", tmp_path / "03_architecture.md"]
    chapters[0].write_text(TITLE_PAGE)
    chapters[1].write_text(CHAPTER)
    figures = tmp_path / "figures"
    figures.mkdir()
    return chapters, figures


def test_a_diagram_not_rendered_yet_stops_the_build_with_its_name(tmp_path: Path) -> None:
    # its Mermaid source would otherwise reach the PDF as a code listing
    chapters, figures = _report(tmp_path)
    with pytest.raises(ValueError, match=r"03_architecture\.md: fig-3-1\.png not rendered"):
        build(chapters, tmp_path / "overleaf", figures, {})


def test_the_build_writes_an_overleaf_project_with_the_figures_it_uses(tmp_path: Path) -> None:
    chapters, figures = _report(tmp_path)
    (figures / "fig-3-1.png").write_bytes(b"png")
    (figures / "fig-6-1.png").write_bytes(b"not used")

    project = build(chapters, tmp_path / "overleaf", figures, {"fig-3-1": r"width=\linewidth"})

    with zipfile.ZipFile(project) as z:
        assert sorted(z.namelist()) == ["figures/fig-3-1.png", "main.tex"]
        tex = z.read("main.tex").decode()
    document = tex.split(r"\begin{document}", 1)[1]
    # the LaTeX title page, then the abstract from the title-page file, then the contents
    assert document.index("Aggimalla Abhishek") < document.index("We built a twin.")
    assert document.index("We built a twin.") < document.index(r"\tableofcontents")
    assert "A Word-only title page" not in document
    assert "editorial note" not in document
    assert r"\diagramframe{\includegraphics[width=\linewidth]{figures/fig-3-1.png}}" in document
    assert r"\textbf{Table 3.1: Two columns}} \\[2pt]" in document
    assert r"\rowcolor{tablehead}" in document
    assert r"\toprule" not in document


# Two figures as pandoc writes them: a diagram and a chart
FIGURES = r"""\begin{figure}
\centering
\pandocbounded{\includegraphics[keepaspectratio,alt={Fig. 3.3.}]{figures/fig-3-3.png}}
\caption{Fig. 3.3.}
\end{figure}

\begin{figure}
\centering
\pandocbounded{\includegraphics[keepaspectratio,alt={Fig. 6.1.}]{figures/fig-6-1.png}}
\caption{Fig. 6.1.}
\end{figure}
"""


def test_a_diagram_is_framed_at_its_size_and_a_chart_is_left_as_it_is() -> None:
    framed = framed_diagrams(FIGURES, {"fig-3-3": r"width=0.55\linewidth"})
    assert framed == FIGURES.replace(
        r"\pandocbounded{\includegraphics[keepaspectratio,alt={Fig. 3.3.}]"
        r"{figures/fig-3-3.png}}",
        r"\diagramframe{\includegraphics[width=0.55\linewidth]{figures/fig-3-3.png}}",
    )
    assert r"\pandocbounded{\includegraphics[keepaspectratio,alt={Fig. 6.1" in framed


def test_a_diagram_missing_from_the_text_is_an_error() -> None:
    # a renamed figure would otherwise lose its frame without a word
    with pytest.raises(ValueError, match="fig-9-9"):
        framed_diagrams(FIGURES, {"fig-9-9": r"width=\linewidth"})


# A table as pandoc writes it: open booktabs rules, no vertical lines
PLAIN = r"""Text before.

{\def\LTcaptype{none} % do not increment counter
\begin{longtable}[]{@{}ll@{}}
\toprule\noalign{}
Case & MAPE \\
\midrule\noalign{}
\endhead
\bottomrule\noalign{}
\endlastfoot
All & 4.5\% \\
Video & 4.0\% \\
\end{longtable}
}
"""


TITLED = r"""\textbf{Table 6.1: Lecture flash
crowd}

{\def\LTcaptype{none} % do not increment counter
\begin{longtable}[]{@{}
  >{\raggedright\arraybackslash}p{(\linewidth - 2\tabcolsep) * \real{0.6000}}
  >{\raggedright\arraybackslash}p{(\linewidth - 2\tabcolsep) * \real{0.4000}}@{}}
\toprule\noalign{}
KPI & V1 \\
\midrule\noalign{}
\endhead
\bottomrule\noalign{}
\endlastfoot
Loss, affected flows (\%) & 43.9 ± 0.3 \\
\end{longtable}
}
"""


def test_a_titled_table_carries_its_title_as_its_first_row() -> None:
    # the title cannot be left at the foot of a page with the table on the next; the columns
    # give back the outer padding and the three rules the box adds
    spec = (
        r"|>{\raggedright\arraybackslash}"
        r"p{(\linewidth - 4\tabcolsep - 3\arrayrulewidth) * \real{0.6000}}"
        r"|>{\raggedright\arraybackslash}"
        r"p{(\linewidth - 4\tabcolsep - 3\arrayrulewidth) * \real{0.4000}}|"
    )
    assert (
        boxed_tables(TITLED)
        == r"""{\def\LTcaptype{none} % do not increment counter
\begin{longtable}[]{"""
        + spec
        + r"""}
\multicolumn{2}{@{}l@{}}{\textbf{Table 6.1: Lecture flash crowd}} \\[2pt]
\hline
\rowcolor{tablehead}
KPI & V1 \\
\hline
\endhead
\endlastfoot
Loss, affected flows (\%) & 43.9 ± 0.3 \\ \hline
\end{longtable}
}
"""
    )


CAPTIONED = (
    PLAIN
    + r"""
\emph{Table 3.3: REST API. Every route
is checked.}

Text after.
"""
)


def test_the_pdf_is_compiled_in_the_project_and_moved_to_its_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "overleaf"
    project.mkdir()
    calls: list[tuple[list[str], object]] = []

    def tectonic(argv: list[str], **kwargs: object) -> None:  # writes main.pdf beside main.tex
        calls.append((argv, kwargs["cwd"]))
        (project / "main.pdf").write_bytes(b"%PDF")

    monkeypatch.setattr("experiments.report_latex.shell.run", tectonic)
    pdf = compile_pdf(project, tmp_path / "report-latex.pdf")
    assert calls == [(["tectonic", "-X", "compile", "main.tex"], project)]
    assert pdf.read_bytes() == b"%PDF"
    assert not (project / "main.pdf").exists()  # not shipped in the next zip


@pytest.mark.parametrize(("argv", "compiled"), [([], False), (["--pdf"], True)])
def test_the_pdf_is_compiled_only_when_asked(
    argv: list[str], compiled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    done: list[str] = []

    def fake_build(_chapters: object) -> Path:
        done.append("build")
        return OUT_ZIP

    def fake_compile() -> Path:
        done.append("pdf")
        return PDF

    monkeypatch.setattr("experiments.report_latex.build", fake_build)
    monkeypatch.setattr("experiments.report_latex.compile_pdf", fake_compile)
    assert main(argv) == 0
    assert done == (["build", "pdf"] if compiled else ["build"])


def test_a_caption_below_a_table_closes_the_table_so_the_two_stay_together() -> None:
    # longtable keeps its last foot with the last row; a paragraph after the table could be
    # left on the next page
    assert boxed_tables(CAPTIONED).endswith(r"""\hline
\endhead
\multicolumn{2}{@{}p{\linewidth}@{}}{\small\emph{Table 3.3: REST API. Every route is checked.}} \\
\endlastfoot
All & 4.5\% \\ \hline
Video & 4.0\% \\ \hline
\end{longtable}
}

Text after.
""")


def test_a_table_is_boxed_with_a_shaded_header_row() -> None:
    assert (
        boxed_tables(PLAIN)
        == r"""Text before.

{\def\LTcaptype{none} % do not increment counter
\begin{longtable}[]{|l|l|}
\hline
\rowcolor{tablehead}
Case & MAPE \\
\hline
\endhead
\endlastfoot
All & 4.5\% \\ \hline
Video & 4.0\% \\ \hline
\end{longtable}
}
"""
    )
