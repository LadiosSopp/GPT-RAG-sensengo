<# 
.SYNOPSIS
    為新公司創建 AI Search Index

.DESCRIPTION
    此腳本會創建一個新的 AI Search Index，使用與現有 ragindex 相同的 Schema。
    適用於需要為不同公司/租戶隔離文件的場景。

.PARAMETER IndexName
    新 Index 的名稱（例如：ragindex-companyA）

.PARAMETER SearchServiceName
    AI Search 服務名稱（預設：srch-d5teispadppru）

.PARAMETER ResourceGroup
    資源群組名稱（預設：rg-ethan-test）

.PARAMETER EmbeddingDimensions
    Embedding 向量維度（預設：3072，對應 text-embedding-3-large）

.PARAMETER AnalyzerName
    搜尋分析器名稱（預設：zh-Hant.microsoft 繁體中文）

.EXAMPLE
    .\create-new-index.ps1 -IndexName "ragindex-companyA"
    
.EXAMPLE
    .\create-new-index.ps1 -IndexName "ragindex-ltimindtree" -AnalyzerName "en.microsoft"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$IndexName,
    
    [Parameter(Mandatory=$false)]
    [string]$SearchServiceName = "srch-d5teispadppru",
    
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = "rg-ethan-test",
    
    [Parameter(Mandatory=$false)]
    [int]$EmbeddingDimensions = 3072,
    
    [Parameter(Mandatory=$false)]
    [string]$AnalyzerName = "zh-Hant.microsoft"
)

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  創建新的 AI Search Index" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Index 名稱: $IndexName" -ForegroundColor Yellow
Write-Host "Search 服務: $SearchServiceName" -ForegroundColor Yellow
Write-Host "Embedding 維度: $EmbeddingDimensions" -ForegroundColor Yellow
Write-Host "分析器: $AnalyzerName" -ForegroundColor Yellow
Write-Host ""

# 取得 Access Token
Write-Host "🔐 取得 Azure 認證..." -ForegroundColor Green
$token = az account get-access-token --resource "https://search.azure.com" --query "accessToken" -o tsv
if (-not $token) {
    Write-Host "❌ 無法取得 Access Token，請先執行 'az login'" -ForegroundColor Red
    exit 1
}

$searchEndpoint = "https://$SearchServiceName.search.windows.net"
$headers = @{ 
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json" 
}

# 檢查 Index 是否已存在
Write-Host "🔍 檢查 Index 是否已存在..." -ForegroundColor Green
try {
    $existingIndex = Invoke-RestMethod -Uri "$searchEndpoint/indexes/$IndexName`?api-version=2024-07-01" -Headers $headers -Method Get -ErrorAction SilentlyContinue
    Write-Host "⚠️  Index '$IndexName' 已存在！" -ForegroundColor Yellow
    $confirm = Read-Host "是否要刪除並重新創建？(y/N)"
    if ($confirm -ne "y" -and $confirm -ne "Y") {
        Write-Host "操作已取消" -ForegroundColor Yellow
        exit 0
    }
    Write-Host "🗑️  刪除現有 Index..." -ForegroundColor Yellow
    Invoke-RestMethod -Uri "$searchEndpoint/indexes/$IndexName`?api-version=2024-07-01" -Headers $headers -Method Delete | Out-Null
    Write-Host "✅ 已刪除" -ForegroundColor Green
}
catch {
    # Index 不存在，繼續創建
}

# Index Schema 定義（與 GPT-RAG 原生 Schema 一致）
$indexDefinition = @{
    name = $IndexName
    fields = @(
        @{ name = "id"; type = "Edm.String"; key = $true; searchable = $true; retrievable = $true; filterable = $true; analyzer = "keyword" }
        @{ name = "parent_id"; type = "Edm.String"; searchable = $false; retrievable = $true }
        @{ name = "metadata_storage_path"; type = "Edm.String"; searchable = $false; retrievable = $true }
        @{ name = "metadata_storage_name"; type = "Edm.String"; searchable = $false; retrievable = $true }
        @{ name = "metadata_storage_last_modified"; type = "Edm.DateTimeOffset"; searchable = $false; retrievable = $true; sortable = $true; filterable = $true }
        @{ name = "metadata_security_id"; type = "Collection(Edm.String)"; searchable = $false; retrievable = $true; filterable = $true }
        @{ name = "chunk_id"; type = "Edm.Int32"; searchable = $false; retrievable = $true }
        @{ name = "content"; type = "Edm.String"; searchable = $true; retrievable = $true; analyzer = $AnalyzerName }
        @{ name = "imageCaptions"; type = "Edm.String"; searchable = $true; retrievable = $true; analyzer = $AnalyzerName }
        @{ name = "page"; type = "Edm.Int32"; searchable = $false; retrievable = $true }
        @{ name = "offset"; type = "Edm.Int64"; searchable = $false; retrievable = $true }
        @{ name = "length"; type = "Edm.Int32"; searchable = $false; retrievable = $true }
        @{ name = "title"; type = "Edm.String"; searchable = $true; retrievable = $true; filterable = $true; analyzer = $AnalyzerName }
        @{ name = "category"; type = "Edm.String"; searchable = $true; retrievable = $true; filterable = $true; analyzer = $AnalyzerName }
        @{ name = "filepath"; type = "Edm.String"; searchable = $true; retrievable = $true; filterable = $true; analyzer = "standard" }
        @{ name = "url"; type = "Edm.String"; searchable = $false; retrievable = $true }
        @{ name = "summary"; type = "Edm.String"; searchable = $true; retrievable = $true }
        @{ name = "relatedImages"; type = "Collection(Edm.String)"; searchable = $false; retrievable = $true }
        @{ name = "relatedFiles"; type = "Collection(Edm.String)"; searchable = $false; retrievable = $true }
        @{ name = "source"; type = "Edm.String"; searchable = $false; retrievable = $true; filterable = $true }
        @{ name = "contentVector"; type = "Collection(Edm.Single)"; searchable = $true; retrievable = $true; dimensions = $EmbeddingDimensions; vectorSearchProfile = "default" }
        @{ name = "captionVector"; type = "Collection(Edm.Single)"; searchable = $true; retrievable = $true; dimensions = $EmbeddingDimensions; vectorSearchProfile = "default" }
    )
    corsOptions = @{
        allowedOrigins = @("*")
        maxAgeInSeconds = 60
    }
    vectorSearch = @{
        profiles = @(
            @{ name = "default"; algorithm = "hnsw" }
        )
        algorithms = @(
            @{
                name = "hnsw"
                kind = "hnsw"
                hnswParameters = @{ 
                    m = 4
                    efConstruction = 400
                    efSearch = 500
                    metric = "cosine" 
                }
            }
        )
    }
    semantic = @{
        configurations = @(
            @{
                name = "semantic-config"
                prioritizedFields = @{
                    prioritizedContentFields = @(
                        @{ fieldName = "content" }
                        @{ fieldName = "imageCaptions" }
                    )
                    prioritizedKeywordsFields = @(
                        @{ fieldName = "category" }
                    )
                }
            }
        )
    }
}

# 創建 Index
Write-Host "📝 創建新 Index..." -ForegroundColor Green
$body = $indexDefinition | ConvertTo-Json -Depth 10

try {
    $result = Invoke-RestMethod -Uri "$searchEndpoint/indexes?api-version=2024-07-01" -Headers $headers -Method Post -Body $body
    Write-Host ""
    Write-Host "✅ Index '$IndexName' 創建成功！" -ForegroundColor Green
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  下一步設定說明" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "1️⃣  在 App Configuration 中新增設定（針對特定公司的 Ingestion）:" -ForegroundColor Yellow
    Write-Host "    Key: AI_SEARCH_INDEX_NAME" -ForegroundColor White
    Write-Host "    Value: $IndexName" -ForegroundColor White
    Write-Host "    Label: company-xxx（可選，用於區分不同公司）" -ForegroundColor Gray
    Write-Host ""
    Write-Host "2️⃣  或在 Container App 環境變數中設定:" -ForegroundColor Yellow
    Write-Host "    az containerapp update --name ca-xxx-dataingest \" -ForegroundColor White
    Write-Host "       --resource-group $ResourceGroup \" -ForegroundColor White
    Write-Host "       --set-env-vars AI_SEARCH_INDEX_NAME=$IndexName" -ForegroundColor White
    Write-Host ""
    Write-Host "3️⃣  Orchestrator 查詢設定:" -ForegroundColor Yellow
    Write-Host "    Key: SEARCH_RAG_INDEX_NAME" -ForegroundColor White
    Write-Host "    Value: $IndexName" -ForegroundColor White
    Write-Host ""
}
catch {
    Write-Host "❌ 創建失敗: $_" -ForegroundColor Red
    Write-Host "Response: $($_.Exception.Response)" -ForegroundColor Red
    exit 1
}
