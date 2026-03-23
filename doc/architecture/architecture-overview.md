# GPT-RAG Project Architecture Overview

## Project Overview

GPT-RAG is an enterprise-grade **Retrieval-Augmented Generation (RAG)** solution accelerator built on **Azure AI services**. It enables organizations to build intelligent Q&A systems that leverage their own documents and data sources.

---

## Multi-Repository Structure

The project consists of 5 interconnected repositories:

| Repository | Purpose | Technology Stack |
|------------|---------|------------------|
| **GPT-RAG** | Main deployment project with Infrastructure as Code | Bicep, Azure Developer CLI |
| **gpt-rag-ui** | Frontend chat interface | Chainlit, FastAPI, Python |
| **gpt-rag-orchestrator** | RAG orchestration engine with AI Agent capabilities | Azure AI Foundry Agent Service, Semantic Kernel, Python |
| **gpt-rag-ingestion** | Document processing and indexing service | Azure AI Search, Python, APScheduler |
| **gpt-rag-mcp** | Model Context Protocol server for tool extensions | FastMCP, Semantic Kernel |

---

## Azure Resources

### Core AI Services

| Service | Resource Name Pattern | Purpose |
|---------|----------------------|---------|
| **Azure AI Foundry** | `aifoundry-{token}` | AI model management platform, hosts Agent Service |
| **Azure OpenAI** | (within AI Foundry) | LLM inference (GPT-4.1, GPT-5, Embeddings) |
| **Azure AI Search** | `search-{token}` | Vector and hybrid search for RAG retrieval |
| **Cosmos DB** | `cosmos-{token}` | Conversation history and state storage |

### Compute & Storage

| Service | Resource Name Pattern | Purpose |
|---------|----------------------|---------|
| **Container Apps** | `ca-{token}-{service}` | Serverless container runtime for all services |
| **Container Apps Environment** | `cae-{token}` | Shared environment for Container Apps |
| **Storage Account** | `st{token}` | Document storage (documents, images, jobs containers) |
| **Container Registry** | `cr{token}` | Docker image storage |

### Configuration & Security

| Service | Resource Name Pattern | Purpose |
|---------|----------------------|---------|
| **App Configuration** | `appconfig-{token}` | Centralized configuration management |
| **Key Vault** | `kv-{token}` | Secrets management (API keys, connection strings) |

### Monitoring

| Service | Resource Name Pattern | Purpose |
|---------|----------------------|---------|
| **Application Insights** | `appi-{token}` | Application performance monitoring and distributed tracing |
| **Log Analytics Workspace** | `law-{token}` | Centralized log collection |

---

## Components

### 1. Frontend (gpt-rag-ui)

**Container App**: `ca-{token}-frontend`

**Responsibilities**:
- Provides Chainlit-based chat interface for users
- Handles SSE (Server-Sent Events) streaming for real-time response display
- Shows timing information for each processing phase
- Supports model switching (GPT-4.1, GPT-5, GPT-5 Mini, GPT-5 Nano)
- Collects user feedback on responses
- Provides document download API

**Key Files**:
- `app.py` - Chainlit event handlers
- `main.py` - FastAPI entry point
- `orchestrator_client.py` - Communication with Orchestrator service

### 2. Orchestrator (gpt-rag-orchestrator)

**Container App**: `ca-{token}-orchestrator`

**Responsibilities**:
- Core RAG orchestration engine
- Manages AI Agent workflows using Azure AI Foundry Agent Service
- Executes tool calls (AI Search retrieval, Bing grounding)
- Handles conversation management with Cosmos DB
- Streams responses back to Frontend via SSE

**Agent Strategies**:
| Strategy | Description |
|----------|-------------|
| `single_agent_rag` | Single agent RAG mode (default) |
| `mcp` | Model Context Protocol server mode |
| `nl2sql` | Natural language to SQL queries |

**Key Files**:
- `src/main.py` - FastAPI entry point
- `src/orchestration/orchestrator.py` - Core orchestration logic
- `src/strategies/` - Agent strategy implementations

### 3. Data Ingestion (gpt-rag-ingestion)

**Container App**: `ca-{token}-dataingest`

**Responsibilities**:
- Processes documents from multiple sources (Blob Storage, SharePoint)
- Chunks documents into searchable segments
- Generates vector embeddings using Azure OpenAI
- Uploads indexed content to Azure AI Search
- Runs scheduled jobs for continuous indexing

**Supported Document Types**:
- PDF, Word (.docx), Excel (.xlsx)
- Images (.png, .jpg) with OCR support
- Text files

**Scheduled Jobs**:
| Job | Trigger | Function |
|-----|---------|----------|
| Blob Indexer | `CRON_RUN_BLOB_INDEX` | Index documents from Blob Storage |
| Blob Purger | `CRON_RUN_BLOB_PURGE` | Remove deleted documents from index |
| SharePoint Indexer | `CRON_RUN_SHAREPOINT_INDEX` | Index SharePoint documents |
| NL2SQL Indexer | `CRON_RUN_NL2SQL_INDEX` | Build NL2SQL metadata |
| Images Purger | `CRON_RUN_IMAGES_PURGE` | Clean up multimodal images |

**Key Files**:
- `main.py` - FastAPI + APScheduler entry point
- `jobs/blob_storage_indexer.py` - Blob indexing logic
- `chunking/` - Document chunking strategies

### 4. MCP Server (gpt-rag-mcp)

**Container App**: `ca-{token}-mcp`

**Responsibilities**:
- Provides Model Context Protocol server for extended tool capabilities
- Exposes additional tools (e.g., Wikipedia search) to the Agent
- Enables custom tool and prompt template extensions
- Integrates with Orchestrator when `AGENT_STRATEGY=mcp`

**Key Files**:
- `src/server.py` - FastMCP server implementation
- `src/tools/` - Custom tool definitions

**Current Status** (2026-01-21):
- 目前預設使用 `AGENT_STRATEGY=single_agent_rag`，MCP Container 處於閒置狀態
- 可將 MCP Container replicas 設為 0 以節省資源
- 啟用方式：將 App Configuration 的 `AGENT_STRATEGY` 改為 `mcp` 並重啟 Orchestrator

---

## Data Flow

### Query Processing Flow

```
User enters question in browser
         │
         ▼
┌─────────────────────────────────────┐
│      Frontend (Chainlit UI)         │
│   Container App: ca-xxx-frontend    │
└─────────────────────────────────────┘
         │ HTTP POST /orchestrator (SSE)
         ▼
┌─────────────────────────────────────┐
│        Orchestrator Service         │
│  Container App: ca-xxx-orchestrator │
└─────────────────────────────────────┘
         │
         ├──────────────────────────────────┐
         │                                  │
         ▼                                  ▼
┌─────────────────┐              ┌─────────────────────┐
│    Cosmos DB    │              │  Azure AI Foundry   │
│ Load/Save Chat  │              │    Agent Service    │
│    History      │              └─────────────────────┘
└─────────────────┘                        │
                                           │
                          ┌────────────────┼────────────────┐
                          │                │                │
                          ▼                ▼                ▼
                 ┌──────────────┐  ┌─────────────┐  ┌──────────────┐
                 │ AI Search    │  │ Azure OpenAI│  │ Bing Search  │
                 │ Retrieval    │  │ LLM (GPT-5) │  │ (Optional)   │
                 │ Tool         │  │             │  │              │
                 └──────────────┘  └─────────────┘  └──────────────┘
                          │                │
                          │                │
                          ▼                ▼
                 ┌─────────────────────────────────────┐
                 │   LLM generates response using     │
                 │   retrieved context + conversation │
                 └─────────────────────────────────────┘
                                   │
                                   │ SSE Stream
                                   ▼
                 ┌─────────────────────────────────────┐
                 │  Frontend displays response in     │
                 │  real-time with timing info        │
                 └─────────────────────────────────────┘
```

**Flow Description**:
1. User enters a question in the Chainlit chat interface
2. Frontend sends request to Orchestrator via HTTP POST with SSE
3. Orchestrator loads conversation history from Cosmos DB
4. Orchestrator invokes Azure AI Foundry Agent Service
5. Agent decides which tools to call (AI Search, Bing, etc.)
6. AI Search retrieves relevant document chunks using vector similarity
7. LLM generates response using retrieved context
8. Response streams back to Frontend via SSE
9. Conversation is saved to Cosmos DB

### Document Ingestion Flow

```
┌─────────────────────────────────────┐
│   Documents uploaded to Blob        │
│   Storage (documents container)     │
└─────────────────────────────────────┘
                   │
                   │ Scheduled trigger (CRON)
                   ▼
┌─────────────────────────────────────┐
│     Ingestion Service               │
│  Container App: ca-xxx-dataingest   │
└─────────────────────────────────────┘
                   │
         ┌────────┴────────┐
         ▼                 ▼
┌─────────────────┐  ┌─────────────────┐
│  Read document  │  │  Parse & OCR    │
│  from Blob      │  │  (if image/PDF) │
└─────────────────┘  └─────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│      Document Chunker               │
│  Split into searchable segments     │
│  (configurable chunk size/overlap)  │
└─────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│      Azure OpenAI Embeddings        │
│  Generate vector embeddings for     │
│  each chunk (text-embedding-3-large)│
└─────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│      Azure AI Search                │
│  Upload chunks with vectors to      │
│  search index (hybrid search ready) │
└─────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│      Job Logging                    │
│  Write status to jobs container     │
└─────────────────────────────────────┘
```

**Flow Description**:
1. Users or systems upload documents to Blob Storage
2. Ingestion service triggers on schedule (configurable CRON)
3. Service reads documents and applies parsing/OCR as needed
4. Documents are split into chunks using configurable strategies
5. Each chunk is converted to vector embedding via Azure OpenAI
6. Chunks with embeddings are uploaded to Azure AI Search index
7. Job status is logged for monitoring

---

## Service Communication Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                     Container Apps Environment (cae-xxx)                      │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐                    ┌──────────────────┐                │
│  │    Frontend      │  HTTP/SSE          │   Orchestrator   │                │
│  │  (External       │◄──────────────────►│  (Internal       │                │
│  │   Ingress)       │                    │   Ingress)       │                │
│  └──────────────────┘                    └──────────────────┘                │
│          ▲                                        │                          │
│          │                                        │                          │
│      Internet                                     │                          │
│      Users                     ┌──────────────────┼──────────────────┐       │
│                                │                  │                  │       │
│                                ▼                  ▼                  ▼       │
│                    ┌──────────────────┐  ┌──────────────┐  ┌──────────────┐  │
│                    │   MCP Server     │  │  Cosmos DB   │  │ AI Foundry   │  │
│                    │  (Internal       │  │              │  │ Agent Svc    │  │
│                    │   Ingress)       │  │              │  │              │  │
│                    └──────────────────┘  └──────────────┘  └──────────────┘  │
│                                                                    │         │
│  ┌──────────────────┐                                              │         │
│  │  Data Ingestion  │                                              ▼         │
│  │  (Internal       │──────────────────────────────────►┌──────────────────┐ │
│  │   Ingress)       │                                   │  Azure AI Search │ │
│  └──────────────────┘                                   │                  │ │
│          │                                              └──────────────────┘ │
│          ▼                                                       ▲           │
│  ┌──────────────────┐                                            │           │
│  │  Blob Storage    │                                            │           │
│  │  (documents)     │────────────────────────────────────────────┘           │
│  └──────────────────┘           Vector embeddings                            │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Configuration Management

All services read configuration from **Azure App Configuration** with Key Vault references for secrets.

### Key Configuration Items

| Configuration Key | Description | Example Value |
|-------------------|-------------|---------------|
| `AGENT_STRATEGY` | Agent strategy to use | `single_agent_rag`, `mcp`, `nl2sql` |
| `CHAT_DEPLOYMENT_NAME` | Default LLM deployment | `chat` |
| `EMBEDDING_DEPLOYMENT_NAME` | Embedding model deployment | `embedding` |
| `SEARCH_RAGINDEX_TOP_K` | Number of search results | `3` |
| `SEARCH_APPROACH` | Search method | `hybrid`, `vector`, `term` |
| `CRON_RUN_BLOB_INDEX` | Blob indexer schedule | `0 */30 * * * *` |

---

## Gemini Image Generation Prompts

### Prompt 1: High-Level Architecture Diagram

```
Create an architecture diagram for a RAG (Retrieval-Augmented Generation) system with these components:

Main components:
1. "Frontend" - Chainlit chat interface, receives user questions, displays streaming responses
2. "Orchestrator" - RAG orchestration service with AI Agent capabilities
3. "Data Ingestion" - Document processing service that chunks and indexes documents
4. "MCP Server" - Model Context Protocol server for tool extensions

Azure services:
- "Azure AI Foundry" with "Agent Service" inside - manages AI agents and tool calls
- "Azure OpenAI" with models "GPT-5" and "Embeddings" - LLM inference
- "Azure AI Search" - vector and hybrid search index
- "Cosmos DB" - conversation history storage
- "Blob Storage" with containers "documents", "images", "jobs"
- "App Configuration" - centralized settings
- "Key Vault" - secrets management
- "Application Insights" - monitoring

All 4 main components run inside "Container Apps Environment"

Connections:
- Users connect to Frontend
- Frontend connects to Orchestrator
- Orchestrator connects to: Cosmos DB, Azure AI Foundry Agent Service
- Agent Service connects to: Azure OpenAI, Azure AI Search
- Orchestrator optionally connects to MCP Server
- Data Ingestion reads from Blob Storage
- Data Ingestion writes to Azure AI Search
- Data Ingestion uses Azure OpenAI for embeddings
```

### Prompt 2: Data Flow Diagram

```
Create a data flow diagram showing two main flows in a RAG system:

FLOW 1 - Query Processing (left side):
Step 1: User enters question
Step 2: Frontend receives question
Step 3: Orchestrator loads chat history from Cosmos DB
Step 4: Orchestrator calls AI Foundry Agent Service
Step 5: Agent calls AI Search to retrieve relevant documents
Step 6: Agent calls Azure OpenAI GPT-5 to generate answer
Step 7: Response streams back through Orchestrator to Frontend
Step 8: Conversation saved to Cosmos DB

FLOW 2 - Document Ingestion (right side):
Step 1: Document uploaded to Blob Storage
Step 2: Ingestion Service triggered by schedule
Step 3: Document parsed and chunked
Step 4: Azure OpenAI generates embeddings for each chunk
Step 5: Chunks with embeddings uploaded to Azure AI Search index
Step 6: Job status logged

Show arrows indicating data flow direction between steps
```

### Prompt 3: Component Relationship Diagram

```
Create a component diagram showing the GPT-RAG multi-repository project structure:

5 repositories connected together:

1. "GPT-RAG" (main) - Infrastructure deployment with Bicep
   - Deploys all Azure resources
   - Contains azure.yaml for Azure Developer CLI

2. "gpt-rag-ui" - Frontend service
   - Chainlit chat interface
   - Connects to Orchestrator

3. "gpt-rag-orchestrator" - Core RAG engine
   - Azure AI Foundry Agent Service integration
   - Semantic Kernel framework
   - Connects to: Cosmos DB, AI Search, Azure OpenAI

4. "gpt-rag-ingestion" - Data processing
   - Document chunking
   - Vector embedding generation
   - Connects to: Blob Storage, AI Search, Azure OpenAI

5. "gpt-rag-mcp" - Tool extensions
   - Model Context Protocol server
   - Custom tools (Wikipedia search, etc.)
   - Connected from Orchestrator when MCP strategy enabled

Show GPT-RAG as the parent deploying all other components
Show data flow arrows between components
```

---

## Summary

GPT-RAG is a modular, enterprise-ready RAG solution with:

- **5 independent services** that can be scaled separately
- **AI Agent capabilities** via Azure AI Foundry Agent Service
- **Multiple data sources** support (Blob Storage, SharePoint, SQL)
- **Real-time streaming** responses via SSE
- **Centralized configuration** via App Configuration
- **Full observability** with Application Insights

---

## Multi-Tenant Architecture (2026-01-20)

GPT-RAG 支援多租戶架構，每個租戶可以有獨立的文件容器和搜尋索引：

### 設計原則

| 操作 | 配置方式 | 說明 |
|------|----------|------|
| **Ingestion (寫入)** | App Configuration 指定 | 批次處理，需預先設定目標 Index |
| **Search (查詢)** | API 動態切換 | 每次查詢可指定不同 Index |

### 資源命名慣例

| 租戶 | Blob Container | Search Index |
|------|----------------|--------------|
| 預設 | `documents` | `ragindex-{token}` |
| Company A | `documents-company-a` | `ragindex-company-a` |
| Company B | `documents-company-b` | `ragindex-company-b` |

### Ingestion 配置

在 App Configuration 中設定 (需使用 `gpt-rag` label)：
```
DOCUMENTS_STORAGE_CONTAINER = documents-company-{x}
SEARCH_RAG_INDEX_NAME = ragindex-company-{x}
```

⚠️ **注意**: 修改配置後需重啟 Ingestion Container App 才會生效

### Search 動態切換

Orchestrator API 已支援 `search_index` 參數：
```json
{
  "ask": "你的問題",
  "search_index": "ragindex-company-a"
}
```

前端可根據用戶租戶身份動態傳入不同的 Index 名稱。
