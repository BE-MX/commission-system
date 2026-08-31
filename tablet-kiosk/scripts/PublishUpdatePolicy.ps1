Set-StrictMode -Version Latest

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
