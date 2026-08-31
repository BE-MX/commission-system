param([Parameter(Mandatory = $true)][string]$ReleaseApk)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$publisher = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\publish-update.ps1')).Path
$releaseApkPath = (Resolve-Path -LiteralPath $ReleaseApk).Path
$buildToolsRoot = Join-Path $env:LOCALAPPDATA 'Android\Sdk\build-tools'
$buildTools = Get-ChildItem -LiteralPath $buildToolsRoot -Directory |
    Sort-Object { [version]$_.Name } -Descending |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'apksigner.bat') } |
    Select-Object -First 1
if (-not $buildTools) { throw 'Android apksigner was not found.' }
$apksigner = Join-Path $buildTools.FullName 'apksigner.bat'
$keytool = (Get-Command keytool.exe -ErrorAction Stop).Source
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('leshine-signer-test-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($testRoot) | Out-Null

function New-RandomSecret {
    $bytes = [byte[]]::new(24)
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return ([System.BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}

function Invoke-External {
    param([string]$FilePath, [string[]]$Arguments, [string]$Failure)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $output = & $FilePath @Arguments 2>&1 } finally {
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) { throw "$Failure (exit $exitCode): $($output -join [Environment]::NewLine)" }
    return @($output)
}

function Invoke-PublisherPrepare {
    param([string]$Apk)
    $preparedDirectory = $null
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $publisher -ApkPath $Apk -PrepareOnly 2>&1
        $exitCode = $LASTEXITCODE
        $text = $output -join [Environment]::NewLine
        $match = [regex]::Match($text, '(?m)^Prepared directory: (.+)$')
        if ($match.Success) { $preparedDirectory = $match.Groups[1].Value.Trim() }
        return [pscustomobject]@{ ExitCode = $exitCode; Output = $text }
    } finally {
        $ErrorActionPreference = $previousPreference
        if ($preparedDirectory -and (Test-Path -LiteralPath $preparedDirectory -PathType Container)) {
            $resolved = [System.IO.Path]::GetFullPath($preparedDirectory)
            $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
            if (-not $resolved.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
                (Split-Path $resolved -Leaf) -cnotmatch '^leshine-expo-update-[0-9a-f]{32}$') {
                throw 'Publisher returned an unsafe prepared directory.'
            }
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}

$env:LESHINE_TEST_KS1 = New-RandomSecret
$env:LESHINE_TEST_KS2 = New-RandomSecret
try {
    $ks1 = Join-Path $testRoot 'other-one.p12'
    $ks2 = Join-Path $testRoot 'other-two.p12'
    $otherApk = Join-Path $testRoot 'other-release.apk'
    $multiApk = Join-Path $testRoot 'multi-release.apk'

    Invoke-External $keytool @(
        '-genkeypair', '-storetype', 'PKCS12', '-keystore', $ks1, '-storepass:env', 'LESHINE_TEST_KS1',
        '-keypass:env', 'LESHINE_TEST_KS1', '-alias', 'other-one', '-keyalg', 'RSA', '-keysize', '4096',
        '-sigalg', 'SHA256withRSA', '-validity', '10000', '-dname', 'CN=Other Expo Release One,O=Test,C=CN'
    ) 'Failed to create the first temporary signer' | Out-Null
    Invoke-External $keytool @(
        '-genkeypair', '-storetype', 'PKCS12', '-keystore', $ks2, '-storepass:env', 'LESHINE_TEST_KS2',
        '-keypass:env', 'LESHINE_TEST_KS2', '-alias', 'other-two', '-keyalg', 'RSA', '-keysize', '4096',
        '-sigalg', 'SHA256withRSA', '-validity', '10000', '-dname', 'CN=Other Expo Release Two,O=Test,C=CN'
    ) 'Failed to create the second temporary signer' | Out-Null

    Invoke-External $apksigner @(
        'sign', '--v3-signing-enabled', 'false', '--v4-signing-enabled', 'false',
        '--ks', $ks1, '--ks-key-alias', 'other-one', '--ks-pass', 'env:LESHINE_TEST_KS1',
        '--key-pass', 'env:LESHINE_TEST_KS1', '--out', $otherApk, $releaseApkPath
    ) 'Failed to create the other-signer APK' | Out-Null
    Invoke-External $apksigner @(
        'sign', '--v3-signing-enabled', 'false', '--v4-signing-enabled', 'false',
        '--ks', $ks1, '--ks-key-alias', 'other-one', '--ks-pass', 'env:LESHINE_TEST_KS1',
        '--key-pass', 'env:LESHINE_TEST_KS1', '--next-signer', '--ks', $ks2, '--ks-key-alias', 'other-two',
        '--ks-pass', 'env:LESHINE_TEST_KS2', '--key-pass', 'env:LESHINE_TEST_KS2', '--out', $multiApk, $releaseApkPath
    ) 'Failed to create the multi-signer APK' | Out-Null

    $official = Invoke-PublisherPrepare $releaseApkPath
    if ($official.ExitCode -ne 0) { throw "Official release signer was rejected: $($official.Output)" }

    $other = Invoke-PublisherPrepare $otherApk
    if ($other.ExitCode -eq 0 -or $other.Output -notmatch 'approved release signer') {
        throw "Another non-debug release signer was not rejected: $($other.Output)"
    }

    $multi = Invoke-PublisherPrepare $multiApk
    if ($multi.ExitCode -eq 0 -or $multi.Output -notmatch 'exactly one signer') {
        throw "A multi-signer APK was not rejected: $($multi.Output)"
    }

    Write-Output 'Release signer continuity self-test passed.'
} finally {
    Remove-Item Env:LESHINE_TEST_KS1,Env:LESHINE_TEST_KS2 -ErrorAction SilentlyContinue
    $resolvedRoot = [System.IO.Path]::GetFullPath($testRoot)
    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($resolvedRoot.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path $resolvedRoot -Leaf) -cmatch '^leshine-signer-test-[0-9a-f]{32}$') {
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
