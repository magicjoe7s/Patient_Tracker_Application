param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $projectRoot
try {
    python -m pip install -e ".[dev,release]"
    if ($LASTEXITCODE -ne 0) { throw "Release dependencies could not be installed." }

    if (-not $SkipTests) {
        python -m ruff check src tests
        if ($LASTEXITCODE -ne 0) { throw "Ruff checks failed." }
        python -m mypy src/icu_patient_tracker
        if ($LASTEXITCODE -ne 0) { throw "Mypy checks failed." }
        $pytestRoot = Join-Path ([IO.Path]::GetTempPath()) (
            "icu-patient-tracker-pytest-" + [Guid]::NewGuid().ToString("N")
        )
        try {
            python -m pytest -q --basetemp=$pytestRoot
            if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
        }
        finally {
            $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
            $resolvedPytest = [IO.Path]::GetFullPath($pytestRoot)
            if (
                $resolvedPytest.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -and
                (Split-Path $resolvedPytest -Leaf).StartsWith("icu-patient-tracker-pytest-") -and
                (Test-Path -LiteralPath $resolvedPytest)
            ) {
                Remove-Item -LiteralPath $resolvedPytest -Recurse -Force
            }
        }
    }

    $releaseBundle = Join-Path $projectRoot "dist/ICU Patient Tracker"
    if (Test-Path -LiteralPath $releaseBundle -PathType Container) {
        $bundleItems = @(
            Get-Item -LiteralPath $releaseBundle -Force
        ) + @(
            Get-ChildItem -LiteralPath $releaseBundle -Recurse -Force
        )
        foreach ($item in $bundleItems) {
            if ($item.Attributes -band [IO.FileAttributes]::ReadOnly) {
                $item.Attributes = (
                    $item.Attributes -band (-bnot [IO.FileAttributes]::ReadOnly)
                )
            }
        }
    }
    $pyInstallerWork = Join-Path ([IO.Path]::GetTempPath()) (
        "icu-patient-tracker-pyinstaller-" + [Guid]::NewGuid().ToString("N")
    )
    try {
        python -m PyInstaller `
            --clean `
            --noconfirm `
            --workpath $pyInstallerWork `
            packaging/icu_patient_tracker.spec
        if ($LASTEXITCODE -ne 0) { throw "Windows executable build failed." }
    }
    finally {
        $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        $resolvedPyInstaller = [IO.Path]::GetFullPath($pyInstallerWork)
        if (
            $resolvedPyInstaller.StartsWith(
                $resolvedTemp,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            (Split-Path $resolvedPyInstaller -Leaf).StartsWith(
                "icu-patient-tracker-pyinstaller-"
            ) -and
            (Test-Path -LiteralPath $resolvedPyInstaller)
        ) {
            Remove-Item -LiteralPath $resolvedPyInstaller -Recurse -Force
        }
    }

    $smokeRoot = Join-Path ([IO.Path]::GetTempPath()) (
        "icu-patient-tracker-smoke-" + [Guid]::NewGuid().ToString("N")
    )
    New-Item -ItemType Directory -Path $smokeRoot | Out-Null
    try {
        $executable = Join-Path $projectRoot "dist/ICU Patient Tracker/ICU Patient Tracker.exe"
        $smokeProcess = Start-Process `
            -FilePath $executable `
            -ArgumentList @("--smoke-test", $smokeRoot) `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        if ($smokeProcess.ExitCode -ne 0) {
            throw "Packaged executable smoke test failed with exit code $($smokeProcess.ExitCode)."
        }
    }
    finally {
        $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        $resolvedSmoke = [IO.Path]::GetFullPath($smokeRoot)
        if (
            $resolvedSmoke.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path $resolvedSmoke -Leaf).StartsWith("icu-patient-tracker-smoke-")
        ) {
            Remove-Item -LiteralPath $resolvedSmoke -Recurse -Force
        }
    }

    $version = python -c "from importlib.metadata import version; print(version('icu-patient-tracker'))"
    if ($LASTEXITCODE -ne 0) { throw "Installed project version could not be read." }
    $archive = Join-Path $projectRoot "dist/icu-patient-tracker-$version-windows-x64.zip"
    $archiveCreated = $false
    $archiveAttempts = 30
    for ($attempt = 1; $attempt -le $archiveAttempts; $attempt++) {
        try {
            Compress-Archive `
                -Path "dist/ICU Patient Tracker/*" `
                -DestinationPath $archive `
                -Force `
                -ErrorAction Stop
            $archiveCreated = $true
            break
        }
        catch {
            if ($attempt -eq $archiveAttempts) {
                throw "Release archive could not be created after $attempt attempts: $($_.Exception.Message)"
            }
            # Windows Defender, indexing, and the packaged smoke test can briefly
            # retain a read handle after process exit. Give those transient handles
            # up to one minute to drain before declaring the release failed.
            Start-Sleep -Seconds 2
        }
    }
    if (-not $archiveCreated) { throw "Release archive was not created." }
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        if ($zip.Entries.Count -eq 0) { throw "Release archive is empty." }
    }
    finally {
        $zip.Dispose()
    }
    $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
    "$digest  $(Split-Path $archive -Leaf)" | Set-Content -Encoding ascii "dist/SHA256SUMS.txt"

    Write-Host "Release verified: $archive"
    Write-Host "SHA-256: $digest"
}
finally {
    Pop-Location
}
