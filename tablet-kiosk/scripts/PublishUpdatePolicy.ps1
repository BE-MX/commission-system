Set-StrictMode -Version Latest

function Assert-VersionName {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowNull()][string]$VersionName,
        [Parameter(Mandatory = $true)][string]$Source
    )

    if ([string]::IsNullOrWhiteSpace($VersionName) -or
        $VersionName -cne $VersionName.Trim() -or
        $VersionName -cmatch '[\x00-\x1f\x7f]') {
        throw "$Source version_name must be non-empty, already trimmed, and contain no control characters."
    }
    return $VersionName
}

function Assert-PublishTarget {
    param([Parameter(Mandatory = $true)][string]$Target)

    if ($Target -cnotmatch '\A[A-Za-z0-9][A-Za-z0-9._-]*@(?:[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?|(?:[0-9]{1,3}\.){3}[0-9]{1,3})\z') {
        throw 'Target must be a controlled user@host value without shell metacharacters.'
    }
}

function Assert-ChannelPolicy {
    param(
        [Parameter(Mandatory = $true)][ValidateSet(200, 404)][int]$HttpStatus,
        [Parameter(Mandatory = $true)][long]$CandidateVersionCode,
        [Nullable[long]]$PublishedVersionCode,
        [switch]$InitializeChannel
    )

    if ($HttpStatus -eq 404) {
        if (-not $InitializeChannel) {
            throw 'Online update manifest returned 404. Use -InitializeChannel only for the controlled first publication.'
        }
        if ($CandidateVersionCode -ne 10) {
            throw "InitializeChannel accepts only the first stable versionCode 10; got $CandidateVersionCode."
        }
        return $true
    }

    if ($InitializeChannel) {
        throw 'InitializeChannel is forbidden because the online update channel already exists.'
    }
    if ($null -eq $PublishedVersionCode) {
        throw 'PublishedVersionCode is required for an existing update channel.'
    }
    $published = [long]$PublishedVersionCode
    if ($CandidateVersionCode -le $published) {
        throw "Refusing versionCode ${CandidateVersionCode}: published versionCode is $published."
    }
    return $false
}

function Read-StrictManifest {
    param([Parameter(Mandatory = $true)][string]$Path)

    $rawManifest = Get-Content -LiteralPath $Path -Raw
    $trimmedManifest = $rawManifest.Trim()
    if (-not ($trimmedManifest.StartsWith('{') -and $trimmedManifest.EndsWith('}'))) {
        throw 'Published manifest root must be a JSON object.'
    }
    try { $manifest = $trimmedManifest | ConvertFrom-Json } catch { throw "Published manifest is invalid JSON: $($_.Exception.Message)" }
    $propertyMatches = [regex]::Matches($trimmedManifest, '(?<!\\)"([^"\\]*(?:\\.[^"\\]*)*)"\s*:')
    $names = @($propertyMatches | ForEach-Object { $_.Groups[1].Value })
    $expected = @('version_code', 'version_name', 'apk_size', 'sha256')
    if ((($names | Sort-Object) -join ',') -cne (($expected | Sort-Object) -join ',')) {
        throw 'Published manifest must contain exactly version_code, version_name, apk_size, and sha256.'
    }
    if ($manifest.version_code -isnot [long] -and $manifest.version_code -isnot [int]) { throw 'Published version_code must be an integer.' }
    if ([long]$manifest.version_code -le 0) { throw 'Published version_code must be positive.' }
    if ($manifest.version_name -isnot [string]) { throw 'Published version_name must be a string.' }
    $manifest.version_name = Assert-VersionName -VersionName ([string]$manifest.version_name) -Source 'Published manifest'
    if ($manifest.apk_size -isnot [long] -and $manifest.apk_size -isnot [int]) { throw 'Published apk_size must be an integer.' }
    if ([long]$manifest.apk_size -le 0) { throw 'Published apk_size must be positive.' }
    if ($manifest.sha256 -isnot [string] -or $manifest.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Published sha256 must be lowercase hexadecimal.' }
    return $manifest
}
