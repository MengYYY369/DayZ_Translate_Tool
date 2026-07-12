param(
    [string]$AppName = "DayZ_Translate_Tool"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EntryPoint = Join-Path $ProjectRoot "main.py"
$Requirements = Join-Path $ProjectRoot "requirements.txt"
$DistRoot = Join-Path $ProjectRoot "dist"
$BuildRoot = Join-Path $ProjectRoot "build"
$ExePath = Join-Path (Join-Path $DistRoot $AppName) "$AppName.exe"

if (-not (Test-Path -LiteralPath $EntryPoint)) {
    throw "Entry point not found: $EntryPoint"
}

$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCommand) {
    throw "Python was not found in PATH."
}

Write-Host "Using Python: $($PythonCommand.Source)"

if (Test-Path -LiteralPath $Requirements) {
    Write-Host "Installing project requirements..."
    & $PythonCommand.Source -m pip install -r $Requirements
}

Write-Host "Ensuring PyInstaller is installed..."
& $PythonCommand.Source -m pip install pyinstaller

$dataArgs = @()
foreach ($DataFileName in @("stringtable.csv", "wordbook.csv")) {
    $SourceDataFile = Join-Path $ProjectRoot $DataFileName
    if (Test-Path -LiteralPath $SourceDataFile) {
        $dataArgs += @("--add-data", "$SourceDataFile;.")
    }
}

$pyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $AppName,
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
$pyInstallerArgs += $dataArgs
$pyInstallerArgs += $EntryPoint

Write-Host "Building executable..."
& $PythonCommand.Source -m PyInstaller @pyInstallerArgs

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Build finished but executable was not found: $ExePath"
}

foreach ($DataFileName in @("stringtable.csv", "wordbook.csv")) {
    $SourceDataFile = Join-Path $ProjectRoot $DataFileName
    if (Test-Path -LiteralPath $SourceDataFile) {
        Copy-Item -LiteralPath $SourceDataFile -Destination (Join-Path (Split-Path -Parent $ExePath) $DataFileName) -Force
    }
}

Write-Host "Build complete: $ExePath"
