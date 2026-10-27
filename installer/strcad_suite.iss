; StrCAD (STR Design & Check 런처 + 전체 모듈) — Windows 설치 프로그램 (Inno Setup 6)
; 빌드: build_windows.bat 실행 (PyInstaller → dist\StrCAD, 그다음 이 스크립트)

#if FileExists(AddBackslash(SourcePath) + "version.iss")
  #include "version.iss"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "StrCAD"
#define AppExe "StrCAD.exe"

[Setup]
AppId={{8C1E2A44-F28C-4B28-9A1D-5752434144B2}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=StrCAD
AppCopyright=© 2026 StrCAD
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\StrCAD
DefaultGroupName=StrCAD
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=StrCAD_Setup_{#AppVersion}
SetupIconFile=..\strcad_cad_analysis\cad_analysis\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=wizard.bmp,wizard_2x.bmp
WizardSmallImageFile=small.bmp,small_2x.bmp
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"
Name: "assocdxf"; Description: ".dxf 파일을 StrCAD로 열기 메뉴 추가"; GroupDescription: "추가 작업:"; Flags: unchecked

[Files]
Source: "..\dist\StrCAD\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\StrCAD"; Filename: "{app}\{#AppExe}"
Name: "{group}\StrCAD 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\StrCAD"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.dxf\OpenWithProgids"; ValueType: string; ValueName: "StrCAD.dxf"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assocdxf
Root: HKA; Subkey: "Software\Classes\StrCAD.dxf"; ValueType: string; ValueName: ""; ValueData: "DXF 도면 (StrCAD)"; Flags: uninsdeletekey; Tasks: assocdxf
Root: HKA; Subkey: "Software\Classes\StrCAD.dxf\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: assocdxf
Root: HKA; Subkey: "Software\Classes\StrCAD.dxf\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assocdxf

[Run]
Filename: "{app}\{#AppExe}"; Description: "StrCAD 실행"; Flags: nowait postinstall skipifsilent

; 사용자 데이터(분석 DB·설정)는 %USERPROFILE%\.strcad 에 있으며 제거 시 지우지 않습니다.
