[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$consoleRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $consoleRoot
try {
    # Tauri invokes this hook exactly once. Keeping the complete preflight here
    # avoids a second Vite build when callers use pnpm build:windows.
    & pnpm build
    if ($LASTEXITCODE -ne 0) { throw "pnpm build failed with exit code $LASTEXITCODE" }
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $consoleRoot "scripts\build-sidecar.ps1")
    if ($LASTEXITCODE -ne 0) { throw "sidecar build failed with exit code $LASTEXITCODE" }
    & node (Join-Path $consoleRoot "scripts\create-bundle-inventory.mjs")
    if ($LASTEXITCODE -ne 0) { throw "bundle inventory failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
