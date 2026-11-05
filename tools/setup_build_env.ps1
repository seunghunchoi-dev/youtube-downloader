# 빌드 전용 파이썬 환경 만들기 (최초 1회)
# Copyright (c) 2026 최승훈. All rights reserved.
#
# 사용자 폴더 경로에 한글이 있으면 Nuitka(MinGW 컴파일러)가 동작하지 않으므로
# 영문 경로 C:\YTBuild 에 python.org 공식 파이썬(NuGet 패키지, 설치 없이 압축 해제)을 둔다.
# tkinter는 NuGet 패키지에 없어서, PC에 설치된 같은 버전(3.11) 파이썬에서 복사한다.
#
# 사용법: powershell -ExecutionPolicy Bypass -File tools\setup_build_env.ps1

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Project = Split-Path $PSScriptRoot -Parent
$BuildRoot = "C:\YTBuild"
$PyVersion = "3.11.9"
$Py = "$BuildRoot\python\python.exe"

if (-not (Test-Path $Py)) {
    Write-Host "== 파이썬 $PyVersion 내려받기 ==" -ForegroundColor Cyan
    $dl = "$BuildRoot\dl"
    New-Item -ItemType Directory -Force $dl | Out-Null
    Invoke-WebRequest "https://www.nuget.org/api/v2/package/python/$PyVersion" -OutFile "$dl\python.zip"
    Expand-Archive "$dl\python.zip" "$dl\pkg" -Force
    Move-Item "$dl\pkg\tools" "$BuildRoot\python"
    Remove-Item $dl -Recurse -Force

    Write-Host "== tkinter 복사 ==" -ForegroundColor Cyan
    $local = (& py -3.11 -c "import sys; print(sys.base_prefix)").Trim()
    if (-not (Test-Path "$local\Lib\tkinter")) { throw "tkinter 가 있는 파이썬 3.11 이 PC에 필요합니다." }
    Copy-Item "$local\Lib\tkinter" "$BuildRoot\python\Lib\tkinter" -Recurse -Force
    Copy-Item "$local\tcl" "$BuildRoot\python\tcl" -Recurse -Force
    foreach ($f in "_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll") {
        if (Test-Path "$local\DLLs\$f") { Copy-Item "$local\DLLs\$f" "$BuildRoot\python\DLLs\$f" -Force }
    }
    & $Py -m ensurepip --quiet
}

Write-Host "== 빌드용 패키지 설치 ==" -ForegroundColor Cyan
& $Py -m pip install --quiet --disable-pip-version-check -r "$Project\requirements-build.txt"
if ($LASTEXITCODE) { throw "패키지 설치 실패" }
& $Py -c "import tkinter, customtkinter, yt_dlp, nuitka; print('빌드 환경 준비 완료: yt-dlp', yt_dlp.version.__version__)"
