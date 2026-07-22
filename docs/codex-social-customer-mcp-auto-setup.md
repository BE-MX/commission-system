# Codex 自动接入社媒客户查询 MCP（Windows）

> 这是一份交给 Codex 执行的配置协议，不是让用户手工复制命令的说明书。
>
> 适用于 Windows 上的 Codex App、Codex CLI 和 Codex IDE 扩展。三者共享当前用户的 `~/.codex/config.toml`。

## 1. 用户只需要做什么

把本文完整提供给 Codex，然后发送：

```text
请严格执行这份文档，为当前 Windows 用户配置“社媒客户查询 MCP”。除文档规定的 token 文件路径外，不要让我手工执行命令；每一步验证通过后再继续。
```

Codex 必须执行下述流程，不能只总结文档，也不能仅在对话中声称已配置。

## 2. 最终目标

- MCP server 名称：`leshine_social_customer`
- MCP URL：`https://leshine.work/mcp/social-customer/`
- transport：Streamable HTTP
- 原始 MCP tool name：`social_customer_search`
- token 保存到当前 Windows 用户环境变量 `SOCIAL_CUSTOMER_MCP_TOKEN`
- `config.toml` 只保存环境变量名，不保存 token 明文
- 修改前备份原有 `config.toml`
- 配置后要求用户完整重启 Codex，再完成加载验收

## 3. Codex 必须遵守的安全规则

1. 不要求用户把 token 粘贴到聊天中，只询问 token 文件的绝对路径。
2. token 文件必须是仅包含一行 token 的 UTF-8 文本文件。
3. 不通过 `Get-Content`、`type`、`cat`、`echo`、日志或异常输出展示 token。
4. 不把 token 写入 Markdown、Git、项目 `.env`、`config.toml` 或命令行参数。
5. 只更新当前 Windows 用户的环境变量和 Codex 用户配置，不修改系统级环境变量。
6. 修改前备份配置；只新增或替换 `leshine_social_customer` 表，不改变其他配置。
7. 如果读取 token 文件、写入 `~/.codex` 或更新用户环境变量需要审批，应向用户说明范围并申请审批，不得绕过配置。
8. 不自动删除用户提供的 token 文件。成功后提醒用户将它移入密码库或自行安全删除。
9. 用户给出的路径不得拼接进 PowerShell 命令。路径只写入固定的临时描述文件，再由固定脚本读取。

## 4. Codex 自动执行流程

### 步骤 1：环境预检

Codex 检查：

- 操作系统是 Windows；
- PowerShell 可用；
- `https://leshine.work/mcp/social-customer/health` 返回 `status=ok`；
- 当前用户目录可确定；
- 是否能执行 `codex mcp --help`；如果不能，再确认 `python` 或 `py -3` 可导入 Python 3.11+ 标准库 `tomllib`。两种方式至少有一种可用。

如果不是 Windows，停止并说明本文不适用。健康检查失败，或 Codex CLI 与 `tomllib` 都不可用时停止，不要索取 token。

### 步骤 2：只询问一次 token 文件路径

预检通过后，Codex 必须发送下面的问题并等待回答：

```text
请让管理员把 MCP token 保存为只含一行 token 的 UTF-8 文本文件，然后把该文件的绝对路径发给我，例如：C:\Users\你的用户名\Downloads\social-customer-mcp.token。不要把 token 内容粘贴到聊天中。
```

用户没有提供路径前不得继续。如果用户直接粘贴 token，Codex 不得复述，应提醒其撤回或删除消息并改用文件。

### 步骤 3：创建固定的临时文件

Codex 对用户回答做以下文本检查：

- 去掉路径两侧的引号；
- 必须是单行 Windows 绝对路径；
- 不得含回车、换行或 NUL；
- 不读取、不显示文件内容。

然后创建 `.codex-tmp` 目录，并使用 `apply_patch` 创建三个文件：

```text
.codex-tmp/token-file-path.txt
.codex-tmp/configure-social-customer-mcp.ps1
.codex-tmp/verify-social-customer-toml.py
```

`token-file-path.txt` 只能包含用户提供的绝对路径和末尾换行。不要把该路径插入任何命令。

TOML 校验脚本内容必须与下方一致。它只输出 `ABSENT`、`MATCH`、`MISMATCH` 或 `SELF_TEST_OK`，不会输出配置内容：

```python
import sys
import tomllib


if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
    print("SELF_TEST_OK")
    raise SystemExit(0)

if len(sys.argv) != 2:
    raise SystemExit(2)

with open(sys.argv[1], "rb") as config_file:
    data = tomllib.load(config_file)

servers = data.get("mcp_servers")
target = servers.get("leshine_social_customer") if isinstance(servers, dict) else None
enabled_tools = target.get("enabled_tools") if isinstance(target, dict) else None
disabled_tools = target.get("disabled_tools", []) if isinstance(target, dict) else []
if target is None:
    print("ABSENT")
elif (
    isinstance(target, dict)
    and target.get("url") == "https://leshine.work/mcp/social-customer/"
    and target.get("bearer_token_env_var") == "SOCIAL_CUSTOMER_MCP_TOKEN"
    and target.get("enabled", True) is not False
    and (
        enabled_tools is None
        or (isinstance(enabled_tools, list) and "social_customer_search" in enabled_tools)
    )
    and isinstance(disabled_tools, list)
    and "social_customer_search" not in disabled_tools
):
    print("MATCH")
else:
    print("MISMATCH")
```

PowerShell 脚本内容必须与下方一致：

```powershell
param(
    [Parameter(Mandatory = $true)]
    [string]$TokenPathFile,
    [Parameter(Mandatory = $true)]
    [string]$TomlVerifierFile
)

$ErrorActionPreference = "Stop"
$serviceName = "leshine_social_customer"
$endpoint = "https://leshine.work/mcp/social-customer/"
$healthEndpoint = "https://leshine.work/mcp/social-customer/health"
$tokenVariableName = "SOCIAL_CUSTOMER_MCP_TOKEN"
$serverBlock = @'
[mcp_servers.leshine_social_customer]
url = "https://leshine.work/mcp/social-customer/"
bearer_token_env_var = "SOCIAL_CUSTOMER_MCP_TOKEN"
'@

function Stop-Setup([string]$Message) {
    throw "Codex MCP 配置失败：$Message"
}

function Get-HttpStatusCode($ErrorRecord) {
    if ($null -eq $ErrorRecord.Exception.Response) { return $null }
    try { return [int]$ErrorRecord.Exception.Response.StatusCode }
    catch { return $null }
}

function Invoke-McpWebRequest(
    [hashtable]$Payload,
    [hashtable]$AdditionalHeaders = @{}
) {
    $requestHeaders = @{
        Authorization = "Bearer $token"
        Accept = "application/json, text/event-stream"
    }
    foreach ($key in $AdditionalHeaders.Keys) {
        $requestHeaders[$key] = $AdditionalHeaders[$key]
    }

    try {
        return Invoke-WebRequest `
            -UseBasicParsing `
            -Uri $endpoint `
            -Method Post `
            -Headers $requestHeaders `
            -ContentType "application/json" `
            -Body ($Payload | ConvertTo-Json -Compress -Depth 10) `
            -TimeoutSec 30
    }
    catch {
        $statusCode = Get-HttpStatusCode $_
        if ($statusCode -eq 401) {
            Stop-Setup "token 无效或已被轮换，请向管理员重新领取"
        }
        if ($statusCode -eq 503) {
            Stop-Setup "服务触发临时限流，请等待至少 60 秒后重试"
        }
        Stop-Setup "MCP 协议请求失败，请检查网络、代理和服务状态"
    }
}

function ConvertFrom-McpResponse($Response) {
    $contentType = [string]$Response.Headers["Content-Type"]
    $content = [string]$Response.Content

    if ($contentType -like "text/event-stream*") {
        $events = [regex]::Split($content, '\r?\n\r?\n')
        foreach ($event in $events) {
            $dataLines = @(
                [regex]::Matches($event, '(?m)^data:[ \t]?(.*)\r?$') |
                    ForEach-Object { $_.Groups[1].Value }
            )
            if ($dataLines.Count -eq 0) { continue }
            $data = ($dataLines -join "`n").Trim()
            if ([string]::IsNullOrWhiteSpace($data) -or $data -eq "[DONE]") {
                continue
            }
            try {
                return $data | ConvertFrom-Json -ErrorAction Stop
            }
            catch {
                continue
            }
        }
        Stop-Setup "MCP 返回了 SSE，但没有可解析的 JSON-RPC data 事件"
    }

    try {
        return $content | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Stop-Setup "MCP 返回内容不是有效的 JSON 或 SSE"
    }
}

function Get-PythonTomlCommand([string]$VerifierPath) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        try {
            & $python.Source $VerifierPath --self-test *> $null
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]@{ Path = $python.Source; Prefix = @() }
            }
        } catch {}
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        try {
            & $pyLauncher.Source -3 $VerifierPath --self-test *> $null
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]@{ Path = $pyLauncher.Source; Prefix = @("-3") }
            }
        } catch {}
    }

    Stop-Setup "Codex CLI 不可执行，且未找到带 tomllib 的 Python 3.11+；为保护现有配置，已停止写入"
}

function Get-TomlTargetStatus(
    [string]$ConfigPath,
    $PythonCommand,
    [string]$VerifierPath
) {
    try {
        if ($PythonCommand.Prefix.Count -gt 0) {
            $output = & $($PythonCommand.Path) $PythonCommand.Prefix[0] $VerifierPath $ConfigPath 2>$null
        } else {
            $output = & $($PythonCommand.Path) $VerifierPath $ConfigPath 2>$null
        }
    }
    catch {
        Stop-Setup "无法使用 Python 校验 Codex TOML 配置：$($_.Exception.Message)"
    }
    if ($LASTEXITCODE -ne 0) {
        Stop-Setup "现有或待写入的 config.toml 不是有效 TOML，已保留原文件"
    }

    $status = ($output | Out-String).Trim()
    if ($status -notin @("ABSENT", "MATCH", "MISMATCH")) {
        Stop-Setup "TOML 校验器返回了未知结果"
    }
    return $status
}

function Set-ConfigWithTomlValidation(
    [string]$ConfigPath,
    [string]$Block,
    [string]$VerifierPath
) {
    $pythonCommand = Get-PythonTomlCommand $VerifierPath
    $configExists = Test-Path -LiteralPath $ConfigPath -PathType Leaf
    $status = if ($configExists) {
        Get-TomlTargetStatus $ConfigPath $pythonCommand $VerifierPath
    } else { "ABSENT" }

    if ($status -eq "MATCH") { return }
    if ($status -eq "MISMATCH") {
        Stop-Setup "已存在同名但参数不同的 MCP 配置；为保护用户配置，已停止自动覆盖"
    }

    [byte[]]$originalBytes = if ($configExists) {
        [System.IO.File]::ReadAllBytes($ConfigPath)
    } else { [byte[]]@() }
    $separator = if ($originalBytes.Length -eq 0) {
        ""
    } elseif ($originalBytes[$originalBytes.Length - 1] -eq 10) {
        "`r`n"
    } else {
        "`r`n`r`n"
    }
    $appendBytes = [System.Text.Encoding]::UTF8.GetBytes($separator + $Block + "`r`n")
    $updatedBytes = New-Object byte[] ($originalBytes.Length + $appendBytes.Length)
    [System.Buffer]::BlockCopy($originalBytes, 0, $updatedBytes, 0, $originalBytes.Length)
    [System.Buffer]::BlockCopy($appendBytes, 0, $updatedBytes, $originalBytes.Length, $appendBytes.Length)

    $temporaryPath = "$ConfigPath.tmp.$([guid]::NewGuid().ToString('N'))"
    try {
        [System.IO.File]::WriteAllBytes($temporaryPath, $updatedBytes)
        if ((Get-TomlTargetStatus $temporaryPath $pythonCommand $VerifierPath) -ne "MATCH") {
            Stop-Setup "写前校验未找到正确的目标 MCP 配置"
        }
        $verifiedBytes = [System.IO.File]::ReadAllBytes($temporaryPath)
        for ($index = 0; $index -lt $originalBytes.Length; $index++) {
            if ($verifiedBytes[$index] -ne $originalBytes[$index]) {
                Stop-Setup "安全校验发现原有 Codex 配置字节发生变化"
            }
        }
        Move-Item -LiteralPath $temporaryPath -Destination $ConfigPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $TokenPathFile -PathType Leaf)) {
    Stop-Setup "找不到 token 路径描述文件"
}
if (-not (Test-Path -LiteralPath $TomlVerifierFile -PathType Leaf)) {
    Stop-Setup "找不到固定的 TOML 校验脚本"
}
$resolvedTomlVerifierFile = (Resolve-Path -LiteralPath $TomlVerifierFile).Path

$tokenFilePath = [System.IO.File]::ReadAllText(
    (Resolve-Path -LiteralPath $TokenPathFile).Path
).Trim()
if ([string]::IsNullOrWhiteSpace($tokenFilePath)) {
    Stop-Setup "token 文件路径为空"
}
if ($tokenFilePath.Contains("`r") -or $tokenFilePath.Contains("`n") -or $tokenFilePath.Contains([char]0)) {
    Stop-Setup "token 文件路径必须只有一行"
}
if (-not [System.IO.Path]::IsPathRooted($tokenFilePath)) {
    Stop-Setup "token 文件必须使用绝对路径"
}
if (-not (Test-Path -LiteralPath $tokenFilePath -PathType Leaf)) {
    Stop-Setup "找不到 token 文件，请检查路径"
}

$token = [System.IO.File]::ReadAllText(
    (Resolve-Path -LiteralPath $tokenFilePath).Path
).Trim()
if ([string]::IsNullOrWhiteSpace($token)) {
    Stop-Setup "token 文件为空"
}
if ($token.Length -lt 32 -or $token.Length -gt 512) {
    Stop-Setup "token 长度不符合要求"
}
if ($token -notmatch '^[A-Za-z0-9._~+/=-]+$') {
    Stop-Setup "token 文件只能包含一行 token，不能含空格或说明文字"
}

[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
try {
    $health = Invoke-RestMethod -Uri $healthEndpoint -Method Get -TimeoutSec 15
    if ($health.status -ne "ok") {
        Stop-Setup "服务健康检查没有返回 ok"
    }
}
catch {
    Stop-Setup "无法访问服务健康检查，请确认网络可访问 leshine.work"
}

$initializeResponse = Invoke-McpWebRequest @{
    jsonrpc = "2.0"
    id = 1
    method = "initialize"
    params = @{
        protocolVersion = "2025-06-18"
        capabilities = @{}
        clientInfo = @{
            name = "codex-social-customer-setup"
            version = "1.0"
        }
    }
}
$initializeResult = ConvertFrom-McpResponse $initializeResponse
if ($null -eq $initializeResult.result -or $null -ne $initializeResult.error) {
    Stop-Setup "MCP initialize 未成功"
}

$sessionHeaders = @{}
$protocolVersion = $initializeResult.result.protocolVersion
if (-not [string]::IsNullOrWhiteSpace($protocolVersion)) {
    $sessionHeaders["MCP-Protocol-Version"] = $protocolVersion
}
$sessionId = $initializeResponse.Headers["Mcp-Session-Id"]
if (-not [string]::IsNullOrWhiteSpace($sessionId)) {
    $sessionHeaders["Mcp-Session-Id"] = $sessionId
}

[void](Invoke-McpWebRequest @{
    jsonrpc = "2.0"
    method = "notifications/initialized"
    params = @{}
} $sessionHeaders)

$listResponse = Invoke-McpWebRequest @{
    jsonrpc = "2.0"
    id = 2
    method = "tools/list"
    params = @{}
} $sessionHeaders
$listResult = ConvertFrom-McpResponse $listResponse
$toolNames = @($listResult.result.tools | ForEach-Object { $_.name })
if ($toolNames -notcontains "social_customer_search") {
    Stop-Setup "服务已连接，但 tools/list 未返回 social_customer_search"
}

$codexHomePath = if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    $env:CODEX_HOME
} else {
    Join-Path $env:USERPROFILE ".codex"
}
if (-not (Test-Path -LiteralPath $codexHomePath)) {
    New-Item -ItemType Directory -Path $codexHomePath -Force | Out-Null
}

$configPath = Join-Path $codexHomePath "config.toml"
$originalConfigExisted = Test-Path -LiteralPath $configPath -PathType Leaf
$backupPath = $null
if ($originalConfigExisted) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupPath = "$configPath.bak-social-customer-$timestamp"
    Copy-Item -LiteralPath $configPath -Destination $backupPath -Force
}

$previousUserToken = [System.Environment]::GetEnvironmentVariable($tokenVariableName, "User")
$configSucceeded = $false
try {
    [System.Environment]::SetEnvironmentVariable($tokenVariableName, $token, "User")
    $env:SOCIAL_CUSTOMER_MCP_TOKEN = $token

    $usedCodexCli = $false
    $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
    if ($null -ne $codexCommand) {
        try {
            & $codexCommand.Source mcp --help *> $null
            $usedCodexCli = ($LASTEXITCODE -eq 0)
        } catch {
            $usedCodexCli = $false
        }
    }

    if ($usedCodexCli) {
        & $codexCommand.Source mcp get $serviceName *> $null
        if ($LASTEXITCODE -eq 0) {
            & $codexCommand.Source mcp remove $serviceName *> $null
            if ($LASTEXITCODE -ne 0) {
                Stop-Setup "Codex CLI 无法移除旧的同名 MCP 配置"
            }
        }
        & $codexCommand.Source mcp add $serviceName --url $endpoint --bearer-token-env-var $tokenVariableName *> $null
        if ($LASTEXITCODE -ne 0) {
            Stop-Setup "Codex CLI 写入 MCP 配置失败"
        }
        & $codexCommand.Source mcp get $serviceName *> $null
        if ($LASTEXITCODE -ne 0) {
            Stop-Setup "Codex CLI 写后校验失败"
        }
    } else {
        Set-ConfigWithTomlValidation $configPath $serverBlock $resolvedTomlVerifierFile
    }

    $configSucceeded = $true
}
catch {
    if ($originalConfigExisted -and $null -ne $backupPath) {
        Copy-Item -LiteralPath $backupPath -Destination $configPath -Force
    } elseif (-not $originalConfigExisted -and (Test-Path -LiteralPath $configPath)) {
        Remove-Item -LiteralPath $configPath -Force
    }
    [System.Environment]::SetEnvironmentVariable($tokenVariableName, $previousUserToken, "User")
    throw
}
finally {
    if (-not $configSucceeded) {
        $env:SOCIAL_CUSTOMER_MCP_TOKEN = $previousUserToken
    }
}

try {
    if (-not ("CodexMcp.NativeMethods" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace CodexMcp {
    public static class NativeMethods {
        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        public static extern IntPtr SendMessageTimeout(
            IntPtr hWnd, uint Msg, IntPtr wParam, string lParam,
            uint flags, uint timeout, out IntPtr result);
    }
}
"@
    }
    $broadcastResult = [IntPtr]::Zero
    [void][CodexMcp.NativeMethods]::SendMessageTimeout(
        [IntPtr]0xffff, 0x001A, [IntPtr]::Zero, "Environment",
        2, 5000, [ref]$broadcastResult
    )
}
catch {
    Write-Warning "环境变量已保存；Windows 刷新通知失败，重启 Codex 后仍会重新读取"
}

$token = $null
$sessionHeaders = $null

Write-Host "CONFIG_OK"
Write-Host "MCP server: $serviceName"
Write-Host "Config: $configPath"
if ($null -ne $backupPath) { Write-Host "Backup: $backupPath" }
Write-Host "Token: 已写入当前 Windows 用户环境变量，未写入 config.toml"
Write-Host "NEXT_STEP: 完全退出并重新启动 Codex"
```

### 步骤 4：语法检查并运行固定命令

先运行语法检查；有解析错误时不得继续：

```powershell
$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    ".codex-tmp\configure-social-customer-mcp.ps1",
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
    throw "自动配置脚本存在 PowerShell 语法错误"
}
```

语法检查通过后，只能运行下面这条固定命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".codex-tmp\configure-social-customer-mcp.ps1" `
  -TokenPathFile ".codex-tmp\token-file-path.txt" `
  -TomlVerifierFile ".codex-tmp\verify-social-customer-toml.py"
```

命令中不得出现用户提供的路径或 token。只有脚本输出 `CONFIG_OK` 才算配置写入成功。

脚本结束后，无论成功还是失败，Codex 都应使用 `apply_patch` 删除自己创建的以下两个临时文件；不要删除用户提供的 token 文件：

```text
.codex-tmp/token-file-path.txt
.codex-tmp/configure-social-customer-mcp.ps1
.codex-tmp/verify-social-customer-toml.py
```

失败处理：

| 结果 | Codex 的动作 |
|---|---|
| HTTP 401 | 停止；提示用户向管理员重新领取 token 文件 |
| HTTP 503 | 等待至少 60 秒后重试，不要解释成“工具不存在” |
| 健康检查失败 | 停止并报告网络或服务不可达 |
| `tools/list` 缺少目标工具 | 停止并报告服务端工具契约异常 |
| 配置写入或校验失败 | 脚本自动恢复原配置和原用户环境变量；报告实际配置路径和错误，不索取 token 内容 |

### 步骤 5：要求用户完整重启 Codex

出现 `CONFIG_OK` 后，Codex 必须告诉用户：

```text
配置已经写入，并通过服务端 initialize、notifications/initialized 和 tools/list 验证。请完全退出 Codex（包括仍在运行的 Codex 窗口或进程），然后重新打开。重启后回到这个任务并回复“已重启”，我会继续检查 MCP 是否已被 Codex 加载。
```

仅新建对话不能代替重启，因为 MCP 配置和用户环境变量需要由新的 Codex host 进程重新读取。

### 步骤 6：重启后的最终验收

用户回复“已重启”后，Codex 按顺序验收：

1. MCP server 列表中存在且启用 `leshine_social_customer`。
2. 该 server 提供底层工具 `social_customer_search`。
3. Codex 内部工具 ID 可能带 server namespace；不能因为内部名称不是纯 `social_customer_search` 就判断工具不存在。
4. 当前界面支持 `/mcp` 时，提示用户输入 `/mcp` 并确认 server 已连接。
5. 不执行真实客户查询，除非用户另外提供邮箱、社交账号或电话并明确要求查询。

验收成功后回复：

```text
社媒客户查询 MCP 已完成配置并加载。服务：leshine_social_customer；底层工具：social_customer_search。
```

## 5. 配置完成后的标准结果

`~/.codex/config.toml` 至少应包含：

```toml
[mcp_servers.leshine_social_customer]
url = "https://leshine.work/mcp/social-customer/"
bearer_token_env_var = "SOCIAL_CUSTOMER_MCP_TOKEN"
```

如果由 Codex CLI 写入，字段顺序或格式可能略有不同，但 URL 与环境变量名必须一致，且不得出现 token 明文。

## 6. 回滚

如果新增配置导致 Codex 启动异常：

1. 完全退出 Codex。
2. 找到脚本输出的 `Backup` 路径。
3. 用备份恢复 `%CODEX_HOME%\config.toml`；未设置 `CODEX_HOME` 时恢复 `%USERPROFILE%\.codex\config.toml`。
4. 如需同时撤销 token，删除当前用户环境变量 `SOCIAL_CUSTOMER_MCP_TOKEN`。
5. 重新启动 Codex。

不要删除或覆盖其他 MCP server 配置。

## 7. 管理员发放 token 文件的要求

- 文件内容只有一行 token，不带变量名、引号或 Markdown。
- 推荐文件名：`social-customer-mcp.token`。
- 通过密码库或受控的一次性文件通道发送，不通过群聊或 Agent 对话发送。
- 用户配置完成后，应将文件移入密码库保护范围或安全删除。
- 当前服务使用共享 token；管理员轮换 token 后，所有用户都要重新执行本文。

## 8. 常见故障

| 现象 | 判断与动作 |
|---|---|
| Codex 说找不到工具，服务器没有请求日志 | 配置未加载；检查实际 `config.toml` 路径并完整重启 Codex |
| HTTP 401 | token 缺失、错误或已轮换 |
| HTTP 503 | 临时限流；等待至少 60 秒后重试 |
| `/mcp` 没有 `leshine_social_customer` | Codex 没有读取到对应用户配置 |
| server 存在但未连接 | 检查用户环境变量、URL、网络和代理 |
| server 已连接但工具名看起来不同 | 查看底层 MCP tool name；Codex 内部可能增加 server namespace |
| PowerShell 无法执行 WindowsApps 中的 `codex.exe` | 脚本会自动改用 Python 标准库 `tomllib` 校验后追加配置；无需用户手工执行 CLI |

## 9. 官方依据

Codex 官方文档确认：

- Codex App、CLI 和 IDE 扩展共享 MCP 配置；
- 用户级配置默认位于 `~/.codex/config.toml`；
- Streamable HTTP server 使用 `url`；
- `bearer_token_env_var` 从环境变量读取 Bearer token；
- CLI 可用 `codex mcp add <name> --url <url> --bearer-token-env-var <ENV_VAR>` 添加服务；
- 保存配置后需要重启 Codex host。

官方说明：<https://developers.openai.com/codex/mcp/>
