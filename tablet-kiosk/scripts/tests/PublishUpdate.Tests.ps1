param(
    [Parameter(Mandatory = $true)][string]$DebugApk,
    [Parameter(Mandatory = $true)][string]$ReleaseApk
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$publisher = Join-Path $PSScriptRoot '..\publish-update.ps1'
$policy = Join-Path $PSScriptRoot '..\PublishUpdatePolicy.ps1'
. $policy

function Assert-Throws {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [Parameter(Mandatory = $true)][string]$MessagePattern
    )

    try {
        & $Action
    } catch {
        if ($_.Exception.Message -notmatch $MessagePattern) {
            throw "Expected error matching '$MessagePattern', got: $($_.Exception.Message)"
        }
        return
    }
    throw "Expected an error matching '$MessagePattern'."
}

function Invoke-WithNetworkSentinels {
    param([Parameter(Mandatory = $true)][hashtable]$PublisherArguments)

    $global:PublishNetworkSentinelHits = 0
    Set-Item -Path Function:global:curl.exe -Value { $global:PublishNetworkSentinelHits++; throw 'curl sentinel invoked' }
    Set-Item -Path Function:global:ssh.exe -Value { $global:PublishNetworkSentinelHits++; throw 'ssh sentinel invoked' }
    Set-Item -Path Function:global:scp.exe -Value { $global:PublishNetworkSentinelHits++; throw 'scp sentinel invoked' }
    try {
        foreach ($sentinelCommand in @('curl.exe', 'ssh.exe', 'scp.exe')) {
            try { & $sentinelCommand } catch {
                if ($_.Exception.Message -notmatch 'sentinel invoked') { throw }
            }
        }
        if ($global:PublishNetworkSentinelHits -ne 3) { throw 'Network command sentinels are not active.' }
        $global:PublishNetworkSentinelHits = 0
        try {
            $output = & $publisher @PublisherArguments 2>&1
            return [pscustomobject]@{ Succeeded = $true; Output = ($output -join [Environment]::NewLine); Error = $null; NetworkHits = $global:PublishNetworkSentinelHits }
        } catch {
            return [pscustomobject]@{ Succeeded = $false; Output = ''; Error = $_.Exception.Message; NetworkHits = $global:PublishNetworkSentinelHits }
        }
    } finally {
        Remove-Item -Path Function:global:curl.exe,Function:global:ssh.exe,Function:global:scp.exe -ErrorAction SilentlyContinue
    }
}

Assert-Throws -MessagePattern 'InitializeChannel' -Action {
    Assert-ChannelPolicy -HttpStatus 404 -CandidateVersionCode 10 -InitializeChannel:$false
}
$initialize = Assert-ChannelPolicy -HttpStatus 404 -CandidateVersionCode 10 -InitializeChannel:$true
if (-not $initialize) { throw 'Explicit version 10 initialization should be accepted.' }
Assert-Throws -MessagePattern 'versionCode 10' -Action {
    Assert-ChannelPolicy -HttpStatus 404 -CandidateVersionCode 11 -InitializeChannel:$true
}
Assert-Throws -MessagePattern 'already exists' -Action {
    Assert-ChannelPolicy -HttpStatus 200 -CandidateVersionCode 10 -PublishedVersionCode 9 -InitializeChannel:$true
}
$existing = Assert-ChannelPolicy -HttpStatus 200 -CandidateVersionCode 10 -PublishedVersionCode 9 -InitializeChannel:$false
if ($existing) { throw 'An existing channel must not be treated as initialization.' }
Assert-Throws -MessagePattern 'published versionCode is 10' -Action {
    Assert-ChannelPolicy -HttpStatus 200 -CandidateVersionCode 10 -PublishedVersionCode 10 -InitializeChannel:$false
}

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

$prepareSentinel = Invoke-WithNetworkSentinels -PublisherArguments @{ ApkPath = $ReleaseApk; PrepareOnly = $true }
if (-not $prepareSentinel.Succeeded) { throw "PrepareOnly failed under network sentinels: $($prepareSentinel.Error)" }
if ($prepareSentinel.NetworkHits -ne 0) { throw 'PrepareOnly attempted a network command.' }

$invalidTarget = Invoke-WithNetworkSentinels -PublisherArguments @{ ApkPath = $ReleaseApk; Target = '-oProxyCommand@154.8.205.162' }
if ($invalidTarget.Succeeded -or $invalidTarget.Error -notmatch 'Target must be') { throw 'An option-like Target was not rejected.' }
if ($invalidTarget.NetworkHits -ne 0) { throw 'Invalid Target validation attempted a network command.' }

$missingCa = Invoke-WithNetworkSentinels -PublisherArguments @{ ApkPath = $ReleaseApk }
if ($missingCa.Succeeded -or $missingCa.Error -notmatch 'CaCertificatePath') { throw 'Missing CA was not rejected.' }
if ($missingCa.NetworkHits -ne 0) { throw 'Missing CA validation attempted a network command.' }

function Invoke-OfflineInitializeTransaction {
    param([switch]$CorruptPostVerification)

    $global:OfflineReleaseApk = (Resolve-Path -LiteralPath $ReleaseApk).Path
    $global:OfflineDebugApk = (Resolve-Path -LiteralPath $DebugApk).Path
    $global:OfflineCurlCalls = 0
    $global:OfflineScpCalls = 0
    $global:OfflineSshScripts = @()
    $global:OfflineCorruptPostVerification = [bool]$CorruptPostVerification
    $global:OfflineBashPath = (Get-Command bash -ErrorAction Stop).Source
    Set-Item -Path Function:global:curl.exe -Value {
        $arguments = @($args)
        $outputIndex = [array]::IndexOf($arguments, '--output')
        if ($outputIndex -lt 0 -or $outputIndex + 1 -ge $arguments.Count) { throw 'Offline curl sentinel did not receive --output.' }
        $outputPath = [string]$arguments[$outputIndex + 1]
        $global:OfflineCurlCalls++
        if ($global:OfflineCurlCalls -eq 1) {
            [System.IO.File]::WriteAllText($outputPath, 'not found')
            Write-Output '404'
            return
        }
        if ($global:OfflineCurlCalls -eq 2) {
            Copy-Item -LiteralPath (Join-Path (Split-Path $outputPath -Parent) 'latest.json') -Destination $outputPath
            Write-Output '200'
            return
        }
        if ($global:OfflineCurlCalls -eq 3) {
            $source = if ($global:OfflineCorruptPostVerification) { $global:OfflineDebugApk } else { $global:OfflineReleaseApk }
            Copy-Item -LiteralPath $source -Destination $outputPath
            Write-Output '200'
            return
        }
        throw 'Offline curl sentinel received an unexpected call.'
    }
    Set-Item -Path Function:global:scp.exe -Value { $global:OfflineScpCalls++ }
    Set-Item -Path Function:global:ssh.exe -Value {
        if ($args.Count -ne 2) { throw 'Offline ssh sentinel expected Target and one quoted script argument.' }
        $remoteScript = [string]$args[1]
        $global:OfflineSshScripts += $remoteScript
        $syntaxFile = [System.IO.Path]::GetTempFileName()
        try {
            [System.IO.File]::WriteAllText($syntaxFile, $remoteScript, [System.Text.UTF8Encoding]::new($false))
            $bashOutput = & $global:OfflineBashPath -n $syntaxFile 2>&1
            if ($LASTEXITCODE -ne 0) { throw "Generated remote transaction script failed bash syntax validation: $($bashOutput -join [Environment]::NewLine)" }
        } finally {
            Remove-Item -LiteralPath $syntaxFile -ErrorAction SilentlyContinue
        }
    }
    try {
        try {
            $output = & $publisher -ApkPath $ReleaseApk -InitializeChannel -CaCertificatePath $publisher 2>&1
            return [pscustomobject]@{
                Succeeded = $true
                Output = ($output -join [Environment]::NewLine)
                Error = $null
                CurlCalls = $global:OfflineCurlCalls
                ScpCalls = $global:OfflineScpCalls
                SshScripts = @($global:OfflineSshScripts)
            }
        } catch {
            return [pscustomobject]@{
                Succeeded = $false
                Output = ''
                Error = $_.Exception.Message
                CurlCalls = $global:OfflineCurlCalls
                ScpCalls = $global:OfflineScpCalls
                SshScripts = @($global:OfflineSshScripts)
            }
        }
    } finally {
        Remove-Item -Path Function:global:curl.exe,Function:global:ssh.exe,Function:global:scp.exe -ErrorAction SilentlyContinue
    }
}

$offlineSuccess = Invoke-OfflineInitializeTransaction
if (-not $offlineSuccess.Succeeded) { throw "Offline initialization transaction failed: $($offlineSuccess.Error)" }
if ($offlineSuccess.CurlCalls -ne 3 -or $offlineSuccess.ScpCalls -ne 1 -or $offlineSuccess.SshScripts.Count -ne 3) {
    throw 'Offline initialization did not execute preflight, begin, switch, HTTPS verification, and finalize exactly once.'
}

$offlineRollback = Invoke-OfflineInitializeTransaction -CorruptPostVerification
if ($offlineRollback.Succeeded -or $offlineRollback.Error -notmatch 'rolled back') {
    throw 'Corrupt post-publication verification did not trigger rollback.'
}
if ($offlineRollback.SshScripts.Count -ne 3 -or $offlineRollback.SshScripts[-1] -notmatch 'previous\.apk') {
    throw 'Rollback did not use the owner-scoped remote recovery script.'
}

Write-Output "Publisher self-test passed. Prepared directory: $preparedDirectory"
