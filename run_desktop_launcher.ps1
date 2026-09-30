$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Resolve-Python {
  $localCandidates = @(
    (Join-Path $PSScriptRoot "runtime\python.exe"),
    (Join-Path $PSScriptRoot "runtime\python\python.exe"),
    (Join-Path $PSScriptRoot ".runtime\python.exe"),
    (Join-Path $PSScriptRoot ".runtime\python\python.exe")
  )

  foreach ($candidate in $localCandidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  $pyCommand = Get-Command py -ErrorAction SilentlyContinue
  if ($pyCommand) {
    return "py -3"
  }

  $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCommand) {
    return $pythonCommand.Source
  }

  throw "未找到可用的 Python。请先安装 Python 3，或把 python.exe 放到 runtime\python\python.exe。"
}

$python = Resolve-Python
$script = Join-Path $PSScriptRoot "src\douyin_desktop_launcher.py"

if ($python -eq "py -3") {
  & py -3 $script
}
else {
  & $python $script
}
