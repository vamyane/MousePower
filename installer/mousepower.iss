; MousePower 安装包 — Inno Setup 7 (Win11 官方主题)
; 主题: modern dynamic windows11 → 深浅色自动跟随系统

#define MyAppName "MousePower"
#define MyAppVersion "1.0.4"
#define MyAppPublisher "MousePower Project"
#define MyAppExeName "MousePower.exe"

[Setup]
AppId={{82196D47-173F-446B-A1AC-DAB28477AB03}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName} 电量工具
WizardStyle=modern dynamic windows11
OutputBaseFilename=MousePower-Setup-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; \
    GroupDescription: "附加任务:"
Name: "autostart"; Description: "开机自动运行（推荐）"; \
    GroupDescription: "附加任务:"

[Files]
Source: "app\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#MyAppName}"; \
    ValueData: """{app}\{#MyAppExeName}"""; \
    Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM MousePower.exe"; \
    RunOnceId: "KillApp"; Flags: runhidden

[UninstallDelete]
; 配置文件保留（用户可能重装），如需彻底清理手动删除 %APPDATA%\MousePower
Type: files; Name: "{app}\mousepower_err.log"
