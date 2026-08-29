<#
  裏で動いている配信（serve.ps1）を止める。

  kiosk.bat の黒い画面を Enter ではなく × で閉じると、配信プロセスだけが
  非表示のまま残ることがある。それが残っていると、フォルダを新しくしても
  古い画面が出続けるので、そのときはこれを実行する。

  ダブルクリックで使う場合は stop.bat を実行してください。
#>

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$found = @()
try {
  $found = @(Get-CimInstance Win32_Process -ErrorAction Stop |
    Where-Object {
      $_.Name -match '^(powershell|pwsh)\.exe$' -and
      $_.CommandLine -and $_.CommandLine -like '*serve.ps1*' -and
      $_.ProcessId -ne $PID
    })
} catch {
  Write-Host 'プロセス一覧を取得できませんでした。' -ForegroundColor Red
}

if ($found.Count -eq 0) {
  Write-Host '裏で動いている配信はありませんでした。' -ForegroundColor Green
} else {
  foreach ($p in $found) {
    Write-Host ("止めます: PID " + $p.ProcessId)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Write-Host ("" + $found.Count + " 個の配信を止めました。") -ForegroundColor Green
}

Write-Host ''
Write-Host 'このあと kiosk.bat を起動し直してください。'
Read-Host '　Enter キーで終了'
