param(
    [string]$GradlePath = 'C:\Users\windb\.gradle\wrapper\dists\gradle-8.7-bin\f06yd7m8w1d0inql2joytq4az\gradle-8.7\bin\gradle.bat'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$kioskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$worktreeRoot = (Resolve-Path -LiteralPath (Join-Path $kioskRoot '..')).Path
$propertiesPath = [System.IO.Path]::GetFullPath((Join-Path $kioskRoot 'keystore.properties'))
$temporaryPath = 'C:\secure\keystore.properties.release-gate-test'
$unsignedApk = [System.IO.Path]::GetFullPath((Join-Path $kioskRoot 'app\build\outputs\apk\release\app-release-unsigned.apk'))

if (-not $propertiesPath.StartsWith($worktreeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Resolved signing-properties path escaped the worktree.'
}
if (-not (Test-Path -LiteralPath $propertiesPath -PathType Leaf)) {
    throw 'Local signing properties are required before this test; their contents are never read.'
}
if (Test-Path -LiteralPath $temporaryPath) {
    throw "Temporary validation path already exists: $temporaryPath"
}

$unsignedBefore = if (Test-Path -LiteralPath $unsignedApk -PathType Leaf) {
    $file = Get-Item -LiteralPath $unsignedApk
    [pscustomobject]@{ Exists = $true; Length = $file.Length; LastWriteTimeUtc = $file.LastWriteTimeUtc }
} else {
    [pscustomobject]@{ Exists = $false; Length = 0L; LastWriteTimeUtc = [datetime]::MinValue }
}

function Invoke-GradleTask {
    param([Parameter(Mandatory = $true)][string]$TaskName)

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $GradlePath -p $kioskRoot $TaskName --offline --console=plain 2>&1
    } finally {
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
    }
    return [pscustomobject]@{
        Task = $TaskName
        ExitCode = $exitCode
        Output = ($output -join [Environment]::NewLine)
    }
}

try {
    Move-Item -LiteralPath $propertiesPath -Destination $temporaryPath
    $releaseResults = @(
        Invoke-GradleTask -TaskName 'assembleRelease'
        Invoke-GradleTask -TaskName 'assemble'
        Invoke-GradleTask -TaskName 'bundleRelease'
        Invoke-GradleTask -TaskName 'build'
    )
    $debugResult = Invoke-GradleTask -TaskName 'assembleDebug'
} finally {
    if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
        Move-Item -LiteralPath $temporaryPath -Destination $propertiesPath
    }
}

foreach ($result in $releaseResults) {
    if ($result.ExitCode -eq 0) { throw "Expected '$($result.Task)' to fail without release signing." }
    if ($result.Output -notmatch 'Copy keystore.properties.example') {
        throw "'$($result.Task)' did not provide signing setup guidance."
    }
}
if ($debugResult.ExitCode -ne 0) {
    throw "assembleDebug must work without release signing: $($debugResult.Output)"
}

$unsignedAfter = if (Test-Path -LiteralPath $unsignedApk -PathType Leaf) { Get-Item -LiteralPath $unsignedApk } else { $null }
if (-not $unsignedBefore.Exists -and $unsignedAfter) { throw 'A new unsigned release APK was created.' }
if ($unsignedBefore.Exists -and (
    -not $unsignedAfter -or
    $unsignedAfter.Length -ne $unsignedBefore.Length -or
    $unsignedAfter.LastWriteTimeUtc -ne $unsignedBefore.LastWriteTimeUtc
)) {
    throw 'The pre-existing unsigned release APK was modified.'
}
if (-not (Test-Path -LiteralPath $propertiesPath -PathType Leaf)) {
    throw 'Signing properties were not restored.'
}

Write-Output 'Release signing gate self-test passed; local signing properties were restored.'
