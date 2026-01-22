---
title: Sensengo 客戶部署資源清單
output: word_document
---

# Sensengo 客戶部署資源清單

> 📅 建立日期: 2026年1月21日  
> 📍 部署區域: East US 2 (建議)  
> 🔧 部署模式: Public Access (無 Network Isolation)

---

## 📋 目錄

1. [部署資源清單](#1-部署資源清單)

---

## 1. 部署資源清單

### 1.1 核心 Azure 資源

| 資源類型 | 資源名稱 (範例) | SKU/層級 | 用途 |
|---------|----------------|----------|------|
| **AI Foundry** | `aif-{token}-sensengo` | Standard | AI 服務託管平台 |
| **Azure OpenAI** | (AI Foundry 內建) | GlobalStandard | LLM 模型部署 |
| **Azure AI Search** | `srch-{token}-sensengo` | **Basic** | 向量與混合搜尋 |
| **Cosmos DB** | `cosmos-{token}-sensengo` | Serverless | 對話歷史、資料來源儲存 |
| **Container Apps** | `ca-{token}-*-sensengo` (3個) | **Consumption** | 微服務運行環境 |
| **Container Apps Environment** | `cae-{token}-sensengo` | - | Container Apps 託管環境 |
| **Container Registry** | `cr{token}sensengo` | Standard | Docker 映像儲存 |
| **Storage Account** | `st{token}sensengo` | Standard LRS | 文檔儲存 |
| **Storage Account (AI Foundry)** | `staif{token}sensengo` | Standard LRS | AI Foundry 專用儲存 |
| **App Configuration** | `appcs-{token}-sensengo` | Standard | 集中配置管理 |
| **Key Vault** | `kv-{token}-sensengo` | Standard | 密鑰管理 |
| **Key Vault (AI)** | `kv-ai-{token}-sensengo` | Standard | AI 服務密鑰 |
| **Log Analytics** | `log-{token}-sensengo` | Pay-as-you-go | 日誌收集 |
| **Application Insights** | `appi-{token}-sensengo` | Pay-as-you-go | 應用監控 |

### 1.2 Container Apps 服務明細

| 服務名稱 | 功能 | Workload Profile | 副本設定 |
|---------|------|------------------|---------|
| `ca-{token}-orchestrator-sensengo` | RAG 協調器 | **Consumption** | min: 0, max: 1 |
| `ca-{token}-frontend-sensengo` | Web UI | **Consumption** | min: 0, max: 1 |
| `ca-{token}-dataingest-sensengo` | 文檔索引 | **Consumption** | min: 0, max: 1 |

> ✅ **成本優化**: 使用 Consumption-only 環境，Container Apps 閒置時 scale to zero，**不產生費用**。


### 1.3 AI 模型部署

| 模型名稱 | 部署名稱 | SKU | 容量 (TPM) |
|---------|---------|-----|-----------|
| **GPT-5.2** | `chat` | GlobalStandard | 40K |
| text-embedding-3-large | `text-embedding` | Standard | 40K |
