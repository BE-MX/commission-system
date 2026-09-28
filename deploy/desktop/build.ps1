param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repoRoot '.deploy_state/desktop-package' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework 4.x compiler is required on the Windows build machine.' }
$tokens = Get-Content -LiteralPath (Join-Path $repoRoot 'frontend/src/styles/tokens.css') -Raw
$mapping = @{ primary = 'color-primary'; success = 'color-success'; danger = 'color-danger'; text = 'text-primary'; muted = 'text-secondary'; background = 'page-bg' }
$theme = @{}
foreach ($key in $mapping.Keys) {
    $match = [regex]::Match($tokens, ('--' + $mapping[$key] + ':\s*(#[0-9A-Fa-f]{3,8})\s*;'))
    if (-not $match.Success) { throw ('Missing design token: ' + $mapping[$key]) }
    $theme[$key] = $match.Groups[1].Value
}
$themePath = Join-Path $OutputDirectory 'theme.json'
$theme | ConvertTo-Json | Set-Content -LiteralPath $themePath -Encoding UTF8
$executable = Join-Path $OutputDirectory 'ArkDeploy.exe'
$arguments = @('/nologo', '/target:winexe', '/platform:anycpu', '/optimize+', '/utf8output', ('/out:' + $executable), '/reference:System.dll', '/reference:System.Core.dll', '/reference:System.Drawing.dll', '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll', ('/resource:' + $themePath + ',theme'))
foreach ($name in @('desktop_host', 'desktop_checks')) { $arguments += '/resource:' + (Join-Path $PSScriptRoot ($name + '.py')) + ',' + $name }
$arguments += Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.cs' | ForEach-Object FullName
& $compiler $arguments
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination (Join-Path $OutputDirectory 'README.md') -Force
Write-Output ('Built ' + $executable)
