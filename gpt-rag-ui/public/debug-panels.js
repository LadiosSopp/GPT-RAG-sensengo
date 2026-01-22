/**
 * Debug Panels JavaScript
 * Creates left and right side panels for displaying timing and prompting information
 * Also handles model indicator display near input field
 * 
 * Mode detection via URL query parameter:
 * - ?mode=demo = Demo mode (clean UI, no debug panels)
 * - Default or ?mode=dev = Dev mode (full debug UI)
 */

(function() {
    'use strict';

    // Store debug info
    let lastTimingInfo = null;
    let lastPromptingInfo = null;
    
    // Detect UI mode from URL query parameter
    // ?mode=demo = demo mode, otherwise dev mode
    const urlParams = new URLSearchParams(window.location.search);
    const uiMode = urlParams.get('mode') === 'demo' ? 'demo' : 'dev';
    let currentModel = 'GPT-5 (Latest)';  // Default model
    
    console.log('[DebugPanels] UI Mode detected from URL:', uiMode);

    // Decode base64 with UTF-8 support (for Chinese characters)
    function decodeBase64UTF8(base64Str) {
        try {
            // Decode base64 to binary string
            const binaryStr = atob(base64Str);
            // Convert binary string to Uint8Array
            const bytes = new Uint8Array(binaryStr.length);
            for (let i = 0; i < binaryStr.length; i++) {
                bytes[i] = binaryStr.charCodeAt(i);
            }
            // Decode UTF-8 bytes to string
            const decoder = new TextDecoder('utf-8');
            return decoder.decode(bytes);
        } catch (e) {
            console.error('[DebugPanels] Error decoding base64 UTF-8:', e);
            return null;
        }
    }

    // Create model indicator near input field gear icon
    function createModelIndicator() {
        if (document.getElementById('model-indicator')) {
            return;
        }
        
        const indicator = document.createElement('div');
        indicator.id = 'model-indicator';
        indicator.className = 'model-indicator';
        indicator.innerHTML = '<span class="model-label">🤖</span><span class="model-name">' + currentModel + '</span>';
        
        // Try to insert next to the gear icon in the input area
        function insertIndicator() {
            // Look for the settings/gear button in the input area
            const gearButton = document.querySelector('[data-testid="settings-button"], button[aria-label*="settings"], button[aria-label*="Settings"], .MuiIconButton-root svg[data-testid="SettingsIcon"]')?.closest('button');
            
            if (gearButton && gearButton.parentElement) {
                // Insert the indicator after the gear button
                gearButton.parentElement.insertBefore(indicator, gearButton.nextSibling);
                indicator.classList.add('model-indicator-inline');
                console.log('[DebugPanels] Model indicator inserted next to gear icon');
                return true;
            }
            
            // Fallback: look for the input area container
            const inputArea = document.querySelector('.composer, [data-testid="composer"], .MuiBox-root:has(textarea)');
            if (inputArea) {
                inputArea.appendChild(indicator);
                console.log('[DebugPanels] Model indicator appended to input area');
                return true;
            }
            
            return false;
        }
        
        // Try to insert, if not found yet, retry a few times
        if (!insertIndicator()) {
            let attempts = 0;
            const retryInterval = setInterval(() => {
                attempts++;
                if (insertIndicator() || attempts > 10) {
                    clearInterval(retryInterval);
                    if (attempts > 10) {
                        // Final fallback: append to body with fixed position
                        document.body.appendChild(indicator);
                        console.log('[DebugPanels] Model indicator appended to body (fallback)');
                    }
                }
            }, 500);
        }
    }

    // Update model indicator
    function updateModelIndicator(modelName) {
        if (!modelName) return;
        currentModel = modelName;
        
        const indicator = document.getElementById('model-indicator');
        if (indicator) {
            const nameSpan = indicator.querySelector('.model-name');
            if (nameSpan) {
                nameSpan.textContent = modelName;
            }
        }
        console.log('[DebugPanels] Model updated to:', modelName);
    }

    // Create the panel container
    function createDebugPanels() {
        // Check if panels already exist
        if (document.getElementById('debug-panels-container')) {
            return;
        }
        
        // Don't create debug panels in demo mode
        if (uiMode === 'demo') {
            console.log('[DebugPanels] Demo mode - skipping debug panels');
            return;
        }

        // Create container
        const container = document.createElement('div');
        container.id = 'debug-panels-container';
        container.innerHTML = `
            <div id="timing-panel" class="debug-panel left-panel">
                <div class="panel-header">
                    <span class="panel-title">⏱️ 時間統計</span>
                    <button class="panel-toggle" onclick="togglePanel('timing-panel')">−</button>
                </div>
                <div class="panel-content" id="timing-content">
                    <p class="empty-state">尚無資料</p>
                </div>
            </div>
            <div id="prompting-panel" class="debug-panel right-panel">
                <div class="panel-header">
                    <span class="panel-title">📝 Prompting 詳情</span>
                    <button class="panel-toggle" onclick="togglePanel('prompting-panel')">−</button>
                </div>
                <div class="panel-content" id="prompting-content">
                    <p class="empty-state">尚無資料</p>
                </div>
            </div>
        `;

        document.body.appendChild(container);
        console.log('[DebugPanels] Panels created');
    }

    // Toggle panel collapse/expand
    window.togglePanel = function(panelId) {
        const panel = document.getElementById(panelId);
        const content = panel.querySelector('.panel-content');
        const toggle = panel.querySelector('.panel-toggle');
        
        if (content.style.display === 'none') {
            content.style.display = 'block';
            toggle.textContent = '−';
        } else {
            content.style.display = 'none';
            toggle.textContent = '+';
        }
    };

    // Map stage names to friendly display names
    function getStageFriendlyName(stage) {
        if (!stage) return stage;
        // Flow stages
        if (stage === 'get_or_create_thread') return '🧵 建立/取得 Thread';
        if (stage === 'get_or_create_agent') return '🤖 建立/取得 Agent';
        if (stage === 'send_user_message') return '📤 發送訊息';
        if (stage === 'consolidate_history') return '📚 整理對話歷史';
        if (stage === 'cleanup_agent') return '🧹 清理 Agent';
        // Streaming stages
        if (stage === 'stream_start') return '⏱️ 開始串流';
        if (stage === 'api_init') return '🔌 API 初始化';
        if (stage.startsWith('llm_thinking_')) {
            const num = stage.split('_')[2];
            return `🧠 LLM 思考 #${num}`;
        }
        if (stage === 'llm_thinking') return '🧠 LLM 思考';
        if (stage === 'tool_execution') return '🔧 工具執行';
        if (stage === 'response_generation') return '✍️ 回應生成';
        return stage;
    }

    // Map stage to service provider
    function getServiceForStage(stage) {
        if (!stage) return '';
        // AI Search related
        if (stage === 'tool_execution') return '🔎 AI Search';
        // All other stages are Azure AI Foundry (Agent API)
        if (stage === 'get_or_create_thread') return '🤖 AI Foundry';
        if (stage === 'get_or_create_agent') return '🤖 AI Foundry';
        if (stage === 'send_user_message') return '🤖 AI Foundry';
        if (stage === 'consolidate_history') return '🤖 AI Foundry';
        if (stage === 'cleanup_agent') return '🤖 AI Foundry';
        if (stage === 'stream_start') return '🤖 AI Foundry';
        if (stage === 'api_init') return '🤖 AI Foundry';
        if (stage.startsWith('llm_thinking')) return '🧠 AI Foundry';
        if (stage === 'response_generation') return '🧠 AI Foundry';
        return '';
    }

    // Format timing info to HTML
    function formatTimingHtml(info) {
        if (!info) return '<p class="empty-state">尚無資料</p>';

        let html = '';
        
        // Total duration - 以秒為主要單位
        const totalMs = info.total_duration_ms || 0;
        const totalSec = totalMs / 1000;
        html += `<div class="stat-item"><strong>總耗時:</strong> ${totalSec.toFixed(2)} 秒</div>`;
        
        // Agent monitoring info
        if (info.agent_id) {
            const agentSourceMap = {
                'model_specific': '模型專用',
                'conversation': '對話重用',
                'generic': '通用',
                'new': '新建'
            };
            const agentSource = agentSourceMap[info.agent_source] || info.agent_source || '未知';
            const agentStatus = info.agent_reused ? '✅ 重用' : '🆕 新建';
            const toolsStatus = info.tools_updated ? '🔄 已更新' : '✓ 不需更新';
            
            html += '<div class="agent-monitor-section">';
            html += '<div class="section-title">🤖 Agent 監控</div>';
            html += `<div class="stat-item"><strong>Agent ID:</strong> <code>${info.agent_id.substring(0, 20)}...</code></div>`;
            html += `<div class="stat-item"><strong>狀態:</strong> ${agentStatus}</div>`;
            html += `<div class="stat-item"><strong>來源:</strong> ${agentSource}</div>`;
            html += `<div class="stat-item"><strong>Tools:</strong> ${toolsStatus}</div>`;
            if (info.tools_configured && info.tools_configured.length > 0) {
                html += `<div class="stat-item"><strong>配置的工具:</strong> ${info.tools_configured.join(', ')}</div>`;
            }
            html += '</div>';
        }
        
        // Calculate sum of phases for comparison
        const timings = info.timings || [];
        const sumMs = timings.reduce((acc, t) => acc + (t.duration_ms || 0), 0);
        if (sumMs > 0 && totalMs > 0) {
            const coverage = ((sumMs / totalMs) * 100).toFixed(1);
            html += `<div class="stat-item" style="font-size:0.85em;color:#666;"><strong>階段覆蓋率:</strong> ${coverage}%</div>`;
        }
        
        // Search timing data
        const searchDebug = info.search_debug || {};
        const embeddingsMs = searchDebug.embeddings_time_ms || 0;
        const searchMs = searchDebug.search_time_ms || 0;
        
        // Timing breakdown - 以秒為主要單位，加入服務歸屬
        if (timings.length > 0) {
            html += '<table class="timing-table"><thead><tr><th>階段</th><th>耗時</th><th>服務</th></tr></thead><tbody>';
            timings.forEach(t => {
                const stage = getStageFriendlyName(t.stage || '');
                const durationMs = t.duration_ms || 0;
                const durationSec = (durationMs / 1000).toFixed(2);
                const service = getServiceForStage(t.stage || '');
                html += `<tr><td>${stage}</td><td>${durationSec} 秒</td><td>${service}</td></tr>`;
                
                // 在工具執行後插入細分的搜尋時間 (作為子項目)
                if (t.stage === 'tool_execution' && (embeddingsMs > 0 || searchMs > 0)) {
                    html += `<tr class="sub-stage"><td>　└ Embeddings</td><td>${(embeddingsMs / 1000).toFixed(2)} 秒</td><td>🔎 AI Search</td></tr>`;
                    html += `<tr class="sub-stage"><td>　└ 搜尋索引</td><td>${(searchMs / 1000).toFixed(2)} 秒</td><td>🔎 AI Search</td></tr>`;
                }
            });
            html += '</tbody></table>';
        }

        // Search results count
        if (searchDebug.results_count) {
            html += `<div class="stat-item" style="margin-top:10px;">🔍 搜尋結果數量: ${searchDebug.results_count}</div>`;
        }

        return html;
    }

    // Format prompting info to HTML - clean up JSON tags
    function formatPromptingHtml(info) {
        if (!info) return '<p class="empty-state">尚無資料</p>';

        let html = '';
        
        // Model name
        html += `<div class="stat-item"><strong>模型:</strong> ${info.model_name || 'unknown'}</div>`;
        
        // System Prompt - cleaned
        const systemPrompt = cleanPrompt(info.system_prompt || '');
        if (systemPrompt) {
            html += '<div class="collapsible-section">';
            html += '<div class="section-header" onclick="this.parentElement.classList.toggle(\'expanded\')">🤖 System Prompt <span class="expand-icon">▶</span></div>';
            html += `<div class="section-body"><pre>${escapeHtml(systemPrompt)}</pre></div>`;
            html += '</div>';
        }

        // Search Info
        const searchDebug = info.search_debug || {};
        if (searchDebug.query) {
            html += '<div class="collapsible-section">';
            html += '<div class="section-header" onclick="this.parentElement.classList.toggle(\'expanded\')">🔎 Search Query <span class="expand-icon">▶</span></div>';
            html += '<div class="section-body">';
            html += `<div class="stat-item"><strong>查詢:</strong> ${escapeHtml(searchDebug.query)}</div>`;
            html += `<div class="stat-item"><strong>索引:</strong> ${escapeHtml(searchDebug.index_name || '')}</div>`;
            html += `<div class="stat-item"><strong>方法:</strong> ${escapeHtml(searchDebug.search_approach || '')}</div>`;
            html += '</div>';
            html += '</div>';
        }

        // Search Results Preview
        const resultsPreview = searchDebug.results_preview || [];
        if (resultsPreview.length > 0) {
            // Show score threshold info if enabled
            const scoreThreshold = searchDebug.score_threshold || 0;
            const filteredCount = searchDebug.filtered_count || 0;
            let headerExtra = '';
            if (scoreThreshold > 0) {
                headerExtra = ` | Threshold: ${scoreThreshold}`;
                if (filteredCount > 0) {
                    headerExtra += ` | Filtered: ${filteredCount}`;
                }
            }
            
            html += '<div class="collapsible-section">';
            html += '<div class="section-header" onclick="this.parentElement.classList.toggle(\'expanded\')">📄 Search Results (' + resultsPreview.length + ')' + escapeHtml(headerExtra) + ' <span class="expand-icon">▶</span></div>';
            html += '<div class="section-body">';
            resultsPreview.forEach((r, i) => {
                const score = r.score !== undefined ? r.score.toFixed(3) : 'N/A';
                html += `<div class="result-item">`;
                html += `<div class="result-header"><strong>${i+1}. ${escapeHtml(r.title || 'No Title')}</strong> <span class="result-score">Score: ${score}</span></div>`;
                if (r.link) {
                    html += `<div class="result-link">📎 ${escapeHtml(r.link)}</div>`;
                }
                if (r.content_preview) {
                    html += `<div class="result-content"><pre>${escapeHtml(r.content_preview)}</pre></div>`;
                }
                html += '</div>';
            });
            html += '</div>';
            html += '</div>';
        }

        // Tool Output - the full JSON sent to LLM
        const toolOutput = searchDebug.tool_output || '';
        if (toolOutput) {
            html += '<div class="collapsible-section">';
            html += '<div class="section-header" onclick="this.parentElement.classList.toggle(\'expanded\')">🔧 Tool Output (完整 JSON 給 LLM) <span class="expand-icon">▶</span></div>';
            html += '<div class="section-body">';
            try {
                // Pretty print JSON
                const parsed = JSON.parse(toolOutput);
                html += `<pre class="tool-output-json">${escapeHtml(JSON.stringify(parsed, null, 2))}</pre>`;
            } catch(e) {
                html += `<pre class="tool-output-json">${escapeHtml(toolOutput)}</pre>`;
            }
            html += '</div>';
            html += '</div>';
        }

        // LLM Stages - show input/output at each stage
        const llmStages = info.llm_stages || [];
        if (llmStages.length > 0) {
            html += '<div class="collapsible-section expanded">';
            html += '<div class="section-header" onclick="this.parentElement.classList.toggle(\'expanded\')">🧠 LLM 處理階段 (' + llmStages.length + ') <span class="expand-icon">▶</span></div>';
            html += '<div class="section-body">';
            llmStages.forEach((stage, i) => {
                const stageName = stage.stage === 'tool_execution' ? '🔧 工具執行' : 
                                  stage.stage === 'response_generation' ? '✍️ 回應生成' : 
                                  stage.stage;
                html += `<div class="llm-stage-item">`;
                html += `<div class="stage-header"><strong>${i+1}. ${stageName}</strong>`;
                if (stage.duration_ms) {
                    html += ` <span class="stage-duration">(${(stage.duration_ms/1000).toFixed(2)}s)</span>`;
                }
                html += `</div>`;
                
                // Tool calls details
                if (stage.tool_calls && stage.tool_calls.length > 0) {
                    stage.tool_calls.forEach((tc, j) => {
                        html += `<div class="tool-call-item">`;
                        html += `<div class="tool-call-name">Tool: ${escapeHtml(tc.function_name || tc.type || 'unknown')}</div>`;
                        if (tc.arguments) {
                            html += `<div class="tool-call-section"><strong>Arguments:</strong><pre>${escapeHtml(tc.arguments)}</pre></div>`;
                        }
                        if (tc.output) {
                            html += `<div class="tool-call-section"><strong>Output:</strong><pre>${escapeHtml(tc.output)}</pre></div>`;
                        }
                        html += `</div>`;
                    });
                }
                
                // Response output
                if (stage.output) {
                    html += `<div class="stage-output"><strong>輸出:</strong><pre>${escapeHtml(stage.output)}</pre></div>`;
                }
                if (stage.total_chars) {
                    html += `<div class="stage-stats">總字元數: ${stage.total_chars}</div>`;
                }
                html += `</div>`;
            });
            html += '</div>';
            html += '</div>';
        }

        return html;
    }

    // Clean up prompt by removing unnecessary JSON-like tags
    function cleanPrompt(prompt) {
        if (!prompt) return '';
        
        // Remove common JSON artifacts
        let cleaned = prompt;
        
        // Remove XML-like tags that might be artifacts
        cleaned = cleaned.replace(/<\/?json>/gi, '');
        cleaned = cleaned.replace(/<\/?data>/gi, '');
        
        // Remove JSON structure markers if the content is wrapped
        if (cleaned.startsWith('{') && cleaned.endsWith('}')) {
            try {
                const parsed = JSON.parse(cleaned);
                if (parsed.content) {
                    cleaned = parsed.content;
                } else if (parsed.text) {
                    cleaned = parsed.text;
                } else if (parsed.prompt) {
                    cleaned = parsed.prompt;
                }
            } catch (e) {
                // Not valid JSON, keep as is
            }
        }
        
        // Truncate if too long
        if (cleaned.length > 3000) {
            cleaned = cleaned.substring(0, 3000) + '\n\n... (truncated)';
        }
        
        return cleaned.trim();
    }

    // Escape HTML to prevent XSS
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Update panel content
    function updateTimingPanel(info) {
        const content = document.getElementById('timing-content');
        if (content) {
            content.innerHTML = formatTimingHtml(info);
            lastTimingInfo = info;
        }
    }

    function updatePromptingPanel(info) {
        const content = document.getElementById('prompting-content');
        if (content) {
            content.innerHTML = formatPromptingHtml(info);
            lastPromptingInfo = info;
        }
    }

    // Expose to global scope for backend to call
    window.updateDebugPanels = function(debugInfo) {
        if (!debugInfo) return;
        
        console.log('[DebugPanels] Updating with new debug info');
        
        // Split info for each panel
        const timingInfo = {
            total_duration_ms: debugInfo.total_duration_ms,
            timings: debugInfo.timings,
            search_debug: {
                embeddings_time_ms: debugInfo.search_debug?.embeddings_time_ms,
                search_time_ms: debugInfo.search_debug?.search_time_ms,
                total_time_ms: debugInfo.search_debug?.total_time_ms,
                results_count: debugInfo.search_debug?.results_count
            },
            // Agent and tool monitoring info
            agent_id: debugInfo.agent_id,
            agent_reused: debugInfo.agent_reused,
            agent_source: debugInfo.agent_source,
            tools_configured: debugInfo.tools_configured,
            tools_updated: debugInfo.tools_updated
        };

        const promptingInfo = {
            model_name: debugInfo.model_name,
            system_prompt: debugInfo.system_prompt,
            user_message: debugInfo.user_message,
            search_debug: debugInfo.search_debug,
            llm_stages: debugInfo.llm_stages,
            final_response: debugInfo.final_response
        };

        updateTimingPanel(timingInfo);
        updatePromptingPanel(promptingInfo);
    };

    // Clear panels
    window.clearDebugPanels = function() {
        const timingContent = document.getElementById('timing-content');
        const promptingContent = document.getElementById('prompting-content');
        if (timingContent) timingContent.innerHTML = '<p class="empty-state">尚無資料</p>';
        if (promptingContent) promptingContent.innerHTML = '<p class="empty-state">尚無資料</p>';
    };

    // Watch for debug messages in the chat
    function observeMessages() {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // Look for debug messages
                        const debugMarker = node.querySelector('[data-debug-info]');
                        if (debugMarker) {
                            try {
                                console.log('[DebugPanels] Found data-debug-info marker');
                                const debugInfo = JSON.parse(debugMarker.dataset.debugInfo);
                                window.updateDebugPanels(debugInfo);
                                // Hide the debug message from chat
                                const messageContainer = debugMarker.closest('.message');
                                if (messageContainer) {
                                    messageContainer.style.display = 'none';
                                }
                            } catch (e) {
                                console.error('[DebugPanels] Error parsing debug info:', e);
                            }
                        }

                        // Also look for hidden debug data
                        const hiddenDebug = node.querySelector('.debug-data-hidden');
                        if (hiddenDebug) {
                            try {
                                console.log('[DebugPanels] Found hidden debug div via observer');
                                
                                // Check for base64 encoded data first
                                let debugInfo;
                                if (hiddenDebug.dataset.debugB64) {
                                    const jsonStr = decodeBase64UTF8(hiddenDebug.dataset.debugB64);
                                    if (jsonStr) {
                                        debugInfo = JSON.parse(jsonStr);
                                    }
                                } else {
                                    debugInfo = JSON.parse(hiddenDebug.textContent);
                                }
                                
                                window.updateDebugPanels(debugInfo);
                                // Hide the entire message containing debug data
                                let parent = hiddenDebug.parentElement;
                                while (parent && !parent.classList.contains('step')) {
                                    parent = parent.parentElement;
                                }
                                if (parent) {
                                    parent.style.display = 'none';
                                } else {
                                    hiddenDebug.style.display = 'none';
                                }
                            } catch (e) {
                                console.error('[DebugPanels] Error parsing hidden debug:', e);
                            }
                        }
                    }
                });
            });
        });

        // Start observing the entire document since Chainlit structure can vary
        observer.observe(document.body, { childList: true, subtree: true });
        console.log('[DebugPanels] Message observer started on document.body');
    }

    // Watch for model selection changes via Chainlit settings dropdown
    function watchModelSelection() {
        // Periodically check for model changes in various UI elements
        setInterval(() => {
            // Method 1: Look for selected option in Chainlit's MUI Select
            const selectedItems = document.querySelectorAll('[role="option"][aria-selected="true"], .MuiMenuItem-root.Mui-selected, .MuiListItem-root.Mui-selected');
            selectedItems.forEach(item => {
                const text = item.textContent || '';
                if (text && text.includes('GPT') && text !== currentModel) {
                    updateModelIndicator(text.trim());
                }
            });
            
            // Method 2: Check the displayed value in select inputs
            const selectDisplays = document.querySelectorAll('.MuiSelect-select, [role="combobox"], .MuiInputBase-input');
            selectDisplays.forEach(display => {
                const text = display.textContent || display.value || '';
                if (text && text.includes('GPT') && text !== currentModel) {
                    updateModelIndicator(text.trim());
                }
            });
            
            // Method 3: Look for model confirmation message in chat
            const messages = document.querySelectorAll('.step .markdown-body, .message-content');
            messages.forEach(msg => {
                const text = msg.textContent || '';
                const match = text.match(/已切換至 \*\*(.+?)\*\* 模型|切換至 (.+?) 模型/);
                if (match) {
                    const modelName = match[1] || match[2];
                    if (modelName && modelName !== currentModel) {
                        updateModelIndicator(modelName.trim());
                    }
                }
            });
        }, 500);
    }

    // Periodic scan for debug data that might be missed by observer
    function startPeriodicScan() {
        setInterval(() => {
            // Skip debug data processing in demo mode
            if (uiMode === 'demo') {
                return;
            }
            
            const hiddenDebugElements = document.querySelectorAll('.debug-data-hidden');
            hiddenDebugElements.forEach((elem) => {
                if (!elem.dataset.processed) {
                    try {
                        console.log('[DebugPanels] Found hidden debug via periodic scan');
                        
                        // Check for base64 encoded data first
                        let debugInfo;
                        if (elem.dataset.debugB64) {
                            // Decode base64 with UTF-8 support
                            const jsonStr = decodeBase64UTF8(elem.dataset.debugB64);
                            if (jsonStr) {
                                debugInfo = JSON.parse(jsonStr);
                                console.log('[DebugPanels] Decoded base64 debug data (UTF-8)');
                            }
                        } else {
                            // Fallback to text content
                            debugInfo = JSON.parse(elem.textContent);
                        }
                        
                        window.updateDebugPanels(debugInfo);
                        elem.dataset.processed = 'true';
                        // Hide the containing message
                        let parent = elem.parentElement;
                        while (parent && !parent.classList.contains('step')) {
                            parent = parent.parentElement;
                        }
                        if (parent) {
                            parent.style.display = 'none';
                        }
                    } catch (e) {
                        console.error('[DebugPanels] Error in periodic scan:', e);
                        elem.dataset.processed = 'error';
                    }
                }
            });
        }, 500); // Scan every 500ms
        console.log('[DebugPanels] Periodic scan started');
    }

    // Initialize when DOM is ready
    function init() {
        console.log('[DebugPanels] Initializing, UI mode:', uiMode);
        
        // Always create model indicator (shows in both dev and demo mode)
        createModelIndicator();
        
        // Only create debug panels in dev mode
        if (uiMode === 'dev') {
            createDebugPanels();
            observeMessages();
            startPeriodicScan();
        } else {
            // In demo mode, still need to hide debug messages
            startDebugMessageHider();
        }
        
        // Watch for model selection changes
        watchModelSelection();
        
        console.log('[DebugPanels] Initialized successfully');
    }
    
    // Simple function to hide debug messages in demo mode
    function startDebugMessageHider() {
        setInterval(() => {
            const hiddenDebugElements = document.querySelectorAll('.debug-data-hidden:not([data-processed])');
            hiddenDebugElements.forEach((elem) => {
                elem.dataset.processed = 'true';
                // Hide the containing message
                let parent = elem.parentElement;
                while (parent && !parent.classList.contains('step')) {
                    parent = parent.parentElement;
                }
                if (parent) {
                    parent.style.display = 'none';
                }
            });
        }, 200);
    }

    // Wait for DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // DOM already loaded, wait a bit for Chainlit to initialize
        setTimeout(init, 1000);
    }
})();
