$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$root = $PSScriptRoot
$configPath = Join-Path $root 'config\douyin_workflow_config.json'
$missing = @()

Write-Host '== 抖音直播数据工作流：首次运行检查 =='
if (-not (Test-Path -LiteralPath $configPath)) {
  Write-Host '[待配置] 缺少本地配置。先复制 config\douyin_workflow_config.example.json 为 config\douyin_workflow_config.json。'
  $missing += 'config'
  $config = $null
}
else {
  $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

$python = $null
foreach ($candidate in @((Join-Path $root 'runtime\python.exe'), (Join-Path $root 'runtime\python\python.exe'))) {
  if (Test-Path -LiteralPath $candidate) { $python = $candidate; break }
}
if (-not $python) {
  $pyCommand = Get-Command py -ErrorAction SilentlyContinue
  $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
  if ($pyCommand) { $python = 'py -3' }
  elseif ($pythonCommand) { $python = $pythonCommand.Source }
}
if ($python) { Write-Host "[OK] Python: $python" }
else { Write-Host '[待安装] 需要 Python 3.12+。'; $missing += 'python' }

$chromeCandidates = @()
if ($config -and $config.chrome_path) { $chromeCandidates += [string]$config.chrome_path }
$chromeCandidates += @('C:\Program Files\Google\Chrome\Application\chrome.exe', 'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe')
$chrome = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($chrome) { Write-Host "[OK] Chrome: $chrome" }
else { Write-Host '[待安装] 未找到 Chrome；安装后可在配置里填写 chrome_path。'; $missing += 'chrome' }

if ($config) {
  foreach ($field in @('chrome_start_url', 'luopan_entry_url', 'obsidian_output_path')) {
    if ([string]::IsNullOrWhiteSpace([string]$config.$field)) {
      Write-Host "[待配置] $field 为空。"
      $missing += $field
    }
    else { Write-Host "[OK] $field 已填写。" }
  }
  if ($config.chromedriver_path) {
    $driver = [string]$config.chromedriver_path
    if (-not [System.IO.Path]::IsPathRooted($driver)) { $driver = Join-Path $root $driver }
    if (Test-Path -LiteralPath $driver) { Write-Host "[OK] ChromeDriver: $driver" }
    else { Write-Host "[待配置] ChromeDriver 不存在: $driver"; $missing += 'chromedriver_path' }
  }
  else { Write-Host '[提示] chromedriver_path 为空；Selenium Manager 会尝试获取匹配的 ChromeDriver。' }
}

if ($missing.Count -gt 0) {
  Write-Host "检查未通过：$($missing -join ', ')"
  exit 1
}
Write-Host '基础检查通过。请先登录平台，再运行工作流。'
