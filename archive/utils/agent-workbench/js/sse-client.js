/**
 * SSE Client for Agent Workbench
 * 
 * Provides a robust EventSource wrapper with:
 * - Automatic reconnection with exponential backoff
 * - Event filtering by channel and context
 * - Event routing to UI components
 * - Connection state management
 * 
 * Usage:
 *   const client = new SSEClient();
 *   client.subscribe(['job_trace'], { job_id: '123' }, (event) => {
 *     console.log(event.message);
 *   });
 *   client.connect();
 */

class SSEClient {
    constructor(options = {}) {
        this.baseUrl = options.baseUrl || '/api/sse/events';
        this.reconnectDelay = options.reconnectDelay || 1000;
        this.maxReconnectDelay = options.maxReconnectDelay || 30000;
        this.heartbeatTimeout = options.heartbeatTimeout || 45000; // 45s (server sends every 30s)
        
        this.eventSource = null;
        this.lastEventId = null;
        this.currentReconnectDelay = this.reconnectDelay;
        this.reconnectTimer = null;
        this.heartbeatTimer = null;
        this.isConnecting = false;
        this.isConnected = false;
        this.shouldReconnect = true;
        
        // Subscriptions: { id: { channels, context, callback } }
        this.subscriptions = new Map();
        this.subscriptionIdCounter = 0;
        
        // Connection state callbacks
        this.onConnected = options.onConnected || (() => {});
        this.onDisconnected = options.onDisconnected || (() => {});
        this.onReconnecting = options.onReconnecting || (() => {});
        this.onError = options.onError || ((error) => console.error('SSE Error:', error));
        
        // Bind methods
        this._handleOpen = this._handleOpen.bind(this);
        this._handleError = this._handleError.bind(this);
        this._handleMessage = this._handleMessage.bind(this);
    }
    
    /**
     * Connect to the SSE endpoint
     */
    connect() {
        if (this.eventSource || this.isConnecting) {
            return;
        }
        
        this.shouldReconnect = true;
        this._doConnect();
    }
    
    _doConnect() {
        if (this.eventSource) {
            this.eventSource.close();
        }
        
        this.isConnecting = true;
        
        // Build URL with filters from all subscriptions
        const url = this._buildUrl();
        
        console.log('[SSE] Connecting to:', url);
        
        try {
            this.eventSource = new EventSource(url);
            
            this.eventSource.onopen = this._handleOpen;
            this.eventSource.onerror = this._handleError;
            
            // Listen for all event types we care about
            const channels = ['job_trace', 'build_trace', 'deploy_trace', 'execution', 'interactive', 'system', 'validation', 'blob_log'];
            channels.forEach(channel => {
                this.eventSource.addEventListener(channel, this._handleMessage);
            });

            // Listen for 'update' events (updates to existing events)
            this.eventSource.addEventListener('update', this._handleMessage);

            // Listen for 'ping' events (server heartbeats) to reset the heartbeat monitor
            this.eventSource.addEventListener('ping', (event) => {
                this._resetHeartbeatMonitor();
            });

            // Also listen for generic messages
            this.eventSource.onmessage = this._handleMessage;
            
        } catch (error) {
            console.error('[SSE] Failed to create EventSource:', error);
            this.isConnecting = false;
            this._scheduleReconnect();
        }
    }
    
    _buildUrl() {
        const params = new URLSearchParams();
        
        // Collect unique channels from all subscriptions
        const allChannels = new Set();
        this.subscriptions.forEach(sub => {
            if (sub.channels) {
                sub.channels.forEach(ch => allChannels.add(ch));
            }
        });
        
        if (allChannels.size > 0) {
            params.set('channels', Array.from(allChannels).join(','));
        }
        
        if (this.lastEventId) {
            params.set('last_event_id', this.lastEventId);
        }
        
        const queryString = params.toString();
        return queryString ? `${this.baseUrl}?${queryString}` : this.baseUrl;
    }
    
    _handleOpen(event) {
        this.isConnecting = false;
        this.isConnected = true;
        this.currentReconnectDelay = this.reconnectDelay;
        
        this._startHeartbeatMonitor();
        this.onConnected();
    }
    
    _handleError(event) {
        // Log diagnostic info to help debug rapid reconnection issues
        const readyState = this.eventSource ? this.eventSource.readyState : 'no-eventsource';
        const reason = event?.type || 'unknown';
        console.log(`[SSE] Connection error or closed (reason=${reason}, readyState=${readyState}, wasConnected=${this.isConnected})`);
        this.isConnecting = false;
        this.isConnected = false;
        this._stopHeartbeatMonitor();
        
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        
        if (this.shouldReconnect) {
            this._scheduleReconnect();
        }
        
        this.onDisconnected();
    }
    
    _handleMessage(event) {
        this._resetHeartbeatMonitor();
        
        // Parse event data
        let eventData;
        try {
            eventData = JSON.parse(event.data);
        } catch (e) {
            console.warn('[SSE] Failed to parse event data:', event.data);
            return;
        }
        
        // Track last event ID for reconnection
        if (eventData.id) {
            this.lastEventId = eventData.id;
        }
        
        // Route to matching subscriptions
        this.subscriptions.forEach((sub, id) => {
            if (this._matchesSubscription(eventData, sub)) {
                try {
                    sub.callback(eventData);
                } catch (e) {
                    console.error('[SSE] Subscription callback error:', e);
                }
            }
        });
    }
    
    _matchesSubscription(event, subscription) {
        // Check channel filter
        if (subscription.channels && subscription.channels.length > 0) {
            if (!subscription.channels.includes(event.channel)) {
                return false;
            }
        }
        
        // Check context filter
        if (subscription.context) {
            for (const [key, value] of Object.entries(subscription.context)) {
                if (event.context && event.context[key] !== value) {
                    return false;
                }
            }
        }
        
        return true;
    }
    
    _scheduleReconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
        }
        
        this.onReconnecting(this.currentReconnectDelay);
        
        this.reconnectTimer = setTimeout(() => {
            this._doConnect();
        }, this.currentReconnectDelay);
        
        // Exponential backoff
        this.currentReconnectDelay = Math.min(
            this.currentReconnectDelay * 2,
            this.maxReconnectDelay
        );
    }
    
    _startHeartbeatMonitor() {
        this._stopHeartbeatMonitor();
        this.heartbeatTimer = setTimeout(() => {
            console.log('[SSE] Heartbeat timeout, reconnecting...');
            this._handleError({ type: 'heartbeat_timeout' });
        }, this.heartbeatTimeout);
    }
    
    _stopHeartbeatMonitor() {
        if (this.heartbeatTimer) {
            clearTimeout(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
    }
    
    _resetHeartbeatMonitor() {
        this._startHeartbeatMonitor();
    }
    
    /**
     * Subscribe to events
     * @param {string[]} channels - Channels to listen to (null = all)
     * @param {object} context - Context filter (e.g., { job_id: '123' })
     * @param {function} callback - Function to call with each event
     * @returns {number} Subscription ID (use to unsubscribe)
     */
    subscribe(channels, context, callback) {
        const id = ++this.subscriptionIdCounter;
        this.subscriptions.set(id, { channels, context, callback });
        
        // If connected, may need to reconnect with new channel filters
        // For simplicity, we filter client-side rather than reconnecting
        
        return id;
    }
    
    /**
     * Unsubscribe from events
     * @param {number} subscriptionId - ID returned from subscribe()
     */
    unsubscribe(subscriptionId) {
        this.subscriptions.delete(subscriptionId);
    }
    
    /**
     * Disconnect from SSE
     */
    disconnect() {
        console.log('[SSE] Disconnecting...');
        this.shouldReconnect = false;
        
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        
        this._stopHeartbeatMonitor();
        
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        
        this.isConnected = false;
        this.isConnecting = false;
    }
    
    /**
     * Check if connected
     */
    get connected() {
        return this.isConnected;
    }
}


/**
 * Activity Panel Manager
 * 
 * Manages the Activity panel UI showing real-time server traces.
 */
class ActivityPanel {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = null;
        this.maxEntries = options.maxEntries || 500;
        this.autoScroll = true;
        this.entries = [];
        this.filterChannel = null;
        this.filterLevel = null;
        this.searchQuery = '';
        
        // Channel colors/icons
        this.channelConfig = {
            'job_trace': { icon: '🚀', label: 'Job', color: '#0078d4' },
            'build_trace': { icon: '🔨', label: 'Build', color: '#107c10' },
            'deploy_trace': { icon: '📦', label: 'Deploy', color: '#8764b8' },
            'execution': { icon: '▶️', label: 'Exec', color: '#ca5010' },
            'interactive': { icon: '🖥️', label: 'Interactive', color: '#00b7c3' },
            'system': { icon: '⚙️', label: 'System', color: '#6e6e6e' },
            'validation': { icon: '✓', label: 'Validation', color: '#107c10' },
            'blob_log': { icon: '📜', label: 'Log Stream', color: '#5c6bc0' }
        };
        
        // Level styles
        this.levelConfig = {
            'debug': { class: 'level-debug', color: '#6e6e6e' },
            'info': { class: 'level-info', color: '#323130' },
            'success': { class: 'level-success', color: '#107c10' },
            'warning': { class: 'level-warning', color: '#ca5010' },
            'error': { class: 'level-error', color: '#d13438' },
            'progress': { class: 'level-progress', color: '#0078d4' }
        };
    }
    
    /**
     * Initialize the panel (create DOM elements)
     */
    init() {
        this.container = document.getElementById(this.containerId);
        if (!this.container) {
            console.error(`[ActivityPanel] Container not found: ${this.containerId}`);
            return false;
        }
        
        // Build panel HTML
        this.container.innerHTML = `
            <div class="activity-panel">
                <div class="activity-toolbar">
                    <div class="activity-filters">
                        <select class="activity-channel-filter" title="Filter by channel">
                            <option value="">All channels</option>
                            ${Object.entries(this.channelConfig).map(([ch, cfg]) => 
                                `<option value="${ch}">${cfg.icon} ${cfg.label}</option>`
                            ).join('')}
                        </select>
                        <select class="activity-level-filter" title="Filter by level">
                            <option value="">All levels</option>
                            <option value="error">❌ Errors</option>
                            <option value="warning">⚠️ Warnings</option>
                            <option value="success">✅ Success</option>
                            <option value="info">ℹ️ Info</option>
                            <option value="debug">🔍 Debug</option>
                        </select>
                        <input type="text" class="activity-search" placeholder="Search..." title="Search messages">
                    </div>
                    <div class="activity-actions">
                        <label class="activity-autoscroll" title="Auto-scroll to latest">
                            <input type="checkbox" checked>
                            <span>Auto-scroll</span>
                        </label>
                        <button class="activity-clear-btn" title="Clear all">Clear</button>
                    </div>
                </div>
                <div class="activity-entries"></div>
            </div>
        `;
        
        // Get references
        this.entriesContainer = this.container.querySelector('.activity-entries');
        this.channelFilter = this.container.querySelector('.activity-channel-filter');
        this.levelFilter = this.container.querySelector('.activity-level-filter');
        this.searchInput = this.container.querySelector('.activity-search');
        this.autoScrollCheckbox = this.container.querySelector('.activity-autoscroll input');
        this.clearBtn = this.container.querySelector('.activity-clear-btn');
        
        // Bind events
        this.channelFilter.addEventListener('change', () => this._applyFilters());
        this.levelFilter.addEventListener('change', () => this._applyFilters());
        this.searchInput.addEventListener('input', () => this._applyFilters());
        this.autoScrollCheckbox.addEventListener('change', (e) => {
            this.autoScroll = e.target.checked;
        });
        this.clearBtn.addEventListener('click', () => this.clear());
        
        return true;
    }
    
    /**
     * Add an event to the panel (or update existing if is_update flag is set)
     */
    addEvent(event) {
        // Check if this is an update to an existing event
        if (event.is_update) {
            this._updateExistingEvent(event);
            return;
        }
        
        // Store event
        this.entries.push(event);
        
        // Trim if too many
        while (this.entries.length > this.maxEntries) {
            this.entries.shift();
        }
        
        // Create DOM element
        const entry = this._createEntryElement(event);
        
        // Check if matches current filter
        if (!this._matchesFilter(event)) {
            entry.classList.add('hidden');
        }
        
        this.entriesContainer.appendChild(entry);
        
        // Trim DOM if needed
        while (this.entriesContainer.children.length > this.maxEntries) {
            this.entriesContainer.removeChild(this.entriesContainer.firstChild);
        }
        
        // Auto-scroll
        if (this.autoScroll && !entry.classList.contains('hidden')) {
            entry.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
    }
    
    /**
     * Update an existing event in the panel
     */
    _updateExistingEvent(event) {
        // Find and update the stored event
        const existingIndex = this.entries.findIndex(e => e.id === event.id);
        if (existingIndex >= 0) {
            // Update the stored event data
            this.entries[existingIndex] = { ...this.entries[existingIndex], ...event, is_update: false };
        }
        
        // Find and update the DOM element
        const existingEntry = this.entriesContainer.querySelector(`[data-event-id="${event.id}"]`);
        if (existingEntry) {
            // Check if it was expanded
            const wasExpanded = existingEntry.classList.contains('expanded');
            
            // Recreate the entry with updated data
            const updatedEntry = this._createEntryElement(event);
            
            // Preserve expanded state
            if (wasExpanded) {
                updatedEntry.classList.add('expanded');
                const toggle = updatedEntry.querySelector('.expand-toggle');
                if (toggle) {
                    toggle.textContent = '▼';
                }
            }
            
            // Check filter
            if (!this._matchesFilter(event)) {
                updatedEntry.classList.add('hidden');
            }
            
            // Replace the old entry
            existingEntry.replaceWith(updatedEntry);
            
            // If expanded and auto-scroll, scroll the details into view
            if (wasExpanded && this.autoScroll) {
                const details = updatedEntry.querySelector('.entry-details');
                if (details) {
                    details.scrollTop = details.scrollHeight;
                }
            }
        }
    }
    
    _createEntryElement(event) {
        const channelCfg = this.channelConfig[event.channel] || { icon: '•', label: event.channel, color: '#666' };
        const levelCfg = this.levelConfig[event.level] || this.levelConfig['info'];
        
        const entry = document.createElement('div');
        entry.className = `activity-entry ${levelCfg.class}`;
        entry.dataset.channel = event.channel;
        entry.dataset.level = event.level;
        entry.dataset.eventId = event.id;
        
        // Mark as expandable if has details
        const hasDetails = event.details && event.details.trim().length > 0;
        if (hasDetails) {
            entry.classList.add('expandable');
        }
        
        // Format timestamp (just time, not date)
        const timestamp = new Date(event.timestamp);
        const timeStr = timestamp.toLocaleTimeString('en-US', { hour12: false });
        
        // Build context badges
        let contextBadges = '';
        if (event.context) {
            if (event.context.job_id) {
                contextBadges += `<span class="context-badge job-badge" title="Job ID">${event.context.job_id.substring(0, 8)}</span>`;
            }
            if (event.context.agent_name) {
                contextBadges += `<span class="context-badge agent-badge" title="Agent">${event.context.agent_name}</span>`;
            }
            // Show session badge if event is from a different session
            if (event.context.session_id && window.discoveryAgent?.currentSessionId &&
                event.context.session_id !== window.discoveryAgent.currentSessionId) {
                const sessionName = event.context.session_name || event.context.session_id.substring(0, 8);
                contextBadges += `<span class="context-badge session-badge" title="From another session">${sessionName}</span>`;
            }
        }
        
        // Progress bar for progress events
        let progressBar = '';
        if (event.level === 'progress' && event.metadata && event.metadata.progress !== undefined) {
            progressBar = `<div class="progress-bar"><div class="progress-fill" style="width: ${event.metadata.progress}%"></div></div>`;
        }
        
        // Expand toggle - always show placeholder for alignment
        let expandToggle = '';
        if (hasDetails) {
            expandToggle = '<span class="expand-toggle" title="Click to expand/collapse">▶</span>';
        } else {
            expandToggle = '<span class="expand-toggle-placeholder"></span>';
        }
        
        // Details container (initially hidden)
        let detailsHtml = '';
        if (hasDetails) {
            // Try to format as JSON if possible
            let formattedDetails = event.details;
            try {
                const parsed = JSON.parse(event.details);
                formattedDetails = JSON.stringify(parsed, null, 2);
            } catch (e) {
                // Not JSON, use as-is
            }
            detailsHtml = `<div class="entry-details"><pre>${this._escapeHtml(formattedDetails)}</pre></div>`;
        }
        
        entry.innerHTML = `
            <div class="entry-header">
                ${expandToggle}
                <span class="entry-time">${timeStr}</span>
                <span class="entry-channel" style="color: ${channelCfg.color}" title="${channelCfg.label}">${channelCfg.icon}</span>
                <span class="entry-message" style="color: ${levelCfg.color}">${this._escapeHtml(event.message)}</span>
                ${contextBadges}
                ${progressBar}
            </div>
            ${detailsHtml}
        `;
        
        // Add click handler for expandable entries
        if (hasDetails) {
            const header = entry.querySelector('.entry-header');
            header.addEventListener('click', () => {
                entry.classList.toggle('expanded');
                const toggle = entry.querySelector('.expand-toggle');
                if (toggle) {
                    toggle.textContent = entry.classList.contains('expanded') ? '▼' : '▶';
                }
            });
        }
        
        return entry;
    }
    
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    _matchesFilter(event) {
        // Channel filter
        if (this.filterChannel && event.channel !== this.filterChannel) {
            return false;
        }
        
        // Level filter
        if (this.filterLevel && event.level !== this.filterLevel) {
            return false;
        }
        
        // Search filter (searches message, context, and details)
        if (this.searchQuery) {
            const query = this.searchQuery.toLowerCase();
            const messageMatch = event.message.toLowerCase().includes(query);
            const contextMatch = event.context && (
                (event.context.job_id && event.context.job_id.toLowerCase().includes(query)) ||
                (event.context.agent_name && event.context.agent_name.toLowerCase().includes(query))
            );
            const detailsMatch = event.details && event.details.toLowerCase().includes(query);
            if (!messageMatch && !contextMatch && !detailsMatch) {
                return false;
            }
        }
        
        return true;
    }
    
    _applyFilters() {
        this.filterChannel = this.channelFilter.value || null;
        this.filterLevel = this.levelFilter.value || null;
        this.searchQuery = this.searchInput.value || '';
        
        // Re-apply to all entries
        const entries = this.entriesContainer.querySelectorAll('.activity-entry');
        entries.forEach(entry => {
            const event = this.entries.find(e => e.id === entry.dataset.eventId);
            if (event && this._matchesFilter(event)) {
                entry.classList.remove('hidden');
            } else {
                entry.classList.add('hidden');
            }
        });
        
        // Count update removed - status bar no longer displayed
    }
    
    /**
     * Clear all events
     */
    clear() {
        this.entries = [];
        this.entriesContainer.innerHTML = '';
    }
    
    /**
     * Update connection status display (no-op - status bar removed)
     */
    setConnectionStatus(connected, reconnecting = false) {
        // Status bar removed - method kept for API compatibility
    }
}


// Export for use in agent.js
if (typeof window !== 'undefined') {
    window.SSEClient = SSEClient;
    window.ActivityPanel = ActivityPanel;
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { SSEClient, ActivityPanel };
}
