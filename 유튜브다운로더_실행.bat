@echo off
rem 개발용 실행 (소스 그대로 실행). 배포용은 tools\build.ps1 로 만든 설치 파일을 사용하세요.
chcp 65001 >nul
cd /d "%~dp0"
start "" pythonw "%~dp0src\youtube_downloader.py"
