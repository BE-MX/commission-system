param(
    [Parameter(Mandatory = $true)][string]$DebugApk,
    [Parameter(Mandatory = $true)][string]$ReleaseApk
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$publisher = Join-Path $PSScriptRoot '..\publish-update.ps1'
$policy = Join-Path $PSScriptRoot '..\PublishUpdatePolicy.ps1'
. $policy

$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$initialPreparedDirectories = @(Get-ChildItem -LiteralPath $tempRoot -Directory -Filter 'leshine-expo-update-*' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
$ownedPreparedDirectories = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

function Register-PreparedDirectory {
    param([string]$OutputText)
    foreach ($match in [regex]::Matches($OutputText, '(?m)^Prepared directory: (.+)$')) {
        $path = [System.IO.Path]::GetFullPath($match.Groups[1].Value.Trim())
        if ($path.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path $path -Leaf) -cmatch '^leshine-expo-update-[0-9a-f]{32}$') {
            [void]$ownedPreparedDirectories.Add($path)
        } else {
            throw 'Publisher reported an unsafe prepared directory.'
        }
    }
}

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
            $text = $output -join [Environment]::NewLine
            Register-PreparedDirectory $text
            return [pscustomobject]@{ Succeeded = $true; Output = $text; Error = $null; NetworkHits = $global:PublishNetworkSentinelHits }
        } catch {
            return [pscustomobject]@{ Succeeded = $false; Output = ''; Error = $_.Exception.Message; NetworkHits = $global:PublishNetworkSentinelHits }
        }
    } finally {
        Remove-Item -Path Function:global:curl.exe,Function:global:ssh.exe,Function:global:scp.exe -ErrorAction SilentlyContinue
    }
}

try {
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

foreach ($invalidVersionName in @('', ' ', ' 1.9', '1.9 ', "1.9`n", "1.9`tstable")) {
    Assert-Throws -MessagePattern 'version_name' -Action {
        Assert-VersionName -VersionName $invalidVersionName -Source 'test' | Out-Null
    }
}
if ((Assert-VersionName -VersionName '1.9' -Source 'test') -cne '1.9') {
    throw 'A valid version_name was changed by the shared policy.'
}

$manifestTestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('leshine-manifest-test-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($manifestTestRoot) | Out-Null
try {
    $invalidManifests = @{
        'array.json' = '[{"version_code":10,"version_name":"1.9","apk_size":1,"sha256":"' + ('a' * 64) + '"}]'
        'scalar.json' = '42'
        'duplicate.json' = '{"version_code":10,"version_code":11,"version_name":"1.9","apk_size":1,"sha256":"' + ('a' * 64) + '"}'
        'leading-space-version.json' = '{"version_code":10,"version_name":" 1.9","apk_size":1,"sha256":"' + ('a' * 64) + '"}'
        'control-version.json' = '{"version_code":10,"version_name":"1.9\tstable","apk_size":1,"sha256":"' + ('a' * 64) + '"}'
    }
    foreach ($entry in $invalidManifests.GetEnumerator()) {
        $path = Join-Path $manifestTestRoot $entry.Key
        [System.IO.File]::WriteAllText($path, $entry.Value, [System.Text.UTF8Encoding]::new($false))
        Assert-Throws -MessagePattern 'manifest' -Action { Read-StrictManifest -Path $path | Out-Null }
    }
} finally {
    Remove-Item -LiteralPath $manifestTestRoot -Recurse -Force -ErrorAction SilentlyContinue
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
Register-PreparedDirectory $releaseResult.Output
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
    param(
        [switch]$CorruptPostVerification,
        [switch]$OversizeManifest,
        [switch]$LoseFirstFinalizeAcknowledgement,
        [switch]$FailSwitchAcknowledgement
    )

    $global:OfflineReleaseApk = (Resolve-Path -LiteralPath $ReleaseApk).Path
    $global:OfflineReleaseApkLength = (Get-Item -LiteralPath $global:OfflineReleaseApk).Length
    $global:OfflineDebugApk = (Resolve-Path -LiteralPath $DebugApk).Path
    $global:OfflineCurlCalls = 0
    $global:OfflineScpCalls = 0
    $global:OfflineSshScripts = @()
    $global:OfflineCorruptPostVerification = [bool]$CorruptPostVerification
    $global:OfflineOversizeManifest = [bool]$OversizeManifest
    $global:OfflineLoseFirstFinalizeAcknowledgement = [bool]$LoseFirstFinalizeAcknowledgement
    $global:OfflineFailSwitchAcknowledgement = [bool]$FailSwitchAcknowledgement
    $global:OfflineFinalizeCalls = 0
    $global:OfflineCurlArguments = @()
    $global:OfflineBashPath = (Get-Command bash -ErrorAction Stop).Source
    Set-Item -Path Function:global:curl.exe -Value {
        $arguments = @($args)
        $global:OfflineCurlArguments += ,$arguments
        foreach ($required in @('--connect-timeout', '--max-time', '--max-filesize', '--max-redirs')) {
            if ([array]::IndexOf($arguments, $required) -lt 0) { throw "Offline curl sentinel did not receive $required." }
        }
        $outputIndex = [array]::IndexOf($arguments, '--output')
        if ($outputIndex -lt 0 -or $outputIndex + 1 -ge $arguments.Count) { throw 'Offline curl sentinel did not receive --output.' }
        $outputPath = [string]$arguments[$outputIndex + 1]
        $global:OfflineCurlCalls++
        $maxSizeIndex = [array]::IndexOf($arguments, '--max-filesize')
        $actualMaxSize = [long]$arguments[$maxSizeIndex + 1]
        $expectedMaxSize = if ($global:OfflineCurlCalls -le 2) { 16384L } else { [long]$global:OfflineReleaseApkLength }
        if ($actualMaxSize -ne $expectedMaxSize) { throw "Unexpected curl max-filesize $actualMaxSize on call $($global:OfflineCurlCalls)." }
        if ($global:OfflineCurlCalls -eq 1) {
            if ($global:OfflineOversizeManifest) {
                [System.IO.File]::WriteAllText($outputPath, ('x' * 16385))
                Write-Output '200'
            } else {
                [System.IO.File]::WriteAllText($outputPath, 'not found')
                Write-Output '404'
            }
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
        if ($global:OfflineFailSwitchAcknowledgement -and $remoteScript -match '(?m)^on_switch_failure\(\)') {
            throw 'simulated switch command transport failure after automatic rollback'
        }
        if ($remoteScript -match '(?m)^rollback_owned_transaction\s*$') {
            Write-Output 'PUBLISH_TXN_ROLLED_BACK'
        } elseif ($remoteScript -match '(?m)^write_receipt finalized\s*$') {
            $global:OfflineFinalizeCalls++
            if ($global:OfflineLoseFirstFinalizeAcknowledgement -and $global:OfflineFinalizeCalls -eq 1) {
                throw 'simulated lost finalize acknowledgement after remote completion'
            }
            Write-Output 'PUBLISH_TXN_FINALIZED'
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

$lostFinalizeAcknowledgement = Invoke-OfflineInitializeTransaction -LoseFirstFinalizeAcknowledgement
if (-not $lostFinalizeAcknowledgement.Succeeded -or $lostFinalizeAcknowledgement.SshScripts.Count -ne 4) {
    throw "Finalize acknowledgement loss was not recovered by a receipt-aware retry: $($lostFinalizeAcknowledgement.Error)"
}

$switchAcknowledgementFailure = Invoke-OfflineInitializeTransaction -FailSwitchAcknowledgement
if ($switchAcknowledgementFailure.Succeeded -or $switchAcknowledgementFailure.Error -notmatch 'safely rolled back' -or
    $switchAcknowledgementFailure.SshScripts.Count -ne 3) {
    throw "Switch failure was not reconciled through the rollback receipt: $($switchAcknowledgementFailure.Error)"
}
if ($offlineRollback.SshScripts.Count -ne 3 -or $offlineRollback.SshScripts[-1] -notmatch 'previous\.apk') {
    throw 'Rollback did not use the owner-scoped remote recovery script.'
}

$oversizeManifest = Invoke-OfflineInitializeTransaction -OversizeManifest
if ($oversizeManifest.Succeeded -or $oversizeManifest.Error -notmatch 'exceeded the allowed size') {
    throw "Oversize manifest was not rejected after download: $($oversizeManifest.Error)"
}
if ($oversizeManifest.ScpCalls -ne 0 -or $oversizeManifest.SshScripts.Count -ne 0) {
    throw 'Oversize manifest validation continued into remote publication.'
}

Write-Output "Publisher self-test passed. Prepared directory: $preparedDirectory"
} finally {
    foreach ($directory in $ownedPreparedDirectories) {
        if (Test-Path -LiteralPath $directory -PathType Container) {
            Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    $newPreparedDirectories = @(Get-ChildItem -LiteralPath $tempRoot -Directory -Filter 'leshine-expo-update-*' -ErrorAction SilentlyContinue |
        ForEach-Object { $_.FullName } | Where-Object { $_ -notin $initialPreparedDirectories })
    if ($newPreparedDirectories.Count -ne 0) {
        throw "Publisher self-test leaked prepared directories: $($newPreparedDirectories -join ', ')"
    }
}
