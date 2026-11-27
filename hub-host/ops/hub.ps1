# One entry point for running the Hub.
#   pwsh ops\hub.ps1 up | down | restart | status | logs [service] | pull | config
param([Parameter(Position = 0)][ValidateSet('up', 'down', 'restart', 'status', 'logs', 'pull', 'config')][string]$Action = 'status',
      [Parameter(Position = 1)][string]$Service)
. "$PSScriptRoot\common.ps1"
if (-not (Wait-Docker 120)) { throw 'Docker engine is not running. Start Docker Desktop first.' }
switch ($Action) {
  'up'      { Invoke-Compose up -d --wait; Invoke-Compose ps }
  'down'    { Invoke-Compose down }          # keeps the data volumes; never add -v here
  'restart' { Invoke-Compose up -d --wait --force-recreate; Invoke-Compose ps }
  'status'  { Invoke-Compose ps -a }
  'logs'    { if ($Service) { Invoke-Compose logs --tail 200 $Service } else { Invoke-Compose logs --tail 80 } }
  'pull'    { Invoke-Compose pull }
  'config'  { Invoke-Compose config --quiet; 'compose config OK' }
}
