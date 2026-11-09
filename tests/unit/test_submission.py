"""The final submission package (experiments/submission.py): what goes into the ZIPs."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from experiments import submission


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # noqa: S603, S607 - test repo


def _write(root: Path, name: str, text: str = "x") -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small repository shaped like the real one: code, ignored data, a secret, a log."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _write(
        root, ".gitignore", ".env\nlogs/\ndata/*\n!data/README.md\nmodels/\nexperiments/results/\n"
    )
    _write(root, "src/a.py", "print('hi')")
    _write(root, ".env", "OPERATOR_TOKEN=do-not-ship")
    _write(root, ".env.example", "OPERATOR_TOKEN=")
    _write(root, "logs/api.log", "token in a log")
    _write(root, "data/scratch/notes.txt", "not part of the evaluation")
    for item in submission.EVIDENCE:  # the recorded evaluation: a file in each required path
        _write(root, item if item.endswith(".md") else f"{item}/part.dat")
    _write(root, "frontend design images/design.png", "png")
    _write(root, "final_submission/dist/old.zip", "an earlier build")
    return root


def _names(zip_path: Path) -> set[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return set(zf.namelist())


def test_repository_files_follow_the_ignore_rules(repo: Path) -> None:
    files = {p.as_posix() for p in submission.repository_files(repo)}
    assert {"src/a.py", ".env.example", "data/README.md", ".gitignore"} <= files
    assert ".env" not in files  # ignored: the secrets
    assert "logs/api.log" not in files
    assert "data/evalv1-v1/part.dat" not in files  # ignored data: added as evidence instead
    assert not any(
        f.startswith(("frontend design images/", "final_submission/dist/")) for f in files
    )


def test_the_recorded_evaluation_is_added_even_though_git_ignores_it(repo: Path) -> None:
    files = {p.as_posix() for p in submission.evidence_files(repo)}
    assert "data/evalv1-v1/part.dat" in files
    assert "models/part.dat" in files
    assert "data/README.md" in files
    assert len(files) == len(submission.EVIDENCE)  # one file in each; data/scratch is not there


def test_a_missing_part_of_the_evaluation_stops_the_build(repo: Path, tmp_path: Path) -> None:
    shutil.rmtree(repo / "data" / "evalv2-v1")
    with pytest.raises(submission.SubmissionError, match="evalv2-v1"):
        submission.build_code_zip(repo, tmp_path / "Code_and_Data.zip")


def test_the_code_zip_holds_code_and_evidence_but_no_secret(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "Code_and_Data.zip"
    size = submission.build_code_zip(repo, out)
    names = _names(out)
    assert size == out.stat().st_size > 0
    assert "Digital-Twin-SDN/src/a.py" in names
    assert "Digital-Twin-SDN/data/evalv1-v1/part.dat" in names
    assert "Digital-Twin-SDN/.env.example" in names
    assert not any(n.endswith("/.env") or "/logs/" in n for n in names)


def test_images_and_pdfs_are_stored_but_parquet_and_text_are_deflated(tmp_path: Path) -> None:
    (tmp_path / "figure.png").write_text("x" * 1000)
    (tmp_path / "notes.txt").write_text("x" * 1000)
    (tmp_path / "rows.parquet").write_text("x" * 1000)  # snappy inside: deflate still gains 25%
    out = tmp_path / "out.zip"
    names = ("figure.png", "notes.txt", "rows.parquet")
    submission.write_zip(out, [(tmp_path / name, name) for name in names])
    with zipfile.ZipFile(out) as zf:
        kinds = {i.filename: i.compress_type for i in zf.infolist()}
    assert kinds == {
        "figure.png": zipfile.ZIP_STORED,
        "notes.txt": zipfile.ZIP_DEFLATED,
        "rows.parquet": zipfile.ZIP_DEFLATED,
    }


@pytest.mark.parametrize(
    "path",
    [".env", "config/.env.local", "keys/server.pem", "id.key", "logs/api.log", "a/logs/b.txt"],
)
def test_a_secret_looking_file_stops_the_build(path: str) -> None:
    with pytest.raises(submission.SubmissionError, match="secret-looking"):
        submission.check_no_secrets([Path("src/a.py"), Path(path)])


def test_the_env_template_is_allowed() -> None:
    submission.check_no_secrets([Path(".env.example"), Path("docs/environment.md")])


def test_a_secret_that_was_tracked_anyway_is_still_refused(repo: Path, tmp_path: Path) -> None:
    _git(repo, "add", "-f", ".env")  # someone forced it in: git's ignore rules no longer help
    with pytest.raises(submission.SubmissionError, match=r"\.env"):
        submission.build_code_zip(repo, tmp_path / "Code_and_Data.zip")
    assert not (tmp_path / "Code_and_Data.zip").exists()


def test_a_zip_over_the_limit_is_deleted_and_refused(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "Code_and_Data.zip"
    with pytest.raises(submission.SubmissionError, match="over the"):
        submission.build_code_zip(repo, out, limit=10)
    assert not out.exists()


def _paper(root: Path) -> Path:
    paper = root / "paper"
    for name in ("main.tex", "references.bib", "generated/numbers.tex", "figures/fig_kpis.pdf"):
        _write(paper, name)
    _write(paper, "main.pdf", "a build output")
    _write(paper, "generated/notes.md", "not LaTeX")
    return paper


def test_the_overleaf_zip_has_the_source_at_its_top_level(tmp_path: Path) -> None:
    out = tmp_path / "Overleaf_Source.zip"
    submission.build_overleaf_zip(_paper(tmp_path), out)
    assert _names(out) == {
        "main.tex",
        "references.bib",
        "generated/numbers.tex",
        "figures/fig_kpis.pdf",
    }  # no main.pdf, no stray files


def test_a_paper_without_its_source_is_refused(tmp_path: Path) -> None:
    paper = _paper(tmp_path)
    (paper / "references.bib").unlink()
    with pytest.raises(submission.SubmissionError, match=r"references\.bib"):
        submission.paper_sources(paper)


def test_checksums_name_each_file_with_its_hash(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("hello")
    (tmp_path / "a.txt").write_text("")
    text = submission.checksums([tmp_path / "b.txt", tmp_path / "a.txt"])
    assert text == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  a.txt\n"
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824  b.txt\n"
    )  # sha256 of "" and of "hello"


def test_the_revision_report_becomes_a_word_document(tmp_path: Path) -> None:
    source = tmp_path / "revision_report.md"
    source.write_text("# Revision report\n\n| Comment | Change |\n|---|---|\n| a | b |\n")
    out = tmp_path / "Revision_Report.docx"
    submission.build_revision_report(source, out)
    assert out.read_bytes().startswith(b"PK")  # a .docx is a ZIP


def test_a_build_that_cannot_be_made_says_why(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def refused() -> dict[str, int]:
        raise submission.SubmissionError("Code_and_Data.zip is 120.0 MB: over the 100 MB limit")

    monkeypatch.setattr(submission, "build", refused)
    assert submission.main([]) == 1
    assert "over the 100 MB limit" in caplog.text


@pytest.mark.parametrize(
    "path",
    [
        *("prod.env", ".envrc", "credentials.json", "a/token.json", "x.token", "secrets/a.txt"),
        *("secrets.json", "app.p12", "id_rsa", "ID.PEM", ".ENV", "api.log", "a/.secrets/x"),
        "x.secret",
    ],
)
def test_every_secret_kind_the_ignore_rules_name_is_refused_too(path: str) -> None:
    with pytest.raises(submission.SubmissionError, match="secret-looking"):
        submission.check_no_secrets([Path(path)])


def test_a_symlink_is_never_packaged(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the project")
    (repo / "src" / "link.txt").symlink_to(outside)
    (repo / "models" / "link.dat").symlink_to(outside)
    names = {p.as_posix() for p in submission.repository_files(repo)}
    names |= {p.as_posix() for p in submission.evidence_files(repo)}
    assert "src/link.txt" not in names
    assert "models/link.dat" not in names


def test_a_folder_that_is_not_a_repository_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(submission.SubmissionError, match="not a git repository"):
        submission.repository_files(tmp_path)


def test_a_paper_that_is_out_of_date_is_not_packaged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(submission, "_stale_paper_files", lambda: "numbers.tex")
    with pytest.raises(submission.SubmissionError, match=r"out of date.*numbers\.tex"):
        submission.build(tmp_path / "dist")
    assert not (tmp_path / "dist").exists()
