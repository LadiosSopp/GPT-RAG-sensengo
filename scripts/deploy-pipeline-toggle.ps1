# Deploy Pipeline Toggle Feature
# 部署 Pipeline 管理開關功能到 Azure Container Apps
#
# 涉及服務：
#   1. gpt-rag-ingestion — 新增 pipeline toggle API endpoints
#   2. gpt-rag-ui — 新增 admin proxy + 前端浮動面板
#
# 使用方法：
#   .\scripts\deploy-pipeline-toggle.ps1
#
# 前提：
# 1. 已用 az login 登入正確的 tenant/subscription
# 2. 有 ACR push 權限

$ErrorActionPreference = "Stop"

# ============================================
# 設定變數
# ============================================
$ACR_NAME = "cr2v3lfktkn4xamgprag"
$RG = "GPRAG"
$SUBSCRIPTION = "2c9b3248-f263-4104-bd24-6446d4db84b9"
$APP_CONFIG_NAME = "appcs-2v3lfktkn4xam-gprag"
$TIMESTAMP = Get-Date -Format "yyyyMMddHHmmss"

$CA_FRONTEND = "ca-2v3lfktkn4xam-frontend-gprag"
$CA_INGESTION = "ca-ingest-gprag"

$PROJECT_ROOT = Split-Path -Parent $PSScriptRoot

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Deploy Pipeline Toggle Feature" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "ACR:           $ACR_NAME" -ForegroundColor Yellow
Write-Host "Resource Group: $RG" -ForegroundColor Yellow
Write-Host "Timestamp:     $TIMESTAMP" -ForegroundColor Yellow
Write-Host "Frontend:      $CA_FRONTEND" -ForegroundColor Yellow
Write-Host "Ingestion:     $CA_INGESTION" -ForegroundColor Yellow
Write-Host ""

# ============================================
# 步驟 0: 確認 subscription
# ============================================
Write-Host "[0/6] 確認 Azure subscription..." -ForegroundColor Green
$sub = (az account show -o json 2>$null | ConvertFrom-Json)
Write-Host "Current subscription: $($sub.name) ($($sub.id))" -ForegroundColor Yellow
if ($sub.id -ne $SUBSCRIPTION) {
    Write-Host "Switching to correct subscription..." -ForegroundColor Red
    az account set --subscription $SUBSCRIPTION
}

# ============================================
# 步驟 1: 確認 ACR 存取
# ============================================
Write-Host ""
Write-Host "[1/6] 確認 ACR 存取..." -ForegroundColor Green
$acrServer = az acr show --name $ACR_NAME --query "loginServer" -o tsv 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "無法存取 ACR: $ACR_NAME"
    exit 1
}
Write-Host "ACR OK: $acrServer"

# ============================================
# 步驟 2: 設定 App Configuration — INGESTION_BASE_URL
# ============================================
Write-Host ""
Write-Host "[2/6] 設定 INGESTION_BASE_URL in App Configuration..." -ForegroundColor Green

$INGESTION_URL = "https://${CA_INGESTION}.nicepond-9d5552be.eastus2.azurecontainerapps.io"

# 檢查是否已存在
$existing = az appconfig kv show `
    --name $APP_CONFIG_NAME `
    --key "INGESTION_BASE_URL" `
    --label "gpt-rag" `
    --auth-mode login `
    -o tsv 2>$null

if ($LASTEXITCODE -eq 0 -and $existing) {
    Write-Host "INGESTION_BASE_URL already exists, updating..." -ForegroundColor Yellow
    az appconfig kv set `
        --name $APP_CONFIG_NAME `
        --key "INGESTION_BASE_URL" `
        --value $INGESTION_URL `
        --label "gpt-rag" `
        --auth-mode login `
        --yes
} else {
    Write-Host "Creating INGESTION_BASE_URL..." -ForegroundColor Yellow
    az appconfig kv set `
        --name $APP_CONFIG_NAME `
        --key "INGESTION_BASE_URL" `
        --value $INGESTION_URL `
        --label "gpt-rag" `
        --auth-mode login `
        --yes
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "設定 INGESTION_BASE_URL 失敗"
    exit 1
}
Write-Host "INGESTION_BASE_URL = $INGESTION_URL" -ForegroundColor Green

# 驗證 INGESTION_APP_APIKEY 已存在
Write-Host "Verifying INGESTION_APP_APIKEY exists..." -ForegroundColor Yellow
$apiKeyCheck = az appconfig kv show `
    --name $APP_CONFIG_NAME `
    --key "INGESTION_APP_APIKEY" `
    --label "gpt-rag" `
    --auth-mode login `
    --query "value" -o tsv 2>$null

if ($LASTEXITCODE -ne 0 -or -not $apiKeyCheck) {
    Write-Host "WARNING: INGESTION_APP_APIKEY not found in App Configuration!" -ForegroundColor Red
    Write-Host "Pipeline toggle API calls will fail without this key." -ForegroundColor Red
    Write-Host "Please set it manually: az appconfig kv set --name $APP_CONFIG_NAME --key INGESTION_APP_APIKEY --value <your-api-key> --label gpt-rag --yes" -ForegroundColor Red
    $continue = Read-Host "Continue deployment anyway? (y/n)"
    if ($continue -ne "y") { exit 1 }
} else {
    Write-Host "INGESTION_APP_APIKEY OK" -ForegroundColor Green
}

# ============================================
# 步驟 3: Build & Push Ingestion Image (ACR Build)
# ============================================
Write-Host ""
Write-Host "[3/6] Building Ingestion via ACR Build..." -ForegroundColor Green
$INGESTION_IMAGE = "$acrServer/dataingest:pipeline-$TIMESTAMP"
$INGESTION_DIR = Join-Path $PROJECT_ROOT "gpt-rag-ingestion"

Write-Host "Directory: $INGESTION_DIR"
Write-Host "Image:     dataingest:pipeline-$TIMESTAMP"

az acr build --registry $ACR_NAME --image "dataingest:pipeline-$TIMESTAMP" $INGESTION_DIR --no-logs 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) {
    Write-Error "Ingestion ACR build 失敗"
    exit 1
}
Write-Host "Ingestion build complete." -ForegroundColor Green

# ============================================
# 步驟 4: Build & Push Frontend Image (ACR Build)
# ============================================
Write-Host ""
Write-Host "[4/6] Building Frontend via ACR Build..." -ForegroundColor Green
$FRONTEND_IMAGE = "$acrServer/frontend:pipeline-$TIMESTAMP"
$FRONTEND_DIR = Join-Path $PROJECT_ROOT "gpt-rag-ui"

Write-Host "Directory: $FRONTEND_DIR"
Write-Host "Image:     frontend:pipeline-$TIMESTAMP"

az acr build --registry $ACR_NAME --image "frontend:pipeline-$TIMESTAMP" $FRONTEND_DIR --no-logs 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) {
    Write-Error "Frontend ACR build 失敗"
    exit 1
}
Write-Host "Frontend build complete." -ForegroundColor Green

# ============================================
# 步驟 5: Update Container Apps
# ============================================
Write-Host ""
Write-Host "[5/6] Updating Container Apps..." -ForegroundColor Green

Write-Host "Updating Ingestion ($CA_INGESTION)..."
az containerapp update `
    --name $CA_INGESTION `
    --resource-group $RG `
    --image $INGESTION_IMAGE
if ($LASTEXITCODE -ne 0) {
    Write-Error "Ingestion Container App 更新失敗"
    exit 1
}
Write-Host "Ingestion updated." -ForegroundColor Green

Write-Host "Updating Frontend ($CA_FRONTEND)..."
az containerapp update `
    --name $CA_FRONTEND `
    --resource-group $RG `
    --image $FRONTEND_IMAGE
if ($LASTEXITCODE -ne 0) {
    Write-Error "Frontend Container App 更新失敗"
    exit 1
}
Write-Host "Frontend updated." -ForegroundColor Green

# ============================================
# 步驟 6: 驗證
# ============================================
Write-Host ""
Write-Host "[6/6] 驗證部署..." -ForegroundColor Green

$FRONTEND_URL = "https://${CA_FRONTEND}.nicepond-9d5552be.eastus2.azurecontainerapps.io"
$INGESTION_API_URL = "$INGESTION_URL/api/pipelines"

Write-Host "Testing Ingestion pipeline API..."
try {
    $headers = @{ "X-API-KEY" = $apiKeyCheck }
    $testResult = Invoke-RestMethod -Uri $INGESTION_API_URL -Headers $headers -Method GET -TimeoutSec 30 -ErrorAction SilentlyContinue
    Write-Host "Pipeline API response OK" -ForegroundColor Green
} catch {
    Write-Host "Pipeline API not yet responding (Container App may still be starting)" -ForegroundColor Yellow
}

# ============================================
# 完成
# ============================================
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Pipeline Toggle 部署完成！" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Image Tags:" -ForegroundColor Cyan
Write-Host "  Ingestion: $INGESTION_IMAGE"
Write-Host "  Frontend:  $FRONTEND_IMAGE"
Write-Host ""
Write-Host "App Configuration:" -ForegroundColor Cyan
Write-Host "  INGESTION_BASE_URL = $INGESTION_URL"
Write-Host ""
Write-Host "使用方式:" -ForegroundColor Cyan
Write-Host "  1. 開啟 $FRONTEND_URL" 
Write-Host "  2. 點擊左下角 ⚙️ 按鈕"
Write-Host "  3. 使用開關控制 STT 通話分析和資料擷取 pipeline"
Write-Host ""
Write-Host "獨立管理頁面:" -ForegroundColor Cyan
Write-Host "  $FRONTEND_URL/admin"
Write-Host ""
