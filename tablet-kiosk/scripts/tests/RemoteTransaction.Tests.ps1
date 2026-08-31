Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$transactionLibrary = Join-Path $PSScriptRoot '..\PublishRemoteTransaction.ps1'
. $transactionLibrary

$bash = (Get-Command bash -ErrorAction Stop).Source
$gitRoot = Split-Path (Split-Path $bash -Parent) -Parent
$cygpath = Join-Path $gitRoot 'usr\bin\cygpath.exe'
if (-not (Test-Path -LiteralPath $cygpath)) { throw 'Git Bash cygpath was not found.' }
$unixRoot = (& $bash -lc 'mktemp -d /tmp/leshine-publish-test.XXXXXX').Trim()
if ($LASTEXITCODE -ne 0 -or $unixRoot -cnotmatch '^/tmp/leshine-publish-test\.[A-Za-z0-9]+$') {
    throw 'Failed to create the controlled remote-transaction test root.'
}
$windowsRoot = (& $cygpath -w $unixRoot).Trim()
$fakeBinUnix = "$unixRoot/fake-bin"
$fakeBinWindows = Join-Path $windowsRoot 'fake-bin'
$homeUnix = "$unixRoot/home"
$homeWindows = Join-Path $windowsRoot 'home'
[System.IO.Directory]::CreateDirectory($fakeBinWindows) | Out-Null
[System.IO.Directory]::CreateDirectory($homeWindows) | Out-Null

function Write-TestFile {
    param([string]$Path, [string]$Content)
    [System.IO.Directory]::CreateDirectory((Split-Path $Path -Parent)) | Out-Null
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

Write-TestFile -Path (Join-Path $fakeBinWindows 'sudo') -Content @'
#!/bin/sh
exec "$@"
'@
Write-TestFile -Path (Join-Path $fakeBinWindows 'mv') -Content @'
#!/bin/sh
source_arg=''
last_arg=''
for arg in "$@"; do
  case "$arg" in
    --|-*) continue ;;
    *) source_arg="$last_arg"; last_arg="$arg" ;;
  esac
done
if [ -n "${FAIL_MANIFEST_SWITCH_ONCE_FILE:-}" ] && [ ! -e "$FAIL_MANIFEST_SWITCH_ONCE_FILE" ] &&
   echo "$source_arg" | grep -q '\.stage$' && [ "${last_arg##*/}" = latest.json ]; then
  : > "$FAIL_MANIFEST_SWITCH_ONCE_FILE"
  exit 91
fi
exec /usr/bin/mv "$@"
'@
Write-TestFile -Path (Join-Path $fakeBinWindows 'cp') -Content @'
#!/bin/sh
for last_arg in "$@"; do :; done
if [ "${FAIL_RESTORE_COPY:-0}" = 1 ] && echo "$last_arg" | grep -q '\.restore\.'; then
  exit 92
fi
exec /usr/bin/cp "$@"
'@
& $bash -lc "chmod +x '$fakeBinUnix/sudo' '$fakeBinUnix/mv' '$fakeBinUnix/cp'"
if ($LASTEXITCODE -ne 0) { throw 'Failed to activate transaction fault-injection commands.' }

function Get-LowerHash {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function New-Scenario {
    param([string]$Name, [ValidateSet('existing', 'initialize')][string]$Mode = 'existing')

    $windowsDirectory = Join-Path $windowsRoot $Name
    $unixDirectory = "$unixRoot/$Name"
    [System.IO.Directory]::CreateDirectory($windowsDirectory) | Out-Null
    $oldApk = Join-Path $windowsDirectory 'leshine-expo-kiosk.apk'
    $oldManifest = Join-Path $windowsDirectory 'latest.json'
    if ($Mode -eq 'existing') {
        Write-TestFile -Path $oldApk -Content "old-apk-$Name"
        Write-TestFile -Path $oldManifest -Content "{`"version_code`":9,`"scenario`":`"$Name`"}"
    }

    $transactionId = ([guid]::NewGuid().ToString('N'))
    $apkUploadName = ".leshine-expo-$transactionId.apk.upload"
    $manifestUploadName = ".leshine-expo-$transactionId.json.upload"
    $apkUpload = Join-Path $homeWindows $apkUploadName
    $manifestUpload = Join-Path $homeWindows $manifestUploadName
    Write-TestFile -Path $apkUpload -Content "new-apk-$Name"
    Write-TestFile -Path $manifestUpload -Content "{`"version_code`":10,`"scenario`":`"$Name`"}"

    $scripts = New-PublishRemoteScripts `
        -RemoteDirectory $unixDirectory `
        -TransactionId $transactionId `
        -Mode $Mode `
        -RemoteApkUploadName $apkUploadName `
        -RemoteManifestUploadName $manifestUploadName `
        -NewApkSha256 (Get-LowerHash $apkUpload) `
        -NewApkSize (Get-Item $apkUpload).Length `
        -NewManifestSha256 (Get-LowerHash $manifestUpload) `
        -NewManifestSize (Get-Item $manifestUpload).Length `
        -BaselineApkSha256 $(if ($Mode -eq 'existing') { Get-LowerHash $oldApk } else { '' }) `
        -BaselineApkSize $(if ($Mode -eq 'existing') { (Get-Item $oldApk).Length } else { 0 }) `
        -BaselineManifestSha256 $(if ($Mode -eq 'existing') { Get-LowerHash $oldManifest } else { '' })

    return [pscustomobject]@{
        Name = $Name
        Mode = $Mode
        WindowsDirectory = $windowsDirectory
        UnixDirectory = $unixDirectory
        TransactionId = $transactionId
        Scripts = $scripts
        OldApkContent = if ($Mode -eq 'existing') { [System.IO.File]::ReadAllText($oldApk) } else { $null }
        OldManifestContent = if ($Mode -eq 'existing') { [System.IO.File]::ReadAllText($oldManifest) } else { $null }
        NewApkContent = [System.IO.File]::ReadAllText($apkUpload)
        NewManifestContent = [System.IO.File]::ReadAllText($manifestUpload)
    }
}

function Invoke-TransactionScript {
    param([string]$Script, [hashtable]$Environment = @{})

    $scriptPathWindows = Join-Path $windowsRoot (([guid]::NewGuid().ToString('N')) + '.sh')
    $scriptPathUnix = (& $cygpath -u $scriptPathWindows).Trim()
    $prefix = @(
        "export PATH='$fakeBinUnix':`$PATH",
        "export HOME='$homeUnix'"
    )
    foreach ($entry in $Environment.GetEnumerator()) {
        if ([string]$entry.Value -cnotmatch '^[/A-Za-z0-9._-]+$') { throw 'Unsafe test environment value.' }
        $prefix += "export $($entry.Key)='$($entry.Value)'"
    }
    Write-TestFile -Path $scriptPathWindows -Content (($prefix + $Script) -join "`n")
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $bash $scriptPathUnix 2>&1
    } finally {
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
        Remove-Item -LiteralPath $scriptPathWindows -ErrorAction SilentlyContinue
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = ($output -join [Environment]::NewLine) }
}

function Assert-Success { param($Result, [string]$Stage); if ($Result.ExitCode -ne 0) { throw "$Stage failed: $($Result.Output)" } }
function Assert-Failure { param($Result, [string]$Stage); if ($Result.ExitCode -eq 0) { throw "$Stage unexpectedly succeeded." } }
function Assert-Content { param([string]$Path, [string]$Expected); if (-not (Test-Path -LiteralPath $Path) -or [System.IO.File]::ReadAllText($Path) -cne $Expected) { throw "Unexpected content at $Path" } }
function Assert-Marker { param($Result, [string]$Marker); if ($Result.Output -notmatch "(?m)^$Marker`$") { throw "Missing transaction marker $Marker in: $($Result.Output)" } }

try {
    $normal = New-Scenario -Name 'normal-existing'
    Assert-Success (Invoke-TransactionScript $normal.Scripts.Begin) 'normal begin'
    Assert-Success (Invoke-TransactionScript $normal.Scripts.Switch) 'normal switch'
    $normalFinalize = Invoke-TransactionScript $normal.Scripts.Finalize
    Assert-Success $normalFinalize 'normal finalize'
    Assert-Marker $normalFinalize 'PUBLISH_TXN_FINALIZED'
    $normalFinalizeRetry = Invoke-TransactionScript $normal.Scripts.Finalize
    Assert-Success $normalFinalizeRetry 'normal finalize retry'
    Assert-Marker $normalFinalizeRetry 'PUBLISH_TXN_FINALIZED'
    Assert-Content (Join-Path $normal.WindowsDirectory 'leshine-expo-kiosk.apk') $normal.NewApkContent
    Assert-Content (Join-Path $normal.WindowsDirectory 'latest.json') $normal.NewManifestContent
    if (Test-Path (Join-Path $normal.WindowsDirectory '.publish-lock')) { throw 'Normal finalize left a lock.' }
    if (-not (Test-Path (Join-Path $normal.WindowsDirectory ".publish-receipts\$($normal.TransactionId).receipt"))) { throw 'Normal finalize did not persist its receipt.' }

    $switchFailure = New-Scenario -Name 'switch-failure'
    Assert-Success (Invoke-TransactionScript $switchFailure.Scripts.Begin) 'switch-failure begin'
    $markerUnix = "$unixRoot/switch-failure.marker"
    Assert-Failure (Invoke-TransactionScript $switchFailure.Scripts.Switch @{ FAIL_MANIFEST_SWITCH_ONCE_FILE = $markerUnix }) 'manifest switch failure'
    Assert-Content (Join-Path $switchFailure.WindowsDirectory 'leshine-expo-kiosk.apk') $switchFailure.OldApkContent
    Assert-Content (Join-Path $switchFailure.WindowsDirectory 'latest.json') $switchFailure.OldManifestContent
    if (Test-Path (Join-Path $switchFailure.WindowsDirectory '.publish-lock')) { throw 'Successful rollback left a lock.' }
    $switchRollbackRetry = Invoke-TransactionScript $switchFailure.Scripts.Rollback
    Assert-Success $switchRollbackRetry 'switch rollback acknowledgement retry'
    Assert-Marker $switchRollbackRetry 'PUBLISH_TXN_ROLLED_BACK'

    $restoreFailure = New-Scenario -Name 'restore-failure'
    Assert-Success (Invoke-TransactionScript $restoreFailure.Scripts.Begin) 'restore-failure begin'
    $restoreMarkerUnix = "$unixRoot/restore-failure.marker"
    Assert-Failure (Invoke-TransactionScript $restoreFailure.Scripts.Switch @{ FAIL_MANIFEST_SWITCH_ONCE_FILE = $restoreMarkerUnix; FAIL_RESTORE_COPY = '1' }) 'restore command failure'
    $restoreLock = Join-Path $restoreFailure.WindowsDirectory '.publish-lock'
    foreach ($required in @('owner', 'state', 'previous.apk', 'previous.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $restoreLock $required))) { throw "Restore failure deleted recovery material: $required" }
    }

    $initializeFailure = New-Scenario -Name 'initialize-failure' -Mode initialize
    Assert-Success (Invoke-TransactionScript $initializeFailure.Scripts.Begin) 'initialize begin'
    $initializeMarkerUnix = "$unixRoot/initialize-failure.marker"
    Assert-Failure (Invoke-TransactionScript $initializeFailure.Scripts.Switch @{ FAIL_MANIFEST_SWITCH_ONCE_FILE = $initializeMarkerUnix }) 'initialize switch failure'
    if ((Test-Path (Join-Path $initializeFailure.WindowsDirectory 'leshine-expo-kiosk.apk')) -or
        (Test-Path (Join-Path $initializeFailure.WindowsDirectory 'latest.json'))) {
        throw 'Initialize rollback did not restore an empty channel.'
    }
    if (Test-Path (Join-Path $initializeFailure.WindowsDirectory '.publish-lock')) { throw 'Successful initialize rollback left a lock.' }

    $ownerMismatch = New-Scenario -Name 'owner-mismatch'
    Assert-Success (Invoke-TransactionScript $ownerMismatch.Scripts.Begin) 'owner begin'
    Assert-Success (Invoke-TransactionScript $ownerMismatch.Scripts.Switch) 'owner switch'
    Write-TestFile -Path (Join-Path $ownerMismatch.WindowsDirectory '.publish-lock\owner') -Content 'different-owner'
    Assert-Failure (Invoke-TransactionScript $ownerMismatch.Scripts.Finalize) 'owner mismatch finalize'
    Assert-Failure (Invoke-TransactionScript $ownerMismatch.Scripts.Rollback) 'owner mismatch rollback'
    Assert-Content (Join-Path $ownerMismatch.WindowsDirectory 'leshine-expo-kiosk.apk') $ownerMismatch.NewApkContent
    Assert-Content (Join-Path $ownerMismatch.WindowsDirectory 'latest.json') $ownerMismatch.NewManifestContent
    if (-not (Test-Path (Join-Path $ownerMismatch.WindowsDirectory '.publish-lock'))) { throw 'Owner mismatch removed the lock.' }

    $stale = New-Scenario -Name 'stale-baseline'
    $staleScripts = New-PublishRemoteScripts `
        -RemoteDirectory $stale.UnixDirectory -TransactionId $stale.TransactionId -Mode existing `
        -RemoteApkUploadName ".leshine-expo-$($stale.TransactionId).apk.upload" `
        -RemoteManifestUploadName ".leshine-expo-$($stale.TransactionId).json.upload" `
        -NewApkSha256 ('a' * 64) -NewApkSize 1 -NewManifestSha256 ('b' * 64) -NewManifestSize 1 `
        -BaselineApkSha256 ('c' * 64) -BaselineApkSize 1 -BaselineManifestSha256 ('d' * 64)
    Assert-Failure (Invoke-TransactionScript $staleScripts.Begin) 'stale baseline begin'
    if (Test-Path (Join-Path $stale.WindowsDirectory '.publish-lock')) { throw 'Stale baseline rejection left its own lock.' }

    $postVerify = New-Scenario -Name 'postverify-rollback'
    Assert-Success (Invoke-TransactionScript $postVerify.Scripts.Begin) 'postverify begin'
    Assert-Success (Invoke-TransactionScript $postVerify.Scripts.Switch) 'postverify switch'
    $postVerifyRollback = Invoke-TransactionScript $postVerify.Scripts.Rollback
    Assert-Success $postVerifyRollback 'postverify rollback'
    Assert-Marker $postVerifyRollback 'PUBLISH_TXN_ROLLED_BACK'
    $postVerifyRollbackRetry = Invoke-TransactionScript $postVerify.Scripts.Rollback
    Assert-Success $postVerifyRollbackRetry 'postverify rollback retry'
    Assert-Marker $postVerifyRollbackRetry 'PUBLISH_TXN_ROLLED_BACK'
    Assert-Failure (Invoke-TransactionScript $postVerify.Scripts.Finalize) 'finalize after rolled-back receipt'
    Assert-Content (Join-Path $postVerify.WindowsDirectory 'leshine-expo-kiosk.apk') $postVerify.OldApkContent
    Assert-Content (Join-Path $postVerify.WindowsDirectory 'latest.json') $postVerify.OldManifestContent
    if (Test-Path (Join-Path $postVerify.WindowsDirectory '.publish-lock')) { throw 'Postverify rollback left a lock.' }

    $lostFinalizeAck = New-Scenario -Name 'lost-finalize-ack'
    Assert-Success (Invoke-TransactionScript $lostFinalizeAck.Scripts.Begin) 'lost-ack begin'
    Assert-Success (Invoke-TransactionScript $lostFinalizeAck.Scripts.Switch) 'lost-ack switch'
    $actualFinalize = Invoke-TransactionScript $lostFinalizeAck.Scripts.Finalize
    Assert-Success $actualFinalize 'lost-ack actual finalize'
    $simulatedTransportFailure = [pscustomobject]@{ ExitCode = 255; Output = '' }
    Assert-Failure $simulatedTransportFailure 'simulated lost finalize acknowledgement'
    $finalizeAfterLostAck = Invoke-TransactionScript $lostFinalizeAck.Scripts.Finalize
    Assert-Success $finalizeAfterLostAck 'finalize receipt retry after lost acknowledgement'
    Assert-Marker $finalizeAfterLostAck 'PUBLISH_TXN_FINALIZED'

    Write-Output 'Remote transaction state-machine self-test passed.'
} finally {
    $resolvedRoot = [System.IO.Path]::GetFullPath($windowsRoot)
    $expectedParent = [System.IO.Path]::GetFullPath((& $cygpath -w '/tmp').Trim())
    if ($resolvedRoot.StartsWith($expectedParent, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path $resolvedRoot -Leaf) -like 'leshine-publish-test.*') {
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
