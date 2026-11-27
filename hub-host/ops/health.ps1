# Health check. Writes one line to logs\health.log; problems also go to logs\health-alerts.log.
# Problems and recoveries are pushed by ops\notify.ps1 (Windows toast + Feishu).
# Exit code 0 = healthy, 1 = problem.   pwsh ops\health.ps1 [-Quiet]
param([switch]$Quiet)
. "$PSScriptRoot\common.ps1"
$problems = @()
$facts = @()
# Docker Desktop sometimes fails to start at logon (2026-11-26: Hub down ~7 h). Start it ourselves.
if (-not (Wait-Docker 20)) {
  $dd = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
  if (Test-Path $dd) {
    Start-Process $dd; Write-HubLog 'health.log' 'docker engine down; started Docker Desktop'
    $facts += 'docker_desktop_started=1'
    if (Wait-Docker 240) { try { Invoke-Compose up -d --wait *> $null } catch { $problems += "compose up after docker start failed: $($_.Exception.Message)" } }
  }
}
if (-not (Wait-Docker 10)) { $problems += 'docker engine not running' }
else {
  $want = 'skillhub-web-1', 'skillhub-server-1', 'skillhub-postgres-1', 'skillhub-redis-1', 'skillhub-skill-scanner-1'
  foreach ($n in $want) {
    $s = & $Docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $n 2>$null
    if ($s -ne 'running/healthy') { $problems += "$n is $(if ($s) { $s } else { 'missing' })" }
  }
  $base = Get-EnvValue 'SKILLHUB_PUBLIC_BASE_URL'
  foreach ($u in @('http://localhost:8088', $base) | Select-Object -Unique) {
    try { $c = (Invoke-WebRequest $u -NoProxy -TimeoutSec 10 -UseBasicParsing).StatusCode; if ($c -ne 200) { $problems += "$u returned $c" } }
    catch { $problems += "$u unreachable: $($_.Exception.Message)" }
  }
  try {
    $h = Invoke-RestMethod 'http://localhost:8088/api/cli/v1/skills/search?q=&limit=1' -NoProxy -TimeoutSec 10
    if ($h.code -ne 0) { $problems += "search api code $($h.code)" }
  } catch { $problems += "search api failed: $($_.Exception.Message)" }
  # versions waiting for review / stuck in scan (informational; >1h scanning is a problem)
  $q = "select count(*) filter (where status='PENDING_REVIEW'), count(*) filter (where status='SCANNING' and created_at < now() - interval '1 hour'), count(*) filter (where status='SCAN_FAILED') from skill_version"
  $r = (& $Docker exec skillhub-postgres-1 psql -U skillhub -d skillhub -At -F ',' -c $q 2>$null) -split ','
  # self-registration is open: report new accounts, new namespaces and any version published
  # outside global/blacklake (each new item is alerted once, then remembered)
  $known = Join-Path $LogDir 'known-accounts.txt'
  $q2 = "select 'user:'||id||' '||coalesce(display_name,'')||' '||coalesce(email,'') from user_account where not system_account union all " +
        "select 'ns:'||slug||' '||type||' by '||coalesce(created_by,'') from namespace union all " +
        "select 'ver:'||n.slug||'/'||s.slug||'@'||v.version||' '||v.status from skill_version v join skill s on s.id=v.skill_id join namespace n on n.id=s.namespace_id " +
        "where n.slug not in ('global','blacklake') and v.status in ('PUBLISHED','PENDING_REVIEW')"
  $now = @(& $Docker exec skillhub-postgres-1 psql -U skillhub -d skillhub -At -c $q2 2>$null)
  if ($LASTEXITCODE -eq 0) {
    $key = { param($l) ($l -split ' ')[0] }
    if (-not (Test-Path $known)) {
      $now | Out-File $known -Encoding utf8; $facts += "accounts_baseline=$($now.Count)"
    } else {
      $seen = @{}; foreach ($l in Get-Content $known) { $seen[(& $key $l)] = 1 }
      $new = @($now | Where-Object { -not $seen.ContainsKey((& $key $_)) })
      if ($new) {
        $problems += "new since last check: $($new -join '; ')"
        $new | Out-File $known -Append -Encoding utf8
      }
    }
  }
  if ($r.Count -eq 3) {
    $facts += "pending_review=$($r[0])"
    if ([int]$r[1] -gt 0) { $problems += "$($r[1]) version(s) scanning for over 1 hour" }
    if ([int]$r[2] -gt 0) { $problems += "$($r[2]) version(s) SCAN_FAILED" }
  }
}
# the LAN address must still belong to this machine (hotspot DHCP may hand out a new one)
$base = Get-EnvValue 'SKILLHUB_PUBLIC_BASE_URL'
$hostPart = ([uri]$base).Host
if ($hostPart -match '^\d+\.\d+\.\d+\.\d+$' -and -not (Get-NetIPAddress -IPAddress $hostPart -ErrorAction SilentlyContinue)) {
  $problems += "public address $hostPart is no longer on this machine; update SKILLHUB_PUBLIC_BASE_URL (see RUNBOOK)"
}
# backups
$last = Get-ChildItem $BackupDir -Directory -ErrorAction SilentlyContinue | Where-Object Name -notmatch 'FAILED' | Sort-Object Name -Descending | Select-Object -First 1
if (-not $last) { $problems += 'no backup yet' }
else {
  $age = (Get-Date) - [datetime]::ParseExact($last.Name, 'yyyyMMdd-HHmmss', $null)
  $facts += "last_backup=$($last.Name)"
  if ($age.TotalHours -gt 36) { $problems += "last backup is $([int]$age.TotalHours) hours old" }
}
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 1); $facts += "c_free_gb=$free"
if ($free -lt 20) { $problems += "C: has only $free GB free" }

if ($problems) {
  $line = "PROBLEM $($problems -join '; ') | $($facts -join ' ')"
  Write-HubLog 'health.log' $line; Write-HubLog 'health-alerts.log' $line
  try { & "$PSScriptRoot\notify.ps1" -Health problem -Detail ($problems -join '; ') } catch { Write-HubLog 'notify.log' "notify failed: $($_.Exception.Message)" }
  if (-not $Quiet) { $line }
  exit 1
}
Write-HubLog 'health.log' "ok $($facts -join ' ')"
try { & "$PSScriptRoot\notify.ps1" -Health ok } catch { Write-HubLog 'notify.log' "notify failed: $($_.Exception.Message)" }
if (-not $Quiet) { "ok $($facts -join ' ')" }
