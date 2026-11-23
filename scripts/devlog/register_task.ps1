# Preview by default. Run -Register only after authorization to enable remote writes.
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Repo = (Resolve-Path "$PSScriptRoot/../..").Path,
    [string]$Python = '',
    [switch]$Register
)
$ErrorActionPreference = 'Stop'
if (-not $Python) { $Python = Join-Path $Repo 'backend/.venv/Scripts/python.exe' }
$Collector = Join-Path $Repo 'scripts/devlog/collect.py'
$State = Join-Path $Repo '.devlog_state'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python executable is missing' }
if (-not (Test-Path -LiteralPath $Collector -PathType Leaf)) { throw 'Collector script is missing' }
$Arguments = '"{0}" --repo "{1}" --state "{2}" --push' -f $Collector, $Repo, $State
Write-Output "ArkDevlogCollector: 08:00–22:00 every two hours (machine must use Beijing timezone)"
Write-Output ('"{0}" {1}' -f $Python, $Arguments)
if (-not $Register) { return }
if ((Get-TimeZone).BaseUtcOffset.TotalHours -ne 8) { throw 'Set machine timezone to UTC+08 before registration' }
if (-not (Test-Path -LiteralPath (Join-Path $State 'collector.json') -PathType Leaf)) { throw 'collector.json is missing' }
if ($PSCmdlet.ShouldProcess('ArkDevlogCollector', 'Register scheduled production ingestion')) {
    $Action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $Repo
    $Triggers = @(8, 10, 12, 14, 16, 18, 20, 22 | ForEach-Object { New-ScheduledTaskTrigger -Daily -At ('{0:00}:00' -f $_) })
    $Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName 'ArkDevlogCollector' -Action $Action -Trigger $Triggers -Settings $Settings -Description 'Ark devlog Git collector; authorized machine ingestion'
}
