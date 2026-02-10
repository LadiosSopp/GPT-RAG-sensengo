/**
 * Debug Panels for GPT-RAG UI
 * Displays timing information and prompting details in collapsible panels
 * 
 * Usage: Navigate to /dev to enable debug mode
 */

(function() {
    'use strict';

    // Debug state
    let debugEnabled = false;
    let timingData = {};
    let promptingData = {};

    // Initialize debug mode based on URL
    function initDebugMode() {
        const urlParams = new URLSearchParams(window.location.search);
        
        // Check URL for debug flag
        const urlDebug = window.location.pathname.includes('/dev') || 
                         urlParams.get('debug') === 'true' ||
                         window.location.search.includes('debug=true');
        
        // If URL has debug flag, store it in localStorage
        if (urlDebug) {
            localStorage.setItem('gptrag_debug', 'true');
        }
        
        // Check localStorage for persisted debug state
        const storedDebug = localStorage.getItem('gptrag_debug') === 'true';
        
        debugEnabled = urlDebug || storedDebug;
        
        console.log('[Debug] Checking debug mode:', {
            pathname: window.location.pathname,
            search: window.location.search,
            urlDebug: urlDebug,
            storedDebug: storedDebug,
            debugEnabled: debugEnabled
        });
        
        if (debugEnabled) {
            console.log('[Debug] Debug mode enabled - creating panels');
            createDebugPanels();
            hookIntoStreaming();
        }
        
        // Also watch for /debug command in chat messages
        watchForDebugCommand();
    }
    
    // Watch for /debug command in chat and auto-enable debug mode
    function watchForDebugCommand() {
        // Use MutationObserver to watch for new messages
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        const text = node.textContent || '';
                        // Check if message contains debug mode enabled indicator
                        if (text.includes('Debug Mode 已啟用') || text.includes('Debug Mode Enabled')) {
                            console.log('[Debug] Detected /debug command - enabling debug panels');
                            localStorage.setItem('gptrag_debug', 'true');
                            if (!debugEnabled) {
                                debugEnabled = true;
                                createDebugPanels();
                                hookIntoStreaming();
                            }
                        } else if (text.includes('Debug Mode 已關閉') || text.includes('Debug Mode Disabled')) {
                            console.log('[Debug] Detected /debug off command - disabling debug panels');
                            localStorage.removeItem('gptrag_debug');
                            debugEnabled = false;
                            const container = document.getElementById('debug-panels-container');
                            if (container) container.remove();
                            adjustMainContent(false);
                        }
                    }
                });
            });
        });
        
        // Start observing when body is available
        if (document.body) {
            observer.observe(document.body, { childList: true, subtree: true });
        } else {
            document.addEventListener('DOMContentLoaded', () => {
                observer.observe(document.body, { childList: true, subtree: true });
            });
        }
    }
    
    // Allow disabling debug mode
    window.disableDebugMode = function() {
        localStorage.removeItem('gptrag_debug');
        location.reload();
    };

    // Adjust main content area for debug sidebar
    function adjustMainContent(enable) {
        // Find Chainlit's main content area
        const root = document.getElementById('root');
        if (!root) return;
        
        if (enable) {
            // Shrink main content to make room for debug sidebar
            root.style.width = '55%';
            root.style.marginRight = '45%';
            root.style.transition = 'all 0.3s ease';
        } else {
            // Restore full width
            root.style.width = '';
            root.style.marginRight = '';
        }
    }

    // Create debug panel UI
    function createDebugPanels() {
        // Check if panels already exist
        if (document.getElementById('debug-panels-container')) return;

        // Adjust main content area
        adjustMainContent(true);

        const container = document.createElement('div');
        container.id = 'debug-panels-container';
        container.innerHTML = `
            <style>
                #debug-panels-container {
                    position: fixed;
                    top: 0;
                    right: 0;
                    width: 45%;
                    height: 100vh;
                    z-index: 10000;
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    font-size: 12px;
                    background: #1a1a2e;
                    border-left: 1px solid #333;
                    overflow-y: auto;
                    padding: 10px;
                    box-sizing: border-box;
                }
                
                .debug-sidebar-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 10px 5px;
                    margin-bottom: 10px;
                    border-bottom: 1px solid #333;
                }
                
                .debug-sidebar-title {
                    font-size: 14px;
                    font-weight: 600;
                    color: #fff;
                }
                
                .debug-close-btn {
                    background: rgba(255,255,255,0.1);
                    border: none;
                    color: #aaa;
                    padding: 5px 10px;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 12px;
                }
                
                .debug-close-btn:hover {
                    background: rgba(255,255,255,0.2);
                    color: #fff;
                }
                
                .debug-panel {
                    background: rgba(30, 30, 30, 0.95);
                    color: #e0e0e0;
                    border-radius: 8px;
                    margin-bottom: 10px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    overflow: hidden;
                }
                
                .debug-panel-header {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 10px 15px;
                    cursor: pointer;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    user-select: none;
                }
                
                .debug-panel-header:hover {
                    filter: brightness(1.1);
                }
                
                .debug-panel-title {
                    font-weight: 600;
                    font-size: 13px;
                }
                
                .debug-panel-toggle {
                    font-size: 16px;
                    transition: transform 0.2s;
                }
                
                .debug-panel.collapsed .debug-panel-toggle {
                    transform: rotate(-90deg);
                }
                
                .debug-panel-content {
                    padding: 12px 15px;
                    max-height: 50vh;
                    overflow-y: auto;
                }
                
                .debug-panel.collapsed .debug-panel-content {
                    display: none;
                }
                
                .timing-row {
                    display: flex;
                    justify-content: space-between;
                    padding: 6px 0;
                    border-bottom: 1px solid rgba(255,255,255,0.1);
                }
                
                .timing-row:last-child {
                    border-bottom: none;
                }
                
                .timing-label {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                
                .timing-icon {
                    font-size: 14px;
                }
                
                .timing-value {
                    font-family: 'Consolas', monospace;
                    color: #4ade80;
                }
                
                .timing-value.pending {
                    color: #fbbf24;
                }
                
                .timing-total {
                    font-weight: bold;
                    color: #60a5fa;
                    font-size: 14px;
                    margin-top: 8px;
                    padding-top: 8px;
                    border-top: 2px solid rgba(255,255,255,0.2);
                }
                
                .prompting-section {
                    margin-bottom: 12px;
                }
                
                .prompting-title {
                    font-weight: 600;
                    color: #818cf8;
                    margin-bottom: 6px;
                    font-size: 11px;
                    text-transform: uppercase;
                }
                
                .prompting-content {
                    background: rgba(0,0,0,0.3);
                    padding: 8px;
                    border-radius: 4px;
                    font-family: 'Consolas', monospace;
                    font-size: 11px;
                    white-space: pre-wrap;
                    word-break: break-word;
                    max-height: 150px;
                    overflow-y: auto;
                }
            </style>
            
            <div class="debug-sidebar-header">
                <span class="debug-sidebar-title">🐛 Debug Panel</span>
                <button class="debug-close-btn" onclick="window.closeDebugPanels()">關閉 ✕</button>
            </div>
            
            <div class="debug-panel" id="timing-panel">
                <div class="debug-panel-header" onclick="window.toggleDebugPanel('timing-panel')">
                    <span class="debug-panel-title">⏱️ Timing</span>
                    <span class="debug-panel-toggle">▼</span>
                </div>
                <div class="debug-panel-content" id="timing-content">
                    <div class="timing-row">
                        <span class="timing-label"><span class="timing-icon">🚀</span> Waiting...</span>
                        <span class="timing-value pending">-</span>
                    </div>
                </div>
            </div>
            
            <div class="debug-panel" id="prompting-panel">
                <div class="debug-panel-header" onclick="window.toggleDebugPanel('prompting-panel')">
                    <span class="debug-panel-title">📝 Prompting Details</span>
                    <span class="debug-panel-toggle">▼</span>
                </div>
                <div class="debug-panel-content" id="prompting-content">
                    <div class="prompting-section">
                        <div class="prompting-title">Waiting for response...</div>
                        <div class="prompting-content">No data yet</div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(container);
    }
    
    // Close debug panels and restore layout
    window.closeDebugPanels = function() {
        localStorage.removeItem('gptrag_debug');
        debugEnabled = false;
        const container = document.getElementById('debug-panels-container');
        if (container) container.remove();
        adjustMainContent(false);
    };

    // Toggle panel collapse state
    window.toggleDebugPanel = function(panelId) {
        const panel = document.getElementById(panelId);
        if (panel) {
            panel.classList.toggle('collapsed');
        }
    };

    // Toggle all panels
    window.toggleAllDebugPanels = function() {
        const panels = document.querySelectorAll('.debug-panel');
        const allCollapsed = Array.from(panels).every(p => p.classList.contains('collapsed'));
        panels.forEach(p => {
            if (allCollapsed) {
                p.classList.remove('collapsed');
            } else {
                p.classList.add('collapsed');
            }
        });
    };

    // Update timing panel
    window.updateTimingPanel = function(data) {
        if (!debugEnabled) return;
        
        const content = document.getElementById('timing-content');
        if (!content) return;

        timingData = { ...timingData, ...data };
        
        // All possible timing stages from orchestrator
        // Note: agent_response is the overall time for _stream_agent_response which includes
        // llm_thinking_1 + tool_execution + llm_thinking_2, so we don't show it separately
        // to avoid double counting
        const stages = [
            { key: 'request_start', icon: '🚀', label: 'Request Started' },
            { key: 'thread_creation', icon: '🧵', label: 'Thread Management' },
            { key: 'agent_management', icon: '🤖', label: 'Agent Management' },
            { key: 'send_message', icon: '📨', label: 'Send Message' },
            { key: 'llm_thinking_1', icon: '🤔', label: 'LLM Thinking #1' },
            { key: 'tool_execution', icon: '🔧', label: 'Tool Execution' },
            { key: 'search_query', icon: '🔍', label: 'AI Search' },
            { key: 'llm_thinking_2', icon: '💭', label: 'LLM Thinking #2' },
            // { key: 'response_streaming', icon: '📡', label: 'Response Streaming' },  // Removed: included in llm_thinking_1/2 + tool_execution
            { key: 'consolidate_history', icon: '📚', label: 'Consolidate History' },
            { key: 'cleanup_agent', icon: '🧹', label: 'Cleanup Agent' },
            { key: 'total_flow', icon: '⏱️', label: 'Orchestrator Total', isTotal: true },
            { key: 'total', icon: '🏁', label: 'End-to-End Total', isTotal: true, isGrandTotal: true }
        ];

        let html = '';
        let summedTime = 0;
        
        stages.forEach(stage => {
            // Use fallback key if primary key is not available
            let value = timingData[stage.key];
            if ((value === undefined || value === null) && stage.fallbackKey) {
                value = timingData[stage.fallbackKey];
            }
            // Skip stages with no data (don't show '-')
            if (value === undefined || value === null) return;
            
            const displayValue = `${value.toFixed(2)}s`;
            const valueClass = 'timing-value';
            
            // Sum up component times (exclude totals)
            if (!stage.isTotal && value) {
                summedTime += value;
            }
            
            if (stage.isGrandTotal) {
                html += `
                    <div class="timing-row timing-total" style="background: rgba(96, 165, 250, 0.2); margin-top: 8px; padding: 8px; border-radius: 4px;">
                        <span class="timing-label"><span class="timing-icon">${stage.icon}</span> ${stage.label}</span>
                        <span class="${valueClass}" style="font-size: 16px;">${displayValue}</span>
                    </div>
                `;
            } else if (stage.isTotal) {
                html += `
                    <div class="timing-row timing-total">
                        <span class="timing-label"><span class="timing-icon">${stage.icon}</span> ${stage.label}</span>
                        <span class="${valueClass}">${displayValue}</span>
                    </div>
                `;
            } else {
                html += `
                    <div class="timing-row">
                        <span class="timing-label"><span class="timing-icon">${stage.icon}</span> ${stage.label}</span>
                        <span class="${valueClass}">${displayValue}</span>
                    </div>
                `;
            }
        });
        
        // Show summed components time vs total (to see overhead)
        if (summedTime > 0 && timingData.total) {
            const overhead = timingData.total - summedTime;
            html += `
                <div class="timing-row" style="font-size: 10px; color: #888; margin-top: 8px;">
                    <span>Components sum: ${summedTime.toFixed(2)}s | Overhead: ${overhead.toFixed(2)}s</span>
                </div>
            `;
        }

        content.innerHTML = html;
    };

    // Update prompting panel
    window.updatePromptingPanel = function(data) {
        if (!debugEnabled) return;
        
        const content = document.getElementById('prompting-content');
        if (!content) return;

        promptingData = { ...promptingData, ...data };

        let html = '';
        
        if (promptingData.user_message) {
            html += `
                <div class="prompting-section">
                    <div class="prompting-title">📝 User Message</div>
                    <div class="prompting-content">${escapeHtml(promptingData.user_message)}</div>
                </div>
            `;
        }
        
        if (promptingData.system_prompt) {
            html += `
                <div class="prompting-section">
                    <div class="prompting-title">⚙️ System Prompt</div>
                    <div class="prompting-content" style="max-height: 300px; overflow-y: auto;">
                        <pre style="white-space: pre-wrap; word-wrap: break-word; font-size: 11px;">${escapeHtml(promptingData.system_prompt)}</pre>
                    </div>
                </div>
            `;
        }
        
        if (promptingData.tool_calls && promptingData.tool_calls.length > 0) {
            html += `
                <div class="prompting-section">
                    <div class="prompting-title">🔧 Tool Calls (${promptingData.tool_calls.length})</div>
                    <div class="prompting-content">
                        <pre style="white-space: pre-wrap; word-wrap: break-word; font-size: 11px;">${escapeHtml(JSON.stringify(promptingData.tool_calls, null, 2))}</pre>
                    </div>
                </div>
            `;
        }
        
        // Full Search Results
        if (promptingData.search_results && promptingData.search_results.results) {
            const results = promptingData.search_results.results;
            const count = promptingData.search_results.count || results.length;
            const queries = promptingData.search_results.queries || [];
            
            html += `
                <div class="prompting-section">
                    <div class="prompting-title">🔍 Search Results (${count} documents)</div>
                    ${queries.length > 0 ? `<div style="font-size: 11px; color: #888; margin-bottom: 8px;">Query: ${escapeHtml(queries.join(', '))}</div>` : ''}
                    <div class="prompting-content" style="max-height: 500px; overflow-y: auto;">
            `;
            
            results.forEach((doc, idx) => {
                const score = doc.score ? ` (Score: ${doc.score.toFixed(4)})` : '';
                html += `
                    <div style="border: 1px solid #444; border-radius: 4px; padding: 8px; margin-bottom: 8px; background: #1a1a2e;">
                        <div style="font-weight: bold; color: #00d4ff; margin-bottom: 4px;">
                            ${idx + 1}. ${escapeHtml(doc.title || 'Untitled')}${score}
                        </div>
                        ${doc.link ? `<div style="font-size: 10px; color: #888; margin-bottom: 4px;"><a href="${escapeHtml(doc.link)}" target="_blank" style="color: #4da6ff;">${escapeHtml(doc.link)}</a></div>` : ''}
                        <div style="font-size: 11px; white-space: pre-wrap; word-wrap: break-word; color: #ccc;">
                            ${escapeHtml(doc.content || 'No content')}
                        </div>
                    </div>
                `;
            });
            
            html += `
                    </div>
                </div>
            `;
        }

        if (promptingData.llm_calls && promptingData.llm_calls.length > 0) {
            html += `
                <div class="prompting-section">
                    <div class="prompting-title">🤖 LLM Calls (${promptingData.llm_calls.length})</div>
                    <div class="prompting-content">
            `;
            promptingData.llm_calls.forEach((call, idx) => {
                html += `
                    <div style="margin-bottom: 8px; padding: 4px; border-left: 2px solid #4da6ff;">
                        <strong>Call ${idx + 1}:</strong> ${escapeHtml(call.model || 'unknown')} | 
                        Input: ${call.input_tokens || 0} tokens | 
                        Output: ${call.output_tokens || 0} tokens | 
                        Duration: ${(call.duration || 0).toFixed(2)}s
                    </div>
                `;
            });
            html += `
                    </div>
                </div>
            `;
        }

        if (promptingData.model) {
            html += `
                <div class="prompting-section">
                    <div class="prompting-title">Model</div>
                    <div class="prompting-content">${escapeHtml(promptingData.model)}</div>
                </div>
            `;
        }

        if (html === '') {
            html = `
                <div class="prompting-section">
                    <div class="prompting-title">Waiting for response...</div>
                    <div class="prompting-content">No data yet</div>
                </div>
            `;
        }

        content.innerHTML = html;
    };

    // Reset debug panels for new query
    window.resetDebugPanels = function() {
        timingData = {};
        promptingData = {};
        window.updateTimingPanel({});
        window.updatePromptingPanel({});
    };

    // Helper: Escape HTML
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Helper: Truncate text
    function truncateText(text, maxLength) {
        if (!text) return '';
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    // Hook into streaming to capture debug data
    function hookIntoStreaming() {
        console.log('[Debug] Setting up API polling for debug data');
        
        let lastTimestamp = 0;
        let pollInterval = null;
        
        // Poll the debug API endpoint
        async function pollDebugData() {
            if (!debugEnabled) return;
            
            try {
                const response = await fetch('/_debug/data');
                if (response.ok) {
                    const data = await response.json();
                    
                    // Only update if we have new data
                    if (data.timestamp && data.timestamp > lastTimestamp) {
                        lastTimestamp = data.timestamp;
                        console.log('[Debug] Received debug data:', data);
                        
                        if (data.timing) {
                            // Pass ALL timing data from backend directly
                            // The backend already has proper keys, just pass them through
                            window.updateTimingPanel({
                                // Map some alternate names for compatibility
                                thread_creation: data.timing.thread_management || data.timing.thread_creation,
                                agent_management: data.timing.agent_management,
                                send_message: data.timing.send_message,
                                llm_thinking_1: data.timing.llm_thinking_1,
                                tool_execution: data.timing.tool_execution,
                                search_query: data.timing.search_query || data.timing.ai_search,
                                llm_thinking_2: data.timing.llm_thinking_2,
                                agent_response: data.timing.agent_response,
                                consolidate_history: data.timing.consolidate_history,
                                cleanup_agent: data.timing.cleanup_agent,
                                response_streaming: data.timing.response_streaming || data.timing.streaming,
                                total_flow: data.timing.total_flow,
                                total: data.timing.total
                            });
                        }
                        
                        if (data.prompting) {
                            window.updatePromptingPanel(data.prompting);
                        }
                    }
                }
            } catch (e) {
                // Silently ignore polling errors
                console.log('[Debug] Polling error (normal if no data yet):', e.message);
            }
        }
        
        // Start polling
        function startPolling() {
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(pollDebugData, 1000);
            console.log('[Debug] Started polling /_debug/data every 1s');
        }
        
        // Track when user sends a message
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                const input = document.querySelector('textarea, input[type="text"]');
                if (input && document.activeElement === input && input.value.trim()) {
                    window.resetDebugPanels();
                    lastTimestamp = 0; // Reset to get new data
                    window.updateTimingPanel({ request_start: 0 });
                    window.updatePromptingPanel({ user_message: input.value.trim() });
                }
            }
        });
        
        // Also watch for button clicks (send button)
        document.addEventListener('click', function(e) {
            const btn = e.target.closest('button');
            if (btn && (btn.type === 'submit' || btn.getAttribute('aria-label')?.includes('send'))) {
                const input = document.querySelector('textarea, input[type="text"]');
                if (input && input.value.trim()) {
                    window.resetDebugPanels();
                    lastTimestamp = 0;
                    window.updateTimingPanel({ request_start: 0 });
                    window.updatePromptingPanel({ user_message: input.value.trim() });
                }
            }
        });
        
        startPolling();
        console.log('[Debug] API polling hooks installed');
    }

    // Auto-initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDebugMode);
    } else {
        initDebugMode();
    }

    // Re-check on navigation (for SPA)
    let lastPath = window.location.pathname;
    setInterval(() => {
        if (window.location.pathname !== lastPath) {
            lastPath = window.location.pathname;
            initDebugMode();
        }
    }, 500);

})();
