; YouTube Downloader 설치 프로그램 (Inno Setup 6)
; Copyright (c) 2026 최승훈. All rights reserved.
;
; 직접 실행하지 말고 tools\build.ps1 로 빌드하세요. 아래 값들은 build.ps1이 넘겨줍니다.
;   AppVersion : 프로그램 버전 (src\youtube_downloader.py 의 APP_VERSION)
;   AppSourceDir  : Nuitka로 컴파일된 프로그램 폴더
;   DocsDir    : 사용권 계약서·고지문 폴더 (UTF-8 BOM으로 변환된 사본)
;   OutputDir  : 설치 파일이 만들어질 폴더

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName "YouTube Downloader"
#define AppExe "YouTubeDownloader.exe"
#define Author "최승훈"

[Setup]
AppId={{6E7B2C1A-4F3D-4E8B-9A51-2D7C0B1F9E42}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Author}
AppCopyright=Copyright (c) 2026 {#Author}. All rights reserved.
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#Author}
VersionInfoCopyright=Copyright (c) 2026 {#Author}. All rights reserved.
VersionInfoDescription={#AppName} 설치 프로그램
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; 관리자 권한 없이 현재 사용자용으로도 설치할 수 있게 선택 창을 띄운다
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile={#DocsDir}\EULA_ko.txt
SetupIconFile={#AppSourceDir}\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir={#OutputDir}
OutputBaseFilename=YouTubeDownloader_Setup_{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DocsDir}\EULA_ko.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DocsDir}\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\사용권 계약서"; Filename: "{app}\EULA_ko.txt"
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent
