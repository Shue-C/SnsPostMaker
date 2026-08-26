<#
  プリンターとの接続診断

  「印刷できない」ときに、どこで止まっているのかを切り分けます。
  ダブルクリックで使う場合は netcheck.bat を実行してください。

  例: netcheck.bat -Printer 192.168.10.100
#>

param(
  [string]$Printer = '',
  [int]$Port = 80,
  [string]$Path = '/cgi-bin/epos/service.cgi',
  # 実際に1ドットだけ紙送りして、印刷経路まで通っているか確かめる
  [switch]$NoPrintTest
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Head($t) {
  Write-Host ''
  Write-Host "--- $t " -ForegroundColor Cyan -NoNewline
  Write-Host ('-' * [Math]::Max(0, 56 - $t.Length)) -ForegroundColor Cyan
}
function OK($t)   { Write-Host "  [OK]   $t" -ForegroundColor Green }
function NG($t)   { Write-Host "  [NG]   $t" -ForegroundColor Red }
function Info($t) { Write-Host "         $t" -ForegroundColor DarkGray }

# --- 1. このPCのネットワーク設定 -----------------------------------------
Head 'このPCのIPアドレス'
$ips = @()
try {
  $ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
    Where-Object { $_.IPAddress -ne '127.0.0.1' })
  foreach ($ip in $ips) {
    $alias = $ip.InterfaceAlias
    $origin = $ip.PrefixOrigin   # Manual = 固定IP, Dhcp = 自動, WellKnown = 169.254 の自動付与
    Write-Host ("  {0,-28} {1}/{2}  ({3})" -f $alias, $ip.IPAddress, $ip.PrefixLength, $origin)
  }
} catch {
  Info 'IPアドレスを取得できませんでした（ipconfig で確認してください）'
}
if (@($ips | Where-Object { $_.PrefixOrigin -eq 'WellKnown' }).Count -gt 0) {
  Info '169.254.x.x は「自動取得に失敗した」印です。固定IPを振ってください。'
}

# --- プリンターIPが未指定なら、ここで聞く --------------------------------
if (-not $Printer) {
  Write-Host ''
  $Printer = Read-Host '  プリンターのIPアドレス（ステータスシートに印刷されています）'
  if (-not $Printer) { Write-Host '  中止しました。'; exit 1 }
}

# --- 2. 同じセグメントに居るか -------------------------------------------
Head "プリンター $Printer との位置関係"
$same = $false
foreach ($ip in $ips) {
  try {
    $mask = ([UInt32]::MaxValue) -shl (32 - $ip.PrefixLength)
    $toInt = {
      param($s)
      $b = ([System.Net.IPAddress]::Parse($s)).GetAddressBytes()
      [Array]::Reverse($b)
      [BitConverter]::ToUInt32($b, 0)
    }
    $a = & $toInt $ip.IPAddress
    $p = & $toInt $Printer
    if ((($a -band $mask) -eq ($p -band $mask))) {
      OK ("$($ip.InterfaceAlias) ($($ip.IPAddress)/$($ip.PrefixLength)) と同じセグメントです")
      $same = $true
    }
  } catch {}
}
if (-not $same) {
  NG 'このPCのどのアダプタとも別のセグメントです'
  Info 'プリンターと同じ第3オクテットまで揃った固定IPを、有線LANアダプタに振ってください。'
  Info "例: プリンターが $Printer なら、PC側は同じ並びの別番号 / 255.255.255.0"
}

# --- 3. ping -------------------------------------------------------------
Head 'ping'
$ping = $false
try { $ping = Test-Connection -ComputerName $Printer -Count 2 -Quiet -ErrorAction Stop } catch {}
if ($ping) { OK '応答あり' }
else {
  NG '応答なし'
  Info 'LANケーブルが刺さっているか、プリンターの電源が入っているか、'
  Info 'IPアドレスが合っているか（ステータスシートで再確認）をみてください。'
}

# --- 4. TCPポート --------------------------------------------------------
Head "TCP $Port"
$open = $false
try {
  $c = New-Object System.Net.Sockets.TcpClient
  $iar = $c.BeginConnect($Printer, $Port, $null, $null)
  $open = $iar.AsyncWaitHandle.WaitOne(3000, $false) -and $c.Connected
  $c.Close()
} catch {}
if ($open) { OK '開いています' }
else {
  NG '繋がりません'
  Info 'ePOS-Print サービスが無効になっている可能性があります。'
  Info "ブラウザで http://$Printer/ を開き、本体のWeb設定を確認してください。"
}

# --- 5. ePOS-Print に実際に投げてみる ------------------------------------
if (-not $NoPrintTest -and $open) {
  Head 'ePOS-Print への送信（1ドットだけ紙送りします）'
  $url = "http://${Printer}:$Port$Path" + '?devid=local_printer&timeout=10000'
  $xml = @'
<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>
<epos-print xmlns="http://www.epson-pos.com/schemas/2011/03/epos-print">
<feed unit="1"/>
</epos-print>
</s:Body></s:Envelope>
'@
  try {
    $res = Invoke-WebRequest -Uri $url -Method Post -Body $xml -TimeoutSec 15 `
      -ContentType 'text/xml; charset=utf-8' -Headers @{ 'SOAPAction' = '""' } -UseBasicParsing
    $body = $res.Content
    if ($body -match 'success="true"') {
      OK 'プリンターが success を返しました。アプリからも印刷できるはずです。'
    } else {
      $code = ''
      if ($body -match 'code="([^"]*)"') { $code = $Matches[1] }
      NG "プリンターがエラーを返しました（code=$code）"
      Info $body
    }
  } catch {
    NG ('送信に失敗しました: ' + $_.Exception.Message)
  }
}

Head 'まとめ'
Write-Host '  アプリ側の設定パネル（画面右上を1.5秒長押し）には'
Write-Host "    印刷方式        : xml"
Write-Host "    IPアドレス      : $Printer"
Write-Host "    XMLポート       : $Port"
Write-Host '  を入れてください。'
Write-Host ''
Read-Host '　Enter キーで終了'
