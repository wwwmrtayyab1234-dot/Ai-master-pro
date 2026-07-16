[CmdletBinding()]
param(
    [switch]$NoPause
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Add-Candidate(
    [System.Collections.Generic.List[object]]$List,
    [string]$Path,
    [string[]]$LaunchArguments
) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path)) {
        return
    }
    foreach ($existing in $List) {
        if ($existing.Path -eq $Path -and (($existing.Arguments -join " ") -eq ($LaunchArguments -join " "))) {
            return
        }
    }
    $List.Add([pscustomobject]@{
        Path = $Path
        Arguments = $LaunchArguments
    })
}

function Find-CompatiblePython {
    $candidates = New-Object 'System.Collections.Generic.List[object]'

    $py = Get-Command py -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $py) {
        Add-Candidate $candidates $py.Source @("-3")
    }

    foreach ($commandName in @("python", "python3")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $command) {
            Add-Candidate $candidates $command.Source @()
        }
    }

    $patterns = @(
        (Join-Path $env:LOCALAPPDATA "Python\pythoncore-*\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python*\python.exe"),
        (Join-Path $env:ProgramFiles "Python*\python.exe")
    )
    foreach ($pattern in $patterns) {
        Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            ForEach-Object { Add-Candidate $candidates $_.FullName @() }
    }

    foreach ($candidate in $candidates) {
        try {
            $versionArguments = @($candidate.Arguments) + @("--version")
            $versionText = (& $candidate.Path @versionArguments 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -ne 0) {
                continue
            }
            if ($versionText -match "Python\s+(\d+)\.(\d+)") {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if ($major -eq 3 -and $minor -ge 11) {
                    return [pscustomobject]@{
                        Path = $candidate.Path
                        Arguments = @($candidate.Arguments)
                        Version = $versionText
                    }
                }
            }
        } catch {
            continue
        }
    }
    return $null
}

try {
    Set-Location $PSScriptRoot
    Write-Host "=============================================="
    Write-Host "AI Master Pro - First-time setup"
    Write-Host "=============================================="

    Write-Step "Detecting Python 3.11 or newer"
    $python = Find-CompatiblePython
    if ($null -eq $python) {
        throw @"
Python 3.11 or newer could not be located.
Install 64-bit Python from https://www.python.org/downloads/windows/
During installation enable "Add python.exe to PATH" and "Install launcher for all users".
Then restart VS Code and run setup_windows.bat again.
"@
    }
    Write-Host "Using $($python.Version): $($python.Path)" -ForegroundColor Green

    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Step "Creating the project virtual environment"
        $venvArguments = @($python.Arguments) + @("-m", "venv", ".venv")
        & $python.Path @venvArguments
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
            throw "Python could not create the .venv environment."
        }
    } else {
        Write-Host "Existing .venv found." -ForegroundColor Green
    }

    Write-Step "Updating pip"
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "pip update failed. Check the internet connection and run setup again."
    }

    Write-Step "Installing project packages"
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Package installation failed. Read the first red error above."
    }

    Write-Step "Checking project imports"
    & $venvPython -c "import flet, flet.cli, flet_desktop, flet_audio, flet_audio_recorder, flet_secure_storage, flet_admob_pro, groq, edge_tts; import main; print('Dependency check passed.')"
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency validation failed."
    }

    Write-Step "Running automated project tests"
    & $venvPython -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) {
        throw "Automated project tests failed."
    }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Installed packages have dependency conflicts."
    }

    $envFile = Join-Path $PSScriptRoot ".env"
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $PSScriptRoot ".env.example") $envFile
        Write-Host "Created .env from .env.example." -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "SETUP SUCCESSFUL" -ForegroundColor Green
    Write-Host "Next: open .env, add NEW rotated API keys, then run build_android_apk.bat."
    exit 0
} catch {
    Write-Host ""
    Write-Host "SETUP STOPPED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
