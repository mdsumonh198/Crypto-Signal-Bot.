# Windows convenience launcher. Default is a single safe, signal-only scan.
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskPrefix = @()
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($taskLauncher) {
        $taskPython = $taskLauncher.Source
        $taskPrefix = @('-3')
    } else {
        $taskPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (-not (Test-Path -LiteralPath $taskPython)) {
            throw 'Install Python 3.11+ and create .venv as described in README.md.'
        }
    }
}
$taskArguments = @($args)
if ($taskArguments.Count -eq 0) {
    $taskArguments = @('scan', '--once', '--no-paper')
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $taskPython @taskPrefix -m scanner @taskArguments
    $taskExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $taskExitCode
