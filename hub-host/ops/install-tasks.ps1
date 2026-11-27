# Registers the SkillHub scheduled tasks for the current user (no admin needed):
#   SkillHub-Backup  daily 03:00 (runs late if the PC was off)
#   SkillHub-Health  every 30 minutes, and 5 minutes after logon
# Remove with: pwsh ops\install-tasks.ps1 -Remove
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$pwsh = (Get-Command pwsh).Source
$ops = $PSScriptRoot
foreach ($n in 'SkillHub-Backup', 'SkillHub-Health') { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue }
if ($Remove) { 'removed'; return }
$set = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$pr = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$hidden = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File'
$a = New-ScheduledTaskAction -Execute $pwsh -Argument "$hidden `"$ops\backup.ps1`""
Register-ScheduledTask -TaskName 'SkillHub-Backup' -Description 'SkillHub daily backup (db + storage + config), keeps 14' -Action $a -Principal $pr -Settings $set `
  -Trigger (New-ScheduledTaskTrigger -Daily -At 3am) | Out-Null
$a = New-ScheduledTaskAction -Execute $pwsh -Argument "$hidden `"$ops\health.ps1`" -Quiet"
$t1 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 30)
$t2 = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"; $t2.Delay = 'PT5M'
Register-ScheduledTask -TaskName 'SkillHub-Health' -Description 'SkillHub health check every 30 min; see logs\health-alerts.log' -Action $a -Principal $pr -Settings $set `
  -Trigger $t1, $t2 | Out-Null
Get-ScheduledTask -TaskName 'SkillHub-*' | Select-Object TaskName, State
