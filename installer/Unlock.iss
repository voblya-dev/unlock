; Standard Windows installer for Unlock (Inno Setup 6+).
;
; Build from the repo root after PyInstaller:
;   py -m PyInstaller unlock.spec --noconfirm
;   py -B tools/build_inno.py --version 2.1.0
;
; The version comes from the release tag via /DMyAppVersion; the fallback
; below only matters for local builds. No [Code] section on purpose: this is
; a plain copy-files installer, so install, update and uninstall are all
; owned by Windows (Apps > Installed apps > Unlock).

#ifndef MyAppVersion
#define MyAppVersion "2.1.0"
#endif
#define MyAppName "Unlock"
#define MyAppPublisher "voblya-dev"
#define MyAppExeName "Unlock.exe"
#define MyAppIcon "..\assets\unlock.ico"

[Setup]
AppId={{B3FD7F51-E195-4878-A3E7-221B0D21BE51}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoProductName={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes
OutputDir=..\dist
OutputBaseFilename=Unlock-{#MyAppVersion}-Setup
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\dist\Unlock\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
