@echo off
rem Odus launcher for Command Prompt. Not using setlocal on purpose, so Live Refresh can update this window.
set "ODUS_REFRESH_FILE=%TEMP%\odus-refresh-%RANDOM%%RANDOM%.cmd"
where py >nul 2>nul && goto :use_py
python "%~dp0odus.py" %*
goto :after
:use_py
py -3 "%~dp0odus.py" %*
:after
set "ODUS_RC=%errorlevel%"
if exist "%ODUS_REFRESH_FILE%" call "%ODUS_REFRESH_FILE%"
if exist "%ODUS_REFRESH_FILE%" del "%ODUS_REFRESH_FILE%" >nul 2>nul
set "ODUS_REFRESH_FILE="
set "ODUS_RC=" & exit /b %ODUS_RC%
