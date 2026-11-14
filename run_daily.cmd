@echo off
REM Scheduled daily run for Windows Task Scheduler.
REM   run_daily.cmd 01/10/2026 11/11/2026 "NORTHERN RLY"
REM   run_daily.cmd 01/10/2026 11/11/2026 "NORTHERN RLY" tenders
REM The fourth argument picks the search: "po" (the default) or "tenders".
REM The CLI never prompts - it uses the cached session and exits with a
REM message if the session has expired.
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs

set FROM=%1
set TO=%2
set ZONE=%3
set MODE=%4
if "%FROM%"=="" set FROM=%DATE:~-10,10%
if "%TO%"=="" set TO=%DATE:~-10,10%
if "%ZONE%"=="" set ZONE=All
if "%MODE%"=="" set MODE=po

echo [%DATE% %TIME%] starting IREPS %MODE% run %FROM% to %TO% zone=%ZONE% >> logs\daily.log
python main.py --cli --mode %MODE% --from %FROM% --to %TO% --zone "%ZONE%" --details --out output >> logs\daily.log 2>&1
if errorlevel 1 (
  echo [%DATE% %TIME%] FAILED - see logs\daily.log >> logs\daily.log
) else (
  echo [%DATE% %TIME%] finished >> logs\daily.log
)
endlocal
