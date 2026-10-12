"""P7 report build (experiments/report.py): Markdown chapters -> one document for pandoc."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from experiments import report
from experiments.report import TOC, assemble, chapter_markdown, diagrams, style_reference

CHAPTER = """# 3. Architecture

<!-- Drafted in P7.1b. Editorial note, not for the reader. -->

Text before.

```mermaid
flowchart LR
    A --> B
```

*Figure 3.1: Two boxes. The arrow is the point.*

```python
print("not a diagram")
```
"""

STYLES = """<w:styles>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:pPr>
      <w:keepNext />
      <w:keepLines />
    </w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:pPr>
      <w:keepNext />
      <w:keepLines />
    </w:pPr>
  </w:style>
  <w:style w:type="table" w:default="1" w:styleId="Table">
    <w:tblPr>
      <w:tblInd w:w="0" w:type="dxa" />
    </w:tblPr>
    <w:tblStylePr w:type="firstRow">
      <w:tcPr>
      </w:tcPr>
    </w:tblStylePr>
  </w:style>
</w:styles>"""


def test_each_diagram_is_found_with_its_figure_number_and_caption() -> None:
    [d] = diagrams(CHAPTER)
    assert (d.number, d.caption) == ("3.1", "Figure 3.1: Two boxes. The arrow is the point.")
    assert d.source == "flowchart LR\n    A --> B"
    assert (d.png, d.mmd) == ("fig-3-1.png", "fig-3-1.mmd")


def test_a_rendered_diagram_becomes_a_figure_with_its_caption(tmp_path: Path) -> None:
    (tmp_path / "fig-3-1.png").write_bytes(b"png")
    text, problems = chapter_markdown(CHAPTER, tmp_path)
    assert "![Figure 3.1: Two boxes. The arrow is the point.](" in text
    assert str(tmp_path / "fig-3-1.png") in text
    assert "```mermaid" not in text
    assert "*Figure 3.1" not in text  # the caption moved into the figure, not repeated
    assert '```python\nprint("not a diagram")\n```' in text  # other code stays
    assert problems == []


def test_a_diagram_not_rendered_yet_stays_as_source_and_is_named(tmp_path: Path) -> None:
    text, problems = chapter_markdown(CHAPTER, tmp_path)
    assert "```mermaid" in text
    assert problems == ["fig-3-1.png not rendered (make report-figures)"]


def test_a_diagram_without_a_figure_caption_is_named_not_dropped_silently(tmp_path: Path) -> None:
    uncaptioned = CHAPTER.replace("*Figure 3.1:", "Figure 3.1:")  # not in the caption form
    _, problems = chapter_markdown(uncaptioned, tmp_path)
    assert problems == ["1 diagram without a *Figure X.Y: ...* caption"]


def test_chapters_are_joined_in_order_with_the_contents_after_the_title_page() -> None:
    joined = assemble(["# Title page\n", "# 1. One\n\nFirst.\n"])
    # title page, then the contents (its own page), then the chapters (Heading 1 breaks)
    assert joined.index("# Title page") < joined.index(TOC) < joined.index("# 1. One")


def test_editorial_notes_are_left_out_before_diagrams_are_found(tmp_path: Path) -> None:
    # a diagram inside a note is not the reader's: neither embedded nor reported
    noted = "<!-- draft:\n```mermaid\nflowchart LR\n```\n\n*Figure 9.9: Old.*\n-->\n" + CHAPTER
    text, problems = chapter_markdown(noted, tmp_path)
    assert "<!--" not in text
    assert problems == ["fig-3-1.png not rendered (make report-figures)"]


def test_the_reference_styles_add_table_borders_and_chapter_page_breaks() -> None:
    styled = style_reference(STYLES)
    heading1 = styled[styled.index('w:styleId="Heading1"') : styled.index('w:styleId="Heading2"')]
    heading2 = styled[styled.index('w:styleId="Heading2"') : styled.index('w:styleId="Table"')]
    assert "<w:pageBreakBefore />" in heading1
    assert "pageBreakBefore" not in heading2  # sections stay on the page
    table = styled[styled.index('w:styleId="Table"') :]
    # borders right after tblInd (the schema's order), and a bold header row
    assert table.index("<w:tblInd") < table.index("<w:tblBorders>") < table.index("</w:tblPr>")
    assert table.index("<w:rPr><w:b /></w:rPr>") < table.index("<w:tcPr>")


def _chapter(tmp_path: Path, source: str) -> Path:
    chapter = tmp_path / "03_architecture.md"
    chapter.write_text(CHAPTER.replace("A --> B", source))
    return chapter


def test_a_failed_render_does_not_mark_the_old_png_as_up_to_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # regression (code review 2026-10-12): the new source was written before rendering, so a
    # failed render left the old PNG next to a matching .mmd and later runs skipped it
    figures = tmp_path / "figures"
    figures.mkdir()
    (figures / "fig-3-1.png").write_bytes(b"old")
    (figures / "fig-3-1.mmd").write_text("flowchart LR\n    A --> B\n")

    def fail(argv: list[str], **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr("experiments.report.shell.run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        report.render([_chapter(tmp_path, "A --> C")], figures)
    assert (figures / "fig-3-1.mmd").read_text() == "flowchart LR\n    A --> B\n"  # not marked


def test_an_unchanged_diagram_is_not_rendered_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    figures = tmp_path / "figures"
    calls: list[list[str]] = []

    def mmdc(argv: list[str], **kwargs: object) -> None:
        calls.append(argv)
        Path(argv[argv.index("-o") + 1]).write_bytes(b"png")

    monkeypatch.setattr("experiments.report.shell.run", mmdc)
    chapter = _chapter(tmp_path, "A --> B")
    assert report.render([chapter], figures) == [figures / "fig-3-1.png"]
    assert report.render([chapter], figures) == []  # same source: skipped, no churn in git
    assert len(calls) == 1


def test_a_department_template_is_used_as_it_is(tmp_path: Path) -> None:
    # Q4b: "a department template, if one turns up, becomes the reference document"
    template = tmp_path / "template.docx"
    template.write_bytes(b"docx")
    assert report.reference_doc(tmp_path / "build" / "reference.docx", template) == template


def test_unknown_reference_styles_are_an_error_not_a_plain_report() -> None:
    with pytest.raises(ValueError, match="Heading1"):
        style_reference("<w:styles></w:styles>")
