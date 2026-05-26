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

& $Python -m dayz_translate_tool.build_checks
if ($LASTEXITCODE -ne 0) {
    throw "Current Python cannot package a ttkbootstrap/Tkinter app. Recreate .venv with a full Python installation that includes Tcl/Tk, then run build.ps1 again."
}

$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", "DayZTranslateTool",
    "--windowed",
    "--distpath", $ReleaseDir,
    "--workpath", $BuildDir,
    "--specpath", $Root,
    "--collect-all", "ttkbootstrap",
    "--add-data", "stringtable.csv;.",
    "main.py"
)

& $Python @PyInstallerArgs

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (Test-Path -LiteralPath $SpecFile) {
    Remove-Item -LiteralPath $SpecFile -Force
}
