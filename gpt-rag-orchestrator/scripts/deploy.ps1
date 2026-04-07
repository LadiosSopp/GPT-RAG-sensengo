<#
.SYNOPSIS
    deploy.ps1 — validate APP_CONFIG_ENDPOINT, load App Config (label=gpt-rag), then build & push

.DESCRIPTION
    - Checks for APP_CONFIG_ENDPOINT in environment; if missing, tries to fetch from `azd env get-values`.
    - Parses App Configuration name from endpoint.
    - Checks Azure CLI login.
    - Fetches required keys (CONTAINER_REGISTRY_NAME, CONTAINER_REGISTRY_LOGIN_SERVER, AZURE_RESOURCE_GROUP, ORCHESTRATOR_APP_NAME) from Azure App Configuration with label "gpt-rag".
      If a key is not found with original casing, tries uppercase.
    - Logs into ACR, builds Docker image (tag from git short HEAD unless $env:tag is set). If local Docker is unavailable, uses `az acr build`.
    - Pushes image and updates the Container App.
.NOTES
    - Requires Azure CLI installed and logged in.
    - Running in PowerShell 5.1+ or PowerShell Core.
#>

#region Helper: color output functions
function Write-Green($msg) {
    Write-Host $msg -ForegroundColor Green
}
function Write-Blue($msg) {
    Write-Host $msg -ForegroundColor Cyan
}
function Write-Yellow($msg) {
    Write-Host $msg -ForegroundColor Yellow
}
function Write-ErrorColored($msg) {
    Write-Host $msg -ForegroundColor Red
}
#endregion

#region Debug toggle
if ($env:DEBUG -eq 'true') {
    $VerbosePreference = 'Continue'
    Write-Verbose "DEBUG mode is ON"
} else {
    $VerbosePreference = 'SilentlyContinue'
}
#endregion

Write-Host ""  # blank line

#region Early Docker validation
$pausedPattern   = 'Docker Desktop is manually paused'
$daemonDownRegex = '((?i)error during connect|Cannot connect to the Docker daemon|Is the docker daemon running|The Docker daemon is not running|dockerDesktopLinuxEngine|dockerDesktopWindowsEngine|The system cannot find the file specified|open \\./pipe/|context deadline exceeded)'
$script:useLocalDocker = $false

# Optional: try service check, but do NOT fail based on it
try {
    $dockerSvc = Get-Service -Name 'com.docker.service' -ErrorAction SilentlyContinue
    if ($dockerSvc) {
        Write-Blue "🔍 Docker Desktop service status: $($dockerSvc.Status)"
    }
} catch { }

if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Blue "🔍 Checking Docker availability…"
    $probeOutput = & docker info 2>&1
    $probeExit   = $LASTEXITCODE
    $probeText   = ($probeOutput | Out-String)

    if ($probeText -match $pausedPattern -or $probeText -match $daemonDownRegex -or $probeExit -ne 0) {
        if ($probeText -match $pausedPattern) {
            Write-Yellow '⚠️  Docker Desktop is manually paused.'
        } else {
            Write-Yellow '⚠️  Docker Desktop is not running.'
        }
        Write-Yellow '⚠️  Will use az acr build (cloud build) instead.'
    } else {
        $script:useLocalDocker = $true
        Write-Green "✅ Docker is available."
    }
} else {
    Write-Yellow '⚠️  Docker CLI not found. Will use az acr build (cloud build) instead.'
}
Write-Host ""
#endregion

#region APP_CONFIG_ENDPOINT check
if ($null -ne $env:APP_CONFIG_ENDPOINT -and $env:APP_CONFIG_ENDPOINT.Trim() -ne '') {
    Write-Green "✅ Using APP_CONFIG_ENDPOINT from environment: $($env:APP_CONFIG_ENDPOINT)"
    $APP_CONFIG_ENDPOINT = $env:APP_CONFIG_ENDPOINT.Trim()
} else {
    Write-Blue "🔍 Fetching APP_CONFIG_ENDPOINT from azd env…"
    try {
        $envValues = azd env get-values 2>$null
    } catch {
        $envValues = $null
    }
    if ($envValues) {
        foreach ($line in $envValues -split "`n") {
            if ($line -match '^\s*APP_CONFIG_ENDPOINT\s*=\s*"?([^"]+)"?\s*$') {
                $APP_CONFIG_ENDPOINT = $Matches[1].Trim()
                break
            }
        }
    }
}
if (-not $APP_CONFIG_ENDPOINT) {
    Write-Yellow "⚠️  Missing APP_CONFIG_ENDPOINT."
    Write-Host "  • Set it with: azd env set APP_CONFIG_ENDPOINT <your-endpoint>"
    Write-Host "  • Or in PowerShell: `$env:APP_CONFIG_ENDPOINT = '<your-endpoint>'` before running."
    exit 1
}
Write-Green "✅ APP_CONFIG_ENDPOINT: $APP_CONFIG_ENDPOINT"
Write-Host ""
#endregion

#region Parse configName from endpoint
$configName = $APP_CONFIG_ENDPOINT -replace '^https?://', ''
$configName = $configName -replace '\.azconfig\.io/?$', ''
if (-not $configName) {
    Write-Yellow ("⚠️ Could not parse config name from endpoint '{0}'." -f $APP_CONFIG_ENDPOINT)
    exit 1
}
Write-Green "✅ App Configuration name: $configName"
Write-Host ""
#endregion

#region Azure CLI login check
Write-Blue "🔐 Checking Azure CLI login and subscription…"
try {
    az account show > $null 2>&1
} catch {
    Write-Yellow "⚠️  Not logged in. Please run 'az login'."
    exit 1
}

# Resolve subscription: env var > azd .env > current default
$subscriptionId = $null
$script:appConfigConnStr = $null
if ($env:AZURE_SUBSCRIPTION_ID) {
    $subscriptionId = $env:AZURE_SUBSCRIPTION_ID.Trim()
    Write-Green ("✅ Using AZURE_SUBSCRIPTION_ID from env: {0}" -f $subscriptionId)
}
if ($env:APP_CONFIG_CONNECTION_STRING) {
    $script:appConfigConnStr = $env:APP_CONFIG_CONNECTION_STRING.Trim()
}

# Try to load missing values from .azure/sensengo-prod/.env
$azdEnvFile = Join-Path $PSScriptRoot '..' '.azure' 'sensengo-prod' '.env'
if (Test-Path $azdEnvFile) {
    foreach ($line in Get-Content $azdEnvFile) {
        if (-not $subscriptionId -and $line -match '^\s*AZURE_SUBSCRIPTION_ID\s*=\s*"?([^"]+)"?\s*$') {
            $subscriptionId = $Matches[1].Trim()
            Write-Green ("✅ Using AZURE_SUBSCRIPTION_ID from .azure env: {0}" -f $subscriptionId)
        }
        if (-not $script:appConfigConnStr -and $line -match '^\s*APP_CONFIG_CONNECTION_STRING\s*=\s*"?([^"]+)"?\s*$') {
            $script:appConfigConnStr = $Matches[1].Trim()
            Write-Green "✅ Using APP_CONFIG_CONNECTION_STRING from .azure env"
        }
    }
}

if ($subscriptionId) {
    $script:subArgs = @('--subscription', $subscriptionId)
    Write-Blue ("🔒 All az commands will use --subscription {0}" -f $subscriptionId)
} else {
    $script:subArgs = @()
    Write-Yellow "⚠️  No AZURE_SUBSCRIPTION_ID set — using current default subscription."
}
Write-Green "✅ Azure CLI is logged in."
Write-Host ""
#endregion

#region Fetch App Configuration values
$label = "gpt-rag"

# Define required keys and allow env var overrides
$keyNames = @('CONTAINER_REGISTRY_NAME', 'CONTAINER_REGISTRY_LOGIN_SERVER', 'SUBSCRIPTION_ID', 'AZURE_RESOURCE_GROUP', 'RESOURCE_TOKEN', 'ORCHESTRATOR_APP_NAME')
$values = @{}
$needFromAppConfig = @()

# Phase 1: Try environment variables first
foreach ($k in $keyNames) {
    $envVal = [System.Environment]::GetEnvironmentVariable($k)
    if ($envVal) {
        $values[$k] = $envVal.Trim()
        Write-Green ("✅ {0} = {1} (from env)" -f $k, $values[$k])
    } else {
        $needFromAppConfig += $k
    }
}

# Phase 2: For missing keys, try App Configuration
if ($needFromAppConfig.Count -gt 0) {
    Write-Green "⚙️ Loading remaining settings from App Configuration (label=$label)…"
    Write-Host ""

    function Get-ConfigValue {
        param(
            [Parameter(Mandatory=$true)][string]$Key
        )
        Write-Blue ("🛠️  Retrieving '{0}' (label={1}) from App Configuration…" -f $Key, $label)
        try {
            if ($script:appConfigConnStr) {
                $val = az appconfig kv show `
                    --connection-string $script:appConfigConnStr `
                    --key $Key `
                    --label $label `
                    --query value -o tsv 2>&1
            } else {
                $val = az appconfig kv show `
                    --name $configName `
                    --key $Key `
                    --label $label `
                    --auth-mode login `
                    --endpoint $APP_CONFIG_ENDPOINT `
                    @script:subArgs `
                    --query value -o tsv 2>&1
            }
            $exitCode = $LASTEXITCODE
        } catch {
            $val = $_.Exception.Message
            $exitCode = 1
        }
        if ($exitCode -ne 0 -or [string]::IsNullOrWhiteSpace($val)) {
            Write-Yellow ("⚠️  Key '{0}' not found or empty. CLI output: {1}" -f $Key, $val)
            return $null
        }
        return $val.Trim()
    }

    $missing = @()
    foreach ($k in $needFromAppConfig) {
        $v = Get-ConfigValue -Key $k
        if ($null -eq $v) {
            $upperKey = $k.ToUpper()
            if ($upperKey -ne $k) {
                Write-Blue ("🔍 Trying uppercase key '{0}'…" -f $upperKey)
                $v = Get-ConfigValue -Key $upperKey
            }
        }
        if ($null -eq $v) {
            $missing += $k
        } else {
            $values[$k] = $v
        }
    }
    if ($missing.Count -gt 0) {
        Write-Yellow ("⚠️  Missing or invalid keys: {0}" -f ($missing -join ', '))
        Write-Host "  💡 Tip: Set them as env vars to bypass App Config, e.g.:"
        foreach ($m in $missing) {
            Write-Host ("     `$env:{0} = '<value>'" -f $m)
        }
        exit 1
    }
}

Write-Green "✅ All configuration values resolved:"
Write-Host ("   CONTAINER_REGISTRY_NAME = {0}" -f $values.CONTAINER_REGISTRY_NAME)
Write-Host ("   CONTAINER_REGISTRY_LOGIN_SERVER = {0}" -f $values.CONTAINER_REGISTRY_LOGIN_SERVER)
Write-Host ("   AZURE_RESOURCE_GROUP = {0}" -f $values.AZURE_RESOURCE_GROUP)
Write-Host ("   ORCHESTRATOR_APP_NAME = {0}" -f $values.ORCHESTRATOR_APP_NAME)
Write-Host ""
#endregion

#region Login to ACR (only needed for local Docker build)
if ($script:useLocalDocker) {
    Write-Green ("🔐 Logging into ACR ({0} in {1})…" -f $values.CONTAINER_REGISTRY_NAME, $values.AZURE_RESOURCE_GROUP)
    try {
        az acr login --name $values.CONTAINER_REGISTRY_NAME --resource-group $values.AZURE_RESOURCE_GROUP @script:subArgs
        Write-Green "✅ Logged into ACR."
    } catch {
        $errMsg = $_.Exception.Message
        Write-Yellow ("⚠️  Failed to login to ACR: {0}" -f $errMsg)
        exit 1
    }
    Write-Host ""
} else {
    Write-Green "ℹ️  Skipping ACR login (using cloud build)."
    Write-Host ""
}
#endregion

#region Determine tag
Write-Blue "Defining tag..."
if ($env:tag) {
    $tag = $env:tag.Trim()
    Write-Verbose ("Using tag from environment: {0}" -f $tag)
} else {
    try {
        $gitTag = & git rev-parse --short HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $gitTag) {
            $tag = $gitTag.Trim()
            Write-Verbose ("Using Git short HEAD as tag: {0}" -f $tag)
        } else {
            Write-Yellow "Could not get Git short HEAD. Generating random tag."
            $randomNumber = Get-Random -Minimum 100000 -Maximum 999999
            $tag = "GPT$randomNumber"
            Write-Verbose ("Generated random tag: {0}" -f $tag)
        }
    } catch {
        $errMsg = $_.Exception.Message
        Write-Yellow ("Error running Git: {0}. Generating random tag." -f $errMsg)
        $randomNumber = Get-Random -Minimum 100000 -Maximum 999999
        $tag = "GPT$randomNumber"
        Write-Verbose ("Generated random tag: {0}" -f $tag)
    }
}

#endregion#region Determine tag
Write-Blue "Defining tag..."
if ($env:tag) {
    $tag = $env:tag.Trim()
    Write-Verbose ("Using tag from environment: {0}" -f $tag)
} else {
    try {
        $gitTag = & git rev-parse --short HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $gitTag) {
            $tag = $gitTag.Trim()
            Write-Verbose ("Using Git short HEAD as tag: {0}" -f $tag)
        } else {
            Write-Yellow "Could not get Git short HEAD. Generating random tag."
            $randomNumber = Get-Random -Minimum 100000 -Maximum 999999
            $tag = "GPT$randomNumber"
            Write-Verbose ("Generated random tag: {0}" -f $tag)
        }
    } catch {
        $errMsg = $_.Exception.Message
        Write-Yellow ("Error running Git: {0}. Generating random tag." -f $errMsg)
        $randomNumber = Get-Random -Minimum 100000 -Maximum 999999
        $tag = "GPT$randomNumber"
        Write-Verbose ("Generated random tag: {0}" -f $tag)
    }
}
#endregion

#region Build or ACR build image
$fullImageName = "$($values.CONTAINER_REGISTRY_LOGIN_SERVER)/azure-gpt-rag/orchestrator:$tag"
Write-Green "🛠️  Building Docker image…"
if ($script:useLocalDocker) {
    try {
        docker build -t $fullImageName .
        Write-Green "✅ Docker build succeeded."
    } catch {
        $errMsg = $_.Exception.Message
        Write-Yellow ("⚠️  Docker build failed: {0}" -f $errMsg)
        exit 1
    }
} else {
    Write-Blue "☁️  Using az acr build (cloud build)…"
    try {
        az acr build `
            --registry $values.CONTAINER_REGISTRY_NAME `
            --image "azure-gpt-rag/orchestrator:$tag" `
            --file Dockerfile `
            @script:subArgs `
            .
        Write-Green "✅ ACR cloud build succeeded."
    } catch {
        $errMsg = $_.Exception.Message
        Write-Yellow ("⚠️  ACR build failed: {0}" -f $errMsg)
        exit 1
    }
}
Write-Host ""
#endregion

#Make sure container registry is registered
Write-Green "🔄 Updating container app registry…"
try {
    $ids = $(az containerapp identity show `
        --name $values.ORCHESTRATOR_APP_NAME `
        --resource-group $values.AZURE_RESOURCE_GROUP `
        @script:subArgs `
        --output json) | ConvertFrom-Json

    if ($ids.type.tostring().contains("UserAssigned"))
    {
        az containerapp registry set `
            --name $values.ORCHESTRATOR_APP_NAME `
            --resource-group $values.AZURE_RESOURCE_GROUP `
            --server "$($values.CONTAINER_REGISTRY_NAME).azurecr.io" `
            --identity "/subscriptions/$($values.SUBSCRIPTION_ID)/resourceGroups/$($values.AZURE_RESOURCE_GROUP)/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uai-ca-$($values.RESOURCE_TOKEN)-orchestrator" `
            @script:subArgs
    }
    else {
        az containerapp registry set `
        --name $values.ORCHESTRATOR_APP_NAME `
        --resource-group $values.AZURE_RESOURCE_GROUP `
        --server "$($values.CONTAINER_REGISTRY_NAME).azurecr.io" `
        --identity "system" `
        @script:subArgs
    }
    

    Write-Green "✅ Container app updated."
} catch {
    $errMsg = $_.Exception.Message
    Write-Yellow ("⚠️  Failed to update container app: {0}" -f $errMsg)
    exit 1
}

#region Push Docker image (if local build used)
if ($script:useLocalDocker) {
    Write-Green "📤 Pushing image…"
    try {
        docker push $fullImageName
        Write-Green "✅ Image pushed."
    } catch {
        $errMsg = $_.Exception.Message
        Write-Yellow ("⚠️  Docker push failed: {0}" -f $errMsg)
        exit 1
    }
    Write-Host ""
} else {
    # If using az acr build, image is already in ACR
    Write-Green "ℹ️  Image built in ACR; no local push needed."
    Write-Host ""
}
#endregion

#region Update Container App
Write-Green "🔄 Updating container app…"
try {
    az containerapp update `
        --name $values.ORCHESTRATOR_APP_NAME `
        --resource-group $values.AZURE_RESOURCE_GROUP `
        --image $fullImageName `
        @script:subArgs
    Write-Green "✅ Container app updated."
} catch {
    $errMsg = $_.Exception.Message
    Write-Yellow ("⚠️  Failed to update container app: {0}" -f $errMsg)
    exit 1
}

#get the current revision
Write-Blue "🔍 Fetching current revision…"
$currentRevision = az containerapp revision list `
    --name $values.ORCHESTRATOR_APP_NAME `
    --resource-group $values.AZURE_RESOURCE_GROUP `
    @script:subArgs `
    --query "[0].name" -o tsv


#region Restart Container App
Write-Green "🔄 Restarting container app…"
try {
    az containerapp revision restart `
        --name $values.ORCHESTRATOR_APP_NAME `
        --resource-group $values.AZURE_RESOURCE_GROUP `
        --revision $currentRevision `
        @script:subArgs
        
    Write-Green "✅ Container app restarted."
} catch {
    $errMsg = $_.Exception.Message
    Write-Yellow ("⚠️  Failed to restart container app: {0}" -f $errMsg)
    exit 1
}
#endregion
