"""The final submission package (final_submission/dist/), built from the current repository.

    make submission     # Final_Submission.zip (the one to upload), and loose copies of its parts

`Final_Submission.zip` (the instructor's list: Overleaf zip, source code, figures, dataset,
README, anything else; at most 100 MB) unpacks to `Final_Submission/`:

- `README.md`, `install_dataset.sh`, `REPRODUCE.md`, `requirements.txt`;
- `Overleaf.zip`: the IEEE paper's source, files at the top level, for Overleaf's "Upload Project";
- `Source_Code/`: every file git tracks or could track (the ignore rules apply, so no `.env`,
  log or key), without the dataset;
- `Dataset/`: the recorded evaluation that `make results` and `make paper` read (datasets, raw
  executor ledgers, model metrics), in the repository's layout; `install_dataset.sh` copies it
  into `Source_Code/`;
- `Figures/`: the paper's figures, the result plots and the report's diagrams;
- `paper.pdf` and `Revision_Report.docx`.

Nothing is copied by hand: everything is built from the files as they are now, and the build
stops if a secret-looking file would be included or the ZIP would exceed the limit.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import shutil
import subprocess
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pypandoc

from experiments import paper_build
from experiments.shell import run

log = logging.getLogger("experiments.submission")
ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = ROOT / "final_submission"
DIST = SUBMISSION / "dist"
ZIP_LIMIT_BYTES = 100 * 1024 * 1024  # the submission form's limit per ZIP
PACKAGE_DIR = "Final_Submission"  # the folder the submission ZIP unpacks to
PACKAGE_ZIP = "Final_Submission.zip"
PACKAGE_DOCS = SUBMISSION / "package"  # its README.md and install_dataset.sh
# where the figures are, by their folder in the package's Figures/
FIGURE_SOURCES = {
    "paper": ("final_submission/paper/figures", "*.pdf"),
    "results": ("experiments/results/figures", "*.png"),
    "report": ("docs/report/figures", "*.png"),
}
# git does not track these (ignored: large and regenerable), but the paper's numbers and
# `make results` need them; the paths are relative to the repository
EVIDENCE = (
    "data/README.md",
    "data/v1",
    "data/actions-v1",
    "data/evalv1-v1",
    "data/evalv2-v1",
    "data/evalv3-v1",
    "data/raw/v1",
    "data/raw/actions-v1",
    "data/raw/genai-v1",
    "data/raw/evalv1-v1",
    "data/raw/evalv2-v1",
    "data/raw/evalv3-v1",
    "models",
    "experiments/results",
)
# tracked or not, never part of the submission
EXCLUDED = (
    "final_submission/dist/",
    "frontend design images/",
    "docs/report/build/",
    ".claude/",  # the assistant's project settings: not part of the work
    "docs/superpowers/",  # design notes of the dashboard
)
# what .gitignore keeps out as a secret, a key, a token or a log: a backstop for files git's
# rules do not see (the evidence folders are added by path) or that were forced in
FORBIDDEN = re.compile(
    r"(^|/)("
    r"\.env(\.[^/]*)?|[^/]*\.env|\.envrc|"
    r"\.?secrets?|logs|id_(rsa|dsa|ecdsa|ed25519)[^/]*|"
    r"[^/]*\.(pem|key|p12|pfx|keystore|token|secret|log)|"
    r"token\.json|[^/]*credentials[^/]*\.json|secrets[^/]*\.json"
    r")($|/)",
    re.IGNORECASE,
)
ALLOWED = {".env.example"}  # the template: every value blank
PAPER_FILES = ("main.tex", "references.bib")
FINAL_PDF = "revisions/paper_final.pdf"  # the authors' Overleaf-compiled PDF, when they have it
STORED_SUFFIXES = {
    ".pdf",
    ".png",
    ".zip",
}  # already deflated (a nested zip too); parquet still shrinks


class SubmissionError(RuntimeError):
    """The package cannot be built as it is; the message says why."""


def repository_files(root: Path) -> list[Path]:
    """Files git tracks or would track (its ignore rules apply), relative to `root`."""
    try:
        out = run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise SubmissionError(
            f"{root} is not a git repository: the ignore rules are unknown"
        ) from exc
    names = [n for n in out.split("\0") if n]
    return sorted(
        Path(n)
        for n in names
        if not n.startswith(EXCLUDED) and (root / n).is_file() and not (root / n).is_symlink()
    )


def evidence_files(root: Path) -> list[Path]:
    """The recorded evaluation under `root`: every file of each EVIDENCE path. A path that is
    missing stops the build: a package without it could not reproduce the paper."""
    missing = [item for item in EVIDENCE if not (root / item).exists()]
    if missing:
        raise SubmissionError(f"the recorded evaluation is missing: {', '.join(missing)}")
    found: set[Path] = set()
    for item in EVIDENCE:
        path = root / item
        files = [path] if path.is_file() else path.rglob("*")
        found |= {f.relative_to(root) for f in files if f.is_file() and not f.is_symlink()}
    return sorted(found)


def check_no_secrets(paths: Iterable[Path]) -> None:
    """SubmissionError if a path looks like a secret, a log or a key (the template is fine)."""
    bad = [
        str(p) for p in paths if FORBIDDEN.search(p.as_posix()) and p.name.lower() not in ALLOWED
    ]
    if bad:
        raise SubmissionError(f"would ship secret-looking files: {', '.join(sorted(bad)[:5])}")


def write_zip(out: Path, files: Iterable[tuple[Path, str]], limit: int = ZIP_LIMIT_BYTES) -> int:
    """Write `files` (source path, name inside the ZIP) to `out`; its size in bytes. A ZIP over
    `limit` is deleted and refused, and so is a name used twice (the second file would shadow
    the first when unpacked)."""
    entries = list(files)
    names = [name for _, name in entries]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise SubmissionError(f"a name is used twice in {out.name}: {', '.join(repeated[:3])}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for source, name in entries:
            kind = zipfile.ZIP_STORED if source.suffix in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
            zf.write(source, name, compress_type=kind)
    size = out.stat().st_size
    if size > limit:
        out.unlink()
        raise SubmissionError(
            f"{out.name} is {size / 2**20:.1f} MB: over the {limit / 2**20:.0f} MB limit"
        )
    return size


def figure_files(root: Path) -> list[tuple[Path, str]]:
    """The figures: (file, name under Figures/) for the paper's, the results' and the report's."""
    found = []
    for folder, (where, pattern) in FIGURE_SOURCES.items():
        for path in sorted((root / where).glob(pattern)):
            found.append((path, f"Figures/{folder}/{path.name}"))
    return found


def build_package(
    root: Path,
    out: Path,
    top_level: Iterable[tuple[Path, str]] = (),
    limit: int = ZIP_LIMIT_BYTES,
) -> int:
    """Final_Submission.zip: `top_level` files (source, name), then Source_Code/ (the repository
    files), Dataset/ (the recorded evaluation, in the repository's layout) and Figures/."""
    top = list(top_level)
    missing = [name for source, name in top if not source.is_file()]
    if missing:
        raise SubmissionError(f"the package is missing: {', '.join(missing)}")
    dataset = evidence_files(root)
    kept_apart = set(dataset)  # the dataset is not repeated in Source_Code/
    code = [p for p in repository_files(root) if p not in kept_apart]
    check_no_secrets([*code, *dataset])
    entries = [
        *top,
        *((root / p, f"Source_Code/{p.as_posix()}") for p in code),
        *((root / p, f"Dataset/{p.as_posix()}") for p in dataset),
        *figure_files(root),
    ]
    return write_zip(out, ((source, f"{PACKAGE_DIR}/{name}") for source, name in entries), limit)


def paper_sources(paper: Path) -> list[Path]:
    """The paper's source files, relative to its folder (no build output)."""
    missing = [n for n in PAPER_FILES if not (paper / n).exists()]
    if missing:
        raise SubmissionError(f"the paper has no {', '.join(missing)}")
    generated = [*(paper / "generated").glob("*.tex"), *(paper / "figures").glob("*.pdf")]
    return [Path(n) for n in PAPER_FILES] + sorted(p.relative_to(paper) for p in generated)


def build_overleaf_zip(paper: Path, out: Path) -> int:
    """Overleaf.zip: the paper's source with its files at the top level."""
    return write_zip(out, ((paper / p, p.as_posix()) for p in paper_sources(paper)))


def chosen_pdf(built: Path, final: Path) -> Path:
    """The PDF that becomes paper.pdf: the authors' final one (compiled on Overleaf) if they put
    it at `final`, else the one built here (Tectonic, a close preview of the IEEE layout)."""
    return final if final.is_file() else built


def build_revision_report(source: Path, out: Path) -> None:
    """Revision_Report.docx from the Markdown report (pandoc, bundled with pypandoc-binary)."""
    pypandoc.convert_file(str(source), "docx", outputfile=str(out))


def checksums(files: Iterable[Path]) -> str:
    """SHA256SUMS.txt text: `<hash>  <file name>` per file."""
    lines = []
    for f in sorted(files):
        with f.open("rb") as handle:  # streamed: the submission ZIP is tens of MB
            lines.append(f"{hashlib.file_digest(handle, 'sha256').hexdigest()}  {f.name}\n")
    return "".join(lines)


def _stale_paper_files() -> str:
    """The generated paper files that differ from the recorded evaluation, comma-separated."""
    try:
        evidence = paper_build.load_evidence()
    except FileNotFoundError as exc:
        raise SubmissionError(f"the recorded evaluation is incomplete: {exc}") from exc
    return ", ".join(paper_build.out_of_date(evidence, paper_build.PAPER))


def build(dist: Path = DIST) -> dict[str, int]:
    """Build every deliverable into `dist`; their sizes in bytes."""
    stale = _stale_paper_files()
    if stale:
        raise SubmissionError(
            f"the paper is out of date with the evaluation ({stale}): `make paper`"
        )
    dist.mkdir(parents=True, exist_ok=True)
    build_overleaf_zip(paper_build.PAPER, dist / "Overleaf.zip")
    shutil.copyfile(
        chosen_pdf(paper_build.compile_pdf(), SUBMISSION / FINAL_PDF), dist / "paper.pdf"
    )
    build_revision_report(
        SUBMISSION / "revisions" / "revision_report.md", dist / "Revision_Report.docx"
    )
    top_level = [
        (PACKAGE_DOCS / "README.md", "README.md"),
        (PACKAGE_DOCS / "install_dataset.sh", "install_dataset.sh"),
        (SUBMISSION / "SETUP.md", "SETUP.md"),
        (SUBMISSION / "REPRODUCE.md", "REPRODUCE.md"),
        (SUBMISSION / "requirements.txt", "requirements.txt"),
        (dist / "Overleaf.zip", "Overleaf.zip"),
        (dist / "paper.pdf", "paper.pdf"),
        (dist / "Revision_Report.docx", "Revision_Report.docx"),
    ]
    build_package(ROOT, dist / PACKAGE_ZIP, top_level)
    deliverables = [
        dist / name for name in (PACKAGE_ZIP, "Overleaf.zip", "paper.pdf", "Revision_Report.docx")
    ]
    (dist / "SHA256SUMS.txt").write_text(checksums(deliverables))
    return {p.name: p.stat().st_size for p in deliverables}


def main(argv: list[str] | None = None) -> int:
    """`make submission`."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        sizes = build()
    except SubmissionError as exc:
        log.error("submission not built: %s", exc)
        return 1
    for name, size in sizes.items():
        log.info("%-22s %7.1f MB", name, size / 2**20)
    log.info("in %s", DIST.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
