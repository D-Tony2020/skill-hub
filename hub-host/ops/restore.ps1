# Restore a backup.
#   Drill (default, safe): restores into a separate throwaway stack on ports 28088/28080/25432/26379,
#                          checks login page, search and a download, then deletes the drill stack.
#     pwsh ops\restore.ps1 -Backup backups\<stamp>
#   Production (destructive: replaces the live data):
#     pwsh ops\restore.ps1 -Backup backups\<stamp> -Production -IUnderstandThisReplacesLiveData
param([Parameter(Mandatory)][string]$Backup, [switch]$Production, [switch]$IUnderstandThisReplacesLiveData, [switch]$KeepDrill)
. "$PSScriptRoot\common.ps1"
$src = (Resolve-Path $Backup).Path
foreach ($f in 'db.dump', 'storage.tgz', '.env.release') { if (-not (Test-Path (Join-Path $src $f))) { throw "backup is missing $f" } }
# integrity
foreach ($line in Get-Content (Join-Path $src 'SHA256SUMS')) {
  $h, $rel = $line -split '  ', 2
  if ((Get-FileHash (Join-Path $src $rel) -Algorithm SHA256).Hash.ToLower() -ne $h) { throw "checksum mismatch: $rel" }
}
if (-not (Wait-Docker 120)) { throw 'Docker engine is not running' }

if ($Production) {
  if (-not $IUnderstandThisReplacesLiveData) { throw 'add -IUnderstandThisReplacesLiveData to replace the live data' }
  $project = 'skillhub'; $envFile = $EnvFile; $files = @('-f', (Join-Path $HubDir 'compose.release.yml'), '-f', (Join-Path $HubDir 'compose.local.yml'))
  & "$PSScriptRoot\backup.ps1"   # safety copy of the current state first
} else {
  $project = 'skillhub-drill'
  $work = Join-Path $env:TEMP "skillhub-drill-$(Get-Random)"; New-Item -ItemType Directory $work | Out-Null
  $t = [IO.File]::ReadAllText((Join-Path $src '.env.release'))
  $over = @{ WEB_PORT = '127.0.0.1:28088'; API_PORT = '127.0.0.1:28080'; POSTGRES_PORT = '25432'; REDIS_PORT = '26379'; SKILLHUB_PUBLIC_BASE_URL = 'http://localhost:28088' }
  foreach ($k in $over.Keys) { $v = $over[$k]; $t = [regex]::Replace($t, "(?m)^$k=.*$", { param($m) "$k=$v" }) }
  $envFile = Join-Path $work '.env'; [IO.File]::WriteAllText($envFile, $t)
  $files = @('-f', (Join-Path $src 'compose.release.yml'))
}
$c = @('compose', '-p', $project, '--env-file', $envFile) + $files
function C { & $Docker @c @args; if ($LASTEXITCODE) { throw "compose $($args -join ' ') failed" } }
$user = 'skillhub'; $db = 'skillhub'
try {
  if ($Production) { C stop web server }
  C up -d postgres redis --wait
  # copy the dump in (piping binary data through PowerShell corrupts it), then restore from the file
  & $Docker cp (Join-Path $src 'db.dump') "${project}-postgres-1:/tmp/db.dump"
  if ($LASTEXITCODE) { throw 'docker cp of db.dump failed' }
  $out = & $Docker exec "$project-postgres-1" pg_restore -U $user -d $db --clean --if-exists --no-owner /tmp/db.dump 2>&1
  $rc = $LASTEXITCODE
  & $Docker exec "$project-postgres-1" rm -f /tmp/db.dump
  $nsCount = & $Docker exec "$project-postgres-1" psql -U $user -d $db -At -c 'select count(*) from namespace'
  if (-not ($nsCount -as [int])) { throw "pg_restore did not restore data (exit $rc): $($out | Select-Object -Last 5)" }
  if ($rc) { Write-HubLog 'restore.log' "pg_restore warnings (exit $rc): $(($out | Select-Object -Last 3) -join ' | ')" }
  & $Docker run --rm --network none -v "${project}_skillhub_storage:/data" -v "${src}:/in:ro" (Get-EnvValue 'POSTGRES_IMAGE') sh -c 'rm -rf /data/* /data/.[!.]* 2>/dev/null; tar -C /data -xzf /in/storage.tgz'
  if ($LASTEXITCODE) { throw 'storage restore failed' }
  C up -d --wait
  $base = if ($Production) { 'http://localhost:8088' } else { 'http://localhost:28088' }
  $page = (Invoke-WebRequest $base -NoProxy -TimeoutSec 30).StatusCode
  $hit = Invoke-RestMethod "$base/api/cli/v1/skills/search?q=&limit=50" -NoProxy
  $item = @($hit.data.items) | Where-Object { $_.namespace -ne 'global' } | Select-Object -First 1
  if (-not $item) { $item = @($hit.data.items)[0] }
  # download through the official CLI (anonymous, isolated HOME so no token is used or written)
  $cliHome = Join-Path $env:TEMP "drill-cli-$(Get-Random)"; New-Item -ItemType Directory $cliHome | Out-Null
  $oldHome = $env:HOME; $env:HOME = $cliHome
  try {
    $cli = (Get-Command skillhub -ErrorAction Stop).Source
    & $cli install "@$($item.namespace)/$($item.slug)" --dir (Join-Path $cliHome 'inst') --registry $base *> $null
    if ($LASTEXITCODE) { throw "skillhub install from the restored stack failed ($LASTEXITCODE)" }
    $md = Get-Content (Join-Path $cliHome "inst\$($item.slug)\.skillhub\metadata.json") -Raw | ConvertFrom-Json
  } finally { $env:HOME = $oldHome; Remove-Item $cliHome -Recurse -Force -ErrorAction SilentlyContinue }
  $msg = "restore ok project=$project from=$(Split-Path $src -Leaf) page=$page skills=$(@($hit.data.items).Count) installed=$($md.namespace)/$($md.slug)@$($md.version)"
  Write-HubLog 'restore.log' $msg; $msg
} catch {
  Write-HubLog 'restore.log' "FAILED project=$project $($_.Exception.Message)"; throw
} finally {
  if (-not $Production -and -not $KeepDrill) {
    & $Docker @c down -v *> $null
    & $Docker volume rm "${project}_skillhub_storage" *> $null   # created by the restore step before compose
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
  }
}
