param([string]$GradlePath = 'C:\Users\windb\.gradle\wrapper\dists\gradle-8.7-bin\f06yd7m8w1d0inql2joytq4az\gradle-8.7\bin\gradle.bat')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$sourceKioskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$worktreeRoot = (Resolve-Path -LiteralPath (Join-Path $sourceKioskRoot '..')).Path
$realPropertiesPath = Join-Path $sourceKioskRoot 'keystore.properties'
$realPropertiesBefore = if (Test-Path -LiteralPath $realPropertiesPath -PathType Leaf) {
    $item = Get-Item -LiteralPath $realPropertiesPath
    [pscustomobject]@{ Exists = $true; Length = $item.Length; LastWriteTimeUtc = $item.LastWriteTimeUtc }
} else {
    [pscustomobject]@{ Exists = $false; Length = 0L; LastWriteTimeUtc = [datetime]::MinValue }
}

$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('leshine-release-gate-' + [guid]::NewGuid().ToString('N'))
$isolatedKioskRoot = Join-Path $testRoot 'tablet-kiosk'
[System.IO.Directory]::CreateDirectory($isolatedKioskRoot) | Out-Null

function Invoke-GradleTask {
    param([Parameter(Mandatory = $true)][string]$TaskName)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $output = & $GradlePath -p $isolatedKioskRoot $TaskName --offline --console=plain 2>&1 } finally {
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
    }
    return [pscustomobject]@{ Task = $TaskName; ExitCode = $exitCode; Output = ($output -join [Environment]::NewLine) }
}

try {
    $trackedKioskFiles = @(& git -C $worktreeRoot ls-files -- tablet-kiosk)
    if ($LASTEXITCODE -ne 0 -or $trackedKioskFiles.Count -eq 0) { throw 'Could not enumerate tracked kiosk files.' }
    foreach ($trackedPath in $trackedKioskFiles) {
        if ($trackedPath -ceq 'tablet-kiosk/keystore.properties' -or $trackedPath -match '\.(?:jks|keystore)$') {
            throw "A signing secret is unexpectedly tracked: $trackedPath"
        }
        $relativePath = $trackedPath.Substring('tablet-kiosk/'.Length).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        $sourcePath = Join-Path $sourceKioskRoot $relativePath
        $destinationPath = Join-Path $isolatedKioskRoot $relativePath
        [System.IO.Directory]::CreateDirectory((Split-Path $destinationPath -Parent)) | Out-Null
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
    }

    $sdkRoot = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
    $sdkRoot = (Resolve-Path -LiteralPath $sdkRoot).Path.Replace('\', '/')
    [System.IO.File]::WriteAllText((Join-Path $isolatedKioskRoot 'local.properties'), "sdk.dir=$sdkRoot`n", [System.Text.UTF8Encoding]::new($false))

    $releaseResults = @(
        Invoke-GradleTask 'assembleRelease'
        Invoke-GradleTask 'assemble'
        Invoke-GradleTask 'bundleRelease'
        Invoke-GradleTask 'build'
    )
    $debugResult = Invoke-GradleTask 'assembleDebug'

    foreach ($result in $releaseResults) {
        if ($result.ExitCode -eq 0) { throw "Expected '$($result.Task)' to fail without release signing." }
        if ($result.Output -notmatch 'Copy keystore.properties.example') { throw "'$($result.Task)' did not provide signing setup guidance." }
    }
    if ($debugResult.ExitCode -ne 0) { throw "assembleDebug must work without release signing: $($debugResult.Output)" }
    $releaseOutputRoot = Join-Path $isolatedKioskRoot 'app\build\outputs'
    if (Test-Path -LiteralPath $releaseOutputRoot) {
        $unsignedArtifacts = @(Get-ChildItem -LiteralPath $releaseOutputRoot -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '(?i)release.*(?:unsigned)?\.(?:apk|aab)$' })
        if ($unsignedArtifacts.Count -ne 0) { throw 'An unsigned release artifact was created in the isolated project.' }
    }
} finally {
    $resolvedRoot = [System.IO.Path]::GetFullPath($testRoot)
    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($resolvedRoot.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path $resolvedRoot -Leaf) -cmatch '^leshine-release-gate-[0-9a-f]{32}$') {
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$realPropertiesAfter = if (Test-Path -LiteralPath $realPropertiesPath -PathType Leaf) { Get-Item -LiteralPath $realPropertiesPath } else { $null }
if ($realPropertiesBefore.Exists -ne [bool]$realPropertiesAfter -or
    ($realPropertiesBefore.Exists -and ($realPropertiesAfter.Length -ne $realPropertiesBefore.Length -or
        $realPropertiesAfter.LastWriteTimeUtc -ne $realPropertiesBefore.LastWriteTimeUtc))) {
    throw 'The real signing-properties metadata changed during the isolated test.'
}

Write-Output 'Release signing gate self-test passed in an isolated tracked-file copy.'
