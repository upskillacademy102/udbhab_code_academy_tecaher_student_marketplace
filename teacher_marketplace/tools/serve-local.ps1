<#
    serve-local.ps1 - bring up the whole app (API + server-rendered frontend) on this machine.

    One Django process serves both the DRF API and the Django-template frontend
    (apps/web), so "backend + frontend" is a single runserver. This script also
    starts the local PostgreSQL 17 + PostGIS cluster the app needs.

    Local stack (installed outside the repo so OneDrive doesn't sync it):
      PostgreSQL + PostGIS binaries : C:\Users\USER\tm-stack\pg\pgsql
      PostgreSQL data directory     : C:\Users\USER\tm-stack\pgdata
      Python virtualenv             : C:\Users\USER\tm-stack\venv

    Usage:
      ./tools/serve-local.ps1              # start Postgres (if needed) + runserver
      ./tools/serve-local.ps1 -StopDb      # stop the Postgres cluster and exit
#>
param(
    [int]$Port = 8000,
    [switch]$StopDb
)

$ErrorActionPreference = "Stop"
$Stack   = "C:\Users\USER\tm-stack"
$PgBin   = Join-Path $Stack "pg\pgsql\bin"
$PgData  = Join-Path $Stack "pgdata"
$Venv    = Join-Path $Stack "venv\Scripts\python.exe"
$Root    = Split-Path $PSScriptRoot -Parent

function Test-PgUp {
    & "$PgBin\pg_isready.exe" -h 127.0.0.1 -p 5432 -q
    return ($LASTEXITCODE -eq 0)
}

if ($StopDb) {
    & "$PgBin\pg_ctl.exe" -D $PgData stop -m fast
    return
}

if (Test-PgUp) {
    Write-Host "PostgreSQL already accepting connections on :5432" -ForegroundColor Green
} else {
    Write-Host "Starting PostgreSQL cluster..." -ForegroundColor Cyan
    & "$PgBin\pg_ctl.exe" -D $PgData -l (Join-Path $Stack "pg.log") -o "-p 5432" start
    Start-Sleep -Seconds 2
    if (-not (Test-PgUp)) { throw "PostgreSQL failed to start - see $Stack\pg.log" }
}

Set-Location $Root
Write-Host "Starting Django (API + frontend) on http://127.0.0.1:$Port/ ..." -ForegroundColor Cyan
Write-Host "  Swagger : http://127.0.0.1:$Port/api/docs/" -ForegroundColor DarkGray
Write-Host "  Admin   : http://127.0.0.1:$Port/admin/   (upskillacademy102@gmail.com / Admin@12345)" -ForegroundColor DarkGray
& $Venv manage.py runserver "127.0.0.1:$Port"
