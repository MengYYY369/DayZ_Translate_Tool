param(
    [string]$AppName = "DayZ_Translate_Tool",
    # Python used for the build. Empty means: prefer the local 3.13 install,
    # so a `python` from PATH that belongs to some other tool's virtualenv
    # does not get PySide6 installed into it.
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EntryPoint = Join-Path $ProjectRoot "main.py"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$DistRoot = Join-Path $ProjectRoot "dist"
$BuildRoot = Join-Path $ProjectRoot "build"
$ExePath = Join-Path (Join-Path $DistRoot $AppName) "$AppName.exe"
$AppIcon = Join-Path $ProjectRoot "assets\app.ico"

if (-not (Test-Path -LiteralPath $EntryPoint)) {
    throw "Entry point not found: $EntryPoint"
}

if (-not (Test-Path -LiteralPath $AppIcon)) {
    throw "Application icon not found: $AppIcon"
}

if (-not $PythonPath) {
    $LocalPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
    if (Test-Path -LiteralPath $LocalPython) {
        $PythonPath = $LocalPython
    }
}
if (-not $PythonPath) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python was not found in PATH. Pass -PythonPath <python.exe>."
    }
    $PythonPath = $PythonCommand.Source
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python not found: $PythonPath"
}

Write-Host "Using Python: $PythonPath"

if (Test-Path -LiteralPath $Requirements) {
    Write-Host "Installing project requirements..."
    & $PythonPath -m pip install -r $Requirements
}

Write-Host "Ensuring PyInstaller is installed..."
& $PythonPath -m pip install pyinstaller

$pyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $AppName,
    "--icon", $AppIcon,
    "--distpath", $DistRoot,
    "--workpath", $BuildRoot,
    "--specpath", $BuildRoot,
    "--exclude-module", "aiohttp",
    "--exclude-module", "anyio",
    "--exclude-module", "cryptography",
    "--exclude-module", "dateutil",
    "--exclude-module", "dns",
    "--exclude-module", "docx2txt",
    "--exclude-module", "email_validator",
    "--exclude-module", "fsspec",
    "--exclude-module", "httpx",
    "--exclude-module", "jinja2",
    "--exclude-module", "lxml",
    "--exclude-module", "markdown_it",
    "--exclude-module", "mypy",
    "--exclude-module", "numpy",
    "--exclude-module", "openpyxl",
    "--exclude-module", "pandas",
    "--exclude-module", "PIL",
    "--exclude-module", "pydantic",
    "--exclude-module", "pydantic_core",
    "--exclude-module", "pygments",
    "--exclude-module", "pypdf",
    "--exclude-module", "pytest",
    "--exclude-module", "rich",
    "--exclude-module", "scipy",
    "--exclude-module", "setuptools",
    "--exclude-module", "websockets",
    "--exclude-module", "yaml"
)
$pyInstallerArgs += $EntryPoint

# PyInstaller COLLECT wipes the dist folder: back up user data files living next
# to the exe first, restore them after the build.
$ExeDir = Split-Path -Parent $ExePath
$BackupDir = Join-Path $BuildRoot "user_data_backup"
$preservedFiles = @()
if (Test-Path -LiteralPath $ExeDir) {
    foreach ($DataFileName in @("stringtable.csv", "wordbook.csv")) {
        $LiveFile = Join-Path $ExeDir $DataFileName
        if (Test-Path -LiteralPath $LiveFile) {
            New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
            Copy-Item -LiteralPath $LiveFile -Destination (Join-Path $BackupDir $DataFileName) -Force
            $preservedFiles += $DataFileName
        }
    }
}

Write-Host "Building executable..."
& $PythonPath -m PyInstaller @pyInstallerArgs

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Build finished but executable was not found: $ExePath"
}

# Restore the user data files that lived next to the exe before the build.
# Never copy project-root csv files over them: those are the user's live data.
foreach ($DataFileName in $preservedFiles) {
    Copy-Item -LiteralPath (Join-Path $BackupDir $DataFileName) -Destination (Join-Path $ExeDir $DataFileName) -Force
}

Write-Host "Build complete: $ExePath"
