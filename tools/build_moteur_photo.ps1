# Construit et installe le moteur photo Rust (`fm_photo/moteur_rust`, module Python `fm_photo_moteur`) dans .venv.
# Prerequis : tools\install_rust.ps1 (chaine Rust) et `pip install maturin` dans .venv.
# Les produits de compilation vont HORS du dossier synchronise (%LOCALAPPDATA%\pipe_fmz\cargo_target).
$ErrorActionPreference = 'Stop'
$racine = Split-Path -Parent $PSScriptRoot
$python = Join-Path $racine '.venv\Scripts\python.exe'
$env:PATH = (Join-Path $env:USERPROFILE '.cargo\bin') + ';' + $env:PATH
$env:CARGO_TARGET_DIR = Join-Path $env:LOCALAPPDATA 'pipe_fmz\cargo_target'
$roues = Join-Path $env:CARGO_TARGET_DIR 'wheels'
if (Test-Path $roues) { Remove-Item -Recurse -Force $roues -Confirm:$false }
& $python -m maturin build --release --locked -m (Join-Path $racine 'fm_photo\moteur_rust\Cargo.toml') -i $python -o $roues
if ($LASTEXITCODE -ne 0) { throw "maturin build a echoue ($LASTEXITCODE)" }
$roue = Get-ChildItem $roues -Filter '*.whl' | Select-Object -First 1
& $python -m pip install --force-reinstall --no-deps $roue.FullName
if ($LASTEXITCODE -ne 0) { throw "pip install a echoue ($LASTEXITCODE)" }
& $python -c "import fm_photo_moteur; print('fm_photo_moteur', fm_photo_moteur.__version__, fm_photo_moteur.operations())"
