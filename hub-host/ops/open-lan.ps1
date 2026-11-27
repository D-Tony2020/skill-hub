# Run elevated. Marks the CURRENT Wi-Fi network as Private and allows inbound TCP 8088
# (SkillHub web) on Private networks only. Public networks stay closed.
param([string]$NetworkName)
$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot '..\logs\open-lan.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
try {
  if ($NetworkName) { Set-NetConnectionProfile -Name $NetworkName -NetworkCategory Private }
  $name = 'SkillHub web (TCP 8088, private networks)'
  Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
  New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8088 -Profile Private | Out-Null
  "$(Get-Date -Format o) ok network=$NetworkName rule=$name" | Out-File $log -Append -Encoding utf8
} catch {
  "$(Get-Date -Format o) FAILED $($_.Exception.Message)" | Out-File $log -Append -Encoding utf8
  exit 1
}
