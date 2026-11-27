# Point the Hub at this machine's current Wi-Fi address (run after switching hotspot / network).
#   pwsh ops\set-address.ps1            # detect the Wi-Fi IPv4, update config, recreate, verify
#   pwsh ops\set-address.ps1 -Ip 1.2.3.4
# Updates: .env.release SKILLHUB_PUBLIC_BASE_URL, the address line in RUNBOOK.md and MEMBER_ACCOUNTS.txt.
# It never touches passwords and never changes Windows settings; if the network is "Public" it tells you
# to run ops\open-lan.ps1 elevated.
param([string]$Ip)
. "$PSScriptRoot\common.ps1"
if (-not $Ip) {
  # the physical adapter that carries the default route (skip proxy TUN "Meta" and WSL/Hyper-V adapters)
  $route = Get-NetRoute -DestinationPrefix 0.0.0.0/0 -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceAlias -notmatch 'Meta|vEthernet|WSL|Loopback' } | Sort-Object RouteMetric | Select-Object -First 1
  if (-not $route) { throw 'no physical network with a default route; connect to Wi-Fi first' }
  $Ip = (Get-NetIPAddress -InterfaceIndex $route.ifIndex -AddressFamily IPv4 | Where-Object PrefixOrigin -ne 'WellKnown' | Select-Object -First 1).IPAddress
  $alias = $route.InterfaceAlias
} else { $alias = (Get-NetIPAddress -IPAddress $Ip -ErrorAction Stop).InterfaceAlias }
if ($Ip -notmatch '^\d+\.\d+\.\d+\.\d+$') { throw "bad address: $Ip" }
$profile = Get-NetConnectionProfile -InterfaceAlias $alias -ErrorAction SilentlyContinue
$newUrl = "http://${Ip}:8088"
$oldUrl = Get-EnvValue 'SKILLHUB_PUBLIC_BASE_URL'
"network: $($profile.Name) ($($profile.NetworkCategory)) on $alias"
"address: $oldUrl -> $newUrl"
if ($profile.NetworkCategory -ne 'Private') {
  Write-Warning "this network is $($profile.NetworkCategory): other devices cannot reach 8088. Run elevated: pwsh ops\open-lan.ps1 -NetworkName '$($profile.Name)'"
}
$utf8 = [Text.UTF8Encoding]::new($false)
if ($oldUrl -ne $newUrl) {
  $t = [IO.File]::ReadAllText($EnvFile)
  $t = [regex]::Replace($t, '(?m)^SKILLHUB_PUBLIC_BASE_URL=.*$', { param($m) "SKILLHUB_PUBLIC_BASE_URL=$newUrl" })
  [IO.File]::WriteAllText($EnvFile, $t, $utf8)
  foreach ($f in 'RUNBOOK.md', 'MEMBER_ACCOUNTS.txt') {
    $p = Join-Path $HubDir $f
    if (Test-Path $p) { $x = [IO.File]::ReadAllText($p); if ($oldUrl -and $x.Contains($oldUrl)) { [IO.File]::WriteAllText($p, $x.Replace($oldUrl, $newUrl), $utf8); "updated $f" } }
  }
  if (-not (Wait-Docker 120)) { throw 'Docker engine is not running. Start Docker Desktop, then rerun.' }
  Invoke-Compose up -d --wait web server
}
$fail = @()
foreach ($u in 'http://localhost:8088', $newUrl) {
  try { $c = (Invoke-WebRequest $u -NoProxy -TimeoutSec 15 -UseBasicParsing).StatusCode } catch { $c = $_.Exception.Message }
  "$u -> $c"; if ($c -ne 200) { $fail += $u }
}
$cfg = (Invoke-WebRequest "$newUrl/runtime-config.js" -NoProxy -TimeoutSec 15 -UseBasicParsing).Content
if ($cfg -notmatch [regex]::Escape("appBaseUrl: `"$newUrl`"")) { $fail += 'runtime-config appBaseUrl' } else { 'web runtime config uses the new address' }
Write-HubLog 'address.log' "$oldUrl -> $newUrl network=$($profile.Name) category=$($profile.NetworkCategory) result=$(if ($fail) { 'FAILED ' + ($fail -join ',') } else { 'ok' })"
if ($fail) { throw "verification failed: $($fail -join ', ')" }
'done. Other devices: use the new address; CLI users run skillhub login --registry <new address> again.'
