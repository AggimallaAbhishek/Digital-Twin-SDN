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
    _write(root, "final_submission/paper/figures/fig_kpis.pdf", "pdf")
    _write(root, "experiments/results/figures/kpis_ap_failure.png", "png")
    _write(root, "docs/report/figures/fig-3-1.png", "png")
    return root


def _top_level(tmp_path: Path) -> list[tuple[Path, str]]:
    """The files that sit at the top of the package (built or copied by `build`)."""
    names = ("README.md", "install_dataset.sh", "Overleaf.zip", "paper.pdf", "Revision_Report.docx")
    for name in names:
        _write(tmp_path / "top", name)
    return [(tmp_path / "top" / name, name) for name in names]


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


def test_the_authors_workspace_is_left_out_but_the_paper_source_stays(repo: Path) -> None:
    _write(repo, "final_submission/README.md")
    _write(repo, "final_submission/revisions/paper_rev1.pdf", "pdf")
    _write(repo, "final_submission/package/run_windows.bat")
    _write(repo, "final_submission/paper/main.tex")
    _write(repo, "tests/unit/test_submission.py")
    files = {p.as_posix() for p in submission.repository_files(repo)}
    assert "final_submission/paper/main.tex" in files  # `make paper-check` reads it
    assert "final_submission/paper/figures/fig_kpis.pdf" in files
    assert not any(
        f.startswith(("final_submission/README", "final_submission/revisions/"))
        or f.startswith("final_submission/package/")
        for f in files
    )
    assert "tests/unit/test_submission.py" not in files  # its inputs are not shipped
    assert "src/a.py" in files


def test_the_recorded_evaluation_is_added_even_though_git_ignores_it(repo: Path) -> None:
    files = {p.as_posix() for p in submission.evidence_files(repo)}
    assert "data/evalv1-v1/part.dat" in files
    assert "models/part.dat" in files
    assert "data/README.md" in files
    assert "experiments/results/figures/kpis_ap_failure.png" in files
    assert "data/scratch/notes.txt" not in files  # not part of the evaluation
    assert len(files) == len(submission.EVIDENCE) + 1  # a file in each path, and that plot


def test_the_evidence_holds_no_os_folder_metadata(repo: Path) -> None:
    _write(repo, "models/.DS_Store", "finder")
    _write(repo, "data/evalv1-v1/Thumbs.db", "explorer")
    files = {p.name for p in submission.evidence_files(repo)}
    assert not files & {".DS_Store", "Thumbs.db"}
    assert "part.dat" in files


def test_a_missing_part_of_the_evaluation_stops_the_build(repo: Path, tmp_path: Path) -> None:
    shutil.rmtree(repo / "data" / "evalv2-v1")
    with pytest.raises(submission.SubmissionError, match="evalv2-v1"):
        submission.build_package(repo, tmp_path / "out.zip", _top_level(tmp_path))


def test_the_package_has_the_parts_the_instructor_listed(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "Final_Submission.zip"
    size = submission.build_package(repo, out, _top_level(tmp_path))
    names = _names(out)
    top = "Final_Submission/"
    assert size == out.stat().st_size > 0
    assert {
        top + n for n in ("README.md", "Overleaf.zip", "paper.pdf", "Revision_Report.docx")
    } <= names
    assert top + "Source_Code/src/a.py" in names  # the code
    assert top + "Source_Code/.env.example" in names
    assert top + "Dataset/data/evalv1-v1/part.dat" in names  # the dataset, in the repository layout
    assert top + "Dataset/data/README.md" in names
    assert top + "Dataset/models/part.dat" in names
    assert top + "Figures/paper/fig_kpis.pdf" in names  # the figures
    assert top + "Figures/results/kpis_ap_failure.png" in names
    assert top + "Figures/report/fig-3-1.png" in names


def test_the_dataset_is_not_repeated_in_the_source_code(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "Final_Submission.zip"
    submission.build_package(repo, out, _top_level(tmp_path))
    in_code = {n for n in _names(out) if "/Source_Code/" in n}
    assert not any(n.endswith(("data/README.md", "part.dat")) for n in in_code)


def test_the_package_holds_no_secret_log_or_frontend_scratch(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "Final_Submission.zip"
    submission.build_package(repo, out, _top_level(tmp_path))
    names = _names(out)
    assert not any(n.endswith(("/.env", ".log")) or "/logs/" in n for n in names)
    assert not any("frontend design images" in n or "/dist/" in n for n in names)


def test_a_missing_top_level_file_stops_the_build(repo: Path, tmp_path: Path) -> None:
    top = _top_level(tmp_path)
    top[2][0].unlink()  # the Overleaf zip was not built
    with pytest.raises(submission.SubmissionError, match=r"Overleaf\.zip"):
        submission.build_package(repo, tmp_path / "out.zip", top)


def test_the_setup_guide_states_what_the_evaluator_needs() -> None:
    guide = (submission.SUBMISSION / "SETUP.md").read_text()
    for needed in (
        "System requirements",
        "Python",
        "Disk",
        "Memory",
        "Internet",
        "install_dataset.sh",
    ):
        assert needed in guide, needed
    assert "SETUP.md" in (submission.PACKAGE_DOCS / "README.md").read_text()  # and it is linked


def test_the_installer_and_readme_of_the_package_exist_in_the_repository() -> None:
    docs = submission.PACKAGE_DOCS
    assert (docs / "README.md").is_file()
    script = docs / "install_dataset.sh"
    assert script.stat().st_mode & 0o100  # executable: `./install_dataset.sh` works after unzip


def test_each_os_has_a_one_click_runner_that_checks_the_results() -> None:
    docs = submission.PACKAGE_DOCS
    assert set(submission.RUNNERS) == {"run_mac_linux.sh", "run_windows.bat", "run_windows.ps1"}
    for name in submission.RUNNERS:
        assert (docs / name).is_file(), name
    assert (docs / "run_mac_linux.sh").stat().st_mode & 0o100  # executable after unzip
    for name in ("run_mac_linux.sh", "run_windows.ps1"):  # the same four steps, no `make` needed
        text = (docs / name).read_text()
        for step in ("uv", "sync", "experiments.analysis.results", "paper_build"):
            assert step in text, (name, step)
    assert "run_windows.ps1" in (docs / "run_windows.bat").read_text()


def test_the_docs_say_ubuntu_is_only_for_rerunning_the_testbed() -> None:
    for doc in (submission.SUBMISSION / "SETUP.md", submission.PACKAGE_DOCS / "README.md"):
        text = doc.read_text()
        assert "run_mac_linux.sh" in text, doc.name
        assert "run_windows.bat" in text, doc.name
        assert "No Ubuntu" in text, doc.name


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
        submission.build_package(repo, tmp_path / "Final_Submission.zip", _top_level(tmp_path))
    assert not (tmp_path / "Final_Submission.zip").exists()


def test_a_zip_over_the_limit_is_deleted_and_refused(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "Final_Submission.zip"
    with pytest.raises(submission.SubmissionError, match="over the"):
        submission.build_package(repo, out, _top_level(tmp_path), limit=10)
    assert not out.exists()


def _paper(root: Path) -> Path:
    paper = root / "paper"
    for name in ("main.tex", "references.bib", "generated/numbers.tex", "figures/fig_kpis.pdf"):
        _write(paper, name)
    _write(paper, "main.pdf", "a build output")
    _write(paper, "generated/notes.md", "not LaTeX")
    return paper


def test_the_overleaf_zip_has_the_source_at_its_top_level(tmp_path: Path) -> None:
    out = tmp_path / "Overleaf.zip"
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
        raise submission.SubmissionError("Final_Submission.zip is 120.0 MB: over the 100 MB limit")

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


def test_two_files_under_one_name_in_the_zip_are_refused(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one")
    (tmp_path / "b.txt").write_text("two")
    out = tmp_path / "out.zip"
    with pytest.raises(submission.SubmissionError, match="twice"):
        submission.write_zip(
            out, [(tmp_path / "a.txt", "x/f.txt"), (tmp_path / "b.txt", "x/f.txt")]
        )
    assert not out.exists()


def test_the_authors_overleaf_pdf_replaces_the_preview_when_it_exists(tmp_path: Path) -> None:
    built, final = tmp_path / "main.pdf", tmp_path / "paper_final.pdf"
    built.write_text("tectonic preview")
    assert submission.chosen_pdf(built, final) == built  # not provided yet
    final.write_text("compiled on Overleaf")
    assert submission.chosen_pdf(built, final) == final
