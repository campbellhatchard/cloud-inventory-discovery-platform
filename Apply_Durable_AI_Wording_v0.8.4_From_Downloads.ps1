[CmdletBinding()]
param(
    [string]$DownloadsPath = (Join-Path $env:USERPROFILE "Downloads"),

    [string]$RepositoryPath =
        "C:\Users\CampbellHatchard\CloudInventoryDiscovery\cloud-inventory-discovery-platform",

    [string]$InstallerRoot =
        "C:\Users\CampbellHatchard\CloudInventoryDiscovery\installers",

    [string]$BaseBranch = "staging",

    [string]$ExpectedBaseSha = "",

    [switch]$PromoteToStaging
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Version = "0.8.4"
$FeatureBranch = "feature/durable-ai-wording-v0.8.4"
$ReleaseFolder = Join-Path $InstallerRoot "v0.8.4-durable-ai-wording"
$CanonicalSourceName = "Cloud_Inventory_Discovery_Platform_v0.8.4_Source.zip"
$ImplementationPackageName = "Cloud_Inventory_Discovery_Platform_v0.8.4_Implementation_Package.zip"
$CommitMessage = "Add durable AI wording persistence and refinement lineage v0.8.4"

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$ArgumentList = @()
    )

    & $Command @ArgumentList

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Command failed with exit code {0}: {1} {2}" -f `
                $LASTEXITCODE, `
                $Command, `
                ($ArgumentList -join " ")
        )
    }
}

function Get-CanonicalDownloadName {
    param([Parameter(Mandatory = $true)][string]$Name)

    $extension = [System.IO.Path]::GetExtension($Name)
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($Name)
    $stem = $stem -replace '(?:\s*\(\d+\))+$', ''

    return $stem + $extension
}

function Stage-DownloadedFile {
    param(
        [Parameter(Mandatory = $true)][System.IO.FileInfo]$Source,
        [Parameter(Mandatory = $true)][string]$DestinationFolder
    )

    $canonicalName = Get-CanonicalDownloadName -Name $Source.Name
    $destination = Join-Path $DestinationFolder $canonicalName

    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $sourceHash = (Get-FileHash -LiteralPath $Source.FullName -Algorithm SHA256).Hash
        $targetHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash

        if ($sourceHash -eq $targetHash) {
            Remove-Item -LiteralPath $Source.FullName -Force
            Write-Host ("Already staged; removed duplicate download: {0}" -f $Source.Name)
            return
        }

        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backupName = "{0}.previous-{1}{2}" -f `
            [System.IO.Path]::GetFileNameWithoutExtension($destination), `
            $timestamp, `
            [System.IO.Path]::GetExtension($destination)

        Move-Item `
            -LiteralPath $destination `
            -Destination (Join-Path $DestinationFolder $backupName) `
            -Force
    }

    Move-Item `
        -LiteralPath $Source.FullName `
        -Destination $destination `
        -Force
}

function Test-ManifestEntry {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$FilePath
    )

    $leaf = Split-Path -Leaf $FilePath
    $expected = $null

    foreach ($line in Get-Content -LiteralPath $ManifestPath) {
        if ($line -match '^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$') {
            if ($Matches[2] -eq $leaf) {
                $expected = $Matches[1].ToLowerInvariant()
                break
            }
        }
    }

    if (-not $expected) {
        Write-Warning ("No checksum entry was found for {0}." -f $leaf)
        return
    }

    $actual = (
        Get-FileHash -LiteralPath $FilePath -Algorithm SHA256
    ).Hash.ToLowerInvariant()

    if ($actual -ne $expected) {
        throw ("Checksum validation failed for {0}." -f $leaf)
    }

    Write-Host ("Checksum confirmed: {0}" -f $leaf) -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $DownloadsPath -PathType Container)) {
    throw ("Downloads folder not found: {0}" -f $DownloadsPath)
}

if (-not (Test-Path -LiteralPath $RepositoryPath -PathType Container)) {
    throw ("Repository folder not found: {0}" -f $RepositoryPath)
}

if (-not (Test-Path -LiteralPath (Join-Path $RepositoryPath ".git") -PathType Container)) {
    throw ("The repository path is not a Git repository: {0}" -f $RepositoryPath)
}

New-Item -ItemType Directory -Path $ReleaseFolder -Force | Out-Null

$currentScript = [System.IO.Path]::GetFullPath($MyInvocation.MyCommand.Path)
Copy-Item `
    -LiteralPath $currentScript `
    -Destination (Join-Path $ReleaseFolder (Split-Path -Leaf $currentScript)) `
    -Force

Write-Step "Moving v0.8.4 release files from Downloads"

$downloads = @(
    Get-ChildItem -LiteralPath $DownloadsPath -File |
    Where-Object {
        $_.Name -like "*v0.8.4*" -and
        [System.IO.Path]::GetFullPath($_.FullName) -ne $currentScript
    }
)

foreach ($file in $downloads) {
    Stage-DownloadedFile -Source $file -DestinationFolder $ReleaseFolder
}

$sourceZipPath = Join-Path $ReleaseFolder $CanonicalSourceName

if (-not (Test-Path -LiteralPath $sourceZipPath -PathType Leaf)) {
    $implementationPackage = Get-ChildItem `
        -LiteralPath $ReleaseFolder `
        -File `
        -Filter "Cloud_Inventory_Discovery_Platform_v0.8.4_Implementation_Package*.zip" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($implementationPackage) {
        Write-Step "Extracting release artifacts from the implementation package"

        $packageTemp = Join-Path `
            ([System.IO.Path]::GetTempPath()) `
            ("ci-discovery-v084-package-{0}" -f ([guid]::NewGuid().ToString("N")))

        New-Item -ItemType Directory -Path $packageTemp -Force | Out-Null

        try {
            Expand-Archive `
                -LiteralPath $implementationPackage.FullName `
                -DestinationPath $packageTemp `
                -Force

            Get-ChildItem -LiteralPath $packageTemp -File | ForEach-Object {
                Copy-Item `
                    -LiteralPath $_.FullName `
                    -Destination (Join-Path $ReleaseFolder $_.Name) `
                    -Force
            }
        }
        finally {
            Remove-Item `
                -LiteralPath $packageTemp `
                -Recurse `
                -Force `
                -ErrorAction SilentlyContinue
        }
    }
}

if (-not (Test-Path -LiteralPath $sourceZipPath -PathType Leaf)) {
    throw @"
The v0.8.4 source ZIP was not found.

Download either:
$CanonicalSourceName

or:
$ImplementationPackageName

to:
$DownloadsPath
"@
}

$manifestPath = Get-ChildItem `
    -LiteralPath $ReleaseFolder `
    -File `
    -Filter "Cloud_Inventory_Discovery_Platform_v0.8.4_SHA256SUMS*.txt" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($manifestPath) {
    Write-Step "Validating the source package checksum"
    Test-ManifestEntry `
        -ManifestPath $manifestPath.FullName `
        -FilePath $sourceZipPath
}
else {
    Write-Warning "Checksum manifest not found. Repository validation will still run before commit."
}

Write-Step "Checking the local Git repository"

$status = & git -C $RepositoryPath status --porcelain
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read Git repository status."
}

if ($status) {
    Write-Host $status
    throw @"
The repository contains uncommitted or untracked files.
No v0.8.4 source was applied.

Review:
git -C "$RepositoryPath" status --short
"@
}

Write-Step "Fetching GitHub and verifying the v0.8.3 baseline"

Invoke-Native `
    -Command "git" `
    -ArgumentList @("-C", $RepositoryPath, "fetch", "origin", "--prune")

$baseRef = "origin/$BaseBranch"
$baseSha = (& git -C $RepositoryPath rev-parse $baseRef).Trim()

if ($LASTEXITCODE -ne 0 -or -not $baseSha) {
    throw ("Unable to resolve {0}." -f $baseRef)
}

if ($ExpectedBaseSha) {
    if ($baseSha.ToLowerInvariant() -ne $ExpectedBaseSha.ToLowerInvariant()) {
        throw @"
Baseline verification failed.

Expected:
$ExpectedBaseSha

Found:
$baseSha

The v0.8.4 package will not be applied to an unexpected baseline commit.
"@
    }
}

$baseConfig = (& git -C $RepositoryPath show "$baseRef`:app/config.py")
if ($LASTEXITCODE -ne 0 -or ($baseConfig -join "`n") -notmatch 'app_version:\s*str\s*=\s*"0\.8\.3"') {
    throw "The verified baseline does not identify itself as application version 0.8.3."
}

& git -C $RepositoryPath cat-file -e "$baseRef`:alembic/versions/h38e1f7c5a88_ai_latency_photo_intelligence.py"
if ($LASTEXITCODE -ne 0) {
    throw "The verified baseline does not contain the v0.8.3 migration h38e1f7c5a88."
}

Write-Host ("Verified baseline: {0}" -f $baseSha) -ForegroundColor Green

Write-Step ("Creating {0} from the verified v0.8.3 baseline" -f $FeatureBranch)

Invoke-Native `
    -Command "git" `
    -ArgumentList @(
        "-C",
        $RepositoryPath,
        "switch",
        "-C",
        $FeatureBranch,
        $baseRef
    )

$tempRoot = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    ("ci-discovery-v084-{0}" -f ([guid]::NewGuid().ToString("N")))

New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    Write-Step "Extracting the v0.8.4 source"

    Expand-Archive `
        -LiteralPath $sourceZipPath `
        -DestinationPath $tempRoot `
        -Force

    $sourceRoot = Join-Path $tempRoot "cloud-inventory-discovery-platform"

    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot "app\main.py") -PathType Leaf)) {
        throw "The source ZIP does not contain the expected application root."
    }

    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot "alembic\versions\i49f2a8d6b99_ai_wording_persistence.py") -PathType Leaf)) {
        throw "The source ZIP does not contain the v0.8.4 migration."
    }

    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot "tests\test_ai_wording_persistence_v084.py") -PathType Leaf)) {
        throw "The source ZIP does not contain the v0.8.4 regression suite."
    }

    $sourceConfig = Get-Content -LiteralPath (Join-Path $sourceRoot "app\config.py") -Raw
    if ($sourceConfig -notmatch 'app_version:\s*str\s*=\s*"0\.8\.4"') {
        throw "The source package does not identify itself as application version 0.8.4."
    }

    Write-Step "Applying v0.8.4 to the feature branch"

    $robocopyArgs = @(
        $sourceRoot,
        $RepositoryPath,
        "/E",
        "/R:2",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NP",
        "/XD",
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".runtime",
        "deployment-output",
        "local-storage",
        "/XF",
        ".env",
        "*.db",
        "*.sqlite",
        "*.sqlite3"
    )

    & robocopy @robocopyArgs
    $copyCode = $LASTEXITCODE

    if ($copyCode -gt 7) {
        throw ("Robocopy failed with exit code {0}." -f $copyCode)
    }

    Write-Step "Locating Windows LibreOffice"

    $libreOfficeCandidates = New-Object System.Collections.Generic.List[string]

    if ($env:ProgramFiles) {
        $libreOfficeCandidates.Add(
            (Join-Path $env:ProgramFiles "LibreOffice\program\soffice.exe")
        )
    }

    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    if ($programFilesX86) {
        $libreOfficeCandidates.Add(
            (Join-Path $programFilesX86 "LibreOffice\program\soffice.exe")
        )
    }

    $sofficeCommand = Get-Command soffice.exe -ErrorAction SilentlyContinue
    if ($sofficeCommand) {
        $libreOfficeCandidates.Add($sofficeCommand.Source)
    }

    $libreOfficePath = $libreOfficeCandidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1

    if ($libreOfficePath) {
        $env:LIBREOFFICE_PATH = $libreOfficePath
        $env:DOCUMENT_WORK_DIR = Join-Path $env:TEMP "ci-discovery-documents"

        New-Item `
            -ItemType Directory `
            -Path $env:DOCUMENT_WORK_DIR `
            -Force |
            Out-Null

        Write-Host ("LibreOffice: {0}" -f $libreOfficePath)
    }
    else {
        Write-Warning "LibreOffice was not found. Document-generation validation may fail."
    }

    Write-Step "Running complete staging validation"

    Push-Location $RepositoryPath
    try {
        & .\Deploy.ps1 `
            -Action Validate `
            -Environment staging `
            -Region ohio

        if (-not $?) {
            throw "Staging validation failed. No commit or push was performed."
        }
    }
    finally {
        Pop-Location
    }

    Write-Step "Creating the validated v0.8.4 Git commit"

    Invoke-Native `
        -Command "git" `
        -ArgumentList @("-C", $RepositoryPath, "add", "-A")

    $changes = & git -C $RepositoryPath status --porcelain

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect staged changes."
    }

    if (-not $changes) {
        throw "No v0.8.4 source changes were detected."
    }

    Invoke-Native `
        -Command "git" `
        -ArgumentList @(
            "-C",
            $RepositoryPath,
            "commit",
            "-m",
            $CommitMessage
        )

    Write-Step "Pushing the validated feature branch to GitHub"

    Invoke-Native `
        -Command "git" `
        -ArgumentList @(
            "-C",
            $RepositoryPath,
            "push",
            "-u",
            "origin",
            $FeatureBranch,
            "--force-with-lease"
        )

    if ($PromoteToStaging) {
        Write-Step "Fast-forwarding the validated build into staging"

        Invoke-Native `
            -Command "git" `
            -ArgumentList @("-C", $RepositoryPath, "fetch", "origin", "--prune")

        Invoke-Native `
            -Command "git" `
            -ArgumentList @("-C", $RepositoryPath, "switch", "staging")

        Invoke-Native `
            -Command "git" `
            -ArgumentList @(
                "-C",
                $RepositoryPath,
                "pull",
                "--ff-only",
                "origin",
                "staging"
            )

        Invoke-Native `
            -Command "git" `
            -ArgumentList @(
                "-C",
                $RepositoryPath,
                "merge",
                "--ff-only",
                $FeatureBranch
            )

        Invoke-Native `
            -Command "git" `
            -ArgumentList @(
                "-C",
                $RepositoryPath,
                "push",
                "origin",
                "staging"
            )
    }

    Write-Host "`nDurable AI Wording Persistence and Refinement Lineage v0.8.4 applied successfully." -ForegroundColor Green
    Write-Host ("Release files: {0}" -f $ReleaseFolder)
    Write-Host ("Baseline commit: {0}" -f $baseSha)
    Write-Host ("Feature branch: {0}" -f $FeatureBranch)
    Write-Host "Validation: passed"
    Write-Host "Pushed to GitHub: True"
    Write-Host ("Promoted to staging: {0}" -f [bool]$PromoteToStaging)

    & git -C $RepositoryPath log -1 --oneline
}
finally {
    Remove-Item `
        -LiteralPath $tempRoot `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue
}
