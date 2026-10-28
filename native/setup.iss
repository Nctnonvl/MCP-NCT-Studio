[Setup]
AppId={{5728A7EF-6F9B-4AD0-8190-31D281CE48D7}
AppName=NCT Studio
AppVersion=1.1.4
AppPublisher=NCT Studio
DefaultDirName={localappdata}\Programs\NCT Studio
DefaultGroupName=NCT Studio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
DisableProgramGroupPage=yes
WizardStyle=modern
WizardSizePercent=115
WizardImageFile=wizard.bmp
WizardSmallImageFile=wizard-small.bmp
SetupIconFile=..\output\NCT-Studio-Portable\studio.ico
UninstallDisplayIcon={app}\NCT Studio.exe
OutputDir=..\output
OutputBaseFilename=NCT-Studio-Setup
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng NCT Studio trên Desktop"; GroupDescription: "Lối tắt:"

[Files]
Source: "..\output\NCT-Studio-Portable\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "portable.mode,data\*,WebView\*,__pycache__\*"
Source: "..\tools\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\NCT Studio"; Filename: "{app}\NCT Studio.exe"
Name: "{autodesktop}\NCT Studio"; Filename: "{app}\NCT Studio.exe"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2..."; Flags: waituntilterminated; Check: NeedsWebView
Filename: "{app}\NCT Studio.exe"; Description: "Mở NCT Studio"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebView(Base: String): Boolean;
var Find: TFindRec;
begin
 Result := False;
 if FindFirst(Base + '\*', Find) then begin
  try
   repeat
    if FileExists(Base + '\' + Find.Name + '\msedgewebview2.exe') then Result := True;
   until Result or not FindNext(Find);
  finally FindClose(Find); end;
 end;
end;
function NeedsWebView: Boolean;
begin
 Result := not (HasWebView(ExpandConstant('{commonpf32}\Microsoft\EdgeWebView\Application')) or HasWebView(ExpandConstant('{localappdata}\Microsoft\EdgeWebView\Application')));
end;
