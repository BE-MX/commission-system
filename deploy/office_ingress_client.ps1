$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$cfg = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($request)) | ConvertFrom-Json
$root = 'D:\commission-system\.deploy_state\office-beijing-tunnel'
$ssh = 'C:\Windows\System32\OpenSSH\ssh.exe'
$keygen = 'C:\Windows\System32\OpenSSH\ssh-keygen.exe'
$nssm = 'C:\Users\acciowork\AppData\Local\Microsoft\WinGet\Links\nssm.exe'
$service = 'ArkOfficeBeijingTunnel'
$key = "$root\id_ed25519"
$known = "$root\known_hosts"
$clientConfig = "$root\ssh_config"
function Native([string]$exe, [string[]]$arguments) {
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & $exe @arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($exitCode -ne 0) { throw "Native command failed: $exe ($exitCode)" }
    return $output
}
if ($env:COMPUTERNAME.ToLowerInvariant() -ne 'lys-acciowork') { throw 'Unexpected office host' }
foreach ($file in @($ssh, $keygen, $nssm, 'D:\commission-system\backend\.env')) {
    if (!(Test-Path -LiteralPath $file)) { throw "Missing office prerequisite: $file" }
}
if ((Get-Service frpc).Status -ne 'Running') { throw 'Singapore fallback is not running' }
$health = Invoke-RestMethod 'http://127.0.0.1:8001/health' -TimeoutSec 10
if ($health.status -ne 'ok') { throw 'Office backend is not healthy' }
if ($cfg.action -eq 'prepare') {
    @{ host=$env:COMPUTERNAME; backend=$health.status; fallback='running'; ssh=(Native $ssh @('-V') | Out-String).Trim() } | ConvertTo-Json -Compress
    exit 0
}
if (!(Test-Path -LiteralPath $root)) {
    New-Item -ItemType Directory -Path $root | Out-Null
}
if ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Tunnel state must not be a link' }
function Protect([string]$path, [bool]$directory) {
    if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Protected file must not be a link' }
    if ($directory) { $acl = New-Object Security.AccessControl.DirectorySecurity }
    else { $acl = New-Object Security.AccessControl.FileSecurity }
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
        $identity = New-Object Security.Principal.SecurityIdentifier($sid)
        $inherit = if ($directory) { 'ContainerInherit,ObjectInherit' } else { 'None' }
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', $inherit, 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    Set-Acl -LiteralPath $path -AclObject $acl
    $actual = Get-Acl -LiteralPath $path
    if (!$actual.AreAccessRulesProtected) { throw 'Protected ACL inheritance check failed' }
    $rules = @($actual.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if ($rules.Count -ne 2 -or @($rules | Where-Object { $_.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544') }).Count) { throw 'Protected ACL verification failed' }
}
Protect $root $true
foreach ($file in @($key, "$key.pub", $known, $clientConfig)) {
    if (Test-Path -LiteralPath $file) { Protect $file $false }
}
if ($cfg.action -eq 'key') {
    if (!(Test-Path -LiteralPath $key)) {
        # Recover only this task's interrupted pre-key process, never another key.
        Get-CimInstance Win32_Process -Filter "Name='ssh-keygen.exe'" | Where-Object {
            $_.CommandLine -like "* -f $key *" -and $_.CommandLine -like '*ark-office-beijing-tunnel*'
        } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        # PowerShell 5.1 drops empty native argv; ProcessStartInfo retains -N "".
        $start = New-Object Diagnostics.ProcessStartInfo
        $start.FileName = $keygen
        $start.Arguments = '-t ed25519 -N "" -f "' + $key + '" -C ark-office-beijing-tunnel'
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $process = [Diagnostics.Process]::Start($start)
        if (!$process.WaitForExit(20000)) { $process.Kill(); throw 'Key generation timeout' }
        if ($process.ExitCode -ne 0) { throw 'Key generation failed' }
        Protect $key $false
        Protect "$key.pub" $false
    }
    @{ public_key=(Get-Content -LiteralPath "$key.pub" -Raw).Trim() } | ConvertTo-Json -Compress
    exit 0
}
if ($cfg.action -eq 'client') {
    if (!(Test-Path -LiteralPath $key)) { throw 'Generate the dedicated key first' }
    if ($cfg.host_key -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]+$') { throw 'Invalid pinned host key' }
    $expected = "154.8.205.162 $($cfg.host_key)`n"
    if ((Test-Path $known) -and ([IO.File]::ReadAllText($known) -ne $expected)) { throw 'Pinned host key drift' }
    [IO.File]::WriteAllText($known, $expected, [Text.UTF8Encoding]::new($false))
    $settings = @"
Host office-beijing
    HostName 154.8.205.162
    User ark-office-tunnel
    Port 22
    IdentityFile D:/commission-system/.deploy_state/office-beijing-tunnel/id_ed25519
    UserKnownHostsFile D:/commission-system/.deploy_state/office-beijing-tunnel/known_hosts
    GlobalKnownHostsFile none
    StrictHostKeyChecking yes
    BatchMode yes
    IdentitiesOnly yes
    ExitOnForwardFailure yes
    ServerAliveInterval 15
    ServerAliveCountMax 3
    ConnectTimeout 10
    ConnectionAttempts 1
    RemoteForward 127.0.0.1:8002 127.0.0.1:8001
    RequestTTY no
"@
    if ((Test-Path $clientConfig) -and ([IO.File]::ReadAllText($clientConfig) -ne $settings)) { throw 'Client config drift' }
    [IO.File]::WriteAllText($clientConfig, $settings, [Text.UTF8Encoding]::new($false))
    Protect $known $false
    Protect $clientConfig $false
    $existing = Get-Service $service -ErrorAction SilentlyContinue
    if ($existing) {
        if ((Native $nssm @('get', $service, 'Application') | Out-String).Trim() -ne $ssh) { throw 'Existing service owner mismatch' }
        if ((Native $nssm @('get', $service, 'AppParameters') | Out-String).Trim() -ne "-N -T -F $clientConfig office-beijing") { throw 'Existing service parameters mismatch' }
    } else {
        Native $nssm @('install', $service, $ssh, '-N', '-T', '-F', $clientConfig, 'office-beijing') | Out-Null
    }
    if ((Get-CimInstance Win32_Service -Filter "Name='$service'").StartName -ne 'LocalSystem') { throw 'Unexpected existing service account' }
        Native $nssm @('set', $service, 'AppDirectory', $root) | Out-Null
        Native $nssm @('set', $service, 'Start', 'SERVICE_AUTO_START') | Out-Null
        Native $nssm @('set', $service, 'AppExit', 'Default', 'Restart') | Out-Null
        Native $nssm @('set', $service, 'AppRestartDelay', '5000') | Out-Null
        Native $nssm @('set', $service, 'AppStderr', "$root\tunnel.log") | Out-Null
        Native $nssm @('set', $service, 'AppRotateFiles', '1') | Out-Null
        Native $nssm @('set', $service, 'AppRotateBytes', '1048576') | Out-Null
    if ((Get-Service $service).Status -ne 'Running') { Start-Service $service }
}
if ($cfg.action -eq 'reconnect') {
    # Kill only this service's ssh child; NSSM must reconnect without manual start.
    $children = @(Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" | Where-Object { $_.CommandLine -like "*$clientConfig*" })
    if ($children.Count -ne 1) { throw 'Cannot identify the dedicated tunnel process' }
    Stop-Process -Id $children[0].ProcessId -Force
    Start-Sleep -Seconds 12
}
if ((Get-Service $service).Status -ne 'Running') { throw 'Tunnel service is not running' }
$processes = @(Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" | Where-Object { $_.CommandLine -like "*$clientConfig*" })
if ($processes.Count -ne 1) { throw 'Expected one dedicated ssh process' }
$svc = Get-CimInstance Win32_Service -Filter "Name='$service'"
if ($svc.StartMode -ne 'Auto' -or $svc.StartName -ne 'LocalSystem') { throw 'Unexpected service identity/start mode' }
@{ service=$service; status='running'; start=$svc.StartMode; pid=$processes[0].ProcessId; fallback=(Get-Service frpc).Status.ToString() } | ConvertTo-Json -Compress
