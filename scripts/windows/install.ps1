param([switch]$SkipAccounts)
$ErrorActionPreference = 'Stop'
try {
    Set-Location -LiteralPath $PSScriptRoot
    $manifest = Get-Content -LiteralPath 'release.json' -Raw -Encoding UTF8 | ConvertFrom-Json
    $packageRoot = [IO.Path]::GetFullPath($PSScriptRoot) + [IO.Path]::DirectorySeparatorChar
    foreach ($entry in $manifest.files.PSObject.Properties) {
        $target = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $entry.Name))
        if (-not $target.StartsWith($packageRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Invalid release path.'
        }
        $stream = [IO.File]::OpenRead($target)
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try {
            $digest = [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
        } finally {
            $stream.Dispose()
            $algorithm.Dispose()
        }
        if ($digest -ne $entry.Value) {
            throw "Release file hash mismatch: $($entry.Name)"
        }
    }
    foreach ($tool in @('uv', 'ffmpeg', 'ffprobe')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "Install $tool and add it to PATH. See docs/PILOT_OPERATIONS.md."
        }
    }
    Set-Location -LiteralPath (Join-Path $PSScriptRoot 'backend')
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $PSScriptRoot 'backend/.venv'
    & uv sync --locked --no-dev --python 3.14
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $python = Join-Path $PSScriptRoot 'backend/.venv/Scripts/python.exe'
    & $python -X utf8 -m app.launcher --check
    if ($LASTEXITCODE -ne 0) { throw 'Installation check failed.' }
    if (-not $SkipAccounts) {
        foreach ($role in @('admin', 'developer')) {
            $account = Read-Host "New $role account name (Enter to keep existing accounts)"
            if ($account) {
                & $python -X utf8 -m app.manage create-user $account --role $role
                if ($LASTEXITCODE -ne 0) { throw 'Account provisioning failed.' }
            }
        }
    }
    Write-Host 'Installation complete. Open Start.cmd. Data: KDOG_DATA_DIR or %LOCALAPPDATA%/K-DOG/data.'
} catch {
    Write-Error $_
    exit 1
}
