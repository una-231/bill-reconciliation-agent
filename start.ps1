$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.venv/Scripts/python.exe')) { python -m venv .venv }
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
& $taskPython -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
if (!(Test-Path -LiteralPath 'models/active.joblib')) {
    & $taskPython scripts/generate_data.py
    & $taskPython scripts/train.py
    if ($LASTEXITCODE -ne 0) { throw '模型训练失败' }
}
Push-Location frontend
try {
    npm ci
    npm run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally { Pop-Location }
& $taskPython run.py
