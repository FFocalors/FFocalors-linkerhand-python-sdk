[CmdletBinding()]
param(
    [string]$SdkRoot = "",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$consoleRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$repoRoot = (Resolve-Path (Join-Path $consoleRoot "..\.." )).Path
if ([string]::IsNullOrWhiteSpace($SdkRoot)) { $SdkRoot = $repoRoot }
$SdkRoot = (Resolve-Path -LiteralPath $SdkRoot).Path
$sdkPackage = Join-Path $SdkRoot "LinkerHand"
if (-not (Test-Path -LiteralPath $sdkPackage -PathType Container)) {
    throw "LINKERHAND_SDK_ROOT must contain LinkerHand/: $sdkPackage"
}

$bridgeRoot = Join-Path $consoleRoot "sidecar\linkerhand-bridge"
$spec = Join-Path $bridgeRoot "linkerhand_bridge.spec"
$dist = Join-Path $bridgeRoot "dist"
$work = Join-Path $bridgeRoot "build"
$binaries = Join-Path $consoleRoot "src-tauri\binaries"
$targetName = "linkerhand-sidecar-x86_64-pc-windows-msvc.exe"
$target = Join-Path $binaries $targetName

if (-not (Test-Path -LiteralPath $spec -PathType Leaf)) { throw "Missing PyInstaller spec: $spec" }
if (Test-Path -LiteralPath $dist) { Remove-Item -LiteralPath $dist -Recurse -Force }
if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
New-Item -ItemType Directory -Force -Path $dist, $work, $binaries | Out-Null

$env:LINKERHAND_SDK_ROOT = $SdkRoot
$pyInstaller = Get-Command pyinstaller -ErrorAction SilentlyContinue
if ($null -ne $pyInstaller) {
    & $pyInstaller.Source --noconfirm --clean --distpath $dist --workpath $work $spec
} else {
    & $Python -m PyInstaller --noconfirm --clean --distpath $dist --workpath $work $spec
}
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$built = Join-Path $dist "linkerhand-sidecar.exe"
if (-not (Test-Path -LiteralPath $built -PathType Leaf)) { throw "PyInstaller did not produce $built" }
Copy-Item -LiteralPath $built -Destination $target -Force
$size = (Get-Item -LiteralPath $target).Length
Write-Output ("Built {0} ({1:N0} bytes)" -f $targetName, $size)
