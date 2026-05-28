<#
.SYNOPSIS
    Manage the Phase 6 worker daemon (start / stop / restart / status / log).

.DESCRIPTION
    Wraps `python -m worker.daemon` as a hidden-window background process with
    stdout / stderr captured to logs/worker.log + logs/worker.err.log. Idempotent:
    starting when already running warns; stopping when not running warns.

    Python lookup order: venv\Scripts\python.exe ->
    %LOCALAPPDATA%\Programs\Python\Python313\python.exe -> PATH.
    Env vars (DATABASE_URL, APP_DATABASE_URL, REDIS_URL, TELEGRAM_BOT_TOKEN, ...) are
    loaded by the daemon itself via python-dotenv from .env in the repo root.

.EXAMPLE
    .\scripts\worker.ps1 start
    .\scripts\worker.ps1 status
    .\scripts\worker.ps1 log
    .\scripts\worker.ps1 stop
    .\scripts\worker.ps1 restart

.NOTES
    First time only: allow local scripts to run for this user, e.g.
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("start", "stop", "restart", "status", "log")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$logDir   = Join-Path $repoRoot "logs"
$logFile  = Join-Path $logDir   "worker.log"
$errFile  = Join-Path $logDir   "worker.err.log"


function Get-WorkerProcess {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -in @("python.exe", "pythonw.exe") -and
            $_.CommandLine -and $_.CommandLine -like "*worker.daemon*"
        }
}

function Find-Python {
    $candidates = @(
        (Join-Path $repoRoot "venv\Scripts\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Python not found (looked in venv, AppData Python313, PATH)."
}

function Start-Worker {
    $existing = Get-WorkerProcess
    if ($existing) {
        Write-Host "[worker] already running - PID $($existing.ProcessId) since $($existing.CreationDate)" -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
    $py = Find-Python
    $proc = Start-Process `
        -FilePath $py `
        -ArgumentList "-m", "worker.daemon" `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError  $errFile `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Milliseconds 800
    if ($proc.HasExited) {
        Write-Host "[worker] FAILED to start (exit $($proc.ExitCode)). Tail of $errFile :" -ForegroundColor Red
        if (Test-Path $errFile) { Get-Content $errFile -Tail 15 | ForEach-Object { "  $_" } }
        exit 1
    }
    Write-Host "[worker] started - PID $($proc.Id) - python $py - log $logFile" -ForegroundColor Green
}

function Stop-Worker {
    $existing = Get-WorkerProcess
    if (-not $existing) {
        Write-Host "[worker] not running - nothing to stop" -ForegroundColor Yellow
        return
    }
    foreach ($p in $existing) {
        Stop-Process -Id $p.ProcessId -Force
        Write-Host "[worker] stopped PID $($p.ProcessId)" -ForegroundColor Green
    }
}

function Show-Status {
    $existing = Get-WorkerProcess
    if ($existing) {
        foreach ($p in $existing) {
            Write-Host "[worker] running - PID $($p.ProcessId) - started $($p.CreationDate)" -ForegroundColor Green
        }
    } else {
        Write-Host "[worker] stopped" -ForegroundColor Yellow
    }
    if (Test-Path $logFile) {
        $size = (Get-Item $logFile).Length
        Write-Host "[worker] log: $logFile ($size bytes)"
    }
}

function Show-Log {
    if (-not (Test-Path $logFile)) {
        Write-Host "[worker] no log file yet at $logFile - run 'start' first" -ForegroundColor Yellow
        return
    }
    Write-Host "[worker] tailing $logFile  (Ctrl+C to exit)" -ForegroundColor Cyan
    Get-Content $logFile -Tail 30 -Wait
}

function Clear-PyCache {
    # Wipe all __pycache__ dirs in the repo. Defends against the case where the
    # worker, restarted across multiple consecutive edits to the same module,
    # imports stale bytecode (we hit this with strategy_params.py producing
    # "Unknown strategy"). Running processes are unaffected — Python regenerates
    # .pyc on next import, never imports the directory directly.
    $count = 0
    Get-ChildItem -Path $repoRoot -Recurse -Filter "__pycache__" -Directory -ErrorAction SilentlyContinue |
        ForEach-Object {
            try {
                Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction Stop
                $count++
            } catch {
                # Another Python process may hold a .pyc handle — skip silently.
            }
        }
    if ($count -gt 0) {
        Write-Host "[worker] cleared $count __pycache__ dirs" -ForegroundColor DarkGray
    }
}


switch ($Action) {
    "start"   { Start-Worker }
    "stop"    { Stop-Worker }
    "restart" { Stop-Worker; Clear-PyCache; Start-Sleep -Seconds 1; Start-Worker }
    "status"  { Show-Status }
    "log"     { Show-Log }
}
