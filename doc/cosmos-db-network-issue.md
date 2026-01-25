# Cosmos DB 網路存取問題排查與解決

## 問題描述

**發生日期**: 2026-01-12

**症狀**: Frontend 顯示 "An internal server error occurred."

**錯誤訊息**:
```
(Forbidden) Request originated from IP 20.10.114.230 through public internet. 
This is blocked by your Cosmos DB account firewall settings.
```

```
(cosmos_vnet_blocked) Access to Cosmos DB is blocked due to VNET configuration. 
Please check your network settings and make sure CosmosDB is public network enabled.
```

## 根本原因

系統中有兩個 Cosmos DB 帳戶的 `publicNetworkAccess` 被設為 `Disabled`：

| Cosmos DB | 用途 | 原始狀態 |
|-----------|------|----------|
| `cosmos-{token}` | 儲存對話記錄 (應用程式用) | `publicNetworkAccess: Disabled` |
| `cosmos-aif-{token}` | Azure AI Agent Service 內部用 | `publicNetworkAccess: Disabled` |

### 為什麼設定被變更？

根據 Activity Log 分析，發現有一個 **Azure Policy 或自動化服務** (AppID: `eadea216-1d5c-4a4b-beaf-4f145e6b1cb4`) 在以下時間點自動修改了 Cosmos DB 設定：

| 時間 | 執行者 | 操作 |
|------|--------|------|
| 2026-01-08 15:10 | {deployer}@{domain}.com | 創建 Cosmos DB |
| **2026-01-08 16:38** | **Azure Policy / 自動化** | **關閉 Public Access** |
| 2026-01-09 00:57 | {deployer}@{domain}.com | 更新設定 |
| **2026-01-09 16:38** | **Azure Policy / 自動化** | **再次關閉 Public Access** |

這很可能是：
1. **Azure Policy** - 企業訂閱常設有「禁止公開 Cosmos DB」的政策
2. **Microsoft Defender for Cloud** - 安全性自動修復
3. **自動化 Runbook** - 定時掃描並關閉公開存取

## 解決方案

### 1. 啟用 Cosmos DB 公共網路存取並設定 IP 白名單

```bash
# 取得 Container App 出站 IP
az containerapp show --name ca-{token}-orchestrator \
  --resource-group {resource-group} \
  --query "properties.outboundIpAddresses" -o tsv

# 取得 Container App Environment Static IP
az containerapp env show --name cae-{token} \
  --resource-group {resource-group} \
  --query "properties.staticIp" -o tsv
```

### 2. 更新應用程式 Cosmos DB

```bash
az cosmosdb update \
  --name cosmos-{token} \
  --resource-group {resource-group} \
  --public-network-access Enabled \
  --ip-range-filter "20.10.114.230,48.214.88.238"
```

### 3. 更新 AI Foundry Cosmos DB

```bash
az cosmosdb update \
  --name cosmos-aif-{token} \
  --resource-group {resource-group} \
  --public-network-access Enabled \
  --ip-range-filter "20.10.114.230,48.214.88.238,0.0.0.0"
```

> **注意**: `0.0.0.0` 表示允許所有 Azure 服務存取，這對 AI Foundry Agent Service 是必要的。

## 目前網路架構

```
┌─────────────────────────────────────────────────────────────┐
│                    Public Internet                          │
└─────────────────────────────────────────────────────────────┘
           │                              │
           ▼                              ▼
┌──────────────────────┐    ┌──────────────────────────────────┐
│  Container Apps      │    │  Azure AI Foundry Agent Service  │
│  (Frontend/Orch)     │    │                                  │
│  IP: 20.10.114.230   │    │                                  │
└──────────────────────┘    └──────────────────────────────────┘
           │                              │
           │ (IP 白名單)                   │ (IP 白名單)
           ▼                              ▼
┌──────────────────────┐    ┌──────────────────────────────────┐
│  cosmos-{token}│    │  cosmos-aif-{token}        │
│  (對話記錄)           │    │  (AI Agent 內部用)                │
└──────────────────────┘    └──────────────────────────────────┘
```

## 驗證設定

```bash
# 檢查 Cosmos DB 設定
az cosmosdb show --name cosmos-{token} \
  --resource-group {resource-group} \
  --query "{name:name, publicNetworkAccess:publicNetworkAccess, ipRules:ipRules[].ipAddressOrRange}" \
  -o json

az cosmosdb show --name cosmos-aif-{token} \
  --resource-group {resource-group} \
  --query "{name:name, publicNetworkAccess:publicNetworkAccess, ipRules:ipRules[].ipAddressOrRange}" \
  -o json
```

## 長期建議

如果需要符合企業安全政策，建議採用以下架構：

### 方案一：Private Endpoint (推薦)

1. 為 Container App Environment 配置 VNet Integration
2. 為 Cosmos DB 建立 Private Endpoint
3. 關閉 Public Network Access

```bash
# 建立 Private Endpoint
az network private-endpoint create \
  --name pe-cosmos-{token} \
  --resource-group {resource-group} \
  --vnet-name <vnet-name> \
  --subnet <subnet-name> \
  --private-connection-resource-id <cosmos-resource-id> \
  --group-id Sql \
  --connection-name cosmos-connection
```

### 方案二：申請 Policy 豁免

如果確認目前架構是合理的，可以申請 Azure Policy 豁免：

```bash
# 查詢相關 Policy
az policy assignment list \
  --scope "/subscriptions/<subscription-id>/resourceGroups/{resource-group}" \
  --query "[?contains(displayName, 'Cosmos') || contains(displayName, 'network')].{name:name, displayName:displayName}" \
  -o table
```

## 相關資源

- [Azure Cosmos DB 網路安全性](https://docs.microsoft.com/azure/cosmos-db/how-to-configure-firewall)
- [Container Apps VNet Integration](https://docs.microsoft.com/azure/container-apps/vnet-custom)
- [Private Endpoints for Cosmos DB](https://docs.microsoft.com/azure/cosmos-db/how-to-configure-private-endpoints)

## 變更歷史

| 日期 | 變更內容 | 執行者 |
|------|----------|--------|
| 2026-01-12 | 發現問題並修復 Cosmos DB 網路設定 | {deployer} |
