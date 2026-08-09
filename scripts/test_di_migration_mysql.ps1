param(
    [string]$DatabaseHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

if ($DatabaseHost -notin @("127.0.0.1", "localhost", "::1")) {
    throw "Refusing non-local database host '$DatabaseHost'. This gate only uses an isolated Docker container."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required to run the isolated MySQL migration gate."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend virtual environment not found at $python"
}

$suffix = [Guid]::NewGuid().ToString("N").Substring(0, 12)
$container = "di-migration-$suffix"
$database = "commission_migration_test"
$password = "Tmp${suffix}Aa9"
$containerStarted = $false

function Invoke-AlembicUpgrade {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Revision,
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $python
    $startInfo.WorkingDirectory = $backendRoot
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Arguments = "-m alembic upgrade $Revision"
    $startInfo.EnvironmentVariables["COMMISSION_DB_HOST"] = "127.0.0.1"
    $startInfo.EnvironmentVariables["COMMISSION_DB_PORT"] = [string]$Port
    $startInfo.EnvironmentVariables["COMMISSION_DB_USER"] = "root"
    $startInfo.EnvironmentVariables["COMMISSION_DB_PASSWORD"] = $password
    $startInfo.EnvironmentVariables["COMMISSION_DB_NAME"] = $database

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "Alembic upgrade to $Revision failed.`n$stdout`n$stderr"
    }
    Write-Host $stdout
    Write-Host $stderr
}

try {
    $containerId = & docker run --detach --name $container `
        --env "MYSQL_ROOT_PASSWORD=$password" `
        --env "MYSQL_DATABASE=$database" `
        --publish "127.0.0.1::3306" `
        mysql:8.4
    if ($LASTEXITCODE -ne 0 -or -not $containerId) {
        throw "Failed to start isolated MySQL container."
    }
    $containerStarted = $true

    $healthy = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        & docker exec --env "MYSQL_PWD=$password" $container mysqladmin ping --user=root --silent 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $healthy = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        throw "Isolated MySQL did not become healthy within 90 seconds."
    }

    $portLine = (& docker port $container "3306/tcp" | Select-Object -First 1).Trim()
    if ($portLine -notmatch ':(\d+)$') {
        throw "Could not determine Docker-assigned MySQL port from '$portLine'."
    }
    $port = [int]$Matches[1]

    Invoke-AlembicUpgrade -Revision "098_customer_image_portal" -Port $port
    Invoke-AlembicUpgrade -Revision "101_di_message_interact" -Port $port

    $columnQuery = @"
SELECT column_name
FROM information_schema.columns
WHERE table_schema = '$database'
  AND table_name = 'ark_design_image_messages'
  AND column_name IN ('client_request_id', 'interaction_json')
ORDER BY column_name;
"@
    $columns = @(& docker exec --env "MYSQL_PWD=$password" $container `
        mysql --user=root --batch --skip-column-names --execute $columnQuery)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect migrated columns."
    }
    if (($columns -join ",") -ne "client_request_id,interaction_json") {
        throw "Expected interaction columns were not created: $($columns -join ', ')"
    }

    $constraintQuery = @"
SELECT constraint_name
FROM information_schema.table_constraints
WHERE table_schema = '$database'
  AND table_name = 'ark_design_image_messages'
  AND constraint_type = 'UNIQUE'
  AND constraint_name = 'uq_di_message_session_client_request';
"@
    $constraints = @(& docker exec --env "MYSQL_PWD=$password" $container `
        mysql --user=root --batch --skip-column-names --execute $constraintQuery)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect migrated constraints."
    }
    if ($constraints.Count -ne 1 -or $constraints[0] -ne "uq_di_message_session_client_request") {
        throw "Expected session/request unique constraint was not created."
    }

    Write-Host "PASS: isolated MySQL migration 098 -> 101 verified."
}
finally {
    if ($containerStarted) {
        & docker rm --force $container | Out-Null
    }
}
