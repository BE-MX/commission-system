param(
    [Parameter(Mandatory = $true)][string]$DebugApk,
    [Parameter(Mandatory = $true)][string]$ReleaseApk
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$publisher = Join-Path $PSScriptRoot '..\publish-update.ps1'

function Invoke-Publisher {
    param([string]$Path)

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $publisher -ApkPath $Path -PrepareOnly 2>&1
    } finally {
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = ($output -join [Environment]::NewLine)
    }
}

$debugResult = Invoke-Publisher -Path $DebugApk
if ($debugResult.ExitCode -eq 0) {
    throw 'Expected the debug APK to be rejected.'
}
if ($debugResult.Output -notmatch 'debug-signed APK cannot be published') {
    throw "Debug rejection did not explain the signing problem: $($debugResult.Output)"
}

$releaseResult = Invoke-Publisher -Path $ReleaseApk
if ($releaseResult.ExitCode -ne 0) {
    throw "Expected the signed release APK to pass prepare-only validation: $($releaseResult.Output)"
}

$preparedMatch = [regex]::Match($releaseResult.Output, '(?m)^Prepared directory: (.+)$')
if (-not $preparedMatch.Success) {
    throw "Publisher did not report its prepared directory: $($releaseResult.Output)"
}

$preparedDirectory = $preparedMatch.Groups[1].Value.Trim()
$manifestPath = Join-Path $preparedDirectory 'latest.json'
$preparedApkPath = Join-Path $preparedDirectory 'leshine-expo-kiosk.apk'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Prepared manifest does not exist: $manifestPath"
}
if (-not (Test-Path -LiteralPath $preparedApkPath -PathType Leaf)) {
    throw "Prepared APK does not exist: $preparedApkPath"
}

$rawManifest = [System.IO.File]::ReadAllText($manifestPath, [System.Text.UTF8Encoding]::new($false))
$manifest = $rawManifest | ConvertFrom-Json
$propertyNames = @($manifest.PSObject.Properties.Name)
$expectedNames = @('version_code', 'version_name', 'apk_size', 'sha256')
if (($propertyNames -join ',') -ne ($expectedNames -join ',')) {
    throw "Manifest fields or order are wrong: $($propertyNames -join ',')"
}
if ([long]$manifest.version_code -ne 10 -or [string]$manifest.version_name -ne '1.9') {
    throw "Unexpected release version: $($manifest.version_code)/$($manifest.version_name)"
}

$preparedFile = Get-Item -LiteralPath $preparedApkPath
$preparedHash = (Get-FileHash -LiteralPath $preparedApkPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ([long]$manifest.apk_size -ne $preparedFile.Length) {
    throw 'Manifest APK size does not match the prepared APK.'
}
if ([string]$manifest.sha256 -cne $preparedHash) {
    throw 'Manifest SHA-256 does not match the prepared APK.'
}
if ($rawManifest.Length -gt 0 -and [int][char]$rawManifest[0] -eq 0xfeff) {
    throw 'Manifest must be UTF-8 without BOM.'
}

Write-Output "Publisher self-test passed. Prepared directory: $preparedDirectory"
