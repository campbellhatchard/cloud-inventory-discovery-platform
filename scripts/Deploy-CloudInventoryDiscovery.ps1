<#
.SYNOPSIS
Builds, validates, publishes, and deploys the Cloud Inventory Site Discovery Platform.

.DESCRIPTION
The script is staging-first and performs validation in a temporary copy before it
changes Git history or pushes to GitHub. It generates an environment-specific
Render Blueprint from render.template.yaml, runs application tests, validates the
Blueprint when the Render CLI or API is available, pushes to GitHub, and opens the
Render Blueprint deployment flow.

Initial Blueprint creation requires an authenticated browser because Render must
be authorized to access the Git repository. Secret values remain outside Git and
are written only to an ignored local handoff file when deployment is requested.

.EXAMPLE
./Deploy.ps1 -Action Deploy -Environment staging -GitHubOwner campbellhatchard

.EXAMPLE
$env:RENDER_API_KEY = "..."
$env:RENDER_WORKSPACE_ID = "tea-..."
./Deploy.ps1 -Action Redeploy -Environment staging -WebServiceId srv-... -WorkerServiceId srv-...
#>

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateSet('Validate', 'Publish', 'Deploy', 'Redeploy')]
    [string]$Action = 'Deploy',

    [ValidateSet('staging', 'production')]
    [string]$Environment = 'staging',

    [string]$GitHubOwner = $env:GITHUB_OWNER,
    [string]$RepositoryName = 'cloud-inventory-discovery-platform',

    [ValidateSet('private', 'public', 'internal')]
    [string]$RepositoryVisibility = 'private',

    [string]$Branch,
    [string]$CommitMessage = 'Deploy Cloud Inventory Discovery Platform',
    [string]$GitAuthorName = $env:GIT_AUTHOR_NAME,
    [string]$GitAuthorEmail = $env:GIT_AUTHOR_EMAIL,

    [ValidateSet('oregon', 'ohio', 'virginia', 'frankfurt', 'singapore')]
    [string]$Region = 'ohio',

    [ValidateSet('starter', 'standard', 'pro', 'pro plus', 'pro max', 'pro ultra')]
    [string]$ServicePlan = 'starter',

    [ValidateSet('basic-256mb', 'basic-1gb', 'basic-4gb', 'pro-4gb', 'pro-8gb', 'pro-16gb', 'pro-32gb')]
    [string]$DatabasePlan = 'basic-256mb',

    [ValidateRange(1, 1024)]
    [int]$DatabaseDiskSizeGB = 5,

    [string]$SecretsFile,
    [string]$RenderWorkspaceId = $env:RENDER_WORKSPACE_ID,
    [string]$WebServiceId = $env:RENDER_WEB_SERVICE_ID,
    [string]$WorkerServiceId = $env:RENDER_WORKER_SERVICE_ID,

    [switch]$SkipTests,
    [switch]$SkipGitHubPush,
    [switch]$SkipGitHubChecks,
    [switch]$BuildDockerImage,
    [switch]$NoBrowser,
    [switch]$NonInteractive,
    [switch]$KeepSecretHandoff,
    [switch]$ConfirmProduction,
    [switch]$ClearBuildCache,
    [switch]$DryRun,

    [ValidateRange(60, 3600)]
    [int]$HealthTimeoutSeconds = 900,

    [ValidateRange(60, 3600)]
    [int]$GitHubChecksTimeoutSeconds = 900
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepositoryRoot = if (Test-Path (Join-Path $ScriptDirectory 'render.template.yaml')) {
    $ScriptDirectory
}
else {
    Split-Path -Parent $ScriptDirectory
}
if (-not (Test-Path (Join-Path $RepositoryRoot 'render.template.yaml'))) {
    throw 'Run the deployment script from the extracted repository, either at its root or from the scripts directory.'
}
$DeploymentOutput = Join-Path $RepositoryRoot 'deployment-output'
$RenderApiBase = 'https://api.render.com/v1'
$script:RenderApiKey = $env:RENDER_API_KEY

if ($PSVersionTable.PSVersion.Major -lt 5 -or ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -lt 1)) {
    throw 'PowerShell 5.1 or PowerShell 7+ is required.'
}
if ($PSVersionTable.PSEdition -eq 'Desktop') {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}
if ([string]::IsNullOrWhiteSpace($Branch)) {
    $Branch = if ($Environment -eq 'staging') { 'staging' } else { 'main' }
}

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Notice {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Gray
}

function Write-Caution {
    param([string]$Message)
    Write-Warning $Message
}

function Test-IsWindows {
    return ($env:OS -eq 'Windows_NT')
}

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $false)][string[]]$Arguments = @(),
        [Parameter(Mandatory = $false)][string]$WorkingDirectory = $RepositoryRoot,
        [switch]$CaptureOutput,
        [switch]$AllowFailure
    )

    $display = $Command + ' ' + (($Arguments | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }) -join ' ')

    if ($DryRun) {
        Write-Notice "DRY RUN: $display"
        if ($CaptureOutput) { return '' }
        return
    }

    Push-Location $WorkingDirectory
    try {
        if ($CaptureOutput) {
            $output = & $Command @Arguments 2>&1
            $exitCode = $LASTEXITCODE
            if ($exitCode -ne 0) {
                if ($AllowFailure) { return '' }
                throw "Command failed with exit code ${exitCode}: $display`n$($output -join [Environment]::NewLine)"
            }
            return ($output -join [Environment]::NewLine)
        }

        & $Command @Arguments
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0 -and -not $AllowFailure) {
            throw "Command failed with exit code ${exitCode}: $display"
        }
    }
    finally {
        Pop-Location
    }
}

function Assert-Command {
    param([string]$Name, [string]$InstallHint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found. $InstallHint"
    }
}

function ConvertTo-PlainText {
    param([Security.SecureString]$SecureString)
    if ($null -eq $SecureString) { return '' }
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function New-CryptographicPassword {
    param([int]$Length = 28)
    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%*-_+='
    $bytes = New-Object byte[] $Length
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    $chars = New-Object char[] $Length
    for ($index = 0; $index -lt $Length; $index++) {
        $chars[$index] = $alphabet[$bytes[$index] % $alphabet.Length]
    }
    return -join $chars
}

function Read-DotEnvFile {
    param([string]$Path)
    $values = @{}
    if (-not $Path -or -not (Test-Path $Path)) { return $values }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $separator = $trimmed.IndexOf('=')
        if ($separator -lt 1) { continue }
        $key = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Get-ConfiguredValue {
    param(
        [hashtable]$Values,
        [string]$Key,
        [string]$Prompt,
        [switch]$Secret,
        [switch]$Optional,
        [string]$DefaultValue = ''
    )

    if ($Values.ContainsKey($Key) -and -not [string]::IsNullOrWhiteSpace([string]$Values[$Key])) {
        return [string]$Values[$Key]
    }

    $environmentValue = [Environment]::GetEnvironmentVariable($Key)
    if (-not [string]::IsNullOrWhiteSpace($environmentValue)) {
        return $environmentValue
    }

    if ($NonInteractive) {
        if ($Optional) { return $DefaultValue }
        throw "Required deployment value $Key is missing. Supply it in -SecretsFile or as an environment variable."
    }

    if ($Secret) {
        $secure = Read-Host $Prompt -AsSecureString
        $plain = ConvertTo-PlainText $secure
        if ([string]::IsNullOrWhiteSpace($plain)) {
            if ($Optional) { return $DefaultValue }
            throw "$Key cannot be blank."
        }
        return $plain
    }

    $suffix = if ($DefaultValue) { " [$DefaultValue]" } else { '' }
    $entered = Read-Host ($Prompt + $suffix)
    if ([string]::IsNullOrWhiteSpace($entered)) {
        if ($DefaultValue) { return $DefaultValue }
        if ($Optional) { return '' }
        throw "$Key cannot be blank."
    }
    return $entered.Trim()
}

function Get-DeploymentSecrets {
    param([string]$Path)
    $source = Read-DotEnvFile $Path
    $values = @{}

    $values['BOOTSTRAP_ADMIN_EMAIL'] = Get-ConfiguredValue $source 'BOOTSTRAP_ADMIN_EMAIL' 'Bootstrap administrator email'

    $existingPassword = ''
    if ($source.ContainsKey('BOOTSTRAP_ADMIN_PASSWORD')) { $existingPassword = [string]$source['BOOTSTRAP_ADMIN_PASSWORD'] }
    if ([string]::IsNullOrWhiteSpace($existingPassword)) { $existingPassword = [Environment]::GetEnvironmentVariable('BOOTSTRAP_ADMIN_PASSWORD') }
    if ([string]::IsNullOrWhiteSpace($existingPassword)) {
        if ($NonInteractive) {
            throw 'BOOTSTRAP_ADMIN_PASSWORD is required in non-interactive mode.'
        }
        $answer = Read-Host 'Press ENTER to generate a strong bootstrap password, or type S to supply one'
        if ($answer -match '^[sS]$') {
            $existingPassword = ConvertTo-PlainText (Read-Host 'Bootstrap administrator password' -AsSecureString)
            if ([string]::IsNullOrWhiteSpace($existingPassword)) { throw 'BOOTSTRAP_ADMIN_PASSWORD cannot be blank.' }
        }
        else {
            $existingPassword = New-CryptographicPassword
            Write-Caution 'A strong bootstrap administrator password was generated. It will be written only to the ignored local handoff file.'
        }
    }
    if ($existingPassword.Length -lt 16) {
        throw 'BOOTSTRAP_ADMIN_PASSWORD must contain at least 16 characters.'
    }
    if ($existingPassword -ceq ('CloudInventory' + '2026!')) {
        throw 'The previously supplied example administrator password is prohibited. Use a unique generated secret.'
    }
    $values['BOOTSTRAP_ADMIN_PASSWORD'] = $existingPassword

    $values['S3_ENDPOINT'] = Get-ConfiguredValue $source 'S3_ENDPOINT' 'Private S3-compatible endpoint'
    $values['S3_BUCKET'] = Get-ConfiguredValue $source 'S3_BUCKET' 'Private object-storage bucket name'
    $values['S3_REGION'] = Get-ConfiguredValue $source 'S3_REGION' 'Object-storage region' -Optional -DefaultValue 'auto'
    $values['S3_ACCESS_KEY_ID'] = Get-ConfiguredValue $source 'S3_ACCESS_KEY_ID' 'Object-storage access key ID'
    $values['S3_SECRET_ACCESS_KEY'] = Get-ConfiguredValue $source 'S3_SECRET_ACCESS_KEY' 'Object-storage secret access key' -Secret

    $values['OPENAI_API_KEY'] = Get-ConfiguredValue $source 'OPENAI_API_KEY' 'OpenAI API key (optional; press ENTER to leave disabled)' -Secret -Optional
    $values['OPENAI_PROJECT_ID'] = Get-ConfiguredValue $source 'OPENAI_PROJECT_ID' 'OpenAI project ID (optional)' -Optional
    $values['AI_ENABLED'] = Get-ConfiguredValue $source 'AI_ENABLED' 'Enable AI now? true/false' -Optional -DefaultValue 'false'
    $values['AI_CONFIDENTIAL_CONTENT_ENABLED'] = Get-ConfiguredValue $source 'AI_CONFIDENTIAL_CONTENT_ENABLED' 'Allow confidential report content to be sent to AI? true/false' -Optional -DefaultValue 'false'
    $values['OPENAI_DATA_CONTROL_MODE'] = Get-ConfiguredValue $source 'OPENAI_DATA_CONTROL_MODE' 'OpenAI data-control mode' -Optional -DefaultValue 'standard-disabled-for-confidential'

    if ($values['AI_ENABLED'].ToLowerInvariant() -eq 'true' -and [string]::IsNullOrWhiteSpace($values['OPENAI_API_KEY'])) {
        throw 'AI_ENABLED=true requires OPENAI_API_KEY.'
    }
    if ($values['AI_CONFIDENTIAL_CONTENT_ENABLED'].ToLowerInvariant() -eq 'true' -and $values['OPENAI_DATA_CONTROL_MODE'] -ne 'zero_data_retention') {
        throw 'Confidential AI processing requires OPENAI_DATA_CONTROL_MODE=zero_data_retention.'
    }

    return $values
}

function Protect-LocalSecretFile {
    param([string]$Path)
    if (-not (Test-IsWindows)) { return }
    $icacls = Get-Command icacls.exe -ErrorAction SilentlyContinue
    if (-not $icacls) { return }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & $icacls.Source $Path '/inheritance:r' "/grant:r" "${identity}:(R,W)" | Out-Null
}

function Quote-DotEnvValue {
    param([string]$Value)
    if ($null -eq $Value) { return '""' }
    $escaped = $Value.Replace('\', '\\').Replace('"', '\"').Replace("`r", '').Replace("`n", '\n')
    return '"' + $escaped + '"'
}

function Write-SecretHandoff {
    param([hashtable]$Values)
    if (-not (Test-Path $DeploymentOutput)) {
        New-Item -ItemType Directory -Path $DeploymentOutput -Force | Out-Null
    }
    $path = Join-Path $DeploymentOutput "render-secrets.$Environment.env"
    $lines = @(
        '# LOCAL SECRET HANDOFF - DO NOT COMMIT',
        "# Environment: $Environment",
        '# Enter BOOTSTRAP_ADMIN_* and S3_* values when Render prompts for sync:false variables.',
        '# Optional OPENAI_* values are applied through the API or configured later in the Render Dashboard.',
        "BOOTSTRAP_ADMIN_EMAIL=$(Quote-DotEnvValue $Values['BOOTSTRAP_ADMIN_EMAIL'])",
        "BOOTSTRAP_ADMIN_PASSWORD=$(Quote-DotEnvValue $Values['BOOTSTRAP_ADMIN_PASSWORD'])",
        "S3_ENDPOINT=$(Quote-DotEnvValue $Values['S3_ENDPOINT'])",
        "S3_BUCKET=$(Quote-DotEnvValue $Values['S3_BUCKET'])",
        "S3_REGION=$(Quote-DotEnvValue $Values['S3_REGION'])",
        "S3_ACCESS_KEY_ID=$(Quote-DotEnvValue $Values['S3_ACCESS_KEY_ID'])",
        "S3_SECRET_ACCESS_KEY=$(Quote-DotEnvValue $Values['S3_SECRET_ACCESS_KEY'])",
        "OPENAI_API_KEY=$(Quote-DotEnvValue $Values['OPENAI_API_KEY'])",
        "OPENAI_PROJECT_ID=$(Quote-DotEnvValue $Values['OPENAI_PROJECT_ID'])"
    )
    Set-Content -LiteralPath $path -Value $lines -Encoding UTF8
    Protect-LocalSecretFile $path
    return $path
}

function Assert-ProductionSafety {
    if ($Environment -ne 'production') { return }
    if (-not $ConfirmProduction) {
        throw 'Production deployment is blocked by default. Re-run with -ConfirmProduction after staging has passed the proving checklist.'
    }
    if ($NonInteractive) {
        if ($env:PRODUCTION_DEPLOY_CONFIRMATION -cne 'DEPLOY PRODUCTION') {
            throw 'Non-interactive production deployment requires PRODUCTION_DEPLOY_CONFIRMATION=DEPLOY PRODUCTION.'
        }
        return
    }
    $confirmation = Read-Host 'Type DEPLOY PRODUCTION to continue'
    if ($confirmation -cne 'DEPLOY PRODUCTION') {
        throw 'Production deployment cancelled.'
    }
}

function Get-ResourceNames {
    $suffix = if ($Environment -eq 'staging') { 'staging' } else { 'production' }
    return @{
        Project = "cloud-inventory-discovery-$suffix"
        Web = "cloud-inventory-discovery-$suffix"
        Worker = "cloud-inventory-discovery-$suffix-worker"
        Database = "cloud-inventory-discovery-$suffix-db"
        EnvironmentDisplay = if ($Environment -eq 'staging') { 'Staging' } else { 'Production' }
        Protection = if ($Environment -eq 'production') { 'enabled' } else { 'disabled' }
    }
}

function New-EnvironmentBlueprint {
    if ($DatabaseDiskSizeGB -ne 1 -and ($DatabaseDiskSizeGB % 5) -ne 0) {
        throw 'Render PostgreSQL disk size must be 1 GB or a multiple of 5 GB.'
    }
    $templatePath = Join-Path $RepositoryRoot 'render.template.yaml'
    $outputPath = Join-Path $RepositoryRoot 'render.yaml'
    if (-not (Test-Path $templatePath)) { throw "Blueprint template not found: $templatePath" }

    $names = Get-ResourceNames
    $content = Get-Content -LiteralPath $templatePath -Raw
    $replacements = @{
        '__PROJECT_NAME__' = $names.Project
        '__ENVIRONMENT_DISPLAY__' = $names.EnvironmentDisplay
        '__ENVIRONMENT_KEY__' = $Environment
        '__PROTECTION__' = $names.Protection
        '__WEB_SERVICE_NAME__' = $names.Web
        '__WORKER_SERVICE_NAME__' = $names.Worker
        '__DATABASE_NAME__' = $names.Database
        '__SERVICE_PLAN__' = $ServicePlan
        '__DATABASE_PLAN__' = $DatabasePlan
        '__DATABASE_DISK_GB__' = [string]$DatabaseDiskSizeGB
        '__REGION__' = $Region
        '__BRANCH__' = $Branch
    }
    foreach ($token in $replacements.Keys) {
        $content = $content.Replace($token, $replacements[$token])
    }
    if ($content -match '__[A-Z0-9_]+__') {
        throw "Blueprint generation left unresolved token: $($Matches[0])"
    }

    if ($DryRun) {
        if (-not (Test-Path $DeploymentOutput)) {
            New-Item -ItemType Directory -Path $DeploymentOutput -Force | Out-Null
        }
        $outputPath = Join-Path $DeploymentOutput "render.generated.$Environment.yaml"
        Write-Notice "DRY RUN: writing generated Blueprint only to $outputPath"
    }
    Set-Content -LiteralPath $outputPath -Value $content -Encoding UTF8
    Write-Success "Generated Render Blueprint for $Environment in $Region."
    return $outputPath
}

function Copy-ValidationWorkspace {
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("ci-discovery-validation-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

    $excludeDirectories = @('.git', '.venv', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'deployment-output', 'local-storage', '__pycache__')
    $excludeFileNames = @('.env', 'discovery.db')

    Get-ChildItem -LiteralPath $RepositoryRoot -Force | ForEach-Object {
        if ($excludeDirectories -contains $_.Name) { return }
        if ($excludeFileNames -contains $_.Name) { return }
        if ($_.Name -like '.env.*' -and $_.Name -ne '.env.example') { return }
        Copy-Item -LiteralPath $_.FullName -Destination $tempRoot -Recurse -Force
    }
    return $tempRoot
}

function Get-PythonCommand {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return [PSCustomObject]@{ Executable = 'python'; PrefixArguments = @() }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return [PSCustomObject]@{ Executable = 'py'; PrefixArguments = @('-3') }
    }
    throw 'Python 3.12 or newer is required for local validation. Install Python or use -SkipTests only after CI has validated the exact commit.'
}

function Invoke-ApplicationValidation {
    if ($SkipTests) {
        Write-Caution 'Local tests were skipped. This should not be used for a production release.'
        return
    }

    Write-Step 'Validating in a temporary workspace'
    $validationRoot = Copy-ValidationWorkspace
    try {
        $python = Get-PythonCommand
        $pythonExe = [string]$python.Executable
        $pythonPrefix = @($python.PrefixArguments)

        Invoke-ExternalCommand $pythonExe ($pythonPrefix + @('-m', 'venv', '.venv')) $validationRoot
        $venvPython = if (Test-IsWindows) { Join-Path $validationRoot '.venv\Scripts\python.exe' } else { Join-Path $validationRoot '.venv/bin/python' }
        Invoke-ExternalCommand $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'requirements-dev.txt') $validationRoot
        Invoke-ExternalCommand $venvPython @('-m', 'ruff', 'check', 'app', 'tests', 'scripts', 'alembic/env.py') $validationRoot
        Invoke-ExternalCommand $venvPython @('-m', 'pytest', '-q') $validationRoot
        Invoke-ExternalCommand $venvPython @('-m', 'compileall', 'app') $validationRoot

        if ($BuildDockerImage) {
            Assert-Command 'docker' 'Install Docker Desktop and ensure the docker command is on PATH.'
            $tag = "cloud-inventory-discovery-validation:$Environment"
            Invoke-ExternalCommand 'docker' @('build', '--pull', '-t', $tag, '.') $validationRoot
        }
        Write-Success 'Application validation completed.'
    }
    finally {
        if (Test-Path $validationRoot) {
            Remove-Item -LiteralPath $validationRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-RepositoryForSecrets {
    param([hashtable]$Secrets)
    Write-Step 'Scanning source files for deployment secrets'

    $candidateSecrets = New-Object System.Collections.Generic.List[string]
    $candidateSecrets.Add(('CloudInventory' + '2026!'))
    foreach ($key in @('BOOTSTRAP_ADMIN_PASSWORD', 'S3_SECRET_ACCESS_KEY', 'OPENAI_API_KEY')) {
        if ($Secrets -and $Secrets.ContainsKey($key)) {
            $value = [string]$Secrets[$key]
            if ($value.Length -ge 8) { $candidateSecrets.Add($value) }
        }
    }

    $extensions = @('.py', '.js', '.css', '.html', '.json', '.yaml', '.yml', '.md', '.toml', '.ini', '.txt', '.ps1', '.csv', '.example')
    $excludedParts = @([IO.Path]::DirectorySeparatorChar + '.git' + [IO.Path]::DirectorySeparatorChar,
                       [IO.Path]::DirectorySeparatorChar + '.venv' + [IO.Path]::DirectorySeparatorChar,
                       [IO.Path]::DirectorySeparatorChar + 'deployment-output' + [IO.Path]::DirectorySeparatorChar,
                       [IO.Path]::DirectorySeparatorChar + 'local-storage' + [IO.Path]::DirectorySeparatorChar)

    foreach ($file in Get-ChildItem -LiteralPath $RepositoryRoot -Recurse -File -Force) {
        $full = $file.FullName
        $excluded = $false
        foreach ($part in $excludedParts) {
            if ($full.Contains($part)) { $excluded = $true; break }
        }
        if ($excluded) { continue }
        if ($file.Name -like 'deploy.secrets*.env') { continue }
        if (($extensions -notcontains $file.Extension.ToLowerInvariant()) -and $file.Name -notin @('.env.example', '.gitignore', 'Dockerfile', 'Makefile')) { continue }
        $text = Get-Content -LiteralPath $full -Raw -ErrorAction SilentlyContinue
        if ($null -eq $text) { continue }
        foreach ($secret in $candidateSecrets) {
            if ($text.Contains($secret)) {
                throw "A deployment secret was found in source file $full. Remove it before committing."
            }
        }
    }
    Write-Success 'No supplied deployment secrets were found in source files.'
}

function Invoke-BlueprintValidationViaApi {
    param([string]$BlueprintPath)
    if ([string]::IsNullOrWhiteSpace($script:RenderApiKey) -or [string]::IsNullOrWhiteSpace($RenderWorkspaceId)) {
        return $false
    }

    Write-Step 'Validating Render Blueprint through the Render API'
    Add-Type -AssemblyName System.Net.Http
    $handler = [Net.Http.HttpClientHandler]::new()
    $client = [Net.Http.HttpClient]::new($handler)
    try {
        $client.DefaultRequestHeaders.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $script:RenderApiKey)
        $client.DefaultRequestHeaders.Accept.Add([Net.Http.Headers.MediaTypeWithQualityHeaderValue]::new('application/json'))
        $form = [Net.Http.MultipartFormDataContent]::new()
        $form.Add([Net.Http.StringContent]::new($RenderWorkspaceId), 'ownerId')
        $bytes = [IO.File]::ReadAllBytes($BlueprintPath)
        $fileContent = [Net.Http.ByteArrayContent]::new($bytes)
        $fileContent.Headers.ContentType = [Net.Http.Headers.MediaTypeHeaderValue]::new('application/yaml')
        $form.Add($fileContent, 'file', 'render.yaml')
        $response = $client.PostAsync("$RenderApiBase/blueprints/validate", $form).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "Render Blueprint validation failed: HTTP $([int]$response.StatusCode) $body"
        }
        $result = $body | ConvertFrom-Json
        if ($result.PSObject.Properties.Name -contains 'valid' -and -not $result.valid) {
            throw "Render Blueprint is invalid: $body"
        }
        Write-Success 'Render API accepted the Blueprint.'
        return $true
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Invoke-BlueprintValidation {
    param([string]$BlueprintPath)
    $render = Get-Command render -ErrorAction SilentlyContinue
    if ($render) {
        Write-Step 'Validating Render Blueprint with the Render CLI'
        $arguments = @('blueprints', 'validate', $BlueprintPath, '--output', 'json')
        if ($RenderWorkspaceId) { $arguments += @('--workspace', $RenderWorkspaceId) }
        Invoke-ExternalCommand $render.Source $arguments $RepositoryRoot
        Write-Success 'Render CLI accepted the Blueprint.'
        return
    }

    if (Invoke-BlueprintValidationViaApi $BlueprintPath) { return }
    Write-Caution 'Render CLI/API validation was unavailable. The Blueprint will still be checked by Render during creation.'
}

function Ensure-GitIdentity {
    $name = Invoke-ExternalCommand 'git' @('config', '--get', 'user.name') $RepositoryRoot -CaptureOutput -AllowFailure
    $email = Invoke-ExternalCommand 'git' @('config', '--get', 'user.email') $RepositoryRoot -CaptureOutput -AllowFailure

    if ([string]::IsNullOrWhiteSpace($name)) {
        if ([string]::IsNullOrWhiteSpace($GitAuthorName) -and -not $NonInteractive) {
            $GitAuthorName = Read-Host 'Git commit author name'
        }
        if ([string]::IsNullOrWhiteSpace($GitAuthorName)) {
            throw 'Git user.name is not configured. Supply -GitAuthorName or configure Git before deployment.'
        }
        Invoke-ExternalCommand 'git' @('config', 'user.name', $GitAuthorName) $RepositoryRoot
    }

    if ([string]::IsNullOrWhiteSpace($email)) {
        if ([string]::IsNullOrWhiteSpace($GitAuthorEmail) -and -not $NonInteractive) {
            $GitAuthorEmail = Read-Host 'Git commit author email'
        }
        if ([string]::IsNullOrWhiteSpace($GitAuthorEmail)) {
            throw 'Git user.email is not configured. Supply -GitAuthorEmail or configure Git before deployment.'
        }
        Invoke-ExternalCommand 'git' @('config', 'user.email', $GitAuthorEmail) $RepositoryRoot
    }
}

function Ensure-GitRepository {
    Assert-Command 'git' 'Install Git for Windows or another supported Git distribution.'
    if (-not (Test-Path (Join-Path $RepositoryRoot '.git'))) {
        Invoke-ExternalCommand 'git' @('init') $RepositoryRoot
        Invoke-ExternalCommand 'git' @('branch', '-M', 'main') $RepositoryRoot
    }
    Ensure-GitIdentity

    $currentBranch = Invoke-ExternalCommand 'git' @('branch', '--show-current') $RepositoryRoot -CaptureOutput
    if (-not [string]::IsNullOrWhiteSpace($currentBranch) -and $currentBranch.Trim() -ne $Branch) {
        Write-Notice "Validated commit will be pushed from local branch '$($currentBranch.Trim())' to remote deployment branch '$Branch'."
    }
}

function Convert-GitRemoteToHttps {
    param([string]$Remote)
    $value = $Remote.Trim()
    if ($value -match '^git@github\.com:(?<path>.+?)(\.git)?$') {
        return "https://github.com/$($Matches['path'] -replace '\.git$', '')"
    }
    if ($value.EndsWith('.git')) { $value = $value.Substring(0, $value.Length - 4) }
    return $value
}

function Get-OrCreateGitHubRepository {
    Ensure-GitRepository
    $remote = Invoke-ExternalCommand 'git' @('remote', 'get-url', 'origin') $RepositoryRoot -CaptureOutput -AllowFailure
    if (-not [string]::IsNullOrWhiteSpace($remote)) {
        return Convert-GitRemoteToHttps $remote
    }

    if ([string]::IsNullOrWhiteSpace($GitHubOwner)) {
        throw 'No Git origin is configured and -GitHubOwner was not supplied.'
    }
    Assert-Command 'gh' 'Install GitHub CLI, run gh auth login, and re-run this script.'
    Invoke-ExternalCommand 'gh' @('auth', 'status') $RepositoryRoot

    $fullName = "$GitHubOwner/$RepositoryName"
    $existing = Invoke-ExternalCommand 'gh' @('repo', 'view', $fullName, '--json', 'url', '--jq', '.url') $RepositoryRoot -CaptureOutput -AllowFailure
    if ([string]::IsNullOrWhiteSpace($existing)) {
        Write-Step "Creating private GitHub repository $fullName"
        if ($PSCmdlet.ShouldProcess($fullName, 'Create GitHub repository')) {
            Invoke-ExternalCommand 'gh' @('repo', 'create', $fullName, "--$RepositoryVisibility", '--source', '.', '--remote', 'origin') $RepositoryRoot
        }
        return "https://github.com/$fullName"
    }

    Invoke-ExternalCommand 'git' @('remote', 'add', 'origin', "https://github.com/$fullName.git") $RepositoryRoot
    return $existing.Trim()
}

function Commit-AndPush {
    param([string]$RepositoryUrl)

    Write-Step 'Committing and publishing the validated release'
    $status = Invoke-ExternalCommand 'git' @('status', '--porcelain') $RepositoryRoot -CaptureOutput
    if ($SkipGitHubPush -and -not [string]::IsNullOrWhiteSpace($status)) {
        throw '-SkipGitHubPush cannot be used while validated local changes are uncommitted because Render would deploy an older remote revision.'
    }
    if (-not [string]::IsNullOrWhiteSpace($status)) {
        Invoke-ExternalCommand 'git' @('add', '-A') $RepositoryRoot
        if ($PSCmdlet.ShouldProcess($RepositoryRoot, 'Create Git commit')) {
            Invoke-ExternalCommand 'git' @('commit', '-m', "$CommitMessage [$Environment]") $RepositoryRoot
        }
    }
    else {
        Write-Notice 'No local changes require a new commit.'
    }

    $commitSha = (Invoke-ExternalCommand 'git' @('rev-parse', 'HEAD') $RepositoryRoot -CaptureOutput).Trim()
    if ($SkipGitHubPush) {
        Write-Caution 'GitHub push was skipped; the existing remote branch revision will be deployed.'
        return $commitSha
    }

    if ($PSCmdlet.ShouldProcess($RepositoryUrl, "Push branch $Branch")) {
        Invoke-ExternalCommand 'git' @('push', 'origin', "HEAD:refs/heads/$Branch") $RepositoryRoot
    }
    Write-Success "Repository published to $RepositoryUrl at commit $commitSha."
    return $commitSha
}

function Get-GitHubRepositorySlug {
    param([string]$RepositoryUrl)
    $value = (Convert-GitRemoteToHttps $RepositoryUrl).TrimEnd('/')
    if ($value -notmatch '^https://github\.com/(?<slug>[^/]+/[^/]+)$') {
        throw "The deployment toolkit requires a GitHub repository URL, but received '$RepositoryUrl'."
    }
    return $Matches['slug']
}

function Wait-GitHubChecks {
    param([string]$RepositoryUrl, [string]$CommitSha)
    if ($SkipGitHubPush -or $SkipGitHubChecks -or $DryRun) {
        if ($SkipGitHubChecks) { Write-Caution 'GitHub Actions checks were explicitly skipped.' }
        return
    }

    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) {
        if ($Environment -eq 'production') {
            throw 'GitHub CLI is required to verify production CI checks. Install gh or explicitly use -SkipGitHubChecks.'
        }
        Write-Caution 'GitHub CLI is unavailable, so remote CI checks could not be awaited. Automatic Render deploys are disabled; the toolkit will continue using the local validation result.'
        return
    }

    $slug = Get-GitHubRepositorySlug $RepositoryUrl
    Write-Step "Waiting for GitHub Actions checks on $Branch at $CommitSha"
    $deadline = [DateTime]::UtcNow.AddSeconds($GitHubChecksTimeoutSeconds)
    $runId = ''
    while ([DateTime]::UtcNow -lt $deadline) {
        $runId = Invoke-ExternalCommand 'gh' @(
            'run', 'list',
            '--repo', $slug,
            '--branch', $Branch,
            '--commit', $CommitSha,
            '--workflow', 'CI',
            '--limit', '20',
            '--json', 'databaseId',
            '--jq', '.[0].databaseId'
        ) $RepositoryRoot -CaptureOutput -AllowFailure
        if (-not [string]::IsNullOrWhiteSpace($runId)) { break }
        Start-Sleep -Seconds 5
    }
    if ([string]::IsNullOrWhiteSpace($runId)) {
        throw "No GitHub Actions run appeared for commit $CommitSha within $GitHubChecksTimeoutSeconds seconds."
    }

    Invoke-ExternalCommand 'gh' @('run', 'watch', $runId.Trim(), '--repo', $slug, '--exit-status') $RepositoryRoot
    Write-Success 'GitHub Actions checks passed.'
}

function Invoke-RenderApi {
    param(
        [ValidateSet('GET', 'POST', 'PUT', 'PATCH', 'DELETE')][string]$Method,
        [string]$Path,
        [object]$Body = $null,
        [int]$MaximumAttempts = 5
    )
    if ([string]::IsNullOrWhiteSpace($script:RenderApiKey)) {
        throw 'RENDER_API_KEY is required for Render API operations.'
    }
    $headers = @{ Authorization = "Bearer $script:RenderApiKey"; Accept = 'application/json' }
    $uri = if ($Path.StartsWith('http')) { $Path } else { "$RenderApiBase$Path" }

    for ($attempt = 1; $attempt -le $MaximumAttempts; $attempt++) {
        try {
            $parameters = @{ Method = $Method; Uri = $uri; Headers = $headers; ErrorAction = 'Stop' }
            if ($null -ne $Body) {
                $parameters['ContentType'] = 'application/json'
                $parameters['Body'] = ($Body | ConvertTo-Json -Depth 12)
            }
            return Invoke-RestMethod @parameters
        }
        catch {
            $statusCode = $null
            if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
                $statusCode = [int]$_.Exception.Response.StatusCode
            }
            if ($statusCode -eq 429 -and $attempt -lt $MaximumAttempts) {
                $delay = [Math]::Min(30, [Math]::Pow(2, $attempt)) + (Get-Random -Minimum 0 -Maximum 3)
                Start-Sleep -Seconds $delay
                continue
            }
            throw
        }
    }
}

function Get-RenderServiceRecord {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($script:RenderApiKey)) { return $null }
    $encodedName = [Uri]::EscapeDataString($Name)
    $query = "/services?name=$encodedName&limit=100"
    if ($RenderWorkspaceId) { $query += "&ownerId=$([Uri]::EscapeDataString($RenderWorkspaceId))" }
    $response = Invoke-RenderApi GET $query
    $records = if ($response.PSObject.Properties.Name -contains 'items') {
        @($response.items)
    }
    elseif ($response.PSObject.Properties.Name -contains 'services') {
        @($response.services)
    }
    else {
        @($response)
    }
    foreach ($item in $records) {
        $service = if ($item.PSObject.Properties.Name -contains 'service') { $item.service } else { $item }
        if ($service -and $service.name -eq $Name) { return $service }
    }
    return $null
}

function Set-RenderEnvironmentVariable {
    param([string]$ServiceId, [string]$Key, [string]$Value)
    $encodedKey = [Uri]::EscapeDataString($Key)
    Invoke-RenderApi PUT "/services/$ServiceId/env-vars/$encodedKey" @{ value = [string]$Value } | Out-Null
}

function Set-RenderSecrets {
    param([string]$WebId, [string]$WorkerId, [hashtable]$Values)
    Write-Step 'Applying service secrets through the Render API'

    foreach ($key in @('BOOTSTRAP_ADMIN_EMAIL', 'BOOTSTRAP_ADMIN_PASSWORD', 'S3_ENDPOINT', 'S3_BUCKET', 'S3_REGION', 'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY', 'OPENAI_API_KEY', 'OPENAI_PROJECT_ID')) {
        Set-RenderEnvironmentVariable $WebId $key $Values[$key]
    }
    foreach ($key in @('S3_ENDPOINT', 'S3_BUCKET', 'S3_REGION', 'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY', 'OPENAI_API_KEY', 'OPENAI_PROJECT_ID')) {
        Set-RenderEnvironmentVariable $WorkerId $key $Values[$key]
    }
    foreach ($key in @('AI_ENABLED', 'AI_CONFIDENTIAL_CONTENT_ENABLED', 'OPENAI_DATA_CONTROL_MODE')) {
        Set-RenderEnvironmentVariable $WebId $key $Values[$key]
        Set-RenderEnvironmentVariable $WorkerId $key $Values[$key]
    }
    Write-Success 'Render service secrets were updated.'
}

function Start-RenderDeploy {
    param([string]$ServiceId)
    $body = @{ clearCache = if ($ClearBuildCache) { 'clear' } else { 'do_not_clear' } }
    return Invoke-RenderApi POST "/services/$ServiceId/deploys" $body
}

function Wait-RenderDeploy {
    param([string]$ServiceId, [string]$DeployId, [string]$Label)
    $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    $terminalFailure = @('build_failed', 'update_failed', 'canceled', 'deactivated', 'pre_deploy_failed', 'timed_out')
    while ([DateTime]::UtcNow -lt $deadline) {
        $deploy = Invoke-RenderApi GET "/services/$ServiceId/deploys/$DeployId"
        $status = [string]$deploy.status
        Write-Host "`r$Label deploy status: $status        " -NoNewline
        if ($status -eq 'live') {
            Write-Host ''
            Write-Success "$Label deployment is live."
            return
        }
        if ($terminalFailure -contains $status) {
            Write-Host ''
            throw "$Label deployment failed with status '$status'."
        }
        Start-Sleep -Seconds 8
    }
    Write-Host ''
    throw "$Label deployment did not complete within $HealthTimeoutSeconds seconds."
}

function Wait-WebHealth {
    param([string]$BaseUrl)
    if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
        Write-Caution 'Render did not return a web service URL; health polling was skipped.'
        return
    }
    $uri = $BaseUrl.TrimEnd('/') + '/readyz'
    $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $uri -Method GET -TimeoutSec 20
            if ($response.status -eq 'ready') {
                Write-Success "Health check passed: $uri"
                return
            }
        }
        catch {
            # Service may still be starting.
        }
        Start-Sleep -Seconds 10
    }
    throw "Health check did not pass within $HealthTimeoutSeconds seconds: $uri"
}

function Open-RenderBlueprint {
    param([string]$RepositoryUrl)
    $repoRef = $RepositoryUrl
    if ($Branch -ne 'main') { $repoRef = "$RepositoryUrl/tree/$Branch" }
    $deployUrl = 'https://render.com/deploy?repo=' + [Uri]::EscapeDataString($repoRef)
    Write-Host "Render Blueprint URL: $deployUrl" -ForegroundColor Yellow
    if (-not $NoBrowser -and -not $DryRun) {
        Start-Process $deployUrl
    }
    return $deployUrl
}

function Resolve-RenderServices {
    $names = Get-ResourceNames
    $web = $null
    $worker = $null
    if ($WebServiceId) {
        $web = Invoke-RenderApi GET "/services/$WebServiceId"
    }
    else {
        $web = Get-RenderServiceRecord $names.Web
    }
    if ($WorkerServiceId) {
        $worker = Invoke-RenderApi GET "/services/$WorkerServiceId"
    }
    else {
        $worker = Get-RenderServiceRecord $names.Worker
    }
    return @{ Web = $web; Worker = $worker }
}

function Invoke-RenderDeployment {
    param([string]$RepositoryUrl, [hashtable]$Secrets, [string]$SecretHandoffPath)

    if ([string]::IsNullOrWhiteSpace($script:RenderApiKey)) {
        Write-Caution 'RENDER_API_KEY is not set, so the script cannot discover services, apply secrets, or poll the deploy.'
        if ($Action -eq 'Redeploy') {
            $dashboardUrl = 'https://dashboard.render.com'
            Write-Host "Open the existing Render services, apply any changed secrets from $SecretHandoffPath, deploy the web service, verify /readyz, and then deploy the worker." -ForegroundColor Yellow
            Write-Host "Render Dashboard: $dashboardUrl" -ForegroundColor Yellow
            if (-not $NoBrowser -and -not $DryRun) { Start-Process $dashboardUrl }
        }
        else {
            Open-RenderBlueprint $RepositoryUrl | Out-Null
            Write-Host "Use the local handoff file while Render prompts for sync:false values: $SecretHandoffPath" -ForegroundColor Yellow
        }
        return 'browser_pending'
    }

    $services = Resolve-RenderServices
    if ($null -eq $services.Web -or $null -eq $services.Worker) {
        Open-RenderBlueprint $RepositoryUrl | Out-Null
        Write-Host "Use the local handoff file while Render prompts for sync:false values: $SecretHandoffPath" -ForegroundColor Yellow
        if ($NonInteractive) {
            throw 'Render services do not exist yet. Complete initial Blueprint creation, then re-run with -Action Redeploy.'
        }
        Read-Host 'Complete the Blueprint creation in the browser, then press ENTER to continue'
        $services = Resolve-RenderServices
        if ($null -eq $services.Web -or $null -eq $services.Worker) {
            throw 'The expected Render web and worker services could not be found after Blueprint creation.'
        }
    }

    $webId = [string]$services.Web.id
    $workerId = [string]$services.Worker.id
    Set-RenderSecrets $webId $workerId $Secrets

    Write-Step 'Deploying web service and running pre-deploy migrations'
    $webDeploy = Start-RenderDeploy $webId
    Wait-RenderDeploy $webId ([string]$webDeploy.id) 'Web'

    $webRecord = Get-RenderServiceRecord (Get-ResourceNames).Web
    if ($webRecord) {
        $webUrl = if ($webRecord.PSObject.Properties.Name -contains 'url') {
            [string]$webRecord.url
        }
        elseif ($webRecord.PSObject.Properties.Name -contains 'serviceDetails' -and $webRecord.serviceDetails) {
            [string]$webRecord.serviceDetails.url
        }
        else {
            ''
        }
        Wait-WebHealth $webUrl
    }

    Write-Step 'Deploying worker after the web migration gate has passed'
    $workerDeploy = Start-RenderDeploy $workerId
    Wait-RenderDeploy $workerId ([string]$workerDeploy.id) 'Worker'
    return 'deployed'
}

try {
    Set-Location $RepositoryRoot
    Assert-ProductionSafety

    Write-Step "Preparing $Environment deployment"
    $blueprintPath = New-EnvironmentBlueprint

    $requiresSecrets = ($Action -in @('Deploy', 'Redeploy')) -and -not $DryRun
    $deploymentSecrets = $null
    $secretHandoffPath = $null
    if ($requiresSecrets) {
        if (-not $SecretsFile) {
            $candidate = Join-Path $RepositoryRoot "deploy.secrets.$Environment.env"
            if (Test-Path $candidate) { $SecretsFile = $candidate }
        }
        $deploymentSecrets = Get-DeploymentSecrets $SecretsFile
        $secretHandoffPath = Write-SecretHandoff $deploymentSecrets
    }

    Test-RepositoryForSecrets $deploymentSecrets
    Invoke-ApplicationValidation
    Invoke-BlueprintValidation $blueprintPath

    if ($Action -eq 'Validate') {
        Write-Success 'Validation completed. No GitHub or Render changes were made.'
        exit 0
    }

    if ($DryRun) {
        $dryOwner = if ([string]::IsNullOrWhiteSpace($GitHubOwner)) { 'example' } else { $GitHubOwner }
        $repositoryUrl = "https://github.com/$dryOwner/$RepositoryName"
        $commitSha = 'DRY-RUN'
        Write-Notice "DRY RUN: GitHub publication target would be $repositoryUrl on branch $Branch."
    }
    else {
        $repositoryUrl = Get-OrCreateGitHubRepository
        $commitSha = Commit-AndPush $repositoryUrl
    }
    Wait-GitHubChecks $repositoryUrl $commitSha

    if ($Action -eq 'Publish') {
        Write-Success 'Repository publication completed. Render was not changed.'
        exit 0
    }
    if ($DryRun) {
        Write-Success 'Dry run completed. No GitHub or Render changes were made and no deployment secrets were requested.'
        exit 0
    }

    $deploymentResult = Invoke-RenderDeployment $repositoryUrl $deploymentSecrets $secretHandoffPath

    if ($secretHandoffPath -and -not $KeepSecretHandoff -and $deploymentResult -eq 'deployed' -and -not $DryRun) {
        Remove-Item -LiteralPath $secretHandoffPath -Force -ErrorAction SilentlyContinue
        Write-Success 'Local secret handoff file removed after deployment.'
    }
    elseif ($secretHandoffPath) {
        Write-Caution "Local secret handoff remains at $secretHandoffPath. Delete it after deployment."
    }

    if ($deploymentResult -eq 'browser_pending') {
        Write-Caution 'The repository is ready and the Render Blueprint flow was opened. Complete the initial approval in the browser, then re-run with -Action Redeploy for API-driven verification.'
    }
    else {
        Write-Success "$Environment deployment workflow completed and verified."
    }
}
catch {
    Write-Error $_
    exit 1
}
