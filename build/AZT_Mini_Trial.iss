#define MyAppName "AZT Mini Trial"
#define MyAppVersion "1.0.0"
#define MyAppExeName "AZT_Mini_Trial.exe"
[Setup]
AppId={{9BEB38F3-4D7C-4E5D-A599-775257EBC1FD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\AZT Mini Trial
DefaultGroupName=AZT Mini Trial
PrivilegesRequired=lowest
OutputDir=..\dist_mini
OutputBaseFilename=AZT_Mini_Trial_Setup
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
[Files]
Source: "..\dist_mini\AZT_Mini_Trial.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\mini_trial\expire_uninstall.cmd"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{autoprograms}\AZT Mini Trial"; Filename: "{app}\{#MyAppExeName}"
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch AZT Mini Trial"; Flags: nowait postinstall skipifsilent
; Keep %LOCALAPPDATA%\AZT_Mini_Trial user state and MT5 trade ledgers for safety.
