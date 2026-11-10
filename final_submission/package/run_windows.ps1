# One command to check the project on Windows 10/11. No Ubuntu, WSL, Docker or LLM is needed.
# Double-click run_windows.bat (it starts this script), or from PowerShell, in the unpacked folder:
#
#   powershell -ExecutionPolicy Bypass -File .\run_windows.ps1            results + paper check
#   powershell -ExecutionPolicy Bypass -File .\run_windows.ps1 -Tests     the same, then the unit tests
#
# Safe to run again: it skips what is done.
param([switch]$Tests)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONUTF8 = '1'   # the code reads and writes UTF-8 text; Windows would default to cp1252

function Say($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nERROR: $text" -ForegroundColor Red; exit 1 }
function Run($what) {   # run a command line; stop if it fails
    & $what[0] $what[1..($what.Length - 1)]
    if ($LASTEXITCODE -ne 0) { Fail "'$($what -join ' ')' failed (exit code $LASTEXITCODE)" }
}

if (-not ((Test-Path "$here\Dataset") -and (Test-Path "$here\Source_Code"))) {
    Fail 'run this script from the unpacked Final_Submission folder (next to Dataset and Source_Code)'
}

Say '1/4  Putting the dataset where the code expects it'
if (Test-Path "$here\Source_Code\data\evalv1-v1") {
    Write-Host 'already done'
} else {
    robocopy "$here\Dataset" "$here\Source_Code" /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "copying Dataset into Source_Code failed (robocopy exit code $LASTEXITCODE)" }
    Write-Host 'copied Dataset into Source_Code'
}

Say '2/4  Checking for uv (it installs Python 3.11 and the packages for you)'
$uvBin = Join-Path $env:USERPROFILE '.local\bin'
$env:Path = "$uvBin;$env:Path"
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "found: $(uv --version)"
} else {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$uvBin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Fail 'uv was installed but is not on the PATH. Open a new PowerShell window and run this script again'
    }
}

Set-Location "$here\Source_Code"

Say '3/4  Installing the Python environment (first time: a few minutes and about 700 MB of downloads)'
Run @('uv', 'sync', '--frozen')

Say '4/4  Regenerating the results and checking them against the paper'
Run @('uv', 'run', 'python', '-m', 'experiments.analysis.results')
Run @('uv', 'run', 'python', '-m', 'experiments.paper_build', '--check')
Write-Host "paper-check passed: the paper's numbers match the evaluation"

if ($Tests) {
    Say 'Unit tests'
    Run @('uv', 'run', 'pytest', 'tests/unit', '-q', '--no-cov')
}

Write-Host @"

DONE.
  Results (tables, plots):    $here\Source_Code\experiments\results\results.md
  The paper:                  $here\paper.pdf
  Re-run the unit tests:      run_windows.bat -Tests
  Compile the paper yourself: upload Overleaf.zip to Overleaf (nothing to install)
"@
