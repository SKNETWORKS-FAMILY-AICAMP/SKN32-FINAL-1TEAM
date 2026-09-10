# 일 1회 공고 수집 배치를 Windows 작업 스케줄러에 등록/조회/실행한다.
#
#   .\schedule-task.ps1                        미리보기 (기본, 아무것도 바꾸지 않음)
#   .\schedule-task.ps1 -Mode Install          등록
#   .\schedule-task.ps1 -Mode Install -At 08:30
#   .\schedule-task.ps1 -Mode Status           상태·마지막 실행 결과
#   .\schedule-task.ps1 -Mode Run              지금 한 번 실행
#   .\schedule-task.ps1 -Mode Uninstall        등록 해제
#
# 등록에는 관리자 권한이 필요할 수 있다.
[CmdletBinding()]
param(
    [ValidateSet('Preview', 'Install', 'Status', 'Run', 'Uninstall')]
    [string]$Mode = 'Preview',
    [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')]
    [string]$At = '09:00',
    [string]$TaskName = 'S-Brain-DailyCollection',
    # 로그온 방식. 기본 S4U 는 로그오프 상태에서도 실행되며 비밀번호를 저장하지 않는다.
    # Interactive 는 사용자 세션 안에서 돌기 때문에 로그오프·절전 시 프로세스가 죽는다.
    [ValidateSet('S4U', 'Interactive')]
    [string]$LogonType = 'S4U'
)
$ErrorActionPreference = 'Stop'

$batchPath = Join-Path $PSScriptRoot 'run_daily.bat'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if ($Mode -eq 'Preview') {
    [pscustomobject]@{
        TaskName           = $TaskName
        DailyAt            = $At
        TimeZone           = (Get-TimeZone).Id
        Command            = $batchPath
        WorkingDirectory   = $PSScriptRoot
        User               = $currentUser
        LogonType          = $LogonType
        MultipleInstances  = 'IgnoreNew'
        StartWhenAvailable = $true
        ExecutionTimeLimit = '2시간'
        PythonReady        = (Test-Path -LiteralPath $pythonPath)
        AlreadyRegistered  = [bool](Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
    }
    Write-Host ''
    Write-Host '미리보기입니다. 등록하려면 -Mode Install 을 주세요.'
    return
}

if ($Mode -eq 'Status') {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) { Write-Host "등록되지 않았습니다: $TaskName"; return }
    $task | Select-Object TaskName, State
    $task.Principal | Select-Object UserId, LogonType, RunLevel
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    $info | Select-Object LastRunTime, NextRunTime, LastTaskResult
    # 흔한 종료 코드 풀이. 0 이 아니면 data\run.log 도 함께 본다.
    switch ($info.LastTaskResult) {
        0          { '결과: 성공' }
        1          { '결과: 수집 실패 또는 예외' }
        2          { '결과: 부분 실패 — 한 출처만 갱신되지 않음' }
        3          { '결과: 이미 실행 중이어서 종료' }
        267009     { '결과: 지금 실행 중' }
        3221225786 { '결과: 외부에서 강제 종료됨 (0xC000013A). LogonType 을 S4U 로 두었는지 확인' }
        default    { "결과 코드: $($info.LastTaskResult)" }
    }
    return
}

if ($Mode -eq 'Run') {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "실행을 요청했습니다. 진행 상황은 data\run.log 를 보세요."
    return
}

if ($Mode -eq 'Uninstall') {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "등록을 해제했습니다: $TaskName"
    return
}

# ── Install ────────────────────────────────────────────────
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "가상환경이 없습니다: $pythonPath`n먼저 만드세요:`n  python -m venv .venv`n  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env'))) {
    Write-Warning ".env 가 없습니다. .env.example 을 복사해 인증키와 DB 접속 정보를 채우세요."
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "이미 등록돼 있습니다: $TaskName`n상태는 -Mode Status, 다시 등록하려면 -Mode Uninstall 후 진행하세요."
}

$action = New-ScheduledTaskAction -Execute $env:ComSpec `
    -Argument ('/d /s /c ""{0}""' -f $batchPath) -WorkingDirectory $PSScriptRoot

$trigger = New-ScheduledTaskTrigger -Daily `
    -At ([datetime]::ParseExact($At, 'HH:mm', [cultureinfo]::InvariantCulture))

# StartWhenAvailable — PC 가 꺼져 있어 놓친 실행을 켜진 뒤에 처리한다.
# IgnoreNew — 이전 실행이 아직 돌고 있으면 새로 시작하지 않는다.
# ExecutionTimeLimit 2시간 — 첨부가 많이 밀린 날을 감안한 상한.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType $LogonType -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description 'S-Brain 공고 수집 배치 (K-Startup + 기업마당 -> 정규화 -> MySQL -> 첨부 본문).'

Write-Host ''
Write-Host "등록했습니다: $TaskName  매일 $At"
Write-Host '확인:  .\schedule-task.ps1 -Mode Status'
Write-Host ''
Write-Host '작업 스케줄러 기록을 켜두면 실패 원인을 볼 수 있습니다 (관리자 권한):'
Write-Host '  wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true'
