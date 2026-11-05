# YouTube Downloader 빌드: Nuitka 네이티브 컴파일 → 설치 파일(Inno Setup) 생성
# Copyright (c) 2026 최승훈. All rights reserved.
#
# 사용법 (PowerShell):
#   powershell -ExecutionPolicy Bypass -File tools\build.ps1              # 전체 빌드
#   powershell -ExecutionPolicy Bypass -File tools\build.ps1 -SkipCompile # 컴파일 생략, 설치 파일만 다시
#
# 결과: dist\YouTubeDownloader_Setup_<버전>.exe

param(
    [switch]$SkipCompile
)

$ErrorActionPreference = "Stop"
$Project = Split-Path $PSScriptRoot -Parent
# MinGW 컴파일러는 한글 경로를 처리하지 못하므로 빌드 작업은 영문 경로에서 한다
$BuildRoot = "C:\YTBuild"
$Py = Join-Path $BuildRoot "python\python.exe"
if (-not (Test-Path $Py)) {
    throw "빌드 환경이 없습니다. 먼저 tools\setup_build_env.ps1 을 실행하세요."
}

$env:TEMP = "$BuildRoot\tmp"
$env:TMP = $env:TEMP
$env:NUITKA_CACHE_DIR = "$BuildRoot\cache"
New-Item -ItemType Directory -Force $env:TEMP | Out-Null

$src = Join-Path $Project "src\youtube_downloader.py"
$version = [regex]::Match((Get-Content $src -Raw -Encoding UTF8), 'APP_VERSION = "([^"]+)"').Groups[1].Value
if (-not $version) { throw "src\youtube_downloader.py 에서 APP_VERSION 을 찾지 못했습니다." }
Write-Host "== YouTube Downloader $version 빌드 ==" -ForegroundColor Cyan

$work = "$BuildRoot\work"
$out = "$BuildRoot\out"
$dist = "$out\YouTubeDownloader.dist"

# 1) Nuitka: 파이썬 코드를 C로 변환해 기계어로 컴파일 (실행 파일에 파이썬 소스·바이트코드가 남지 않음)
#    yt_dlp.extractor.lazy_extractors 는 시작 속도용 선택 모듈인데 C 파일 하나가 너무 커서
#    컴파일러가 메모리 부족으로 멈춘다 → 제외 (없으면 yt-dlp가 일반 모듈로 동작)
#    mutagen 은 GPL 이라 함께 컴파일하면 프로그램 전체가 GPL 이 된다. 이 프로그램은 쓰지 않는
#    기능(썸네일 삽입)용 선택 패키지이므로 제외한다 → 아래 라이선스 검사로 확인
if (-not $SkipCompile) {
    Remove-Item $work, $out -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force $work | Out-Null
    Copy-Item $src "$work\YouTubeDownloader.py"
    Push-Location $work
    try {
        & $Py -m nuitka `
            --standalone `
            --assume-yes-for-downloads `
            --mingw64 `
            --experimental=force-dependencies-pefile `
            --enable-plugin=tk-inter `
            --include-package=yt_dlp `
            --nofollow-import-to=yt_dlp.__pyinstaller `
            --nofollow-import-to=yt_dlp.extractor.lazy_extractors `
            --nofollow-import-to=mutagen `
            --include-package=yt_dlp_ejs `
            --include-package-data=yt_dlp_ejs `
            --include-package-data=customtkinter `
            --windows-console-mode=disable `
            "--windows-icon-from-ico=$Project\assets\app.ico" `
            "--company-name=최승훈" `
            "--product-name=YouTube Downloader" `
            "--file-description=YouTube Downloader" `
            "--file-version=$version" `
            "--product-version=$version" `
            "--copyright=Copyright (c) 2026 최승훈. All rights reserved." `
            --output-filename=YouTubeDownloader.exe `
            "--output-dir=$out" `
            "--jobs=$([Environment]::ProcessorCount)" `
            YouTubeDownloader.py
        if ($LASTEXITCODE) { throw "Nuitka 컴파일 실패 (종료 코드 $LASTEXITCODE)" }
    }
    finally {
        Pop-Location
    }
}
if (-not (Test-Path "$dist\YouTubeDownloader.exe")) { throw "컴파일된 실행 파일이 없습니다: $dist" }

# GPL 패키지가 실행 파일에 들어가지 않았는지 검사 (yt-dlp 안의 "mutagen" 글자는 정상이므로 모듈 파일 이름으로 찾는다)
& $Py -c @"
import pathlib, sys
data = pathlib.Path(r'$dist\YouTubeDownloader.exe').read_bytes()
sys.exit(1 if b'mutagen\\_constants.py' in data or b'mutagen._file' in data else 0)
"@
if ($LASTEXITCODE) { throw "실행 파일에 GPL 패키지 mutagen 이 들어 있습니다. 배포하면 안 됩니다." }

# 2) 함께 배포할 파일: 아이콘, ffmpeg·node, 라이선스
Write-Host "== 배포 파일 정리 ==" -ForegroundColor Cyan
New-Item -ItemType Directory -Force "$dist\assets", "$dist\bin", "$dist\licenses" | Out-Null
Copy-Item "$Project\assets\app.ico" "$dist\assets\" -Force
Get-ChildItem "$Project\bin" -File | Where-Object { $_.Extension -ne ".txt" } | Copy-Item -Destination "$dist\bin\" -Force
Get-ChildItem "$Project\bin" -Filter "*LICENSE*.txt" | Copy-Item -Destination "$dist\licenses\" -Force
Copy-Item "$BuildRoot\python\LICENSE.txt" "$dist\licenses\PYTHON_LICENSE.txt" -Force
Copy-Item "$dist\tk\license.terms" "$dist\licenses\TCL_TK_LICENSE.txt" -Force
# 파이썬에 포함된 OpenSSL·zlib·expat·libffi 등의 라이선스 원문 (CPython 문서 사본)
Copy-Item "$Project\installer\licenses\*" "$dist\licenses\" -Force
# 파이썬 패키지 라이선스 원문을 dist-info 에서 모은다 (실행 파일에 포함되는 패키지 전부)
& $Py -c @"
import importlib.metadata as md, pathlib, shutil
dest = pathlib.Path(r'$dist\licenses')
pkgs = ['yt-dlp', 'yt-dlp-ejs', 'customtkinter', 'darkdetect', 'packaging', 'pillow', 'brotli', 'certifi',
        'charset-normalizer', 'idna', 'pycryptodomex', 'requests', 'urllib3', 'websockets']
for pkg in pkgs:
    found = [f for f in md.distribution(pkg).files or []
             if any(w in f.name.lower() for w in ('licen', 'copying', 'notice'))]
    if not found:
        raise SystemExit(f'{pkg}: license file not found')
    for f in found:
        shutil.copy(f.locate(), dest / f'{pkg}_{f.name}')
"@
if ($LASTEXITCODE) { throw "라이선스 수집 실패" }

# 3) 설치 파일: Inno Setup은 한글 문서를 UTF-8 BOM 으로 읽으므로 사본을 변환해 넘긴다
Write-Host "== 설치 파일 생성 ==" -ForegroundColor Cyan
$docs = "$BuildRoot\docs"
New-Item -ItemType Directory -Force $docs | Out-Null
foreach ($f in "EULA_ko.txt", "THIRD_PARTY_NOTICES.txt", "setup.iss") {
    $text = [IO.File]::ReadAllText("$Project\installer\$f", [Text.Encoding]::UTF8)
    [IO.File]::WriteAllText("$docs\$f", $text, (New-Object Text.UTF8Encoding $true))
}
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 이 없습니다. winget install JRSoftware.InnoSetup" }
New-Item -ItemType Directory -Force "$Project\dist" | Out-Null
& $iscc /Q "/DAppVersion=$version" "/DAppSourceDir=$dist" "/DDocsDir=$docs" "/DOutputDir=$Project\dist" "$docs\setup.iss"
if ($LASTEXITCODE) { throw "Inno Setup 실패 (종료 코드 $LASTEXITCODE)" }

$setup = Get-Item "$Project\dist\YouTubeDownloader_Setup_$version.exe"
Write-Host ("완료: {0}  ({1:N1} MB)" -f $setup.FullName, ($setup.Length / 1MB)) -ForegroundColor Green
