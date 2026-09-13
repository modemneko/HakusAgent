#!/usr/bin/env pwsh
# Package the built desktop app into installer payload app-payload.zip
param(
  [string]$DesktopBundle = "",
  [string]$OutZip = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$desktopRoot = Join-Path $repoRoot "HakusAgent\frontend\desktop-tauri"
$installerPayload = Join-Path $repoRoot "HakusAgent\frontend\installer\src-tauri\payload"

if (-not $DesktopBundle) {
  $DesktopBundle = Join-Path $desktopRoot "src-tauri\target\release"
}
if (-not $OutZip) {
  $OutZip = Join-Path $installerPayload "app-payload.zip"
}

if (-not (Test-Path $DesktopBundle)) {
  throw "Desktop build output not found: $DesktopBundle"
}

$stage = Join-Path $env:TEMP ("hakusai-payload-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$exe = Join-Path $DesktopBundle "HakusAI.exe"
if (-not (Test-Path $exe)) {
  # Fallback: nested bundle path from some tauri layouts
  $candidate = Get-ChildItem -Path $DesktopBundle -Recurse -Filter "HakusAI.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($candidate) { $exe = $candidate.FullName }
}
if (-not (Test-Path $exe)) {
  throw "HakusAI.exe not found under $DesktopBundle"
}

$exeDir = Split-Path -Parent $exe
Write-Host "Staging from $exeDir"
Copy-Item -Path (Join-Path $exeDir "*") -Destination $stage -Recurse -Force

# Prefer product folder name so strip_common_prefix works for either layout
$payloadRoot = Join-Path $stage "HakusAI"
if (-not (Test-Path $payloadRoot)) {
  New-Item -ItemType Directory -Force -Path $payloadRoot | Out-Null
  Get-ChildItem $stage | Where-Object { $_.Name -ne "HakusAI" } | ForEach-Object {
    Move-Item $_.FullName -Destination $payloadRoot -Force
  }
}

New-Item -ItemType Directory -Force -Path (Split-Path $OutZip) | Out-Null
if (Test-Path $OutZip) { Remove-Item $OutZip -Force }

Compress-Archive -Path (Join-Path $payloadRoot "*") -DestinationPath $OutZip -CompressionLevel Optimal
Write-Host "Wrote $OutZip ($([math]::Round((Get-Item $OutZip).Length/1MB,1)) MB)"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
