param(
    [Parameter(Mandatory = $true)][string]$KindleRoot,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$targetRoot = [IO.Path]::GetFullPath($KindleRoot)
if ($targetRoot -ne [IO.Path]::GetPathRoot($targetRoot)) { throw 'KindleRoot must be the USB drive root, such as E:\' }
if (-not (Test-Path -LiteralPath (Join-Path $targetRoot 'documents'))) { throw 'Kindle documents folder not found' }
if (-not (Test-Path -LiteralPath (Join-Path $targetRoot 'system'))) { throw 'Kindle system folder not found' }
if (-not (Test-Path -LiteralPath (Join-Path $targetRoot 'koreader/reader.lua'))) { throw 'Install and launch the PW2-family KOReader package before this add-on' }
$volume = Get-Volume -DriveLetter $targetRoot.Substring(0, 1)
if ($volume.DriveType -ne 'Removable') { throw 'The target must be the Kindle removable USB volume' }
$packageRoot = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $packageRoot 'manifest.json'))) { throw 'Run install.ps1 from the extracted release package' }
if ([IO.Path]::GetPathRoot($packageRoot) -eq [IO.Path]::GetPathRoot($targetRoot)) { throw 'Extract the package onto the computer, not onto the Kindle' }
$manifest = Get-Content -LiteralPath (Join-Path $packageRoot 'manifest.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest.files.PSObject.Properties) {
    $source = [IO.Path]::GetFullPath((Join-Path $packageRoot $entry.Name))
    if (-not $source.StartsWith($packageRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid manifest path' }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { throw "Package checksum failed: $($entry.Name)" }
}
$folders = @('koreader/plugins/tinta.koplugin', 'koreader/tinta-apps/ark_board')
foreach ($relative in $folders) {
    $target = [IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
    if (-not $target.StartsWith($targetRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Target escaped Kindle root' }
    Write-Output "Install: $relative"
}
if ($DryRun) { Write-Output 'Dry run passed. No Kindle files changed.'; return }
$backup = Join-Path $packageRoot ('backups/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($relative in $folders) {
    $target = [IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
    $source = Join-Path $packageRoot $relative
    if (Test-Path -LiteralPath $target) {
        $saved = Join-Path $backup $relative
        New-Item -ItemType Directory -Path $saved -Force | Out-Null
        # Enumerate only this fixed, verified add-on target.
        Get-ChildItem -Force -LiteralPath $target | Copy-Item -Destination $saved -Recurse -Force
    }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    Get-ChildItem -Force -LiteralPath $source | Copy-Item -Destination $target -Recurse -Force
}
foreach ($entry in $manifest.files.PSObject.Properties | Where-Object { $_.Name.StartsWith('koreader/') }) {
    $installed = Join-Path $targetRoot $entry.Name
    if ((Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { throw "Installed file mismatch: $($entry.Name)" }
}
Write-Output "Add-on files verified. Previous add-on files backed up to: $backup"
Write-Output 'Safely eject the Kindle, unplug USB, launch KOReader, then open Tinta from Tools.'
