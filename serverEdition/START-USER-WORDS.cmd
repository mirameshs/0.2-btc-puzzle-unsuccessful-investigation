@echo off
setlocal
call "%~dp0START-SERVER.cmd" --config "%~dp0search-user-words.json" %*
