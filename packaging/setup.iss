; Inno Setup script for the Store Master Normalizer.
;
; Build with the Inno Setup compiler (ISCC.exe):
;
;     ISCC.exe packaging\setup.iss
;
; This expects the PyInstaller --onedir output already exists at
; dist\StoreMasterTool\.  Output lands at dist\StoreMasterTool-Setup.exe.

#define MyAppName        "Store Master Normalizer"
#define MyAppVersion     "0.4.0"
#define MyAppPublisher   "Internal Tool"
#define MyAppExeName     "StoreMasterTool.exe"
#define MyAppShortcut    "Store Master Normalizer"

[Setup]
AppId={{C9F2A3B7-1D8E-4F0B-8A7C-2E5A9B8C4D11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\StoreMasterTool
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\dist
OutputBaseFilename=StoreMasterTool-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
  GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
; PyInstaller --onedir output: copy the entire folder.
Source: "..\dist\StoreMasterTool\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppShortcut}"; Filename: "{app}\{#MyAppExeName}"; \
  IconFilename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppShortcut}"; Filename: "{app}\{#MyAppExeName}"; \
  IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Launch {#MyAppName} now"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Wipe temp/ on uninstall so we don't leave operator data on disk.
Type: filesandordirs; Name: "{app}\temp"
