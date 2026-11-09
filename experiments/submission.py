"""The final submission package (final_submission/dist/), built from the current repository.

    make submission     # Overleaf_Source.zip, Code_and_Data.zip, paper.pdf, Revision_Report.docx

- `Overleaf_Source.zip`: the IEEE paper's source (main.tex, references.bib, generated/, figures/),
  files at the top level, ready for Overleaf's "Upload Project".
- `Code_and_Data.zip` (the form allows 100 MB): every file git tracks or could track (the
  ignore rules apply, so no `.env`, log or key), plus the recorded evaluation that `make results`
  and `make paper` read: the datasets, the raw executor ledgers and the model metrics.
- `paper.pdf`, `Revision_Report.docx`, and `SHA256SUMS.txt` for all four.

Nothing is copied by hand: the ZIPs are built from the files as they are now, and the build
stops if a secret-looking file would be included or a ZIP would exceed the limit.
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
PROJECT_DIR = "Digital-Twin-SDN"  # the folder the code ZIP unpacks to
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
STORED_SUFFIXES = {".pdf", ".png"}  # already deflated; parquet (snappy) still shrinks by a quarter


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
    `limit` is deleted and refused."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for source, name in files:
            kind = zipfile.ZIP_STORED if source.suffix in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
            zf.write(source, name, compress_type=kind)
    size = out.stat().st_size
    if size > limit:
        out.unlink()
        raise SubmissionError(
            f"{out.name} is {size / 2**20:.1f} MB: over the {limit / 2**20:.0f} MB limit"
        )
    return size


def build_code_zip(root: Path, out: Path, limit: int = ZIP_LIMIT_BYTES) -> int:
    """Code_and_Data.zip: the repository files plus the recorded evaluation."""
    paths = sorted({*repository_files(root), *evidence_files(root)})
    check_no_secrets(paths)
    return write_zip(out, ((root / p, f"{PROJECT_DIR}/{p.as_posix()}") for p in paths), limit)


def paper_sources(paper: Path) -> list[Path]:
    """The paper's source files, relative to its folder (no build output)."""
    missing = [n for n in PAPER_FILES if not (paper / n).exists()]
    if missing:
        raise SubmissionError(f"the paper has no {', '.join(missing)}")
    generated = [*(paper / "generated").glob("*.tex"), *(paper / "figures").glob("*.pdf")]
    return [Path(n) for n in PAPER_FILES] + sorted(p.relative_to(paper) for p in generated)


def build_overleaf_zip(paper: Path, out: Path) -> int:
    """Overleaf_Source.zip: the paper's source with its files at the top level."""
    return write_zip(out, ((paper / p, p.as_posix()) for p in paper_sources(paper)))


def build_revision_report(source: Path, out: Path) -> None:
    """Revision_Report.docx from the Markdown report (pandoc, bundled with pypandoc-binary)."""
    pypandoc.convert_file(str(source), "docx", outputfile=str(out))


def checksums(files: Iterable[Path]) -> str:
    """SHA256SUMS.txt text: `<hash>  <file name>` per file."""
    lines = []
    for f in sorted(files):
        with f.open("rb") as handle:  # streamed: the code ZIP is tens of MB
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
    build_overleaf_zip(paper_build.PAPER, dist / "Overleaf_Source.zip")
    build_code_zip(ROOT, dist / "Code_and_Data.zip")
    shutil.copyfile(paper_build.compile_pdf(), dist / "paper.pdf")
    build_revision_report(
        SUBMISSION / "revisions" / "revision_report.md", dist / "Revision_Report.docx"
    )
    deliverables = [
        dist / name
        for name in (
            "Overleaf_Source.zip",
            "Code_and_Data.zip",
            "paper.pdf",
            "Revision_Report.docx",
        )
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
