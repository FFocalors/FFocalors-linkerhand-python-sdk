[CmdletBinding()]
param(
    [string]$ReleaseExe = ""
)

$ErrorActionPreference = "Stop"
$consoleRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$package = Get-Content -LiteralPath (Join-Path $consoleRoot "package.json") -Raw | ConvertFrom-Json
$version = $package.version
$name = "LinkerHand-Console-v$version-win-x64-portable"
$artifacts = Join-Path $consoleRoot "artifacts"
$stageParent = Join-Path $artifacts "portable"
$stage = Join-Path $stageParent $name
$zip = Join-Path $artifacts "$name.zip"
$binaries = Join-Path $consoleRoot "src-tauri\binaries"
if ([string]::IsNullOrWhiteSpace($ReleaseExe)) {
    $ReleaseExe = Join-Path $consoleRoot "target\x86_64-pc-windows-msvc\release\linkerhand-console.exe"
    if (-not (Test-Path -LiteralPath $ReleaseExe)) {
        $ReleaseExe = Join-Path $consoleRoot "target\release\linkerhand-console.exe"
    }
}
$ReleaseExe = (Resolve-Path -LiteralPath $ReleaseExe).Path

if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
New-Item -ItemType Directory -Force -Path $stage, (Join-Path $stage "resources"), (Join-Path $stage "sidecar") | Out-Null
Copy-Item -LiteralPath $ReleaseExe -Destination (Join-Path $stage "linkerhand-console.exe")
$sidecar = Get-ChildItem -LiteralPath $binaries -Filter "linkerhand-sidecar-*.exe" -File | Select-Object -First 1
if ($null -eq $sidecar) { throw "Missing real sidecar. Run scripts/build-sidecar.ps1 first." }
Copy-Item -LiteralPath $sidecar.FullName -Destination (Join-Path $stage "sidecar\linkerhand-sidecar.exe")
$inventory = Join-Path $artifacts "bundle-inventory.json"
if (Test-Path -LiteralPath $inventory) { Copy-Item -LiteralPath $inventory -Destination (Join-Path $stage "resources\bundle-inventory.json") }
else { throw "Missing bundle inventory. Run pnpm bundle:inventory after building." }

Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal
$size = (Get-Item -LiteralPath $zip).Length
Write-Output ("Wrote {0} ({1:N0} bytes)" -f (Split-Path $zip -Leaf), $size)
