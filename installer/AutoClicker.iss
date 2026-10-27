; Inno Setup script — builds the Windows installer for Auto Clicker.
; Build the app first (build.bat), which passes /DAppVersion=<__version__> automatically:
;   ISCC.exe /DAppVersion=1.0.1 installer\AutoClicker.iss

#ifndef AppVersion
  #define AppVersion "1.0.1"
#endif
#define AppName "Auto Clicker"
#define AppExe "AutoClicker.exe"

[Setup]
AppId={{B6F2D9A4-5C1E-4E7B-9A3D-2F8C61D7E0B5}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
AppPublisher=E7TRAF702
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=AutoClicker-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Installs per-user without admin rights; the user can still choose "all users".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\AutoClicker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// Offer to remove saved settings (%APPDATA%\AutoClicker). Silent uninstalls keep them.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if MsgBox('Also delete your saved Auto Clicker settings?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{userappdata}\AutoClicker'), True, True, True);
end;
