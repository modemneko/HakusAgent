#!/usr/bin/env pwsh
# Package the built desktop app into installer payload app-payload.zip
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
$candidateNames = @(
  "HakusAI.exe",
  "desktop-tauri.exe",
  "hakusai.exe"
)

$exe = $null
foreach ($name in $candidateNames) {
  $direct = Join-Path $DesktopBundle $name
  if (Test-Path $direct) {
    $exe = $direct
    break
  }
}

if (-not $exe) {
  # Search one level under target/release for app binaries (skip installer/NSIS helpers).
  $found = Get-ChildItem -Path $DesktopBundle -Recurse -File -Include *.exe -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -match '^(HakusAI|desktop-tauri|hakusai)\.exe$' -and
      $_.FullName -notmatch '\\bundle\\' -and
      $_.FullName -notmatch 'nsis'
    } |
    Select-Object -First 1
  if ($found) {
    $exe = $found.FullName
  }
}

if (-not $exe) {
  Write-DirListing $DesktopBundle
  Write-DirListing (Join-Path $DesktopBundle "bundle")
  throw "Desktop app exe not found under $DesktopBundle (looked for: $($candidateNames -join ', '))"
}

$exeDir = Split-Path -Parent $exe
Write-Host "Staging from $exeDir (exe=$([IO.Path]::GetFileName($exe)))"

$stage = Join-Path $env:TEMP ("hakusai-payload-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $stage | Out-Null

try {
  Copy-Item -Path (Join-Path $exeDir "*") -Destination $stage -Recurse -Force

  # Normalize layout: zip entries live under HakusAI/ so the installer can strip a single root.
  $payloadRoot = Join-Path $stage "HakusAI"
  if (-not (Test-Path $payloadRoot)) {
    New-Item -ItemType Directory -Force -Path $payloadRoot | Out-Null
    Get-ChildItem $stage | Where-Object { $_.Name -ne "HakusAI" } | ForEach-Object {
      Move-Item $_.FullName -Destination $payloadRoot -Force
    }
  }

  # Installer looks for HakusAI.exe — copy/rename the crate binary if needed.
  $appExe = Get-ChildItem -Path $payloadRoot -Filter "*.exe" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(HakusAI|desktop-tauri|hakusai)\.exe$' } |
    Select-Object -First 1
  if (-not $appExe) {
    Write-DirListing $payloadRoot
    throw "No app exe inside staged payload"
  }
  if ($appExe.Name -ne "HakusAI.exe") {
    Copy-Item $appExe.FullName (Join-Path $payloadRoot "HakusAI.exe") -Force
    Write-Host "Normalized $($appExe.Name) -> HakusAI.exe"
  }

  New-Item -ItemType Directory -Force -Path (Split-Path $OutZip) | Out-Null
  if (Test-Path $OutZip) { Remove-Item $OutZip -Force }

  Compress-Archive -Path (Join-Path $payloadRoot "*") -DestinationPath $OutZip -CompressionLevel Optimal
  $sizeMb = [math]::Round((Get-Item $OutZip).Length / 1MB, 1)
  Write-Host "Wrote $OutZip ($sizeMb MB)"
}
finally {
  if (Test-Path $stage) {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
  }
}
