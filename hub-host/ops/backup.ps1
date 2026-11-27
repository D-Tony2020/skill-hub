# Daily backup: PostgreSQL dump + skill package storage volume + private config.
# Keeps the newest $KeepBackups folders in backups\. Safe to run while the Hub is up.
#   pwsh ops\backup.ps1
. "$PSScriptRoot\common.ps1"
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dest = Join-Path $BackupDir $stamp
try {
  if (-not (Wait-Docker 300)) { throw 'Docker engine is not running' }
  New-Item -ItemType Directory $dest | Out-Null
  $db = Get-EnvValue 'POSTGRES_DB'; if (-not $db) { $db = 'skillhub' }
  $user = Get-EnvValue 'POSTGRES_USER'; if (-not $user) { $user = 'skillhub' }

  # 1. database (custom format, restorable with pg_restore)
  $p = Start-Process $Docker -ArgumentList 'exec', 'skillhub-postgres-1', 'pg_dump', '-U', $user, '-Fc', $db `
         -RedirectStandardOutput (Join-Path $dest 'db.dump') -RedirectStandardError (Join-Path $dest 'pg_dump.err') -NoNewWindow -Wait -PassThru
  if ($p.ExitCode) { throw "pg_dump failed: $(Get-Content (Join-Path $dest 'pg_dump.err') -Raw)" }

  # 2. skill package storage (read-only mount, tar via the pinned postgres image already on disk)
  $img = Get-EnvValue 'POSTGRES_IMAGE'
  $p = Start-Process $Docker -ArgumentList 'run', '--rm', '--network', 'none', '-v', 'skillhub_skillhub_storage:/data:ro', '-v', "${dest}:/out",
         $img, 'tar', '-C', '/data', '-czf', '/out/storage.tgz', '.' -NoNewWindow -Wait -PassThru
  if ($p.ExitCode) { throw 'storage tar failed' }

  # 3. private config needed to restore (secrets: this folder stays on this machine)
  Copy-Item $EnvFile, (Join-Path $HubDir 'compose.release.yml'), (Join-Path $HubDir 'compose.local.yml') $dest
  Copy-Item (Join-Path $HubDir 'custom') (Join-Path $dest 'custom') -Recurse
  Remove-Item (Join-Path $dest 'pg_dump.err') -ErrorAction SilentlyContinue

  $dbSize = (Get-Item (Join-Path $dest 'db.dump')).Length
  if ($dbSize -lt 10KB) { throw "database dump looks too small ($dbSize bytes)" }
  $sums = @(Get-ChildItem $dest -Recurse -File) | Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  $($_.Path.Substring($dest.Length + 1))" }
  $sums | Out-File (Join-Path $dest 'SHA256SUMS') -Encoding utf8

  # retention
  Get-ChildItem $BackupDir -Directory | Sort-Object Name -Descending | Select-Object -Skip $KeepBackups | Remove-Item -Recurse -Force
  Write-HubLog 'backup.log' "ok $stamp db=$dbSize bytes storage=$((Get-Item (Join-Path $dest 'storage.tgz')).Length) bytes"
  "backup ok: $dest"
} catch {
  Write-HubLog 'backup.log' "FAILED $stamp $($_.Exception.Message)"
  if (Test-Path $dest) { Rename-Item $dest "$stamp-FAILED" -ErrorAction SilentlyContinue }
  throw
}
