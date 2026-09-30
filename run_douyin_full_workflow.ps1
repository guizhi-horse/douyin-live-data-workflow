param(
  [switch]$LaunchChrome
)

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
$config = Join-Path $PSScriptRoot "config\douyin_workflow_config.json"
$outputRoot = Join-Path $PSScriptRoot "output"
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$summaryPath = Join-Path $outputRoot "douyin_full_workflow_result.json"
$backupRoot = Join-Path $outputRoot "archives"
$mailDraftRoot = Join-Path $outputRoot "mail-drafts"
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"

if (-not (Test-Path $config)) {
  Write-Host "Missing config\douyin_workflow_config.json. Please export the launcher config and save it there first."
  exit 1
}

function Wait-ForUser {
  param(
    [string]$Message
  )

  Write-Host ""
  Write-Host $Message
  [void](Read-Host "Press Enter to continue")
}

function Read-JsonFile {
  param(
    [string]$Path
  )

  $utf8Text = [System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($true))
  return $utf8Text | ConvertFrom-Json
}

function Get-ConfiguredTargetDates {
  $payload = Read-JsonFile -Path $config
  if ($payload.date_mode -eq "today") {
    return (Get-Date).ToString("yyyy-MM-dd")
  }
  if ($payload.date_mode -eq "single_date") {
    return [DateTime]::ParseExact(
      [string]$payload.target_date,
      "yyyy-MM-dd",
      [Globalization.CultureInfo]::InvariantCulture
    ).ToString("yyyy-MM-dd")
  }

  $startDate = [DateTime]::ParseExact(
    [string]$payload.start_date,
    "yyyy-MM-dd",
    [Globalization.CultureInfo]::InvariantCulture
  )
  $endDate = [DateTime]::ParseExact(
    [string]$payload.end_date,
    "yyyy-MM-dd",
    [Globalization.CultureInfo]::InvariantCulture
  )
  $dates = @()
  for ($currentDate = $startDate; $currentDate -le $endDate; $currentDate = $currentDate.AddDays(1)) {
    $dates += $currentDate.ToString("yyyy-MM-dd")
  }
  return $dates
}

function Ensure-AutoPrepared {
  param(
    [string]$TargetName
  )

  $prepareScript = Join-Path $PSScriptRoot "src\douyin_auto_prepare_stage.py"
  $prepareOutput = Join-Path $outputRoot ("douyin_prepare_" + $TargetName + "_result.json")
  $prepareResult = Invoke-Stage `
    -StageName ("Prepare " + $TargetName) `
    -ScriptPath $prepareScript `
    -ResultPath $prepareOutput `
    -ExtraArgs @("--target", $TargetName)

  $summary.stages["prepare_" + $TargetName] = $prepareResult
  Save-Summary $summary

  if ($prepareResult.status -ne "ready") {
    throw "Could not automatically prepare the $TargetName page."
  }
}

function Invoke-Stage {
  param(
    [string]$StageName,
    [string]$ScriptPath,
    [string]$ResultPath,
    [string[]]$ExtraArgs = @()
  )

  # Never allow a failed stage to inherit a successful JSON file from an
  # earlier date. The old behavior only checked whether the path existed.
  if (Test-Path -LiteralPath $ResultPath) {
    Remove-Item -LiteralPath $ResultPath -Force
  }
  $stageStartedUtc = [DateTime]::UtcNow
  $argsList = @($ScriptPath, "--config", $config, "--result-output", $ResultPath) + $ExtraArgs
  if ($python -eq "py -3") {
    $output = & py -3 @argsList
  }
  else {
    $output = & $python @argsList
  }
  $stageExitCode = $LASTEXITCODE

  try {
    Write-Host ""
    Write-Host "[$StageName]"
    Write-Host $output
  } catch {
    Write-Host ""
    Write-Host "[$StageName]"
    Write-Host "Console output could not be rendered cleanly. Please check the saved result file."
  }

  if ($stageExitCode -ne 0) {
    throw "$StageName failed with exit code $stageExitCode."
  }
  if (-not (Test-Path -LiteralPath $ResultPath)) {
    throw "Stage result file was not created: $ResultPath"
  }

  $resultFile = Get-Item -LiteralPath $ResultPath
  if ($resultFile.LastWriteTimeUtc -lt $stageStartedUtc) {
    throw "$StageName did not create a fresh result file: $ResultPath"
  }

  return Read-JsonFile -Path $ResultPath
}

function Ensure-StageReady {
  param(
    [string]$StageName,
    [string]$ScriptPath,
    [string]$ResultPath,
    [string]$RetryPrompt,
    [string[]]$ExtraArgs = @(),
    [int]$MaxAttempts = 3
  )

  $attempt = 1
  $result = Invoke-Stage -StageName $StageName -ScriptPath $ScriptPath -ResultPath $ResultPath -ExtraArgs $ExtraArgs
  while ($result.status -eq "wrong_page" -and $attempt -lt $MaxAttempts) {
    Write-Host ""
    Write-Host $RetryPrompt
    Start-Sleep -Seconds 2
    $attempt += 1
    $result = Invoke-Stage -StageName $StageName -ScriptPath $ScriptPath -ResultPath $ResultPath -ExtraArgs $ExtraArgs
  }
  return $result
}

function Save-Summary {
  param(
    [hashtable]$Summary
  )

  $json = $Summary | ConvertTo-Json -Depth 8
  [System.IO.File]::WriteAllText($summaryPath, $json, [System.Text.UTF8Encoding]::new($true))
}

function Invoke-PostProcess {
  param(
    [string]$Command,
    [string[]]$ExtraArgs = @()
  )

  $scriptPath = Join-Path $PSScriptRoot "src\douyin_postprocess.py"
  $argsList = @($scriptPath, $Command, "--config", $config, "--summary", $summaryPath) + $ExtraArgs
  try {
    if ($python -eq "py -3") {
      $output = & py -3 @argsList
    }
    else {
      $output = & $python @argsList
    }
    if ($output) {
      Write-Host ""
      Write-Host "[$Command]"
      Write-Host $output
    }
  } catch {
    Write-Host ""
    Write-Host "[$Command]"
    Write-Host "Post-process step failed: $($_.Exception.Message)"
  }
}

function Invoke-SessionWorkflow {
  param(
    [int]$SessionIndex
  )

  if ($SessionIndex -eq 0) {
    Ensure-AutoPrepared -TargetName "list"
  }
  else {
    Write-Host ""
    Write-Host ("Reusing the filtered list page for session " + ($SessionIndex + 1) + ".")
  }

  $listResult = Ensure-StageReady `
    -StageName ("List stage " + ($SessionIndex + 1)) `
    -ScriptPath (Join-Path $PSScriptRoot "src\douyin_list_stage.py") `
    -ResultPath (Join-Path $outputRoot "douyin_list_stage_result.json") `
    -RetryPrompt 'List page was not detected.' `
    -ExtraArgs @("--candidate-index", [string]$SessionIndex)
  $summary.stages.list = $listResult
  Save-Summary $summary

  $actualTargetDates = @($listResult.target_dates | ForEach-Object { [string]$_ })
  $dateDifference = @(Compare-Object -ReferenceObject $expectedTargetDates -DifferenceObject $actualTargetDates)
  if ($dateDifference.Count -gt 0) {
    throw "List stage target dates do not match the current config. Expected: $($expectedTargetDates -join ', '); actual: $($actualTargetDates -join ', ')."
  }

  if ($listResult.status -eq "live_in_progress") {
    throw "The target session is still live. Workflow stopped."
  }
  if (-not $listResult.detail_open_result) {
    throw "List stage did not open detail candidate $($SessionIndex + 1)."
  }

  $openedDate = [string]$listResult.detail_open_result.matched_date
  if (-not $openedDate -or $openedDate -notin $expectedTargetDates) {
    throw "List stage opened a session for the wrong date. Expected one of: $($expectedTargetDates -join ', '); opened: $openedDate."
  }

  $detailResult = Ensure-StageReady `
    -StageName ("Detail stage " + ($SessionIndex + 1)) `
    -ScriptPath (Join-Path $PSScriptRoot "src\douyin_detail_stage.py") `
    -ResultPath (Join-Path $outputRoot "douyin_detail_stage_result.json") `
    -RetryPrompt 'Detail page was not detected. Switch to the target live detail page, then continue.'
  $summary.stages.detail = $detailResult
  Save-Summary $summary

  if ($detailResult.status -ne "finished") {
    throw "Detail candidate $($SessionIndex + 1) is not in finished state."
  }

  $dashboardResult = Ensure-StageReady `
    -StageName ("Dashboard stage " + ($SessionIndex + 1)) `
    -ScriptPath (Join-Path $PSScriptRoot "src\douyin_dashboard_stage.py") `
    -ResultPath (Join-Path $outputRoot "douyin_dashboard_stage_result.json") `
    -RetryPrompt 'Base dashboard was not detected.'
  $summary.stages.dashboard = $dashboardResult
  Save-Summary $summary

  Ensure-AutoPrepared -TargetName "professional"
  $professionalResult = Ensure-StageReady `
    -StageName ("Professional stage " + ($SessionIndex + 1)) `
    -ScriptPath (Join-Path $PSScriptRoot "src\douyin_professional_stage_stable.py") `
    -ResultPath (Join-Path $outputRoot "douyin_professional_stage_result.json") `
    -RetryPrompt 'Professional dashboard was not detected.'
  $summary.stages.professional = $professionalResult
  Save-Summary $summary

  Ensure-AutoPrepared -TargetName "qianchuan"
  $qianchuanResult = Ensure-StageReady `
    -StageName ("Qianchuan stage " + ($SessionIndex + 1)) `
    -ScriptPath (Join-Path $PSScriptRoot "src\douyin_qianchuan_stage.py") `
    -ResultPath (Join-Path $outputRoot "douyin_qianchuan_stage_result.json") `
    -RetryPrompt 'Qianchuan core data page was not detected.'
  $summary.stages.qianchuan = $qianchuanResult
  Save-Summary $summary

  $noteArgs = @(
    "--detail-result", (Join-Path $outputRoot "douyin_detail_stage_result.json"),
    "--dashboard-result", (Join-Path $outputRoot "douyin_dashboard_stage_result.json"),
    "--professional-result", (Join-Path $outputRoot "douyin_professional_stage_result.json"),
    "--qianchuan-result", (Join-Path $outputRoot "douyin_qianchuan_stage_result.json")
  )
  $noteResult = Invoke-Stage `
    -StageName ("Note stage " + ($SessionIndex + 1)) `
    -ScriptPath (Join-Path $PSScriptRoot "src\douyin_note_stage_clean.py") `
    -ResultPath (Join-Path $outputRoot "douyin_note_stage_result.json") `
    -ExtraArgs $noteArgs
  $summary.stages.note = $noteResult
  Save-Summary $summary

  return [pscustomobject]@{
    candidate_count = @($listResult.detail_candidates).Count
    note_result = $noteResult
    stages = [ordered]@{
      session_index = $SessionIndex
      list = $listResult
      detail = $detailResult
      dashboard = $dashboardResult
      professional = $professionalResult
      qianchuan = $qianchuanResult
      note = $noteResult
    }
  }
}

if ($LaunchChrome) {
  & (Join-Path $PSScriptRoot "launch_douyin_chrome.ps1")
}

$summary = @{
  started_at = (Get-Date).ToString("s")
  stages = @{}
  sessions = @()
  final_status = "running"
}
$expectedTargetDates = @(Get-ConfiguredTargetDates)

try {
  $firstSession = Invoke-SessionWorkflow -SessionIndex 0
  $sessionCount = [int]$firstSession.candidate_count
  if ($sessionCount -lt 1) {
    throw "No finished detail candidates were found for the configured date."
  }
  $summary.sessions += $firstSession.stages
  $summary.session_count = $sessionCount
  $lastSession = $firstSession
  Save-Summary $summary

  for ($sessionIndex = 1; $sessionIndex -lt $sessionCount; $sessionIndex++) {
    Write-Host ""
    Write-Host ("Starting session " + ($sessionIndex + 1) + " of " + $sessionCount + "...")
    $sessionRun = Invoke-SessionWorkflow -SessionIndex $sessionIndex
    if ([int]$sessionRun.candidate_count -ne $sessionCount) {
      throw "The number of list candidates changed during collection. Expected $sessionCount; found $($sessionRun.candidate_count)."
    }
    $summary.sessions += $sessionRun.stages
    $lastSession = $sessionRun
    Save-Summary $summary
  }

  $summary.final_status = "completed"
  $summary.finished_at = (Get-Date).ToString("s")
  Save-Summary $summary
  Invoke-PostProcess -Command "backup" -ExtraArgs @("--backup-root", $backupRoot)

  Write-Host ""
  Write-Host "Workflow completed."
  Write-Host "Collected sessions: $sessionCount"
  Write-Host "Note path: $($lastSession.note_result.note_path)"
  Write-Host "Summary path: $summaryPath"
}
catch {
  $summary.final_status = "failed"
  $summary.error = $_.Exception.Message
  $summary.finished_at = (Get-Date).ToString("s")
  Save-Summary $summary
  Invoke-PostProcess -Command "backup" -ExtraArgs @("--backup-root", $backupRoot)
  Invoke-PostProcess -Command "notify-failure" -ExtraArgs @("--drafts-root", $mailDraftRoot)
  Write-Host ""
  Write-Host "Workflow failed: $($_.Exception.Message)"
  Write-Host "Summary saved to: $summaryPath"
  exit 10
}
