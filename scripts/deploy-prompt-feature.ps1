# Deploy Prompt Switching Feature
# 部署 prompt 切換功能到 Azure Container Apps
#
# 使用方法：
#   .\scripts\deploy-prompt-feature.ps1
#
# 前提：
# 1. Docker Desktop 正在運行
# 2. 已用 az login 登入正確的 tenant/subscription
# 3. 有 ACR push 權限

$ErrorActionPreference = "Stop"

# ============================================
# 設定變數
# ============================================
$ACR_NAME = "cr2v3lfktkn4xamgprag"
$RG = "GPRAG"
$TIMESTAMP = Get-Date -Format "yyyyMMddHHmmss"

$CA_FRONTEND = "ca-2v3lfktkn4xam-frontend-gprag"
$CA_ORCHESTRATOR = "ca-2v3lfktkn4xam-orch-gprag"

$PROJECT_ROOT = "c:\SynologyDrive\LTIMindtree\Source Code\sensengo"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Deploy Prompt Switching Feature" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "ACR: $ACR_NAME" -ForegroundColor Yellow
Write-Host "Resource Group: $RG" -ForegroundColor Yellow
Write-Host "Timestamp: $TIMESTAMP" -ForegroundColor Yellow
Write-Host ""

# ============================================
# 步驟 0: 確認 subscription
# ============================================
$sub = (az account show -o json 2>$null | ConvertFrom-Json)
Write-Host "Subscription: $($sub.name) ($($sub.id))" -ForegroundColor Yellow
if ($sub.id -ne "2c9b3248-f263-4104-bd24-6446d4db84b9") {
    Write-Host "⚠️  Not on ehs-ai-lab subscription! Switching..." -ForegroundColor Red
    az account set --subscription "2c9b3248-f263-4104-bd24-6446d4db84b9"
}

# ============================================
# 步驟 1: 登入 ACR (token-based, no Docker needed)
# ============================================
Write-Host "[1/5] 確認 ACR 存取..." -ForegroundColor Green
az acr show --name $ACR_NAME --query "loginServer" -o tsv 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "無法存取 ACR: $ACR_NAME"
    exit 1
}
Write-Host "ACR OK: $ACR_NAME.azurecr.io"

# ============================================
# 步驟 2: Build Orchestrator (using ACR Build - no local Docker needed)
# ============================================
Write-Host ""
Write-Host "[2/5] Building Orchestrator via ACR Build..." -ForegroundColor Green
$ORCHESTRATOR_IMAGE = "$ACR_NAME.azurecr.io/orchestrator:prompt-$TIMESTAMP"
$ORCHESTRATOR_DIR = Join-Path $PROJECT_ROOT "gpt-rag-orchestrator"

Write-Host "Directory: $ORCHESTRATOR_DIR"
Write-Host "Image: $ORCHESTRATOR_IMAGE"

az acr build --registry $ACR_NAME --image "orchestrator:prompt-$TIMESTAMP" $ORCHESTRATOR_DIR --no-logs 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) {
    Write-Error "Orchestrator ACR build 失敗"
    exit 1
}
Write-Host "Orchestrator build complete." -ForegroundColor Green

# ============================================
# 步驟 3: Build Frontend (using ACR Build)
# ============================================
Write-Host ""
Write-Host "[3/5] Building Frontend via ACR Build..." -ForegroundColor Green
$FRONTEND_IMAGE = "$ACR_NAME.azurecr.io/frontend:prompt-$TIMESTAMP"
$FRONTEND_DIR = Join-Path $PROJECT_ROOT "gpt-rag-ui"

Write-Host "Directory: $FRONTEND_DIR"
Write-Host "Image: $FRONTEND_IMAGE"

az acr build --registry $ACR_NAME --image "frontend:prompt-$TIMESTAMP" $FRONTEND_DIR --no-logs 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) {
    Write-Error "Frontend ACR build 失敗"
    exit 1
}
Write-Host "Frontend build complete." -ForegroundColor Green

# ============================================
# 步驟 4: (Skipped - ACR Build pushes automatically)
# ============================================
Write-Host ""
Write-Host "[4/5] Images already pushed by ACR Build. Skipping." -ForegroundColor Green

# ============================================
# 步驟 5: Update Container Apps
# ============================================
Write-Host ""
Write-Host "[5/5] Updating Container Apps..." -ForegroundColor Green

Write-Host "Updating Orchestrator..."
az containerapp update `
    --name $CA_ORCHESTRATOR `
    --resource-group $RG `
    --image $ORCHESTRATOR_IMAGE
if ($LASTEXITCODE -ne 0) {
    Write-Error "Orchestrator 更新失敗"
    exit 1
}

Write-Host "Updating Frontend..."
az containerapp update `
    --name $CA_FRONTEND `
    --resource-group $RG `
    --image $FRONTEND_IMAGE
if ($LASTEXITCODE -ne 0) {
    Write-Error "Frontend 更新失敗"
    exit 1
}

# ============================================
# 完成
# ============================================
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " 部署完成！" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Image Tags:" -ForegroundColor Cyan
Write-Host "  Orchestrator: $ORCHESTRATOR_IMAGE"
Write-Host "  Frontend:     $FRONTEND_IMAGE"
Write-Host ""
Write-Host "新功能測試:" -ForegroundColor Cyan
Write-Host "  1. 開啟 Frontend"
Write-Host "  2. /prompt            - 查看目前 prompt 模式"
Write-Host "  3. /prompt lite       - 切換到精簡版 (減少 LLM 思考時間)"
Write-Host "  4. /prompt standard   - 切回標準版"
Write-Host "  5. /debug on          - 開啟 debug 比較 Thinking #1 時間差異"
Write-Host ""
Write-Host "Frontend URL:" -ForegroundColor Yellow
Write-Host "  https://$CA_FRONTEND.nicepond-9d5552be.eastus2.azurecontainerapps.io"
Write-Host ""
