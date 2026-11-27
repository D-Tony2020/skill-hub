# Shared settings for the SkillHub ops scripts. Dot-source it: . "$PSScriptRoot\common.ps1"
$ErrorActionPreference = 'Stop'
$HubDir     = Split-Path $PSScriptRoot -Parent
$EnvFile    = Join-Path $HubDir '.env.release'
$Docker     = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
$ComposeArgs = @('compose', '--project-directory', $HubDir, '-p', 'skillhub', '--env-file', $EnvFile,
                 '-f', (Join-Path $HubDir 'compose.release.yml'), '-f', (Join-Path $HubDir 'compose.local.yml'))
$BackupDir  = Join-Path $HubDir 'backups'
$LogDir     = Join-Path $HubDir 'logs'
$KeepBackups = 14
New-Item -ItemType Directory -Force $BackupDir, $LogDir | Out-Null

function Write-HubLog([string]$File, [string]$Text) {
  "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Text" | Out-File (Join-Path $LogDir $File) -Append -Encoding utf8
}
function Invoke-Compose { & $Docker @ComposeArgs @args; if ($LASTEXITCODE) { throw "docker compose $($args -join ' ') failed ($LASTEXITCODE)" } }
function Get-EnvValue([string]$Key) {
  $line = Get-Content $EnvFile | Where-Object { $_ -match "^$Key=" } | Select-Object -Last 1
  if ($line) { $line.Substring($Key.Length + 1) }
}
function Wait-Docker([int]$Seconds = 180) {
  $t = [Diagnostics.Stopwatch]::StartNew()
  while ($t.Elapsed.TotalSeconds -lt $Seconds) {
    & $Docker info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -eq 0) { return $true }
    Start-Sleep 5
  }
  $false
}
