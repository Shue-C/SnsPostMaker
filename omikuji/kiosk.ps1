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

<#
  そのポートで配信しているのが「このフォルダのおみくじ」かどうかを確かめる。

  前回の配信プロセスは非表示で動いているので、閉じ忘れたまま残ることがある。
  それを気づかずに使い回すと、フォルダを新しくしても古い画面が出続けるので、
  必ず名乗らせてから使う。
#>
function Get-ServeStatus([int]$p) {
  try {
    $r = Invoke-WebRequest -Uri "http://localhost:$p/__status" -TimeoutSec 3 -UseBasicParsing
    return ($r.Content | ConvertFrom-Json)
  } catch { return $null }
}

# 自分が起こした serve.ps1 だけを止める（他のPowerShellには触らない）
function Stop-ServeProcesses {
  $n = 0
  try {
    Get-CimInstance Win32_Process -ErrorAction Stop |
      Where-Object {
        $_.Name -match '^(powershell|pwsh)\.exe$' -and
        $_.CommandLine -and $_.CommandLine -like '*serve.ps1*' -and
        $_.ProcessId -ne $PID
      } |
      ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $n++
      }
  } catch {}
  if ($n -gt 0) { Start-Sleep -Milliseconds 700 }
  return $n
}

# serve.ps1 のバージョンを読んでおき、ポートに居る配信と突き合わせる
$expectedVersion = ''
try {
  $serveText = Get-Content -LiteralPath $Serve -Raw -ErrorAction Stop
  if ($serveText -match "\`$OmikujiVersion\s*=\s*'([^']*)'") { $expectedVersion = $Matches[1] }
} catch {}

# --- 配信を起動 ----------------------------------------------------------
$server = $null
$needStart = $true

if (Test-Port $Port) {
  $status = Get-ServeStatus $Port
  if ($status -and $status.app -eq 'omikuji' -and
      $status.root -eq $Root -and
      ($expectedVersion -eq '' -or $status.version -eq $expectedVersion)) {
    Write-Host "このフォルダの配信が既に動いています。そのまま使います。" -ForegroundColor DarkGray
    $needStart = $false
  } else {
    if ($status -and $status.app -eq 'omikuji') {
      Write-Host '古い配信プロセスが残っていました。止めて起動し直します。' -ForegroundColor Yellow
      Write-Host ("  残っていたフォルダ : " + $status.root) -ForegroundColor DarkGray
      Write-Host ("  残っていた版       : " + $status.version) -ForegroundColor DarkGray
    } else {
      Write-Host "ポート $Port を別のプログラムが使っています。" -ForegroundColor Yellow
      Write-Host 'おみくじの古い配信であれば止めます。' -ForegroundColor Yellow
    }
    $stopped = Stop-ServeProcesses
    if ($stopped -gt 0) { Write-Host "  $stopped 個の配信プロセスを止めました。" -ForegroundColor DarkGray }
    if (Test-Port $Port) {
      Write-Host "ポート $Port がまだ空きません。おみくじ以外のプログラムが使っています。" -ForegroundColor Red
      Write-Host "別のポートで起動してください:  kiosk.bat -Port 8081"
      Read-Host '　Enter キーで終了'
      exit 1
    }
  }
}

if ($needStart) {
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
    Write-Host "別のポートで試す例:  kiosk.bat -Port 8081"
    Read-Host '　Enter キーで終了'
    exit 1
  }
}

# 何を配信しているのかを画面に出す（フォルダの取り違えをここで潰す）
$status = Get-ServeStatus $Port
if ($status) {
  Write-Host ("  公開フォルダ : " + $status.root) -ForegroundColor DarkGray
  Write-Host ("  中身の版     : " + $status.appVersion) -ForegroundColor DarkGray
  Write-Host ("  用紙幅       : " + $status.widthDots + " ドット") -ForegroundColor DarkGray
  if ($expectedVersion -and $status.appVersion -and $status.appVersion -ne $expectedVersion) {
    Write-Host '  !! フォルダの中身が古いです。フォルダごと入れ替え直してください。' -ForegroundColor Red
  }
}

# --- Edge をキオスクモードで開く -----------------------------------------
# 末尾に起動時刻を付けて、ブラウザのキャッシュを確実に外す
$url = "http://localhost:$Port/?v=" + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
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
