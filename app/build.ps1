# Monta o programa da SHIRO no Windows: dependências, fontes, modelo 3D, compilação e atalho.
# Uso, na pasta do projeto:  powershell -ExecutionPolicy Bypass -File app\build.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path pubspec.yaml)) {
    Set-Location ..
    Move-Item app app-src
    flutter create --platforms=windows,android --org dev.shiro --project-name shiro_app app
    Copy-Item app-src\* app -Recurse -Force
    Remove-Item app-src -Recurse -Force
    Remove-Item app\test\widget_test.dart -ErrorAction SilentlyContinue
    Set-Location app
}

Get-Process shiro_app -ErrorAction SilentlyContinue | Stop-Process -Force
flutter pub add qr_flutter webview_windows | Out-Null

# Fontes da identidade (ADR-0012), licença OFL.
New-Item -ItemType Directory -Force fonts | Out-Null
$base = 'https://raw.githubusercontent.com/google/fonts/main/ofl'
$files = @{
    'ChakraPetch-Light.ttf'    = 'chakrapetch/ChakraPetch-Light.ttf'
    'ChakraPetch-Regular.ttf'  = 'chakrapetch/ChakraPetch-Regular.ttf'
    'ChakraPetch-Medium.ttf'   = 'chakrapetch/ChakraPetch-Medium.ttf'
    'ChakraPetch-SemiBold.ttf' = 'chakrapetch/ChakraPetch-SemiBold.ttf'
    'JetBrainsMono.ttf'        = 'jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf'
}
foreach ($name in $files.Keys) {
    if (-not (Test-Path "fonts\$name")) { Invoke-WebRequest "$base/$($files[$name])" -OutFile "fonts\$name" }
}

# pubspec: a tela do avatar e as fontes.
$pubspec = Get-Content pubspec.yaml -Raw
if ($pubspec -notmatch 'family: Chakra Petch') {
    $block = @'
  uses-material-design: true
  assets:
    - assets/avatar.html
  fonts:
    - family: Chakra Petch
      fonts:
        - asset: fonts/ChakraPetch-Light.ttf
          weight: 300
        - asset: fonts/ChakraPetch-Regular.ttf
          weight: 400
        - asset: fonts/ChakraPetch-Medium.ttf
          weight: 500
        - asset: fonts/ChakraPetch-SemiBold.ttf
          weight: 600
    - family: JetBrains Mono
      fonts:
        - asset: fonts/JetBrainsMono.ttf
'@
    $pubspec = $pubspec -replace '(?m)^  uses-material-design: true\s*$', $block
    Set-Content pubspec.yaml $pubspec -Encoding utf8
}

# Título da janela.
$runner = 'windows\runner\main.cpp'
(Get-Content $runner -Raw) -replace 'L"shiro_app"', 'L"SHIRO"' | Set-Content $runner -Encoding utf8

# O modelo 3D exportado do VRoid Studio vai para a pasta de dados dela.
$avatar = Join-Path $env:LOCALAPPDATA 'SHIRO\avatar'
New-Item -ItemType Directory -Force $avatar | Out-Null
$model = @([Environment]::GetFolderPath('MyDocuments'), "$HOME\Documents", "$HOME\OneDrive\Documentos") |
    ForEach-Object { Join-Path $_ 'SHIRO.vrm' } | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($model) { Copy-Item $model (Join-Path $avatar 'SHIRO.vrm') -Force; "modelo 3D: $model" }
else { 'modelo 3D: SHIRO.vrm não encontrado em Documentos (o programa usa o núcleo no lugar)' }

flutter build windows --release
$exe = Join-Path $PSScriptRoot 'build\windows\x64\runner\Release\shiro_app.exe'
$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'SHIRO.lnk'))
$link.TargetPath = $exe
$link.WorkingDirectory = Split-Path $exe
$link.Save()
"pronto: $exe"
