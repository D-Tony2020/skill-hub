# One-shot HTTP file server (no admin rights needed): serves -Path at /<Token> once, then exits.
param([Parameter(Mandatory=$true)][string]$Path, [int]$Port = 8765, [Parameter(Mandatory=$true)][string]$Token)
$ErrorActionPreference = "Stop"
$bytes = [System.IO.File]::ReadAllBytes($Path)
$listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $Port)
$listener.Start()
Write-Host "[bag] listening on port $Port"
try {
  while ($true) {
    $client = $listener.AcceptTcpClient()
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $line = $reader.ReadLine()
    while ($true) { $h = $reader.ReadLine(); if ($h -eq $null -or $h -eq "") { break } }
    if ($line -match "^GET /$Token ") {
      $hdr = "HTTP/1.0 200 OK`r`nContent-Type: text/x-shellscript`r`nContent-Length: $($bytes.Length)`r`nConnection: close`r`n`r`n"
      $hb = [System.Text.Encoding]::ASCII.GetBytes($hdr)
      $stream.Write($hb, 0, $hb.Length); $stream.Write($bytes, 0, $bytes.Length); $stream.Flush()
      Write-Host "[bag] served to $($client.Client.RemoteEndPoint)"
      $client.Close()
      break
    } else {
      $nf = [System.Text.Encoding]::ASCII.GetBytes("HTTP/1.0 404 Not Found`r`nContent-Length: 0`r`n`r`n")
      $stream.Write($nf, 0, $nf.Length); $client.Close()
    }
  }
} finally { $listener.Stop() }
