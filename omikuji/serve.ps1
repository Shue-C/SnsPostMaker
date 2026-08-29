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

# 「今どのファイルが動いているか」を確かめるための目印。
# アプリの設定パネルに出るバージョンと一致していれば、新旧の取り違えは無い。
$OmikujiVersion = '2026-08-29 local-1'

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

# --- ローカル印刷（USB / Bluetooth / LAN 共通） --------------------------
# ブラウザから受け取った ESC/POS を、Windowsのプリンターへ RAW のまま流す。
# ブラウザの印刷機能を通さないので、余白もヘッダーも印刷ダイアログも出ない。
$printReady = $true
try {
  Add-Type -ErrorAction Stop -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class OmikujiRawPrinter
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public class DOCINFO
    {
        [MarshalAs(UnmanagedType.LPWStr)] public string pDocName;
        [MarshalAs(UnmanagedType.LPWStr)] public string pOutputFile;
        [MarshalAs(UnmanagedType.LPWStr)] public string pDataType;
    }

    [DllImport("winspool.Drv", EntryPoint = "OpenPrinterW", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool OpenPrinter(string src, out IntPtr hPrinter, IntPtr pd);
    [DllImport("winspool.Drv", EntryPoint = "ClosePrinter", SetLastError = true)]
    private static extern bool ClosePrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint = "StartDocPrinterW", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool StartDocPrinter(IntPtr hPrinter, int level, [In, MarshalAs(UnmanagedType.LPStruct)] DOCINFO di);
    [DllImport("winspool.Drv", EntryPoint = "EndDocPrinter", SetLastError = true)]
    private static extern bool EndDocPrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint = "StartPagePrinter", SetLastError = true)]
    private static extern bool StartPagePrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint = "EndPagePrinter", SetLastError = true)]
    private static extern bool EndPagePrinter(IntPtr hPrinter);
    [DllImport("winspool.Drv", EntryPoint = "WritePrinter", SetLastError = true)]
    private static extern bool WritePrinter(IntPtr hPrinter, IntPtr pBytes, int dwCount, out int dwWritten);

    public static void Send(string printerName, byte[] bytes)
    {
        IntPtr h;
        if (!OpenPrinter(printerName, out h, IntPtr.Zero))
            throw new Exception("プリンターを開けません（名前が違うか、オフラインです）: " + printerName);
        try
        {
            DOCINFO di = new DOCINFO();
            di.pDocName = "Omikuji";
            di.pDataType = "RAW";
            if (!StartDocPrinter(h, 1, di))
                throw new Exception("印刷ジョブを開始できませんでした");
            try
            {
                if (!StartPagePrinter(h))
                    throw new Exception("ページを開始できませんでした");
                IntPtr p = Marshal.AllocCoTaskMem(bytes.Length);
                try
                {
                    Marshal.Copy(bytes, 0, p, bytes.Length);
                    int written;
                    if (!WritePrinter(h, p, bytes.Length, out written))
                        throw new Exception("プリンターへ送信できませんでした");
                }
                finally { Marshal.FreeCoTaskMem(p); }
                EndPagePrinter(h);
            }
            finally { EndDocPrinter(h); }
        }
        finally { ClosePrinter(h); }
    }
}
'@
} catch {
  $printReady = $false
  Write-Host ('ローカル印刷を初期化できませんでした: ' + $_.Exception.Message) -ForegroundColor Yellow
}

function ConvertTo-JsonText([string]$value) {
  $t = [string]$value
  $t = $t.Replace('\', '\\').Replace('"', '\"')
  $t = $t.Replace("`r", '\r').Replace("`n", '\n').Replace("`t", '\t')
  return '"' + $t + '"'
}

function Get-DefaultPrinterName {
  try {
    $d = Get-CimInstance Win32_Printer -ErrorAction Stop |
      Where-Object { $_.Default } | Select-Object -First 1
    if ($d) { return [string]$d.Name }
  } catch {}
  return ''
}

function Get-PrinterNames {
  try {
    return @(Get-Printer -ErrorAction Stop | Select-Object -ExpandProperty Name)
  } catch {}
  try {
    return @(Get-CimInstance Win32_Printer -ErrorAction Stop | Select-Object -ExpandProperty Name)
  } catch {}
  return @()
}

function Send-JsonResponse($res, [string]$json, [int]$status) {
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
  $res.StatusCode = $status
  $res.ContentType = 'application/json; charset=utf-8'
  $res.ContentLength64 = $bytes.Length
  $res.AddHeader('Cache-Control', 'no-store')
  $res.OutputStream.Write($bytes, 0, $bytes.Length)
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
# 配信しようとしているフォルダが本当に新しいものかを、起動時に自分で確かめる。
# 「ファイルを入れ替えたのに変わらない」の大半は、古いフォルダを配信していることが原因。
$folderVersion = ''
$folderWidth = ''
try {
  $appJs = Get-Content -LiteralPath (Join-Path $Root 'js\app.js') -Raw -ErrorAction Stop
  if ($appJs -match "APP_VERSION\s*=\s*'([^']*)'") { $folderVersion = $Matches[1] }
} catch {}
try {
  $cfgJs = Get-Content -LiteralPath (Join-Path $Root 'js\config.js') -Raw -ErrorAction Stop
  if ($cfgJs -match 'widthDots:\s*(\d+)') { $folderWidth = $Matches[1] }
} catch {}

Write-Host "  バージョン   : $OmikujiVersion"
Write-Host "  公開フォルダ : $Root"
if ($folderVersion -and $folderVersion -ne $OmikujiVersion) {
  Write-Host "  !! 中身が古いです : js/app.js は $folderVersion" -ForegroundColor Red
  Write-Host '     serve.ps1 だけ新しく、他のファイルが古いフォルダです。' -ForegroundColor Red
  Write-Host '     フォルダごと入れ替え直してください。' -ForegroundColor Red
} elseif ($folderVersion) {
  Write-Host "  中身の版     : $folderVersion（一致）"
}
if ($folderWidth) {
  $mm = [Math]::Round([double]$folderWidth / 203 * 25.4, 1)
  Write-Host "  用紙幅       : $folderWidth ドット（約 $mm mm）"
}
if ($printReady) {
  $defName = Get-DefaultPrinterName
  if (-not $defName) { $defName = '（見つかりません）' }
  Write-Host "  ローカル印刷 : 使えます / 既定のプリンター: $defName"
} else {
  Write-Host '  ローカル印刷 : 使えません（印刷方式 local は動きません）' -ForegroundColor Yellow
}
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
      $route = $req.Url.AbsolutePath.TrimEnd('/')

      # 使えるプリンターの一覧（設定パネルの選択肢になる）
      if ($route -eq '/printers') {
        $names = Get-PrinterNames
        $def = Get-DefaultPrinterName
        $items = @($names | ForEach-Object { ConvertTo-JsonText $_ }) -join ','
        Send-JsonResponse $res ('{"printers":[' + $items + '],"defaultPrinter":' + (ConvertTo-JsonText $def) + '}') 200
        Write-Host ("200 /printers  ({0} 台)" -f @($names).Count) -ForegroundColor DarkGray
        continue
      }

      # ESC/POS をそのままプリンターへ流す
      if ($route -eq '/print') {
        if ($req.HttpMethod -ne 'POST') {
          Send-JsonResponse $res '{"ok":false,"error":"POSTしてください"}' 405
          continue
        }
        if (-not $printReady) {
          Send-JsonResponse $res '{"ok":false,"error":"ローカル印刷を初期化できていません"}' 500
          continue
        }
        $reader = New-Object System.IO.StreamReader($req.InputStream, [System.Text.Encoding]::UTF8)
        $bodyText = $reader.ReadToEnd()
        $reader.Close()
        try {
          $payload = $bodyText | ConvertFrom-Json
          $name = [string]$payload.printer
          if (-not $name) { $name = Get-DefaultPrinterName }
          if (-not $name) { throw 'プリンターが指定されておらず、既定のプリンターも見つかりません' }
          $data = [Convert]::FromBase64String([string]$payload.data)
          [OmikujiRawPrinter]::Send($name, $data)
          Send-JsonResponse $res '{"ok":true}' 200
          Write-Host ("200 /print  {0}  ({1:N0} bytes)" -f $name, $data.Length) -ForegroundColor Green
        } catch {
          $msg = $_.Exception.Message
          if (-not $msg) { $msg = [string]$_ }
          Send-JsonResponse $res ('{"ok":false,"error":' + (ConvertTo-JsonText $msg) + '}') 200
          Write-Host ("印刷失敗: " + $msg) -ForegroundColor Red
        }
        continue
      }

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
