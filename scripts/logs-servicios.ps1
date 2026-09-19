# Logs de todo lo que NO es Pulsar: microservicios + Postgres.
# Uso:  powershell -ExecutionPolicy Bypass -File .\scripts\logs-servicios.ps1
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$pulsar = @("zookeeper", "pulsar-init", "bookie", "broker")
$running = @(docker compose ps --services --status running)
if (-not $running) {
    Write-Host "No hay servicios corriendo. Levanta el stack con: docker compose up -d" -ForegroundColor Yellow
    exit 1
}

$otros = @($running | Where-Object { $pulsar -notcontains $_ })
if (-not $otros) {
    Write-Host "Solo esta Pulsar. No hay microservicios ni bases en marcha." -ForegroundColor Yellow
    exit 1
}

Write-Host "=== Servicios (sin Pulsar): $($otros -join ', ') - Ctrl+C para salir ===" -ForegroundColor Cyan
docker compose logs -f --timestamps --tail=80 @otros
