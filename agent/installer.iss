; Inno Setup script for BuildHarvey Windows installer.
; Usage: iscc /DMyAppVersion=1.0.0 installer.iss
;
; Output: Output\BuildHarveySetup-{version}.exe
;
; Note: Windows SmartScreen will warn on the first run of a new version.
; Instruct users: click "More info" → "Run anyway".

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppName=BuildHarvey
AppVersion={#MyAppVersion}
AppPublisher=BuildHarvey
DefaultDirName={autopf}\BuildHarvey
DefaultGroupName=BuildHarvey
OutputBaseFilename=BuildHarveySetup-{#MyAppVersion}
OutputDir=Output
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\BuildHarvey.exe
; Require only user-level install (no admin rights needed)
PrivilegesRequired=lowest
; Allow reinstall without uninstalling first
AllowCancelDuringInstall=yes

[Files]
Source: "dist\BuildHarvey\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\BuildHarvey"; Filename: "{app}\BuildHarvey.exe"
Name: "{commondesktop}\BuildHarvey"; Filename: "{app}\BuildHarvey.exe"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\BuildHarvey.exe"; Description: "Launch BuildHarvey"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Attempt graceful quit before uninstall
Filename: "{app}\BuildHarvey.exe"; Parameters: "--quit"; Flags: skipifdoesntexist runhidden

[Code]
// User data at ~/.buildharvey/ is preserved by default on reinstall and uninstall.
// Only deleted if the user manually removes it.
