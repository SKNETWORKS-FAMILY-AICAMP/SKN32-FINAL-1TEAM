@echo off
REM 일 1회 공고 수집 배치.
REM   K-Startup + 기업마당 -> 정규화 -> MySQL -> 첨부 받기/본문 추출
REM
REM 작업 스케줄러가 이 파일을 부른다. 등록은 schedule-task.ps1 참조.
REM 인자는 그대로 넘어간다.  예)  run_daily.bat --skip-attach
setlocal
cd /d "%~dp0"

if not exist "data" mkdir "data"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv 가 없습니다. requirements.txt 로 먼저 만드세요. >> "data\run.log"
    exit /b 1
)

set PYTHONUTF8=1
echo [%date% %time%] start >> "data\run.log"
".venv\Scripts\python.exe" daily_pipeline.py %* >> "data\run.log" 2>&1
set "EXITCODE=%errorlevel%"
echo [%date% %time%] exit=%EXITCODE% >> "data\run.log"

REM 0 성공 / 1 실패 / 2 부분 실패 / 3 이미 실행 중
exit /b %EXITCODE%
