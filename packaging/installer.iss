; Inno Setup 6 script: per-user installer for the one-folder build (no admin rights needed).
; Build after PyInstaller, from the repo root, passing the version from the package:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=0.1.0 packaging\installer.iss
; (packaging\build_windows.bat and the CI workflow do this for you.)
; Output: packaging\Output\LaserControl-Setup-<version>.exe

#define AppName "Laser Control"
#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=x.y.z packaging\installer.iss
#endif
#define AppExe "LaserControl.exe"

[Setup]
AppId={{6F0E7A52-3C1B-4E7B-9C1E-5A1B7C2D9E41}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\LaserControl
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=LaserControl-Setup-{#AppVersion}
SetupIconFile=..\resources\laser_control.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[InstallDelete]
; An upgrade must not mix old and new PyInstaller runtime files.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\LaserControl\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} (simulation)"; Filename: "{app}\{#AppExe}"; Parameters: "--simulate"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
