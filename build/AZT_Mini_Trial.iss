#define MyAppName "AZT Mini 14-Day Trial"
#define MyAppVersion "2.0.0"
#define MyAppExeName "AZT_Mini_Trial.exe"
[Setup]
AppId={{36D28943-15B6-45F6-AF9E-7C1065BE522A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\AZT Mini 14-Day Trial
DefaultGroupName=AZT Mini 14-Day Trial
PrivilegesRequired=lowest
OutputDir=..\dist_mini
OutputBaseFilename=AZT_Mini_14Day_Trial_Setup
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Files]
Source: "..\dist_mini\AZT_Mini_Trial.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\mini_trial\expire_uninstall.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\mini_trial\delayed_uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\mini_trial\register_expiry_task.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\AZT Mini 14-Day Trial"; Filename: "{app}\{#MyAppExeName}"

[Run]
; Windows task checks for expiration without starting an unactivated lease.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File ""{app}\register_expiry_task.ps1"" -Executable ""{app}\{#MyAppExeName}"""; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Launch AZT Mini 14-Day Trial"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ""AZT Mini 14-Day Expiry"""; Flags: runhidden; RunOnceId: "RemoveAZTMini14ExpiryTask"

[Code]
procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'This is the standalone AGORA ZION TRADER Mini evaluation. It works with your locally installed MetaTrader 5 and does not require an AZT pairing code.' + #13#10 + #13#10 +
    'Your personal 14-day access begins when the app first verifies internet UTC. The installer creates a visible current-user task that checks every 30 minutes and automatically removes the trial after it expires, when Windows is running and the app is closed.' + #13#10 + #13#10 +
    'Expiry stops new automated entries. MetaTrader 5, any broker-side orders and SL/TP, and your local trading records are deliberately preserved. Internet time checks are required for trading.';
end;
