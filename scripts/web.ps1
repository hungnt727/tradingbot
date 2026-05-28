<#
.SYNOPSIS
    Manage the Phase 6 web app (uvicorn) - start / stop / restart / status / log.

.DESCRIPTION
    Wraps `python -m uvicorn web.app:app --host 127.0.0.1 --port 8000 --reload`
    as a hidden-window background process with stdout / stderr captured to
    logs/web.log + logs/web.err.log. Idempotent: starting when already running
    warns; stopping when not running warns.

    Detection is doubled (CommandLine match OR PID listening on port 8000) to
    catch both the uvicorn master and the --reload child subprocess.

    Python lookup order: venv\Scripts\python.exe ->
    %LOCALAPPDATA%\Programs\Python\Python313\python.exe -> PATH.
    Env vars (APP_DATABASE_URL, DATABASE_URL, REDIS_URL, TELEGRAM_BOT_TOKEN, ...)
    are loaded by app_db.session via python-dotenv from .env in the repo root.

.EXAMPLE
    .\scripts\web.ps1 start
    .\scripts\web.ps1 status
    .\scripts\web.ps1 log
    .\scripts\web.ps1 stop
    .\scripts\web.ps1 restart

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
$logFile  = Join-Path $logDir   "web.log"
$errFile  = Join-Path $logDir   "web.err.log"
$BindHost = "127.0.0.1"
$BindPort = 8000


function Get-WebProcess {
    # CommandLine match (catches the uvicorn master process).
    $byCmd = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -in @("python.exe", "pythonw.exe") -and
            $_.CommandLine -and
            ($_.CommandLine -like "*uvicorn*web.app*" -or
             $_.CommandLine -like "*-m*uvicorn*web*")
        }
    # Port-listen match (catches the --reload child whose CommandLine may be restricted).
    $byPort = Get-NetTCPConnection -State Listen -LocalPort $BindPort -ErrorAction SilentlyContinue |
        ForEach-Object {
            Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" -ErrorAction SilentlyContinue
        }
    @($byCmd) + @($byPort) | Where-Object { $_ } | Sort-Object ProcessId -Unique
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

function Start-Web {
    $existing = Get-WebProcess
    if ($existing) {
        $first = $existing | Select-Object -First 1
        Write-Host "[web] already running - PID $($first.ProcessId) since $($first.CreationDate)" -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
    $py = Find-Python
    $proc = Start-Process `
        -FilePath $py `
        -ArgumentList "-m", "uvicorn", "web.app:app", "--host", $BindHost, "--port", "$BindPort", "--reload" `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError  $errFile `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Seconds 2  # uvicorn takes ~1-2s to bind the port
    if ($proc.HasExited) {
        Write-Host "[web] FAILED to start (exit $($proc.ExitCode)). Tail of $errFile :" -ForegroundColor Red
        if (Test-Path $errFile) { Get-Content $errFile -Tail 20 | ForEach-Object { "  $_" } }
        exit 1
    }
    $bound = Get-NetTCPConnection -State Listen -LocalPort $BindPort -ErrorAction SilentlyContinue
    if (-not $bound) {
        Write-Host "[web] process up but port $BindPort not bound yet - check $errFile if it doesn't appear in a few seconds" -ForegroundColor Yellow
    }
    Write-Host "[web] started - PID $($proc.Id) - http://${BindHost}:${BindPort} - log $logFile" -ForegroundColor Green
}

function Stop-Web {
    $existing = Get-WebProcess
    if (-not $existing) {
        Write-Host "[web] not running - nothing to stop" -ForegroundColor Yellow
        return
    }
    foreach ($p in $existing) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Host "[web] stopped PID $($p.ProcessId)" -ForegroundColor Green
        } catch {
            # Child process may have already died when we killed the parent - fine.
            Write-Host "[web] PID $($p.ProcessId) already gone" -ForegroundColor DarkGray
        }
    }
}

function Show-Status {
    $existing = Get-WebProcess
    if ($existing) {
        foreach ($p in $existing) {
            Write-Host "[web] running - PID $($p.ProcessId) - started $($p.CreationDate)" -ForegroundColor Green
        }
        $bound = Get-NetTCPConnection -State Listen -LocalPort $BindPort -ErrorAction SilentlyContinue
        if ($bound) {
            Write-Host "[web] listening on http://${BindHost}:${BindPort}"
        } else {
            Write-Host "[web] WARNING: process up but port $BindPort not listening" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[web] stopped" -ForegroundColor Yellow
    }
    if (Test-Path $logFile) {
        $size = (Get-Item $logFile).Length
        Write-Host "[web] log: $logFile ($size bytes)"
    }
}

function Show-Log {
    if (-not (Test-Path $logFile)) {
        Write-Host "[web] no log file yet at $logFile - run 'start' first" -ForegroundColor Yellow
        return
    }
    Write-Host "[web] tailing $logFile  (Ctrl+C to exit)" -ForegroundColor Cyan
    Get-Content $logFile -Tail 30 -Wait
}

function Clear-PyCache {
    # Wipe all __pycache__ dirs so the next process import starts from source.
    # Running processes are unaffected — Python regenerates .pyc on import.
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
        Write-Host "[web] cleared $count __pycache__ dirs" -ForegroundColor DarkGray
    }
}


switch ($Action) {
    "start"   { Start-Web }
    "stop"    { Stop-Web }
    "restart" { Stop-Web; Clear-PyCache; Start-Sleep -Seconds 1; Start-Web }
    "status"  { Show-Status }
    "log"     { Show-Log }
}
