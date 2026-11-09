<#
.SYNOPSIS
  Build the Lumina Studio Plus Windows desktop package (NSIS installer + portable zip).

.DESCRIPTION
  1. Downloads the official CPython 3.12 x64 runtime (python.org NuGet package)
     and verifies it against NuGet's published SHA-512.
  2. Installs requirements.txt into that runtime (no venv: it must stay relocatable).
  3. Builds the frontend (pnpm) and stages the backend tree.
  4. Runs the backend self-tests with the bundled runtime.
  5. Packages everything with electron-builder.

  Requirements on the build machine: Windows x64, Node.js 22.13+ / 24, pnpm 10.33.2,
  network access. No system Python is needed.

  在 Windows x64 上运行：下载内置 Python、安装依赖、构建前端、自检，然后用
  electron-builder 生成安装包和免安装 zip。产物在 dist-desktop\。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#>
[CmdletBinding()]
param(
  # CPython version from the official python.org NuGet package.
  [string]$PythonVersion = "3.12.10",
  # Optional pinned base64 SHA-512 of the .nupkg; NuGet's registration hash is used otherwise.
  [string]$PythonSha512 = "",
  # Skip electron-builder (stage + self-test only).
  [switch]$StageOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Work = Join-Path $PSScriptRoot "work"
$Stage = Join-Path $PSScriptRoot "stage"
$StageApp = Join-Path $Stage "app"
$StagePython = Join-Path $Stage "python"

function Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }
function Invoke-Checked {
  param([string]$File, [string[]]$Arguments, [string]$WorkingDirectory = $RepoRoot)
  Push-Location $WorkingDirectory
  try {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
  } finally { Pop-Location }
}

New-Item -ItemType Directory -Force -Path $Work | Out-Null
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $StageApp, $StagePython | Out-Null

# ── 1. Python runtime ─────────────────────────────────────────────
# Official python.org build published on NuGet (package "python"): a complete,
# relocatable CPython with its own VC++ runtime DLLs. 3.12.10 is the final
# 3.12 release with Windows binaries.
Step "Downloading CPython $PythonVersion (python.org NuGet package)"
$PackageId = "python"
$NupkgUrl = "https://api.nuget.org/v3-flatcontainer/$PackageId/$PythonVersion/$PackageId.$PythonVersion.nupkg"
$NupkgPath = Join-Path $Work "$PackageId.$PythonVersion.nupkg"
if (-not (Test-Path $NupkgPath)) { Invoke-WebRequest -Uri $NupkgUrl -OutFile $NupkgPath }
if ($PythonSha512) {
  $ExpectedHash = $PythonSha512
} else {
  # The registration entry records the SHA-512 NuGet computed at publish time.
  $Registration = Invoke-RestMethod -Uri "https://api.nuget.org/v3/registration5-semver1/$PackageId/$PythonVersion.json"
  $Catalog = Invoke-RestMethod -Uri $Registration.catalogEntry
  if ($Catalog.packageHashAlgorithm -ne "SHA512") { throw "Unexpected NuGet hash algorithm $($Catalog.packageHashAlgorithm)" }
  $ExpectedHash = $Catalog.packageHash
}
$Sha512 = [System.Security.Cryptography.SHA512]::Create()
$Stream = [System.IO.File]::OpenRead($NupkgPath)
try { $ActualHash = [Convert]::ToBase64String($Sha512.ComputeHash($Stream)) } finally { $Stream.Dispose() }
if ($ActualHash -ne $ExpectedHash) { Remove-Item $NupkgPath; throw "Checksum mismatch for $PackageId $PythonVersion" }
Write-Host "Verified $PackageId $PythonVersion (SHA-512 $ActualHash)"

$Extract = Join-Path $Work "python-extract"
if (Test-Path $Extract) { Remove-Item -Recurse -Force $Extract }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($NupkgPath, $Extract)
Copy-Item -Recurse -Force (Join-Path $Extract "tools\*") $StagePython
$Python = Join-Path $StagePython "python.exe"
if (-not (Test-Path $Python)) { throw "python.exe missing from the NuGet package" }
& $Python --version

# ── 2. Python dependencies ────────────────────────────────────────
Step "Installing Python dependencies into the bundled runtime"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"
Invoke-Checked $Python @("-m", "ensurepip", "--upgrade")
Invoke-Checked $Python @("-m", "pip", "install", "--no-warn-script-location", "--upgrade", "pip")
Invoke-Checked $Python @("-m", "pip", "install", "--no-warn-script-location",
  "-r", (Join-Path $RepoRoot "requirements.txt"),
  "-c", (Join-Path $PSScriptRoot "constraints.txt"))
& $Python -m pip freeze | Set-Content -Encoding utf8 (Join-Path $Stage "python-freeze.txt")

# ── 3. Frontend + backend tree ────────────────────────────────────
Step "Building the frontend"
Invoke-Checked "pnpm" @("--dir", "frontend", "install", "--frozen-lockfile")
Invoke-Checked "pnpm" @("--dir", "frontend", "build")

Step "Staging the backend"
$CopyDirs = @("api", "core", "utils", "assets", "lut-preset", "machine_registry", "third_party")
foreach ($dir in $CopyDirs) {
  $source = Join-Path $RepoRoot $dir
  if (Test-Path $source) {
    robocopy $source (Join-Path $StageApp $dir) /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ .pytest_cache /XF *.pyc | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying $dir failed (robocopy exit $LASTEXITCODE)" }
  }
}
$global:LASTEXITCODE = 0
robocopy (Join-Path $RepoRoot "frontend\dist") (Join-Path $StageApp "frontend\dist") /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying frontend\dist failed" }
$global:LASTEXITCODE = 0
$CopyFiles = @("api_server.py", "config.py", "icon.ico", "logo.png", "LICENSE", "LICENSING.md",
  "THIRD_PARTY_NOTICES.md", "OUTPUT-TERMS.md", "COMMERCIAL-LICENSE.md", "README.md", "README_CN.md", ".env.example")
foreach ($file in $CopyFiles) {
  $source = Join-Path $RepoRoot $file
  if (Test-Path $source) { Copy-Item -Force $source (Join-Path $StageApp $file) }
}
# Record the source revision for "About" and bug reports.
$Revision = (git -C $RepoRoot rev-parse HEAD 2>$null)
if ($Revision) { Set-Content -Encoding ascii (Join-Path $StageApp "SOURCE_REVISION") $Revision.Trim() }

# ── 4. Self-tests with the bundled runtime ────────────────────────
Step "Running backend self-tests"
$SelfTestData = Join-Path $Work "selftest-data"
if (Test-Path $SelfTestData) { Remove-Item -Recurse -Force $SelfTestData }
$env:LUMINA_OUTPUT_DIR = Join-Path $SelfTestData "output"
$env:LUMINA_MATERIALS_DIR = Join-Path $SelfTestData "materials"
$env:LUMINA_LOG_DIR = Join-Path $SelfTestData "logs"
$env:NUMBA_CACHE_DIR = Join-Path $SelfTestData "numba"
$env:LUMINA_FEEDBACK_SERVER_URL = "off"
$Svg = Join-Path $SelfTestData "selftest.svg"
New-Item -ItemType Directory -Force -Path $SelfTestData | Out-Null
Set-Content -Encoding utf8 $Svg '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20"><rect x="2" y="2" width="16" height="16" fill="#e11d48"/><circle cx="10" cy="10" r="4" fill="#2563eb"/></svg>'
Invoke-Checked $Python @((Join-Path $StageApp "api_server.py"), "--native-svg-self-test", $Svg) -WorkingDirectory $StageApp
Invoke-Checked $Python @((Join-Path $StageApp "api_server.py"), "--svg-hole-compensation-self-test") -WorkingDirectory $StageApp
Invoke-Checked $Python @((Join-Path $StageApp "api_server.py"), "--material-sampling-self-test") -WorkingDirectory $StageApp
foreach ($name in @("LUMINA_OUTPUT_DIR", "LUMINA_MATERIALS_DIR", "LUMINA_LOG_DIR", "NUMBA_CACHE_DIR", "LUMINA_FEEDBACK_SERVER_URL")) {
  Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
# Self-tests must not leave files inside the packaged tree.
Get-ChildItem -Path $StageApp -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
foreach ($leftover in @("output", "materials", "logs", "feedback")) {
  $path = Join-Path $StageApp $leftover
  if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}

if ($StageOnly) { Step "Stage ready at $Stage"; exit 0 }

# ── 5. Package ────────────────────────────────────────────────────
Step "Packaging with electron-builder"
# electron-builder pulls @electron/node-gyp from GitHub over SSH; use HTTPS so
# machines without a GitHub SSH key can build. Scoped to this process only.
$env:GIT_CONFIG_COUNT = "1"
$env:GIT_CONFIG_KEY_0 = "url.https://github.com/.insteadOf"
$env:GIT_CONFIG_VALUE_0 = "git@github.com:"
Invoke-Checked "pnpm" @("--dir", "electron", "install", "--frozen-lockfile")
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
Invoke-Checked "pnpm" @("--dir", "electron", "run", "dist:win")

Step "Done. Output:"
Get-ChildItem (Join-Path $RepoRoot "dist-desktop") -File | Where-Object { $_.Extension -in ".exe", ".zip" } |
  ForEach-Object { "{0}  {1:N0} MB" -f $_.Name, ($_.Length / 1MB) }
