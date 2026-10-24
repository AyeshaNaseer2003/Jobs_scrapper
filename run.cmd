@echo off
setlocal
pushd "%~dp0"
set "agent_python="
if exist "%~dp0.venv\Scripts\python.exe" set "agent_python=%~dp0.venv\Scripts\python.exe"
if not defined agent_python if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "agent_python=%VIRTUAL_ENV%\Scripts\python.exe"
if not defined agent_python if exist "%~dp0..\.venv\Scripts\python.exe" set "agent_python=%~dp0..\.venv\Scripts\python.exe"
if not defined agent_python (
    echo Project environment is missing. Run these commands once:
    echo python -m venv .venv
    echo .venv\Scripts\python.exe -m pip install -r requirements.txt
    popd
    exit /b 1
)
"%agent_python%" -m job_agent %*
set "agent_exit=%errorlevel%"
popd
exit /b %agent_exit%
