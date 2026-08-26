<#
  omikuji 配信スクリプト（Windows / PowerShell だけで動きます。Python 不要）

  このフォルダ（omikuji）を、同じネットワークの iPad から見られるように
  HTTP で配信します。ダブルクリックで使う場合は serve.bat を実行してください。

  使い方:
    1. serve.bat をダブルクリック
    2. 「このアプリがデバイスに変更を…」に「はい」（管理者権限が必要）
    3. 表示された http://192.168.x.x:8080/ を iPad の Safari で開く
    4. 終了するときは、この黒い画面で Ctrl+C
#>

param(
  [int]$Port = 8080,
  [switch]$NoFirewall,
  # このPCのブラウザからしか開かない場合に指定する。
  # localhost だけで待ち受けるので、管理者権限もファイアウォール設定も要らない。
  [switch]$LocalOnly
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# --- 管理者権限がなければ昇格して起動し直す -----------------------------
# http://+:PORT/ で待ち受けるには管理者権限が必要（localhost だけなら不要だが、
# それでは iPad から見えない）。
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $LocalOnly -and -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host '管理者権限で起動し直します...' -ForegroundColor Yellow
  $psArgs = @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', "`"$PSCommandPath`"",
    '-Port', $Port
  )
  if ($NoFirewall) { $psArgs += '-NoFirewall' }
  Start-Process -FilePath 'powershell.exe' -ArgumentList $psArgs -Verb RunAs
  exit
}

$Root = Split-Path -Parent $PSCommandPath
if (-not (Test-Path (Join-Path $Root 'index.html'))) {
  Write-Host "index.html が見つかりません: $Root" -ForegroundColor Red
  Write-Host 'このスクリプトは omikuji フォルダの中に置いてください。'
  Read-Host '　Enter キーで終了'
  exit 1
}

# --- ファイアウォールの穴あけ（プライベートネットワークのみ） -------------
$ruleName = "Omikuji Kiosk HTTP $Port"
if (-not $NoFirewall -and -not $LocalOnly) {
  try {
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if (-not $existing) {
      New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $Port -Profile Private | Out-Null
      Write-Host "ファイアウォールを開けました（$ruleName）" -ForegroundColor DarkGray
    }
  } catch {
    Write-Host 'ファイアウォール設定をスキップしました（手動で許可が必要かもしれません）' -ForegroundColor Yellow
  }
}

# --- MIME タイプ ---------------------------------------------------------
$mime = @{
  '.html' = 'text/html; charset=utf-8'
  '.htm'  = 'text/html; charset=utf-8'
  '.css'  = 'text/css; charset=utf-8'
  '.js'   = 'application/javascript; charset=utf-8'
  '.json' = 'application/json; charset=utf-8'
  '.txt'  = 'text/plain; charset=utf-8'
  '.md'   = 'text/plain; charset=utf-8'
  '.svg'  = 'image/svg+xml'
  '.png'  = 'image/png'
  '.jpg'  = 'image/jpeg'
  '.jpeg' = 'image/jpeg'
  '.gif'  = 'image/gif'
  '.webp' = 'image/webp'
  '.ico'  = 'image/x-icon'
  '.woff' = 'font/woff'
  '.woff2'= 'font/woff2'
  '.ttf'  = 'font/ttf'
  '.otf'  = 'font/otf'
}

# --- 待ち受け開始 --------------------------------------------------------
$listener = New-Object System.Net.HttpListener
if ($LocalOnly) {
  # localhost 限定なら管理者権限は不要
  $listener.Prefixes.Add("http://localhost:$Port/")
} else {
  $listener.Prefixes.Add("http://+:$Port/")
}
try {
  $listener.Start()
} catch {
  Write-Host "ポート $Port を開けませんでした。" -ForegroundColor Red
  Write-Host '他のアプリが同じポートを使っている可能性があります。'
  Write-Host "別のポートで試す例:  powershell -ExecutionPolicy Bypass -File serve.ps1 -Port 8081"
  Read-Host '　Enter キーで終了'
  exit 1
}

# 自分の IPv4 アドレスを列挙（他の端末から開く URL を案内するため）
$addrs = @()
if (-not $LocalOnly) {
  try {
    $addrs = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
      Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.PrefixOrigin -ne 'WellKnown' } |
      Select-Object -ExpandProperty IPAddress)
  } catch {
    $addrs = @([System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
      Where-Object { $_.AddressFamily -eq 'InterNetwork' } |
      ForEach-Object { $_.IPAddressToString })
  }
}

Write-Host ''
Write-Host '============================================================'
Write-Host '  精霊魔法おみくじ  配信中' -ForegroundColor Cyan
Write-Host '============================================================'
Write-Host "  公開フォルダ : $Root"
Write-Host ''
if ($LocalOnly) {
  Write-Host '  このPCのブラウザで次を開いてください:'
  Write-Host "    http://localhost:$Port/" -ForegroundColor Green
  Write-Host '    （localhost 限定で待ち受けています。他の端末からは開けません）' -ForegroundColor DarkGray
} else {
  Write-Host '  iPad の Safari で次のどれかを開いてください:'
  foreach ($a in $addrs) {
    if ($a -like '192.168.137.*') {
      Write-Host "    http://${a}:$Port/    ← モバイルホットスポット" -ForegroundColor Green
    } else {
      Write-Host "    http://${a}:$Port/" -ForegroundColor Green
    }
  }
  if ($addrs.Count -eq 0) { Write-Host '    （IPアドレスを取得できませんでした）' -ForegroundColor Yellow }
}
Write-Host ''
Write-Host '  終了するには Ctrl+C'
Write-Host '============================================================'
Write-Host ''

try {
  while ($listener.IsListening) {
    $ctx = $listener.GetContext()
    $req = $ctx.Request
    $res = $ctx.Response
    try {
      # URL → ローカルパス
      $rel = [System.Uri]::UnescapeDataString($req.Url.AbsolutePath)
      if ($rel -eq '/' -or $rel -eq '') { $rel = '/index.html' }
      $rel = $rel.TrimStart('/').Replace('/', '\')
      $path = Join-Path $Root $rel

      # ディレクトリを抜け出す指定（..）を弾く
      $full = [System.IO.Path]::GetFullPath($path)
      $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
      if (-not $full.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
        $res.StatusCode = 403
        Write-Host "403 $rel" -ForegroundColor Red
        continue
      }

      if (Test-Path -LiteralPath $full -PathType Container) {
        $full = Join-Path $full 'index.html'
      }

      if (Test-Path -LiteralPath $full -PathType Leaf) {
        $ext = [System.IO.Path]::GetExtension($full).ToLower()
        $type = $mime[$ext]
        if (-not $type) { $type = 'application/octet-stream' }
        $bytes = [System.IO.File]::ReadAllBytes($full)
        $res.StatusCode = 200
        $res.ContentType = $type
        $res.ContentLength64 = $bytes.Length
        # 会場で差し替えたファイルが確実に反映されるようキャッシュさせない
        $res.AddHeader('Cache-Control', 'no-store')
        $res.OutputStream.Write($bytes, 0, $bytes.Length)
        Write-Host ("200 {0}  ({1:N0} bytes)" -f $rel, $bytes.Length) -ForegroundColor DarkGray
      } else {
        $body = [System.Text.Encoding]::UTF8.GetBytes('404 Not Found')
        $res.StatusCode = 404
        $res.ContentType = 'text/plain; charset=utf-8'
        $res.ContentLength64 = $body.Length
        $res.OutputStream.Write($body, 0, $body.Length)
        Write-Host "404 $rel" -ForegroundColor Yellow
      }
    } catch {
      Write-Host ("エラー: " + $_.Exception.Message) -ForegroundColor Red
    } finally {
      try { $res.Close() } catch {}
    }
  }
} finally {
  try { $listener.Stop(); $listener.Close() } catch {}
  Write-Host '配信を終了しました。'
}
