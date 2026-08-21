#define MyAppName "GameCoin Mainnet"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "EmilyGaming"
#define MyAppURL "https://emilygaming.com/gamecoin/"
#define MyAppExeName "GameCoinMainnetWallet.exe"

[Setup]
AppId={{A8AA5DB8-680A-4E13-93D5-9C3E5E55C7FA}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\GameCoin Mainnet
DefaultGroupName=GameCoin Mainnet
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=GameCoin-Setup-v1.0.0-Mainnet
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes
VersionInfoVersion=1.0.0.0
VersionInfoTextVersion=1.0.0
VersionInfoProductVersion=1.0.0.0
VersionInfoProductTextVersion=1.0.0
VersionInfoCompany=EmilyGaming
VersionInfoDescription=GameCoin Mainnet Setup
VersionInfoProductName=GameCoin Mainnet
VersionInfoCopyright=Copyright (c) 2026 EmilyGaming
VersionInfoOriginalFileName=GameCoin-Setup-v1.0.0-Mainnet.exe
SetupIconFile=..\assets\gamecoin_protocol_mark.ico

[Files]
Source: "..\dist\GameCoinMainnetWallet.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\GameCoinMainnetNode.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\GameCoinMainnetMiner.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\FIRST_RUN.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SECURITY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\DISCLAIMER.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\MAINNET_GENESIS.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\RELEASE_NOTES-v1.0.0.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\gamecoin_protocol_mark.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "..\assets\gamecoin_protocol_full.png"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\GameCoin Mainnet"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\GameCoin Mainnet"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch GameCoin Mainnet"; Flags: nowait postinstall skipifsilent


[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { v0.7.x could occasionally leave the background node running after the
    wallet window closed. Stop node/miner processes before replacing binaries. }
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /T /IM GameCoinMainnetMiner.exe >NUL 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /T /IM GameCoinMainnetNode.exe >NUL 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
