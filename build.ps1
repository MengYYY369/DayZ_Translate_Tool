$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReleaseDir = Join-Path $Root "release"
$BuildDir = Join-Path $Root "build"
$SpecFile = Join-Path $Root "DayZTranslateTool.spec"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }

if (-not (Test-Path -LiteralPath $ReleaseDir)) {
    New-Item -ItemType Directory -Path $ReleaseDir | Out-Null
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name DayZTranslateTool `
    --windowed `
    --distpath $ReleaseDir `
    --workpath $BuildDir `
    --specpath $Root `
    --add-data "stringtable.csv;." `
    "main.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (Test-Path -LiteralPath $SpecFile) {
    Remove-Item -LiteralPath $SpecFile -Force
}
