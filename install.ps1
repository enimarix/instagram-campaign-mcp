<#
.SYNOPSIS
  One-command setup of the studio on Windows.

.DESCRIPTION
  1. Python: creates .venv (Python 3.12 via uv if installed, otherwise any installed
     Python 3.10+) and installs the package, with the yt-dlp fallback on 3.11+.
  2. Creates .env from env.example if it does not exist yet (never overwritten).
  3. Writes mcp-config.json with this machine's paths (Claude Desktop / any MCP client).
  4. Website build (web/) and motion packages (motion/), with Node.js.
  5. Reel downloader: the git submodule and `ig-campaign downloader setup`, only when
     missing (a re-run never undoes `ig-campaign downloader update`).
  6. Optional: tests, Claude Code registration, the OS schedule (-Schedule).
  7. `ig-campaign doctor`: ffmpeg, Claude Code CLI and everything above.

  Safe to re-run: it upgrades what is there and skips what is done. System tools
  (ffmpeg, Node.js, git) are never installed for you: it prints the command.

.PARAMETER Schedule
  Register Task Scheduler tasks (current user, no admin): `ig-campaign up` at logon
  and the daily agent runs of AGENT_SCHEDULE, which wake the PC. Remove them with
  `ig-campaign agent install-schedule --remove`.

.PARAMETER Dev
  Also install test dependencies and run the test suite.

.PARAMETER RegisterClaudeCode
  Register the MCP server with Claude Code (user scope) via `claude mcp add`.

.PARAMETER Name
  MCP server name used in the generated config (default: instagram).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -Schedule
#>
param(
    [switch]$Schedule,
    [switch]$Dev,
    [switch]$RegisterClaudeCode,
    [string]$Name = "instagram"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$Igc = Join-Path $Venv "Scripts\ig-campaign.exe"
$ServerExe = Join-Path $Venv "Scripts\ig-campaign-mcp.exe"
# The download extra (yt-dlp fallback) only installs on Python 3.11+ (marker in pyproject).
$Target = if ($Dev) { "$Root[dev,download]" } else { "$Root[download]" }
$script:Failed = $false
$Tick = [char]0x2714
$Cross = [char]0x2716

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "$Tick $msg" -ForegroundColor Green }
function Write-Fail([string]$what, [string]$fix) {
    Write-Host "$Cross $what" -ForegroundColor Red
    Write-Host "    -> $fix"
    $script:Failed = $true
}
function Has([string]$cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

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
        if (-not (Has $c[0])) { continue }
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

# --- 1. Python (the only step that stops the script) ---------------------
Write-Step "Python environment and package"
if (Test-Path $Py) {
    & $Py -c "import sys; sys.exit(sys.version_info < (3, 10))"
    if ($LASTEXITCODE -ne 0) {
        throw "Existing .venv uses Python < 3.10. Delete the .venv folder and re-run."
    }
}
if (Has uv) {
    if (-not (Test-Path $Py)) {
        & uv venv --seed $Venv --python 3.12
        Assert-Ok "uv venv"
    }
    & uv pip install --quiet --python $Py -e $Target
    Assert-Ok "uv pip install"
} else {
    if (-not (Test-Path $Py)) {
        $python = Find-Python
        if (-not $python) {
            throw ("No Python 3.10+ found. Install uv (winget install --id astral-sh.uv -e) " +
                   "or Python 3.12 from python.org, then re-run this script.")
        }
        $extra = @($python | Select-Object -Skip 1)
        & $python[0] @extra -m venv $Venv
        Assert-Ok "python -m venv"
    }
    & $Py -m pip install --quiet --upgrade pip
    Assert-Ok "pip upgrade"
    & $Py -m pip install --quiet -e $Target
    Assert-Ok "pip install"
}
Push-Location $Root
try { & $Py -c "import src.instagram_mcp_server"; Assert-Ok "Import check" } finally { Pop-Location }
$pyVersion = & $Py -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Ok "Python $pyVersion in .venv, package installed"

# --- 2. .env (never overwritten, never printed) --------------------------
Write-Step ".env"
$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
    Write-Ok ".env already there (kept as it is)"
} else {
    Copy-Item (Join-Path $Root "env.example") $EnvFile
    Write-Ok "created .env from env.example"
}

# --- 3. MCP client config ------------------------------------------------
$config = @{ mcpServers = @{ $Name = @{ command = $ServerExe } } } | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText((Join-Path $Root "mcp-config.json"), $config + "`n",
                        (New-Object Text.UTF8Encoding $false))
Write-Ok "wrote mcp-config.json (for Claude Desktop or any MCP client)"
if ($RegisterClaudeCode) {
    if (-not (Has claude)) {
        Write-Fail "Claude Code registration" "install Claude Code first, then re-run with -RegisterClaudeCode"
    } else {
        & claude mcp add --scope user $Name -- $ServerExe
        if ($LASTEXITCODE -eq 0) { Write-Ok "registered '$Name' with Claude Code (user scope)" }
        else { Write-Fail "claude mcp add" "if '$Name' already exists: claude mcp remove $Name --scope user, then re-run" }
    }
}

# --- 4. Website and motion packages (Node.js) ----------------------------
Write-Step "Website and motion packages"
if (Has npm) {
    Push-Location (Join-Path $Root "web")
    try {
        & npm ci --silent
        if ($LASTEXITCODE -eq 0) { & npm run build }
        if ($LASTEXITCODE -eq 0) { Write-Ok "website built (web\dist)" }
        else { Write-Fail "website build" "see the npm output above, then: npm --prefix web ci; npm --prefix web run build" }
    } finally { Pop-Location }
    Push-Location (Join-Path $Root "motion")
    try {
        & npm ci --silent
        if ($LASTEXITCODE -eq 0) { Write-Ok "motion packages installed" }
        else { Write-Fail "motion packages" "see the npm output above, then: npm --prefix motion ci" }
    } finally { Pop-Location }
} else {
    Write-Fail "Node.js not found" "winget install OpenJS.NodeJS.LTS, open a new terminal, then re-run"
}

# --- 5. Reel downloader (only when missing) ------------------------------
Write-Step "Reel downloader"
$Dl = Join-Path $Root "vendor\instagram-reels-downloader"
if (-not (Test-Path (Join-Path $Dl "package.json"))) {
    $checkedOut = $false
    if (Has git) {
        & git -C $Root submodule update --init vendor/instagram-reels-downloader
        $checkedOut = $LASTEXITCODE -eq 0
    }
    if ($checkedOut) { Write-Ok "submodule checked out" }
    else { Write-Fail "downloader submodule" "needs git and a git clone: git submodule update --init vendor/instagram-reels-downloader" }
}
if (Test-Path (Join-Path $Dl ".next\BUILD_ID")) {
    Write-Ok "downloader already built (ig-campaign downloader update moves it to upstream's latest)"
} elseif (Test-Path (Join-Path $Dl "package.json")) {
    Push-Location $Root
    try {
        & $Igc downloader setup | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Ok "downloader built" }
        else { Write-Fail "downloader setup" "see the message above, then: ig-campaign downloader setup" }
    } finally { Pop-Location }
}

# --- 6. Optional: tests, OS schedule -------------------------------------
if ($Dev) {
    Write-Step "Tests"
    Push-Location $Root
    try {
        & $Py -m pytest -q
        if ($LASTEXITCODE -eq 0) { Write-Ok "tests pass" } else { Write-Fail "tests" "see the pytest output above" }
    } finally { Pop-Location }
}
if ($Schedule) {
    Write-Step "OS schedule (Task Scheduler)"
    Push-Location $Root
    try {
        & $Igc agent install-schedule
        if ($LASTEXITCODE -eq 0) { Write-Ok "IGCampaignUp at logon, daily agent runs (remove: ig-campaign agent install-schedule --remove)" }
        else { Write-Fail "agent install-schedule" "see the message above" }
    } finally { Pop-Location }
}

# --- 7. Doctor: ffmpeg, Claude Code CLI, everything above ----------------
Write-Step "Checks (ig-campaign doctor, re-run it any time)"
Push-Location $Root
try { & $Igc doctor; if ($LASTEXITCODE -ne 0) { $script:Failed = $true } } finally { Pop-Location }

Write-Host ""
if ($script:Failed) {
    Write-Host "Almost done: fix the $Cross lines above, then re-run install.ps1." -ForegroundColor Yellow
} else {
    Write-Host "Done." -ForegroundColor Green
}
Write-Host "Next:"
Write-Host "  1. Fill in .env (INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID, ...): see README, Setup."
Write-Host "  2. Start the studio:  $Igc up"
Write-Host "  3. Open http://127.0.0.1:8765"
if (-not $Schedule) {
    Write-Host "  4. To start it at logon and run the agent every night: install.ps1 -Schedule"
}
if ($script:Failed) { exit 1 }
