param(
    [Parameter(Mandatory = $true)][string]$ApkPath,
    [switch]$PrepareOnly,
    [switch]$InitializeChannel,
    [string]$Target = 'ubuntu@154.8.205.162',
    [string]$CaCertificatePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'PublishUpdatePolicy.ps1')
. (Join-Path $PSScriptRoot 'PublishRemoteTransaction.ps1')

$ExpectedPackage = 'com.leshine.expokiosk'
$ManifestUrl = 'https://154.8.205.162/expo-app/latest.json'
$ApkUrl = 'https://154.8.205.162/expo-app/leshine-expo-kiosk.apk'
$RemoteDirectory = '/var/www/ark-updates/expo-kiosk'

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $FilePath @Arguments 2>&1
    } finally {
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "$([System.IO.Path]::GetFileName($FilePath)) failed with exit code $exitCode.`n$($output -join [Environment]::NewLine)"
    }
    return @($output)
}

function Find-AndroidBuildTools {
    $sdkRoots = @(
        $env:ANDROID_HOME,
        $env:ANDROID_SDK_ROOT,
        $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Android\Sdk' })
    ) | Where-Object { $_ } | Select-Object -Unique

    $candidates = foreach ($sdkRoot in $sdkRoots) {
        $buildToolsRoot = Join-Path $sdkRoot 'build-tools'
        if (-not (Test-Path -LiteralPath $buildToolsRoot -PathType Container)) { continue }
        foreach ($directory in Get-ChildItem -LiteralPath $buildToolsRoot -Directory) {
            $aapt = Join-Path $directory.FullName $(if ($env:OS -eq 'Windows_NT') { 'aapt.exe' } else { 'aapt' })
            $apksigner = Join-Path $directory.FullName $(if ($env:OS -eq 'Windows_NT') { 'apksigner.bat' } else { 'apksigner' })
            if ((Test-Path -LiteralPath $aapt -PathType Leaf) -and (Test-Path -LiteralPath $apksigner -PathType Leaf)) {
                [pscustomobject]@{ Directory = $directory; Aapt = $aapt; ApkSigner = $apksigner }
            }
        }
    }

    $selected = $candidates | Sort-Object { [version]$_.Directory.Name } -Descending | Select-Object -First 1
    if (-not $selected) {
        throw 'Android SDK build-tools with aapt and apksigner were not found. Set ANDROID_HOME or ANDROID_SDK_ROOT.'
    }
    return $selected
}

function Read-ApkMetadata {
    param(
        [Parameter(Mandatory = $true)][string]$ResolvedApkPath,
        [Parameter(Mandatory = $true)]$BuildTools
    )

    $badging = Invoke-CheckedCommand -FilePath $BuildTools.Aapt -Arguments @('dump', 'badging', $ResolvedApkPath)
    $packageLine = $badging | Where-Object { $_ -match '^package:' } | Select-Object -First 1
    if (-not $packageLine) { throw 'aapt did not return APK package metadata.' }
    $match = [regex]::Match($packageLine, "^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'")
    if (-not $match.Success) { throw 'APK package metadata is malformed.' }

    $packageName = $match.Groups[1].Value
    $versionCode = [long]$match.Groups[2].Value
    $versionName = $match.Groups[3].Value
    if ($packageName -cne $ExpectedPackage) { throw "Unexpected APK package: $packageName" }
    if ($versionCode -le 9) { throw "APK versionCode must be greater than 9; got $versionCode." }
    if ([string]::IsNullOrWhiteSpace($versionName)) { throw 'APK versionName must not be empty.' }

    $signing = Invoke-CheckedCommand -FilePath $BuildTools.ApkSigner -Arguments @('verify', '--print-certs', $ResolvedApkPath)
    $signingText = $signing -join [Environment]::NewLine
    if ($signingText -match '(?i)certificate DN:\s*.*CN\s*=\s*Android Debug' -or
        $signingText -match '(?i)CN\s*=\s*Android Debug\s*,\s*O\s*=\s*Android\s*,\s*C\s*=\s*US') {
        throw 'debug-signed APK cannot be published'
    }
    $digestMatch = [regex]::Match($signingText, '(?im)^(?:Signer #\d+|V\d+ Signer): certificate SHA-256 digest:\s*([0-9a-f]{64})\s*$')
    if (-not $digestMatch.Success) { throw 'apksigner did not report a signer SHA-256 digest.' }

    return [pscustomobject]@{
        PackageName = $packageName
        VersionCode = $versionCode
        VersionName = $versionName
        SignerSha256 = $digestMatch.Groups[1].Value.ToLowerInvariant()
    }
}

function Read-StrictManifest {
    param([Parameter(Mandatory = $true)][string]$Path)

    $rawManifest = Get-Content -LiteralPath $Path -Raw
    try { $manifest = $rawManifest | ConvertFrom-Json } catch { throw "Published manifest is invalid JSON: $($_.Exception.Message)" }
    $propertyMatches = [regex]::Matches($rawManifest, '(?<!\\)"([^"\\]*(?:\\.[^"\\]*)*)"\s*:')
    $names = @($propertyMatches | ForEach-Object { $_.Groups[1].Value })
    $expected = @('version_code', 'version_name', 'apk_size', 'sha256')
    $actualNames = (($names | Sort-Object) -join ',')
    $expectedNames = (($expected | Sort-Object) -join ',')
    if ($actualNames -cne $expectedNames) {
        throw 'Published manifest must contain exactly version_code, version_name, apk_size, and sha256.'
    }
    if ($manifest.version_code -isnot [long] -and $manifest.version_code -isnot [int]) { throw 'Published version_code must be an integer.' }
    if ([long]$manifest.version_code -le 0) { throw 'Published version_code must be positive.' }
    if ($manifest.version_name -isnot [string] -or [string]::IsNullOrWhiteSpace($manifest.version_name)) { throw 'Published version_name must be non-empty.' }
    if ($manifest.apk_size -isnot [long] -and $manifest.apk_size -isnot [int]) { throw 'Published apk_size must be an integer.' }
    if ([long]$manifest.apk_size -le 0) { throw 'Published apk_size must be positive.' }
    if ($manifest.sha256 -isnot [string] -or $manifest.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Published sha256 must be lowercase hexadecimal.' }
    return $manifest
}

function Invoke-CurlDownload {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [Parameter(Mandatory = $true)][string]$CaPath,
        [switch]$AllowNotFound
    )

    $statusOutput = & curl.exe --silent --show-error --cacert $CaPath --output $OutputPath --write-out '%{http_code}' --max-redirs 0 $Url 2>&1
    if ($LASTEXITCODE -ne 0) { throw "HTTPS verification/download failed for $Url." }
    $status = ($statusOutput -join '').Trim()
    if ($status -eq '404' -and $AllowNotFound) { return 404 }
    if ($status -ne '200') { throw "Unexpected HTTP status $status for $Url." }
    return 200
}

$resolvedApk = (Resolve-Path -LiteralPath $ApkPath -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $resolvedApk -PathType Leaf)) { throw "APK does not exist: $ApkPath" }
$buildTools = Find-AndroidBuildTools
$metadata = Read-ApkMetadata -ResolvedApkPath $resolvedApk -BuildTools $buildTools
$sourceApk = Get-Item -LiteralPath $resolvedApk
$apkHash = (Get-FileHash -LiteralPath $resolvedApk -Algorithm SHA256).Hash.ToLowerInvariant()

$preparedDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ('leshine-expo-update-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($preparedDirectory) | Out-Null
$preparedApk = Join-Path $preparedDirectory 'leshine-expo-kiosk.apk'
$preparedManifest = Join-Path $preparedDirectory 'latest.json'
Copy-Item -LiteralPath $resolvedApk -Destination $preparedApk
$manifest = [ordered]@{
    version_code = [long]$metadata.VersionCode
    version_name = [string]$metadata.VersionName
    apk_size = [long]$sourceApk.Length
    sha256 = $apkHash
}
$manifestJson = $manifest | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($preparedManifest, $manifestJson, [System.Text.UTF8Encoding]::new($false))
$preparedManifestFile = Get-Item -LiteralPath $preparedManifest
$preparedManifestHash = (Get-FileHash -LiteralPath $preparedManifest -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Output "Prepared directory: $preparedDirectory"
Write-Output "Package: $($metadata.PackageName)"
Write-Output "Version: $($metadata.VersionCode) ($($metadata.VersionName))"
Write-Output "Signer SHA-256: $($metadata.SignerSha256)"
Write-Output "APK SHA-256: $apkHash"
Write-Output "APK size: $($sourceApk.Length)"

if ($PrepareOnly) { return }

Assert-PublishTarget -Target $Target
if ([string]::IsNullOrWhiteSpace($CaCertificatePath) -or -not (Test-Path -LiteralPath $CaCertificatePath -PathType Leaf)) {
    throw 'CaCertificatePath must point to the trusted HTTPS CA certificate; insecure TLS is forbidden.'
}
$resolvedCa = (Resolve-Path -LiteralPath $CaCertificatePath).Path

$onlineManifest = Join-Path $preparedDirectory 'online-latest.json'
$onlineStatus = Invoke-CurlDownload -Url $ManifestUrl -OutputPath $onlineManifest -CaPath $resolvedCa -AllowNotFound
$onlineVersion = $null
$onlineManifestHash = ''
$onlineApkHash = ''
$onlineApkSize = 0L
if ($onlineStatus -eq 200) {
    $online = Read-StrictManifest -Path $onlineManifest
    $onlineVersion = [long]$online.version_code
    $onlineManifestHash = (Get-FileHash -LiteralPath $onlineManifest -Algorithm SHA256).Hash.ToLowerInvariant()
    $onlineApkHash = [string]$online.sha256
    $onlineApkSize = [long]$online.apk_size
}
$initializing = Assert-ChannelPolicy -HttpStatus $onlineStatus -CandidateVersionCode $metadata.VersionCode -PublishedVersionCode $onlineVersion -InitializeChannel:$InitializeChannel

$transactionId = [guid]::NewGuid().ToString('N')
$transactionMode = if ($initializing) { 'initialize' } else { 'existing' }
$remoteApkUpload = ".leshine-expo-$transactionId.apk.upload"
$remoteManifestUpload = ".leshine-expo-$transactionId.json.upload"
$uploadApk = Join-Path $preparedDirectory $remoteApkUpload
$uploadManifest = Join-Path $preparedDirectory $remoteManifestUpload
Copy-Item -LiteralPath $preparedApk -Destination $uploadApk
Copy-Item -LiteralPath $preparedManifest -Destination $uploadManifest

$remoteScripts = New-PublishRemoteScripts `
    -RemoteDirectory $RemoteDirectory `
    -TransactionId $transactionId `
    -Mode $transactionMode `
    -RemoteApkUploadName $remoteApkUpload `
    -RemoteManifestUploadName $remoteManifestUpload `
    -NewApkSha256 $apkHash `
    -NewApkSize $sourceApk.Length `
    -NewManifestSha256 $preparedManifestHash `
    -NewManifestSize $preparedManifestFile.Length `
    -BaselineApkSha256 $onlineApkHash `
    -BaselineApkSize $onlineApkSize `
    -BaselineManifestSha256 $onlineManifestHash
$beginScript = $remoteScripts.Begin
$switchScript = $remoteScripts.Switch
$rollbackScript = $remoteScripts.Rollback
$finalizeScript = $remoteScripts.Finalize

$transactionAttempted = $false
try {
    $transactionAttempted = $true
    Invoke-CheckedCommand -FilePath 'ssh.exe' -Arguments @($Target, $beginScript) | Out-Null
    Invoke-CheckedCommand -FilePath 'scp.exe' -Arguments @($uploadApk, $uploadManifest, "${Target}:~/") | Out-Null
    Invoke-CheckedCommand -FilePath 'ssh.exe' -Arguments @($Target, $switchScript) | Out-Null

    $verifiedManifestPath = Join-Path $preparedDirectory 'verified-latest.json'
    $verifiedApkPath = Join-Path $preparedDirectory 'verified-app.apk'
    Invoke-CurlDownload -Url $ManifestUrl -OutputPath $verifiedManifestPath -CaPath $resolvedCa | Out-Null
    $verifiedManifest = Read-StrictManifest -Path $verifiedManifestPath
    Invoke-CurlDownload -Url $ApkUrl -OutputPath $verifiedApkPath -CaPath $resolvedCa | Out-Null
    $verifiedFile = Get-Item -LiteralPath $verifiedApkPath
    $verifiedHash = (Get-FileHash -LiteralPath $verifiedApkPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([long]$verifiedManifest.version_code -ne [long]$metadata.VersionCode -or
        [string]$verifiedManifest.version_name -cne [string]$metadata.VersionName -or
        [long]$verifiedManifest.apk_size -ne [long]$sourceApk.Length -or
        [string]$verifiedManifest.sha256 -cne $apkHash -or
        $verifiedFile.Length -ne $sourceApk.Length -or
        $verifiedHash -cne $apkHash) {
        throw 'Post-publication HTTPS verification did not match the prepared release.'
    }

    try {
        Invoke-CheckedCommand -FilePath 'ssh.exe' -Arguments @($Target, $finalizeScript) | Out-Null
    } catch {
        Invoke-CheckedCommand -FilePath 'ssh.exe' -Arguments @($Target, $finalizeScript) | Out-Null
    }
    $transactionAttempted = $false
} catch {
    $publishFailure = $_.Exception.Message
    if ($transactionAttempted) {
        try {
            Invoke-CheckedCommand -FilePath 'ssh.exe' -Arguments @($Target, $rollbackScript) | Out-Null
        } catch {
            throw "Publication failed and automatic rollback could not verify transaction ownership. The recovery lock was preserved; inspect it manually. Publish error: $publishFailure Rollback error: $($_.Exception.Message)"
        }
    }
    throw "Publication failed; the owned transaction was rolled back or safely finalized. $publishFailure"
}

Write-Output "Publication verified: versionCode $($metadata.VersionCode), SHA-256 $apkHash"
