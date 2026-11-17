<#
.SYNOPSIS
  One-step setup of instagram-campaign-mcp on a new Windows machine.

.DESCRIPTION
  1. Creates .venv with Python 3.12 (via uv if installed, otherwise any
     installed Python 3.10+) and installs the package into it.
  2. Creates .env from env.example if it does not exist yet.
  3. Writes mcp-config.json with this machine's paths, ready to paste into
     Claude Desktop (or any MCP client).
  4. Optionally registers the server with Claude Code and runs the tests.
  5. Optionally starts the studio at logon and schedules the daily agent runs.

  Safe to re-run: it upgrades the install and never overwrites .env.

.PARAMETER Dev
  Also install test dependencies and run the test suite.

.PARAMETER RegisterClaudeCode
  Register the server with Claude Code (user scope) via `claude mcp add`.

.PARAMETER Schedule
  Register Task Scheduler tasks (current user, no admin): `ig-campaign up` at logon
  and the daily agent runs of AGENT_SCHEDULE, which wake the PC. Remove them with
  `ig-campaign agent install-schedule --remove`.

.PARAMETER Name
  MCP server name used in the generated config (default: instagram).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -RegisterClaudeCode
#>
param(
    [switch]$Dev,
    [switch]$RegisterClaudeCode,
    [switch]$Schedule,
    [string]$Name = "instagram"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$ServerExe = Join-Path $Venv "Scripts\ig-campaign-mcp.exe"
$Target = if ($Dev) { "$Root[dev]" } else { $Root }

function Write-Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Assert-Ok([string]$what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

function Find-Python {
    # First installed Python >= 3.10, as @(exe, args...), or $null.
    $candidates = @(
        @("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("py", "-3.10"),
        @("python"), @("python3")
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        $extra = @($c | Select-Object -Skip 1)
        try {
            $v = & $c[0] @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        } catch { continue }
        if ($LASTEXITCODE -eq 0 -and $v -and ([version]"$v" -ge [version]"3.10")) {
            return ,$c
        }
    }
    return $null
}

# --- 1. Virtual environment + package ------------------------------------
if (Test-Path $Py) {
    & $Py -c "import sys; sys.exit(sys.version_info < (3, 10))"
    if ($LASTEXITCODE -ne 0) {
        throw "Existing .venv uses Python < 3.10. Delete the .venv folder and re-run."
    }
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    Write-Step "Installing with uv"
    if (-not (Test-Path $Py)) {
        & uv venv --seed $Venv --python 3.12
        Assert-Ok "uv venv"
    }
    & uv pip install --python $Py -e $Target
    Assert-Ok "uv pip install"
} else {
    if (Test-Path $Py) {
        Write-Step "Updating existing .venv"
    } else {
        $python = Find-Python
        if (-not $python) {
            throw ("No Python 3.10+ found. Install uv (winget install --id astral-sh.uv -e) " +
                   "or Python 3.12 from python.org, then re-run this script.")
        }
        Write-Step "Installing with $($python -join ' ')"
        $extra = @($python | Select-Object -Skip 1)
        & $python[0] @extra -m venv $Venv
        Assert-Ok "python -m venv"
    }
    & $Py -m pip install --quiet --upgrade pip
    Assert-Ok "pip upgrade"
    & $Py -m pip install --quiet -e $Target
    Assert-Ok "pip install"
}

& $Py -c "import src.instagram_mcp_server"
Assert-Ok "Import check"

# ffmpeg renders and probes the videos. Like uv above, we point to the install
# command rather than installing system tools ourselves.
$needsFfmpeg = -not ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -and
                     (Get-Command ffprobe -ErrorAction SilentlyContinue))

# --- 2. .env -------------------------------------------------------------
$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root "env.example") $EnvFile
    Write-Step "Created .env from env.example"
}
$needsToken = Select-String -Path $EnvFile -Pattern "^INSTAGRAM_ACCESS_TOKEN=(your_long_lived_access_token)?\s*$" -Quiet

# --- 3. MCP client config ------------------------------------------------
$config = @{ mcpServers = @{ $Name = @{ command = $ServerExe } } } | ConvertTo-Json -Depth 5
$ConfigFile = Join-Path $Root "mcp-config.json"
[IO.File]::WriteAllText($ConfigFile, $config + "`n", (New-Object Text.UTF8Encoding $false))
Write-Step "Wrote mcp-config.json"

# --- 4. Optional: Claude Code registration, tests ------------------------
if ($RegisterClaudeCode) {
    if (Get-Command claude -ErrorAction SilentlyContinue) {
        Write-Step "Registering '$Name' with Claude Code (user scope)"
        & claude mcp add --scope user $Name -- $ServerExe
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "claude mcp add failed. If '$Name' already exists: claude mcp remove $Name --scope user, then re-run."
        }
    } else {
        Write-Warning "Claude Code CLI ('claude') not found on PATH; skipped registration."
    }
}

if ($Dev) {
    Write-Step "Running tests"
    Push-Location $Root
    try { & $Py -m pytest -q; Assert-Ok "pytest" } finally { Pop-Location }
}

# --- 5. Optional: autostart and daily agent runs -------------------------
if ($Schedule) {
    Write-Step "Registering autostart (IGCampaignUp) and daily agent runs"
    Push-Location $Root
    try { & $Py -m src.scheduler agent install-schedule; Assert-Ok "install-schedule" } finally { Pop-Location }
}

# --- Summary -------------------------------------------------------------
Write-Host ""
Write-Host "Done." -ForegroundColor Green
if ($needsToken) {
    Write-Host "Next: edit .env and set INSTAGRAM_ACCESS_TOKEN (and INSTAGRAM_BUSINESS_ACCOUNT_ID)." -ForegroundColor Yellow
}
if ($needsFfmpeg) {
    Write-Host "Next: install ffmpeg (video rendering): winget install --id Gyan.FFmpeg -e, then open a new terminal." -ForegroundColor Yellow
}
Write-Host "MCP server:      $ServerExe"
Write-Host "Claude Code:     claude mcp add --scope user $Name -- `"$ServerExe`""
Write-Host "Claude Desktop:  merge mcp-config.json into $env:APPDATA\Claude\claude_desktop_config.json"
Write-Host "Scheduler:       $(Join-Path $Venv 'Scripts\ig-campaign.exe') daemon"
