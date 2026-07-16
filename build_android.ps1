[CmdletBinding()]
param(
    [ValidateSet("apk", "aab")]
    [string]$Target = "apk"
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-AndroidSdk([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }
    return (
        (Test-Path (Join-Path $Path "platform-tools")) -and
        (Test-Path (Join-Path $Path "platforms")) -and
        (Test-Path (Join-Path $Path "build-tools"))
    )
}

function Copy-Directory([string]$Source, [string]$Destination, [string]$Label) {
    Write-Step "Copying $Label to a path without spaces"
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy.exe $Source $Destination /E /R:2 /W:1 /NFL /NDL /NP
    $code = $LASTEXITCODE
    if ($code -gt 7) {
        throw "$Label copy failed. Robocopy exit code: $code"
    }
}

function Find-FlutterBat([string]$DevToolsRoot) {
    $command = Get-Command flutter -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command -and (Test-Path $command.Source)) {
        return $command.Source
    }

    $searchRoots = @(
        (Join-Path $DevToolsRoot "flutter"),
        (Join-Path $DevToolsRoot "FlutterSdk"),
        (Join-Path $env:USERPROFILE "flutter")
    )
    foreach ($root in $searchRoots) {
        if (-not (Test-Path $root)) {
            continue
        }
        $match = Get-ChildItem -Path $root -Filter "flutter.bat" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Directory.Name -eq "bin" } |
            Select-Object -First 1
        if ($null -ne $match) {
            return $match.FullName
        }
    }
    return $null
}

function Add-UserPathEntry([string]$Entry) {
    if ([string]::IsNullOrWhiteSpace($Entry)) {
        return
    }
    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if (-not [string]::IsNullOrWhiteSpace($current)) {
        $parts = @($current -split ";" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }
    if ($parts -notcontains $Entry) {
        $updated = (@($Entry) + $parts) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $updated, "User")
    }
}

try {
    $projectRoot = (Resolve-Path $PSScriptRoot).Path.TrimEnd("\")
    if ($projectRoot -match "\s") {
        throw @"
The project path contains spaces:
$projectRoot

Extract/copy the supplied folder to exactly:
D:\AMP\AI_Master_Pro_Full_MVP

Then open that folder in VS Code and run build_android_apk.bat again.
"@
    }

    $driveRoot = [System.IO.Path]::GetPathRoot($projectRoot)
    $devToolsRoot = Join-Path $driveRoot "DevTools"
    New-Item -ItemType Directory -Force -Path $devToolsRoot | Out-Null

    Write-Step "Locating Flutter"
    $flutterBat = Find-FlutterBat $devToolsRoot
    if ([string]::IsNullOrWhiteSpace($flutterBat)) {
        throw "Flutter was not found. Install Flutter once, or place it under $devToolsRoot\flutter."
    }

    $flutterBin = Split-Path $flutterBat -Parent
    $flutterRoot = Split-Path $flutterBin -Parent
    if ($flutterRoot -match "\s") {
        $safeFlutterRoot = Join-Path $devToolsRoot "FlutterSdk"
        Copy-Directory $flutterRoot $safeFlutterRoot "Flutter SDK"
        $flutterRoot = $safeFlutterRoot
        $flutterBin = Join-Path $flutterRoot "bin"
        $flutterBat = Join-Path $flutterBin "flutter.bat"
    }
    if (-not (Test-Path $flutterBat)) {
        throw "Flutter executable was not found at $flutterBat"
    }

    Write-Step "Locating Android SDK"
    $safeSdk = Join-Path $devToolsRoot "Android\Sdk"
    $candidates = @(
        $safeSdk,
        $env:ANDROID_SDK_ROOT,
        $env:ANDROID_HOME,
        (Join-Path $env:LOCALAPPDATA "Android\Sdk"),
        "C:\Android\Sdk"
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique

    $sourceSdk = $null
    foreach ($candidate in $candidates) {
        if (Test-AndroidSdk $candidate) {
            $sourceSdk = (Resolve-Path $candidate).Path
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($sourceSdk)) {
        throw @"
Android SDK files were not found.
Open Android Studio > SDK Manager and install:
- Android SDK Platform
- Android SDK Build-Tools
- Android SDK Platform-Tools

After installation, run this build file again. It will copy the SDK automatically.
"@
    }

    if ($sourceSdk -match "\s") {
        Copy-Directory $sourceSdk $safeSdk "Android SDK"
        $androidSdk = $safeSdk
    } else {
        $androidSdk = $sourceSdk
    }
    if (-not (Test-AndroidSdk $androidSdk)) {
        throw "Android SDK is incomplete at $androidSdk"
    }

    $pubCache = Join-Path $devToolsRoot "PubCache"
    $gradleCache = Join-Path $devToolsRoot "GradleCache"
    $tempRoot = Join-Path $devToolsRoot "Temp"
    New-Item -ItemType Directory -Force -Path $pubCache, $gradleCache, $tempRoot | Out-Null

    $platformTools = Join-Path $androidSdk "platform-tools"
    $env:PATH = "$flutterBin;$platformTools;$env:PATH"
    $env:FLUTTER_ROOT = $flutterRoot
    $env:ANDROID_HOME = $androidSdk
    $env:ANDROID_SDK_ROOT = $androidSdk
    $env:PUB_CACHE = $pubCache
    $env:GRADLE_USER_HOME = $gradleCache
    $env:TEMP = $tempRoot
    $env:TMP = $tempRoot
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    try {
        [Environment]::SetEnvironmentVariable("ANDROID_HOME", $androidSdk, "User")
        [Environment]::SetEnvironmentVariable("ANDROID_SDK_ROOT", $androidSdk, "User")
        [Environment]::SetEnvironmentVariable("PUB_CACHE", $pubCache, "User")
        [Environment]::SetEnvironmentVariable("GRADLE_USER_HOME", $gradleCache, "User")
        Add-UserPathEntry $platformTools
        Add-UserPathEntry $flutterBin
    } catch {
        Write-Warning "The build can continue, but Windows user environment variables could not be saved permanently."
    }

    Write-Step "Configuring Flutter Android SDK"
    & $flutterBat config --android-sdk $androidSdk
    if ($LASTEXITCODE -ne 0) {
        throw "Flutter could not configure the Android SDK."
    }

    $fletExe = Join-Path $projectRoot ".venv\Scripts\flet.exe"
    if (-not (Test-Path $fletExe)) {
        throw "Project environment is missing. Run setup_windows.bat first."
    }
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

    Write-Step "Running pre-build project verification"
    Set-Location $projectRoot
    & $venvPython -m compileall -q main.py config.py services tests
    if ($LASTEXITCODE -ne 0) {
        throw "Python source validation failed."
    }
    & $venvPython -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) {
        throw "Automated tests failed. The Android build was not started."
    }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Installed packages have dependency conflicts."
    }
    if ($Target -eq "aab") {
        Write-Step "Checking Play Store production configuration"
        & $venvPython release_check.py
        if ($LASTEXITCODE -ne 0) {
            throw "The AAB release check failed. Fix every item listed above."
        }
    }

    Write-Step "Building Android $($Target.ToUpperInvariant())"
    & $fletExe build $Target --clear-cache
    if ($LASTEXITCODE -ne 0) {
        throw "Flet returned exit code $LASTEXITCODE. Read the first red error above this message."
    }

    $extension = if ($Target -eq "apk") { "*.apk" } else { "*.aab" }
    $artifact = Get-ChildItem -Path (Join-Path $projectRoot "build") -Filter $extension -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $artifact) {
        throw "Build finished but the $Target output file could not be located."
    }

    $releaseDirectory = Join-Path $projectRoot "release"
    New-Item -ItemType Directory -Force -Path $releaseDirectory | Out-Null
    $releaseName = if ($Target -eq "apk") { "AI_Master_Pro.apk" } else { "AI_Master_Pro.aab" }
    $releasePath = Join-Path $releaseDirectory $releaseName
    Copy-Item -Path $artifact.FullName -Destination $releasePath -Force

    Write-Host ""
    Write-Host "BUILD SUCCESSFUL" -ForegroundColor Green
    Write-Host "Output: $releasePath" -ForegroundColor Green
    exit 0
} catch {
    Write-Host ""
    Write-Host "BUILD STOPPED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
