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
    }
    
    // Allow disabling debug mode
    window.disableDebugMode = function() {
        localStorage.removeItem('gptrag_debug');
        location.reload();
    };

    // Create debug panel UI
    function createDebugPanels() {
        // Check if panels already exist
        if (document.getElementById('debug-panels-container')) return;

        const container = document.createElement('div');
        container.id = 'debug-panels-container';
        container.innerHTML = `
            <style>
                #debug-panels-container {
                    position: fixed;
                    top: 60px;
                    right: 10px;
                    z-index: 10000;
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    font-size: 12px;
                }
                
                .debug-panel {
                    background: rgba(30, 30, 30, 0.95);
                    color: #e0e0e0;
                    border-radius: 8px;
                    margin-bottom: 10px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    overflow: hidden;
                    min-width: 300px;
                    max-width: 450px;
                }
                
                .debug-panel.right-panel {
                    max-width: 450px;
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
                    max-height: 400px;
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
                
                .debug-badge {
                    position: fixed;
                    bottom: 20px;
                    right: 20px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 8px 16px;
                    border-radius: 20px;
                    font-size: 12px;
                    font-weight: 600;
                    cursor: pointer;
                    z-index: 10001;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
                }
                
                .debug-badge:hover {
                    transform: scale(1.05);
                }
            </style>
            
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
            
            <div class="debug-panel right-panel" id="prompting-panel">
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
            
            <div class="debug-badge" onclick="window.toggleAllDebugPanels()">
                🐛 Debug Mode
            </div>
        `;
        
        document.body.appendChild(container);
    }

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
        
        const stages = [
            { key: 'request_start', icon: '🚀', label: 'Request Started' },
            { key: 'thread_creation', icon: '🧵', label: 'Thread Creation' },
            { key: 'llm_thinking_1', icon: '🤔', label: 'LLM Thinking #1' },
            { key: 'tool_execution', icon: '🔧', label: 'Tool Execution' },
            { key: 'search_query', icon: '🔍', label: 'AI Search' },
            { key: 'llm_thinking_2', icon: '💭', label: 'LLM Thinking #2' },
            { key: 'response_streaming', icon: '📤', label: 'Response Streaming' },
            { key: 'total', icon: '⏱️', label: 'Total Time', isTotal: true }
        ];

        let html = '';
        stages.forEach(stage => {
            const value = timingData[stage.key];
            const displayValue = value !== undefined ? `${value.toFixed(2)}s` : '-';
            const valueClass = value !== undefined ? 'timing-value' : 'timing-value pending';
            
            if (stage.isTotal) {
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
                    <div class="prompting-title">User Message</div>
                    <div class="prompting-content">${escapeHtml(promptingData.user_message)}</div>
                </div>
            `;
        }
        
        if (promptingData.system_prompt) {
            html += `
                <div class="prompting-section">
                    <div class="prompting-title">System Prompt</div>
                    <div class="prompting-content">${escapeHtml(truncateText(promptingData.system_prompt, 500))}</div>
                </div>
            `;
        }
        
        if (promptingData.tool_calls && promptingData.tool_calls.length > 0) {
            html += `
                <div class="prompting-section">
                    <div class="prompting-title">Tool Calls</div>
                    <div class="prompting-content">${escapeHtml(JSON.stringify(promptingData.tool_calls, null, 2))}</div>
                </div>
            `;
        }
        
        if (promptingData.search_results) {
            html += `
                <div class="prompting-section">
                    <div class="prompting-title">Search Results (${promptingData.search_results.count || 0} docs)</div>
                    <div class="prompting-content">${escapeHtml(truncateText(promptingData.search_results.preview || 'N/A', 300))}</div>
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
                            window.updateTimingPanel({
                                llm_thinking_1: data.timing.ttfb,
                                response_streaming: data.timing.streaming,
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
