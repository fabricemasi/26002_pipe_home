# Installe la chaine Rust (rustup, profil minimal, cible MSVC) pour le moteur photo `fm_photo/moteur_rust`.
# Reproductible et reversible : source officielle (static.rust-lang.org), somme SHA-256 verifiee, PATH NON modifie
# (les scripts du projet appellent %USERPROFILE%\.cargo\bin directement). Desinstaller : `rustup self uninstall`.
# Prerequis : Visual Studio Build Tools avec l'outillage C++ (lieur MSVC + SDK Windows).
$ErrorActionPreference = 'Stop'
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
if (Test-Path $cargo) { & $cargo --version; exit 0 }
$dir = Join-Path $env:TEMP ('rustup_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $dir | Out-Null
$exe = Join-Path $dir 'rustup-init.exe'
$base = 'https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe'
Invoke-WebRequest -Uri $base -OutFile $exe -UseBasicParsing
$sumText = (Invoke-WebRequest -Uri ($base + '.sha256') -UseBasicParsing).Content
if ($sumText -is [byte[]]) { $sumText = [Text.Encoding]::ASCII.GetString($sumText) }
$expected = ($sumText -split '\s+')[0].ToLower()
$actual = (Get-FileHash -Algorithm SHA256 $exe).Hash.ToLower()
if ($expected -ne $actual) { throw "Somme de controle de rustup-init.exe inattendue : $actual (attendu $expected)" }
& $exe -y --no-modify-path --profile minimal --default-toolchain stable --default-host x86_64-pc-windows-msvc
if ($LASTEXITCODE -ne 0) { throw "rustup-init a echoue ($LASTEXITCODE)" }
Remove-Item -Recurse -Force $dir
& $cargo --version
