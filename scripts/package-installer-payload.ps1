#!/usr/bin/env pwsh
# Package only the distributable desktop app files into app-payload.zip.
#
# Intentionally does NOT copy the whole target/release tree — that directory
# contains Cargo build caches (deps/, build/, incremental/, .fingerprint/)
# and MSVC .pdb debug symbols, which ballooned the payload to ~1GB.
param(
  [string]$DesktopBundle = "",
  [string]$OutZip = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktopRoot = Join-Path $repoRoot "HakusAgent\frontend\desktop-tauri"
$installerPayload = Join-Path $repoRoot "HakusAgent\frontend\installer\src-tauri\payload"

if (-not $DesktopBundle) {
  $DesktopBundle = Join-Path $desktopRoot "src-tauri\target\release"
}
if (-not $OutZip) {
  $OutZip = Join-Path $installerPayload "app-payload.zip"
}

function Write-DirListing([string]$path) {
  Write-Host "Listing $path :"
  if (-not (Test-Path $path)) {
    Write-Host "  (missing)"
    return
  }
  Get-ChildItem -Path $path -ErrorAction SilentlyContinue | Select-Object -First 80 | ForEach-Object {
    Write-Host ("  {0}  {1}" -f $_.Mode, $_.Name)
  }
}

if (-not (Test-Path $DesktopBundle)) {
  Write-DirListing (Join-Path $desktopRoot "src-tauri\target")
  throw "Desktop build output not found: $DesktopBundle"
}

# Tauri/Cargo may emit either the productName or the crate bin name.
$candidateNames = @("HakusAI.exe", "desktop-tauri.exe", "hakusai.exe")

$exe = $null
foreach ($name in $candidateNames) {
  $direct = Join-Path $DesktopBundle $name
  if (Test-Path $direct) {
    $exe = $direct
    break
  }
}

if (-not $exe) {
  $found = Get-ChildItem -Path $DesktopBundle -File -Filter *.exe -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -match '^(HakusAI|desktop-tauri|hakusai)\.exe$' -and
      $_.FullName -notmatch '\\bundle\\' -and
      $_.FullName -notmatch 'nsis'
    } |
    Select-Object -First 1
  if ($found) { $exe = $found.FullName }
}

if (-not $exe) {
  Write-DirListing $DesktopBundle
  throw "Desktop app exe not found under $DesktopBundle (looked for: $($candidateNames -join ', '))"
}

Write-Host "Source exe: $exe ($([math]::Round((Get-Item $exe).Length/1MB,1)) MB)"

$stage = Join-Path $env:TEMP ("hakusai-payload-" + [guid]::NewGuid().ToString("N"))
$payloadRoot = Join-Path $stage "HakusAI"
New-Item -ItemType Directory -Force -Path $payloadRoot | Out-Null

try {
  # Tauri embeds frontend assets into the single binary. Ship only the app
  # exe plus any real runtime sidecars / resources — never Cargo caches.
  Copy-Item $exe (Join-Path $payloadRoot "HakusAI.exe") -Force

  # Optional sidecar binaries that some builds place next to the main exe.
  # Skip known Cargo/MSVC noise.
  $skipName = @(
    '^HakusAI\.pdb$', '^desktop-tauri\.pdb$', '^hakusai\.pdb$',
    '^build-script-', '^\.cargo-lock$', '^\.rustc_info\.json$'
  )
  $skipDir = @('deps', 'build', 'incremental', '.fingerprint', 'bundle', 'examples', 'native')

  Get-ChildItem -Path $DesktopBundle -File -ErrorAction SilentlyContinue | ForEach-Object {
    $name = $_.Name
    if ($name -ieq 'HakusAI.exe' -or $name -ieq 'desktop-tauri.exe' -or $name -ieq 'hakusai.exe') { return }
    foreach ($pat in $skipName) { if ($name -match $pat) { return } }
    if ($name -match '\.(pdb|d|rlib|rcgu|exp|lib|obj|ilk|ipdb|iobj)$') { return }
    # Keep only plausible runtime companions (dll/exe/json/toml) in the root.
    if ($name -match '\.(dll|exe|json|toml|txt|md)$') {
      Copy-Item $_.FullName (Join-Path $payloadRoot $name) -Force
      Write-Host "  + $name"
    }
  }

  # Optional resources/ directory if the app ever ships external assets.
  $resDir = Join-Path $DesktopBundle 'resources'
  if (Test-Path $resDir) {
    Copy-Item $resDir (Join-Path $payloadRoot 'resources') -Recurse -Force
    Write-Host "  + resources/"
  }

  $appExe = Join-Path $payloadRoot "HakusAI.exe"
  if (-not (Test-Path $appExe)) {
    Write-DirListing $payloadRoot
    throw "Staged payload is missing HakusAI.exe"
  }

  New-Item -ItemType Directory -Force -Path (Split-Path $OutZip) | Out-Null
  if (Test-Path $OutZip) { Remove-Item $OutZip -Force }

  Compress-Archive -Path (Join-Path $payloadRoot "*") -DestinationPath $OutZip -CompressionLevel Optimal
  $zipMb = [math]::Round((Get-Item $OutZip).Length / 1MB, 1)
  $rawMb = [math]::Round((Get-ChildItem $payloadRoot -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
  Write-Host "Payload files: $rawMb MB uncompressed -> zip $zipMb MB ($OutZip)"

  if ($zipMb -gt 120) {
    Write-Host "::warning::Payload zip is unexpectedly large ($zipMb MB). Inspect staged files."
    Write-DirListing $payloadRoot
  }
}
finally {
  if (Test-Path $stage) {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
  }
}
