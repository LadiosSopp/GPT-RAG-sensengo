# Deploy Debug Feature to Azure Container Apps
# 部署 Debug 功能到 Azure Container Apps
#
# 使用方法：
#   .\scripts\deploy-debug-feature.ps1
#
# 需要先確認：
# 1. 已安裝 Docker Desktop 並正在運行
# 2. 已安裝 Azure CLI 並已登入 (az login)
# 3. 有 ACR push 權限

$ErrorActionPreference = "Stop"

# ============================================
# 設定變數 (根據 history.md 中的實際值)
# ============================================
$ACR_NAME = "cr2v3lfktkn4xam"
$RG = "rg-2v3lfktkn4xam-gprag"
$TIMESTAMP = Get-Date -Format "yyyyMMddHHmmss"

# Container App 名稱 (根據 history.md)
$CA_FRONTEND = "ca-2v3lfktkn4xam-frontend-gprag"
$CA_ORCHESTRATOR = "ca-2v3lfktkn4xam-orch-gprag"

# 專案根目錄
$PROJECT_ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Deploy Debug Feature" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "ACR: $ACR_NAME" -ForegroundColor Yellow
Write-Host "Resource Group: $RG" -ForegroundColor Yellow
Write-Host "Timestamp: $TIMESTAMP" -ForegroundColor Yellow
Write-Host ""

# ============================================
# 步驟 1: 登入 ACR
# ============================================
Write-Host "[1/5] 登入 Azure Container Registry..." -ForegroundColor Green
az acr login --name $ACR_NAME
if ($LASTEXITCODE -ne 0) {
    Write-Error "ACR 登入失敗"
    exit 1
}

# ============================================
# 步驟 2: Build Frontend
# ============================================
Write-Host ""
Write-Host "[2/5] Building Frontend Docker image..." -ForegroundColor Green
$FRONTEND_IMAGE = "$ACR_NAME.azurecr.io/frontend:$TIMESTAMP"
$FRONTEND_DIR = Join-Path $PROJECT_ROOT "gpt-rag-ui"

Write-Host "Directory: $FRONTEND_DIR"
Write-Host "Image: $FRONTEND_IMAGE"

Push-Location $FRONTEND_DIR
docker build -t $FRONTEND_IMAGE .
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Write-Error "Frontend build 失敗"
    exit 1
}
Pop-Location

# ============================================
# 步驟 3: Build Orchestrator
# ============================================
Write-Host ""
Write-Host "[3/5] Building Orchestrator Docker image..." -ForegroundColor Green
$ORCHESTRATOR_IMAGE = "$ACR_NAME.azurecr.io/orchestrator:$TIMESTAMP"
$ORCHESTRATOR_DIR = Join-Path $PROJECT_ROOT "gpt-rag-orchestrator"

Write-Host "Directory: $ORCHESTRATOR_DIR"
Write-Host "Image: $ORCHESTRATOR_IMAGE"

Push-Location $ORCHESTRATOR_DIR
docker build -t $ORCHESTRATOR_IMAGE .
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Write-Error "Orchestrator build 失敗"
    exit 1
}
Pop-Location

# ============================================
# 步驟 4: Push Images to ACR
# ============================================
Write-Host ""
Write-Host "[4/5] Pushing images to ACR..." -ForegroundColor Green

Write-Host "Pushing Frontend..."
docker push $FRONTEND_IMAGE
if ($LASTEXITCODE -ne 0) {
    Write-Error "Frontend push 失敗"
    exit 1
}

Write-Host "Pushing Orchestrator..."
docker push $ORCHESTRATOR_IMAGE
if ($LASTEXITCODE -ne 0) {
    Write-Error "Orchestrator push 失敗"
    exit 1
}

# ============================================
# 步驟 5: Update Container Apps
# ============================================
Write-Host ""
Write-Host "[5/5] Updating Container Apps..." -ForegroundColor Green

Write-Host "Updating Frontend Container App..."
az containerapp update `
    --name $CA_FRONTEND `
    --resource-group $RG `
    --image $FRONTEND_IMAGE
if ($LASTEXITCODE -ne 0) {
    Write-Error "Frontend Container App 更新失敗"
    exit 1
}

Write-Host "Updating Orchestrator Container App..."
az containerapp update `
    --name $CA_ORCHESTRATOR `
    --resource-group $RG `
    --image $ORCHESTRATOR_IMAGE
if ($LASTEXITCODE -ne 0) {
    Write-Error "Orchestrator Container App 更新失敗"
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
Write-Host "  Frontend:     $FRONTEND_IMAGE"
Write-Host "  Orchestrator: $ORCHESTRATOR_IMAGE"
Write-Host ""
Write-Host "測試步驟:" -ForegroundColor Cyan
Write-Host "  1. 開啟 Frontend URL"
Write-Host "  2. 在對話框輸入 /debug 開啟 debug 模式"
Write-Host "  3. 問一個問題，等待回應"
Write-Host "  4. 應該看到 Debug 面板顯示 Timing 和 Prompting 詳情"
Write-Host ""
Write-Host "Frontend URL:" -ForegroundColor Yellow
Write-Host "  https://$CA_FRONTEND.nicepond-9d5552be.eastus2.azurecontainerapps.io"
Write-Host ""
