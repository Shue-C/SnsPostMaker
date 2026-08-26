<#
  omikuji キオスク起動（Windows単体運用）

  serve.ps1 を localhost 限定で起動し、Microsoft Edge をキオスクモード
  （全画面・タブもアドレスバーも無し）で開きます。iPadは要りません。
  ダブルクリックで使う場合は kiosk.bat を実行してください。

  終了: Edge は Ctrl+W または Alt+F4。配信はこの黒い画面で Enter。
#>

param(
  [int]$Port = 8080
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Root  = Split-Path -Parent $PSCommandPath
$Serve = Join-Path $Root 'serve.ps1'
if (-not (Test-Path $Serve)) {
  Write-Host "serve.ps1 が見つかりません: $Root" -ForegroundColor Red
  Read-Host '　Enter キーで終了'
  exit 1
}

function Test-Port([int]$p) {
  try {
    $c = New-Object System.Net.Sockets.TcpClient
    $c.Connect('127.0.0.1', $p)
    $c.Close()
    return $true
  } catch { return $false }
}

# --- 配信を起動（すでに動いていればそれを使う） --------------------------
$server = $null
if (Test-Port $Port) {
  Write-Host "ポート $Port は既に配信中です。そのまま使います。" -ForegroundColor DarkGray
} else {
  Write-Host "配信を開始します（http://localhost:$Port/）..."
  $server = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -PassThru -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', "`"$Serve`"",
    '-Port', $Port,
    '-LocalOnly'
  )
  $ok = $false
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 200
    if (Test-Port $Port) { $ok = $true; break }
  }
  if (-not $ok) {
    Write-Host "配信を開始できませんでした（ポート $Port）。" -ForegroundColor Red
    Write-Host '他のアプリが同じポートを使っているかもしれません。'
    Write-Host "別のポートで試す例:  kiosk.bat -Port 8081"
    Read-Host '　Enter キーで終了'
    exit 1
  }
}

# --- Edge をキオスクモードで開く -----------------------------------------
$url = "http://localhost:$Port/"
$edgeArgs = @(
  '--kiosk', $url,
  '--edge-kiosk-type=fullscreen',   # InPrivateにせず、通常プロファイルで全画面
  '--kiosk-idle-timeout-minutes=0', # 放置しても勝手にリセットさせない
  '--kiosk-printing',               # 印刷ダイアログを出さず既定のプリンターへ直接刷る
  '--no-first-run',
  '--disable-features=msEdgeSplitScreen,msImplicitSignin'
)
$opened = $false
try {
  Start-Process -FilePath 'msedge' -ArgumentList $edgeArgs | Out-Null
  $opened = $true
} catch {
  Write-Host 'Microsoft Edge を起動できませんでした。既定のブラウザで開きます。' -ForegroundColor Yellow
  try { Start-Process $url | Out-Null; $opened = $true } catch {}
}

Write-Host ''
Write-Host '============================================================'
Write-Host '  精霊魔法おみくじ  キオスク起動中' -ForegroundColor Cyan
Write-Host '============================================================'
Write-Host "  URL          : $url"
if (-not $opened) {
  Write-Host '  ブラウザを自動で開けませんでした。上のURLを手で開いてください。' -ForegroundColor Yellow
}
Write-Host ''
Write-Host '  設定パネル   : 画面右上を1.5秒ほど長押し'
Write-Host '  キオスク解除 : Edge の画面で Ctrl+W（または Alt+F4）'
Write-Host ''
Write-Host '  この画面で Enter を押すと配信を停止します。'
Write-Host '============================================================'
Read-Host

if ($server -and -not $server.HasExited) {
  try { Stop-Process -Id $server.Id -Force } catch {}
  Write-Host '配信を停止しました。'
}
