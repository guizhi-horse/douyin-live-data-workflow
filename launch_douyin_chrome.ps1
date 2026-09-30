$ErrorActionPreference = "Stop"

$configPath = Join-Path $PSScriptRoot "config\douyin_workflow_config.json"
$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profileDir = Join-Path $PSScriptRoot ".chrome-automation"
$debugPort = 9222
$startUrl = "about:blank"

if (Test-Path $configPath) {
  try {
    $configText = [System.IO.File]::ReadAllText($configPath, [System.Text.UTF8Encoding]::new($true))
    $config = $configText | ConvertFrom-Json
    if ($config.chrome_path) { $chromePath = [string]$config.chrome_path }
    if ($config.chrome_profile_dir) {
      $configuredProfileDir = [string]$config.chrome_profile_dir
      if ([System.IO.Path]::IsPathRooted($configuredProfileDir)) {
        $profileDir = $configuredProfileDir
      }
      else {
        $profileDir = Join-Path $PSScriptRoot $configuredProfileDir
      }
    }
    if ($config.chrome_debug_port) { $debugPort = [int]$config.chrome_debug_port }
    if ($config.chrome_start_url) { $startUrl = [string]$config.chrome_start_url }
  } catch {
    Write-Host "读取配置失败，改用默认 Chrome 启动参数。"
  }
}

if (-not (Test-Path $chromePath)) {
  $fallbacks = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
  )
  foreach ($candidate in $fallbacks) {
    if (Test-Path $candidate) {
      $chromePath = $candidate
      break
    }
  }
}

if (-not (Test-Path $chromePath)) {
  throw "未找到 Chrome，请先安装 Chrome，或在 config\douyin_workflow_config.json 中填写 chrome_path。"
}

New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

Start-Process -FilePath $chromePath -ArgumentList @(
  "--remote-debugging-port=$debugPort",
  "--user-data-dir=$profileDir",
  "--no-first-run",
  "--no-default-browser-check",
  $startUrl
)
