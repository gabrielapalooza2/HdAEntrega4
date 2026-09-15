# Logs del cluster Apache Pulsar (ZooKeeper + Bookie + Broker).
# Uso:  powershell -ExecutionPolicy Bypass -File .\scripts\logs-pulsar.ps1
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

Write-Host "=== Pulsar (zookeeper, bookie, broker) - Ctrl+C para salir ===" -ForegroundColor Cyan
docker compose logs -f --timestamps --tail=80 zookeeper bookie broker
