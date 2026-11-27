# SkillHub alerts: Windows toast on this PC + Feishu (Lark) group bot.
#   pwsh ops\notify.ps1 -Test                         send a test message to every configured channel
#   pwsh ops\notify.ps1 -Title <t> -Body <b>          send one message
#   pwsh ops\notify.ps1 -Health ok|problem -Detail <problems>
#        called by health.ps1; sends only when the state changes (ok -> problem, problem -> ok),
#        when the set of problems changes, or every $RepeatHours while a problem persists.
# Feishu settings live in notify.env next to .env.release (NOT in git, NOT in backups):
#   FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx
#   FEISHU_SECRET=xxxx        (only if the bot has "signature verification" turned on)
# If the bot uses "custom keywords", add the keyword SkillHub.
param([string]$Title = 'SkillHub', [string]$Body = '', [switch]$Test,
      [ValidateSet('ok', 'problem')][string]$Health, [string]$Detail = '')
. "$PSScriptRoot\common.ps1"
$RepeatHours = 6
$StateFile = Join-Path $LogDir 'notify-state.json'
$NotifyEnv = Join-Path $HubDir 'notify.env'

function Get-NotifyValue([string]$Key) {
  if (-not (Test-Path $NotifyEnv)) { return $null }
  $line = Get-Content $NotifyEnv -Encoding utf8 | Where-Object { $_ -match "^\s*$Key\s*=" } | Select-Object -Last 1
  if ($line) { ($line -replace "^\s*$Key\s*=\s*", '').Trim().Trim('"') }
}

function Send-Toast([string]$T, [string]$B) {
  # Windows PowerShell 5.1 can load the WinRT toast API; pwsh 7 cannot. Pass the script as UTF-16 base64.
  $esc = { param($s) ([Security.SecurityElement]::Escape($s)) -replace "'", "''" }
  $xml = "<toast><visual><binding template='ToastGeneric'><text>$(& $esc $T)</text><text>$(& $esc $B)</text></binding></visual></toast>"
  $script = @"
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
`$x = New-Object Windows.Data.Xml.Dom.XmlDocument
`$x.LoadXml('$($xml -replace "'", "''")')
`$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier(`$app).Show([Windows.UI.Notifications.ToastNotification]::new(`$x))
"@
  $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
  $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  & $ps -NoProfile -NonInteractive -EncodedCommand $enc 2>&1 | Out-Null
  if ($LASTEXITCODE) { throw "toast failed ($LASTEXITCODE)" }
}

function Send-Feishu([string]$T, [string]$B) {
  $hook = Get-NotifyValue 'FEISHU_WEBHOOK'
  if (-not $hook) { return 'skipped (no FEISHU_WEBHOOK in notify.env)' }
  $msg = @{ msg_type = 'text'; content = @{ text = "[SkillHub] $T`n$B" } }
  $secret = Get-NotifyValue 'FEISHU_SECRET'
  if ($secret) {
    $ts = [string][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $h = [Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes("$ts`n$secret"))
    $msg.timestamp = $ts; $msg.sign = [Convert]::ToBase64String($h.ComputeHash([byte[]]@()))
  }
  $json = $msg | ConvertTo-Json -Depth 4 -Compress
  $r = Invoke-RestMethod -Method Post -Uri $hook -ContentType 'application/json; charset=utf-8' `
         -Body ([Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec 15
  $code = if ($null -ne $r.code) { $r.code } else { $r.StatusCode }
  if ($code -ne 0) { throw "feishu returned code=$code msg=$($r.msg)" }
  'ok'
}

function Send-All([string]$T, [string]$B) {
  $res = @()
  try { Send-Toast $T $B; $res += 'toast=ok' } catch { $res += "toast=FAILED $($_.Exception.Message)" }
  try { $res += "feishu=$(Send-Feishu $T $B)" } catch { $res += "feishu=FAILED $($_.Exception.Message)" }
  Write-HubLog 'notify.log' "$T | $($res -join '; ')"
  $res -join '; '
}

$where = "$env:COMPUTERNAME $(Get-Date -Format 'yyyy-MM-dd HH:mm') (host time)"
if ($Test) { Send-All 'notification test' "If you can read this, SkillHub alerts reach you. $where"; return }
if (-not $Health) { Send-All $Title $Body; return }

# state machine for health.ps1
$state = if (Test-Path $StateFile) { Get-Content $StateFile -Raw | ConvertFrom-Json } else { [pscustomobject]@{ status = 'ok'; since = (Get-Date).ToString('o'); detail = ''; lastSent = $null } }
$now = Get-Date
if ($Health -eq 'problem') {
  $changed = $state.status -ne 'problem' -or $state.detail -ne $Detail
  $stale = -not $state.lastSent -or ($now - [datetime]$state.lastSent).TotalHours -ge $RepeatHours
  if ($state.status -ne 'problem') { $state.since = $now.ToString('o') }
  if ($changed -or $stale) {
    $mins = [int]($now - [datetime]$state.since).TotalMinutes
    Send-All 'Hub PROBLEM' "$Detail`nfor $mins min. Run: pwsh ops\health.ps1 ; see RUNBOOK section 8. $where" | Out-Null
    $state.lastSent = $now.ToString('o')
  }
  $state.status = 'problem'; $state.detail = $Detail
} else {
  if ($state.status -eq 'problem') {
    $mins = [int]($now - [datetime]$state.since).TotalMinutes
    Send-All 'Hub recovered' "Healthy again after about $mins min. Last problem: $($state.detail). $where" | Out-Null
    $state.since = $now.ToString('o'); $state.lastSent = $now.ToString('o')
  }
  $state.status = 'ok'; $state.detail = ''
}
$state | ConvertTo-Json | Out-File $StateFile -Encoding utf8
