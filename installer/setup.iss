; Inno Setup Script para ArchiveConverter
; Requiere Inno Setup 6 (https://jrsoftware.org/isdl.php)

#define MyAppName "ArchiveConverter"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "ArchiveConverter Open Source"
#define MyAppURL "https://github.com"
#define MyAppExeName "ArchiveConverter.exe"

[Setup]
; Identificador de aplicación único
AppId={{5F7C7A28-D9E4-4284-9694-87A29E4C93B1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
; Licencia
LicenseFile=..\LICENSE
; Carpeta de salida para el instalador generado
OutputDir=..\dist_installer
OutputBaseFilename=ArchiveConverter-Setup-v{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Incluye todos los archivos generados por PyInstaller en dist\ArchiveConverter
Source: "..\dist\ArchiveConverter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
