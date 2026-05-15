/**
 * Chat and User Interface Management Utilities
 * Comprehensive utilities for managing chat messages, UI states, user interactions, and interface animations
 */

class ChatUIManager {
    constructor(discoveryAgent) {
        this.agent = discoveryAgent;
        this.typingIndicator = null;
    }

    // ================================
    // MESSAGE MANAGEMENT
    // ================================

    /**
     * Add a user message to the chat area
     * @param {string} message - The user's message
     */
    addUserMessage(message) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'chat-message user-message';
        messageDiv.innerHTML = `
            <div class="message-content">
                <div class="message-text">${this.escapeHtml(message)}</div>
            </div>
        `;
        
        // Remove welcome message if it exists
        const welcomeMessage = this.agent.chatArea.querySelector('.welcome-message');
        if (welcomeMessage) {
            welcomeMessage.remove();
        }
        
        this.agent.chatArea.appendChild(messageDiv);
        this.scrollToBottom();
        
        // Add fade-in animation
        setTimeout(() => messageDiv.classList.add('visible'), 10);
    }

    /**
     * Add an assistant response to the chat area
     * @param {Object} response - The assistant's response object
     */
    addAssistantResponse(response) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'chat-message assistant-message';
        
        let content = '';
        if (response.answer_items) {
            response.answer_items.forEach((item, index) => {
                if (item.type === 'text') {
                    try {
                        // Sanitize content before markdown parsing
                        const sanitizedContent = this.sanitizeContent(item.content);
                        content += marked.parse(sanitizedContent);
                    } catch (error) {
                        console.warn('Markdown parsing failed, falling back to plain text:', error);
                        content += this.escapeHtml(this.sanitizeContent(item.content));
                    }
                } else if (item.type === 'code') {
                    content += this.createCodeBlock(item, index);
                }
            });
        } else {
            content = '<p>Invalid response format received.</p>';
        }

        messageDiv.innerHTML = `
            <div class="message-header">
                <div class="assistant-header-row">
                    <img src="images/icon.svg" alt="Assistant" width="20" height="20">
                    <div class="assistant-name" id="assistant-name">${this.agent.getAgentName()}</div>
                </div>
            </div>
            <div class="message-content">
                <div class="message-text">${content}</div>
            </div>
        `;
        
        this.agent.chatArea.appendChild(messageDiv);
        this.scrollToBottom();
        
        // Add fade-in animation
        setTimeout(() => messageDiv.classList.add('visible'), 10);
        
        // Apply syntax highlighting to any code blocks
        this.agent.applyCodeHighlighting(messageDiv);
    }

    /**
     * Add an error message to the chat area
     * @param {string} message - The error message
     */
    addErrorMessage(message) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'chat-message assistant-message error-message';
        messageDiv.innerHTML = `
            <div class="message-header">
                <div class="assistant-header-row">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                    </svg>
                    <div class="assistant-name">System Error</div>
                </div>
            </div>
            <div class="message-content">
                <div class="message-text error-text">${this.escapeHtml(message)}</div>
            </div>
        `;
        
        this.agent.chatArea.appendChild(messageDiv);
        this.scrollToBottom();
        
        setTimeout(() => messageDiv.classList.add('visible'), 10);
    }
    
    /**
     * Show a system message in the chat area
     * @param {string} message - The system message
     * @param {boolean} isLoading - Whether to show loading spinner
     * @returns {HTMLElement} - The created message element
     */
    showSystemMessage(message, isLoading = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'chat-message system-message';
        messageDiv.innerHTML = `
            <div class="message-content">
                <div class="message-text">
                    ${isLoading ? '<div class="loading-spinner"></div>' : ''}
                    ${this.escapeHtml(message)}
                </div>
            </div>
        `;
        
        this.agent.chatArea.appendChild(messageDiv);
        this.scrollToBottom();
        
        setTimeout(() => messageDiv.classList.add('visible'), 10);
        
        return messageDiv;
    }

    /**
     * Show typing indicator animation
     */
    showTypingIndicator() {
        this.typingIndicator = document.createElement('div');
        this.typingIndicator.className = 'chat-message assistant-message typing-indicator';
        this.typingIndicator.innerHTML = `
            <div class="message-content">
                <div class="loading-animation">
                    <div class="loading-header">
                        <img src="images/icon.svg" alt="${this.agent.getAgentName()}" width="20" height="20">
                        <span class="loading-text">${this.agent.getAgentName()}</span>
                    </div>
                    <div class="loading-progress">
                        <img src="images/copilot-loader-endless.gif" alt="Loading..." height="8" width="128">
                    </div>
                </div>
            </div>
        `;
        
        this.agent.chatArea.appendChild(this.typingIndicator);
        this.scrollToBottom();
        
        setTimeout(() => this.typingIndicator.classList.add('visible'), 10);
    }
    
    /**
     * Hide typing indicator animation
     */
    hideTypingIndicator() {
        if (this.typingIndicator) {
            this.typingIndicator.remove();
            this.typingIndicator = null;
        }
    }

    /**
     * Scroll chat area to bottom smoothly
     */
    scrollToBottom() {
        requestAnimationFrame(() => {
            this.agent.chatArea.scrollTo({
                top: this.agent.chatArea.scrollHeight,
                behavior: 'smooth'
            });
        });
    }

    // ================================
    // CODE BLOCK MANAGEMENT
    // ================================

    /**
     * Create a code block with syntax highlighting and controls
     * @param {Object} item - Code item with content and language
     * @param {number} index - Index for unique IDs
     * @returns {string} - HTML string for the code block
     */
    createCodeBlock(item, index) {
        const uniqueId = `code-${Date.now()}-${index}`;
        const containerId = `container-${uniqueId}`;
        const toggleId = `toggle-${uniqueId}`;
        
        // Sanitize code content
        const sanitizedContent = this.sanitizeContent(item.content);
        
        // Use provided language or detect if not provided
        let detectedLanguage;
        if (item.language) {
            // Use the language specified by the LLM in the markdown
            detectedLanguage = this.agent.normalizeLanguage(item.language);
        } else {
            // Fall back to detection only if no language was specified
            detectedLanguage = this.agent.detectLanguage(sanitizedContent) || 'plaintext';
        }
        const languageDisplayName = this.agent.getLanguageDisplayName(detectedLanguage);

        // Define which languages are executable (can be run)
        const executableLanguages = ['python', 'bash', 'shell', 'sh', 'javascript', 'qsharp'];
        const isExecutable = executableLanguages.includes(detectedLanguage);

        const codeLines = sanitizedContent.split('\n');
        const shouldTruncate = codeLines.length > 15;

        // Split content into visible and hidden parts
        const visibleContent = shouldTruncate ? codeLines.slice(0, 15).join('\n') : sanitizedContent;
        const hiddenContent = shouldTruncate ? codeLines.slice(15).join('\n') : '';

        // Build the Run button HTML only for executable languages
        const runButtonHtml = isExecutable ? `
                        <div class="run-button-container">
                            <button class="run-btn" onclick="discoveryAgent.runCode('${uniqueId}')">Run</button>
                            <div class="run-dropdown">
                                <button class="run-dropdown-btn" onclick="discoveryAgent.toggleRunDropdown('${uniqueId}', event)">
                                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                                        <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                                <div class="run-dropdown-menu" id="run-dropdown-${uniqueId}" style="display: none;">
                                    <div class="run-dropdown-item" onclick="discoveryAgent.runCode('${uniqueId}')">
                                        <span>Docker client (local)</span>
                                        <small>Execute locally via Docker client</small>
                                    </div>
                                    <!-- Container where nodepool-specific run items will be inserted by agent.populateRunDropdownNodepools -->
                                    <div id="run-supercomputer-${uniqueId}" class="run-supercomputer-container">
                                        <div class="run-dropdown-item" style="opacity: 0.7; cursor: default;">
                                            <span>Loading Supercomputer nodepools...</span>
                                            <small>Fetching available nodepools</small>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>` : '';

        return `
            <div class="code-block-container" id="${containerId}">
                <div class="code-header">
                    <div class="code-language-chip">
                        <img src="images/code.svg" alt="Code" class="code-icon">
                        <span class="code-language-text">${languageDisplayName}</span>
                    </div>
                    <div class="button-container">
                        <button type="button" id="copy-button-${uniqueId}" role="button" aria-label="Copy code" class="copy-btn" onclick="discoveryAgent.copyCode('${uniqueId}')">
                            <span class="copy-btn-icon">
                                <svg fill="currentColor" aria-hidden="true" width="20" height="20" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M7.09 3c.2-.58.76-1 1.41-1h3c.65 0 1.2.42 1.41 1h1.59c.83 0 1.5.67 1.5 1.5v5.88a1.5 1.5 0 0 0-1-.38V4.5a.5.5 0 0 0-.5-.5h-1.59c-.2.58-.76 1-1.41 1h-3a1.5 1.5 0 0 1-1.41-1H5.5a.5.5 0 0 0-.5.5v12c0 .28.22.5.5.5h3.96l.4.47c.3.35.72.53 1.14.53H5.5A1.5 1.5 0 0 1 4 16.5v-12C4 3.67 4.67 3 5.5 3h1.59ZM8.5 3a.5.5 0 0 0 0 1h3a.5.5 0 0 0 0-1h-3Zm6.99 8.64a.5.5 0 1 0-.97-.28l-2 7a.5.5 0 1 0 .97.28l2-7Zm-4.11 1.68a.5.5 0 1 0-.76-.65l-1.5 1.75a.5.5 0 0 0 0 .65l1.5 1.75a.5.5 0 1 0 .76-.65l-1.22-1.42 1.22-1.43Zm5.3 3.56a.5.5 0 0 1-.06-.71l1.22-1.42-1.22-1.43a.5.5 0 0 1 .76-.65l1.5 1.75a.5.5 0 0 1 0 .65l-1.5 1.75a.5.5 0 0 1-.7.06Z"/>
                                </svg>
                            </span>
                        </button>${runButtonHtml}
                    </div>
                </div>
                <div class="code-content">
                    <pre><code id="${uniqueId}" class="${detectedLanguage === 'plaintext' ? '' : `language-${detectedLanguage}`}">${this.escapeHtml(shouldTruncate ? visibleContent : sanitizedContent)}</code></pre>
                    ${shouldTruncate ? `<pre class="code-hidden-pre" id="${uniqueId}-hidden-pre" style="display: none;"><code id="${uniqueId}-hidden" class="${detectedLanguage === 'plaintext' ? '' : `language-${detectedLanguage}`}">${this.escapeHtml(hiddenContent)}</code></pre>` : ''}
                    ${shouldTruncate ? `
                    <div class="show-more-container">
                        <button type="button" id="${toggleId}" class="show-more-btn" onclick="discoveryAgent.toggleCodeExpansion('${uniqueId}', '${toggleId}')">
                            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M2 2.5C2 2.22386 2.22386 2 2.5 2H13.5C13.7761 2 14 2.22386 14 2.5C14 2.77614 13.7761 3 13.5 3H2.5C2.22386 3 2 2.77614 2 2.5ZM2 14.5C2 14.2239 2.22386 14 2.5 14H13.5C13.7761 14 14 14.2239 14 14.5C14 14.7761 13.7761 15 13.5 15H2.5C2.22386 15 2 14.7761 2 14.5ZM9 10.5C9 10.2239 9.22386 10 9.5 10H13.5C13.7761 10 14 10.2239 14 10.5C14 10.7761 13.7761 11 13.5 11H9.5C9.22386 11 9 10.7761 9 10.5ZM9 6.5C9 6.22386 9.22386 6 9.5 6H13.5C13.7761 6 14 6.22386 14 6.5C14 6.77614 13.7761 7 13.5 7H9.5C9.22386 7 9 6.77614 9 6.5ZM4.5 12C2.567 12 1 10.433 1 8.5C1 6.567 2.567 5 4.5 5C6.433 5 8 6.567 8 8.5C8 10.433 6.433 12 4.5 12ZM5 6.5C5 6.22386 4.77614 6 4.5 6C4.22386 6 4 6.22386 4 6.5V8H2.5C2.22386 8 2 8.22386 2 8.5C2 8.77614 2.22386 9 2.5 9H4V10.5C4 10.7761 4.22386 11 4.5 11C4.77614 11 5 10.7761 5 10.5V9H6.5C6.77614 9 7 8.77614 7 8.5C7 8.22386 6.77614 8 6.5 8H5V6.5Z" fill="currentColor"/>
                            </svg>
                            <span class="btn-text">Show more lines</span>
                        </button>
                    </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    /**
     * Toggle code block expansion/collapse
     * @param {string} codeId - The code block ID
     * @param {string} toggleId - The toggle button ID
     */
    toggleCodeExpansion(codeId, toggleId) {
        const mainCode = document.getElementById(codeId);
        const hiddenPre = document.getElementById(`${codeId}-hidden-pre`);
        const toggleBtn = document.getElementById(toggleId);
        
        if (!hiddenPre || !toggleBtn || !mainCode) {
            console.error('Code expansion elements not found:', { codeId, toggleId });
            return;
        }
        
        const isExpanded = hiddenPre.style.display !== 'none';
        
        if (isExpanded) {
            // Collapse - hide hidden content
            hiddenPre.style.display = 'none';
            toggleBtn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M2 2.5C2 2.22386 2.22386 2 2.5 2H13.5C13.7761 2 14 2.22386 14 2.5C14 2.77614 13.7761 3 13.5 3H2.5C2.22386 3 2 2.77614 2 2.5ZM2 14.5C2 14.2239 2.22386 14 2.5 14H13.5C13.7761 14 14 14.2239 14 14.5C14 14.7761 13.7761 15 13.5 15H2.5C2.22386 15 2 14.7761 2 14.5ZM9 10.5C9 10.2239 9.22386 10 9.5 10H13.5C13.7761 10 14 10.2239 14 10.5C14 10.7761 13.7761 11 13.5 11H9.5C9.22386 11 9 10.7761 9 10.5ZM9 6.5C9 6.22386 9.22386 6 9.5 6H13.5C13.7761 6 14 6.22386 14 6.5C14 6.77614 13.7761 7 13.5 7H9.5C9.22386 7 9 6.77614 9 6.5ZM4.5 12C2.567 12 1 10.433 1 8.5C1 6.567 2.567 5 4.5 5C6.433 5 8 6.567 8 8.5C8 10.433 6.433 12 4.5 12ZM5 6.5C5 6.22386 4.77614 6 4.5 6C4.22386 6 4 6.22386 4 6.5V8H2.5C2.22386 8 2 8.22386 2 8.5C2 8.77614 2.22386 9 2.5 9H4V10.5C4 10.7761 4.22386 11 4.5 11C4.77614 11 5 10.7761 5 10.5V9H6.5C6.77614 9 7 8.77614 7 8.5C7 8.22386 6.77614 8 6.5 8H5V6.5Z" fill="currentColor"/>
                </svg>
                <span class="btn-text">Show more lines</span>
            `;
        } else {
            // Expand - show hidden content
            hiddenPre.style.display = 'block';
            toggleBtn.innerHTML = `
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M5 3.5C5 3.22386 5.22386 3 5.5 3H17.5C17.7761 3 18 3.22386 18 3.5C18 3.77614 17.7761 4 17.5 4H5.5C5.22386 4 5 3.77614 5 3.5ZM5 15.5C5 15.2239 5.22386 15 5.5 15H17.5C17.7761 15 18 15.2239 18 15.5C18 15.7761 17.7761 16 17.5 16H5.5C5.22386 16 5 15.7761 5 15.5ZM11 7.5C11 7.22386 11.2239 7 11.5 7H17.5C17.7761 7 18 7.22386 18 7.5C18 7.77614 17.7761 8 17.5 8H11.5C11.2239 8 11 7.77614 11 7.5ZM11 11.5C11 11.2239 11.2239 11 11.5 11H17.5C17.7761 11 18 11.2239 18 11.5C18 11.7761 17.7761 12 17.5 12H11.5C11.2239 12 11 11.7761 11 11.5ZM9 9.5C9 11.433 7.433 13 5.5 13C3.567 13 2 11.433 2 9.5C2 7.567 3.567 6 5.5 6C7.433 6 9 7.567 9 9.5ZM3.5 9C3.22386 9 3 9.22386 3 9.5C3 9.77614 3.22386 10 3.5 10H7.5C7.77614 10 8 9.77614 8 9.5C8 9.22386 7.77614 9 7.5 9H3.5Z" fill="currentColor"/>
                </svg>
                <span class="btn-text">Show less</span>
            `;
        }
        
        // Re-apply syntax highlighting if Prism is available
        const hiddenCode = document.getElementById(`${codeId}-hidden`);
        if (typeof Prism !== 'undefined' && hiddenCode) {
            Prism.highlightElement(hiddenCode);
        }
    }

    // ================================
    // UI STATE MANAGEMENT
    // ================================

    /**
     * Set a random greeting message
     */
    setRandomGreeting() {
        const greetings = [
            "Hi there, try asking, 'what can you do?'",
            "What can I help you with?"
        ];
        
        const randomGreeting = greetings[Math.floor(Math.random() * greetings.length)];
        if (this.agent.welcomeGreeting) {
            this.agent.welcomeGreeting.textContent = randomGreeting;
        }
    }

    /**
     * Show the welcome state interface
     */
    showWelcomeState() {
        if (this.agent.chatArea) {
            this.agent.chatArea.classList.add('welcome-state');
        }
        
        // Move input container back to welcome centered and remove bottom positioning
        if (this.agent.inputContainer && this.agent.welcomeCentered) {
            this.agent.inputContainer.classList.remove('bottom-positioned', 'transitioning-to-bottom');
            this.agent.welcomeCentered.appendChild(this.agent.inputContainer);
        }
        
        if (this.agent.welcomeCentered) {
            this.agent.welcomeCentered.style.display = 'flex';
        }
        
        // Focus the input after state change
        setTimeout(() => {
            if (this.agent.promptInput) {
                this.agent.promptInput.focus();
            }
        }, 100);
    }

    /**
     * Hide the welcome state and show chat interface
     */
    hideWelcomeState() {
        if (this.agent.chatArea) {
            this.agent.chatArea.classList.remove('welcome-state');
        }
        
        // Animate the input container from center to bottom
        this.animateInputToBottom();
    }

    /**
     * Animate input container from center to bottom position
     */
    animateInputToBottom() {
        if (!this.agent.inputContainer) return;

        // Hide welcome first to avoid any flicker
        if (this.agent.welcomeCentered) {
            this.agent.welcomeCentered.style.display = 'none';
        }

        // Add bottom positioning immediately when moving
        this.agent.inputContainer.classList.add('transitioning-to-bottom', 'bottom-positioned');
        
        // Move the input container to the left panel
        const leftPanel = document.querySelector('.left-panel');
        leftPanel.appendChild(this.agent.inputContainer);

        // After animation completes, clean up transition classes
        setTimeout(() => {
            this.agent.inputContainer.classList.remove('transitioning-to-bottom');
            
            // Maintain focus on input after transition
            if (this.agent.promptInput) {
                this.agent.promptInput.focus();
            }
        }, 400); // Match CSS transition duration
    }

    /**
     * Reset chat to welcome state
     */
    resetChatToWelcome() {
        // Clear any existing chat messages, but keep the welcome structure
        const existingMessages = this.agent.chatArea.querySelectorAll('.chat-message');
        existingMessages.forEach(msg => msg.remove());
        
        // Clear typing indicator if it exists
        this.hideTypingIndicator();
        
        // Clear input field
        if (this.agent.promptInput) {
            this.agent.promptInput.value = '';
            this.agent.promptInput.style.height = 'auto';
        }
        
        // Reset to welcome state with the existing input container
        this.setRandomGreeting();
        this.showWelcomeState();
          
        // Update attachment button state
        this.agent.updateAttachmentButton();
        
        // Update button visibility (will hide enhance and send buttons since input is empty)
        this.updateButtonVisibility();
    }

    /**
     * Reinitialize DOM references and event listeners
     */
    reinitializeReferences() {
        // References should still be valid since we're using the same DOM elements
        // Just ensure we have the right references
        this.agent.promptInput = document.getElementById('promptInput');
        this.agent.submitBtn = document.getElementById('submitBtn');
        this.agent.enhanceBtn = document.querySelector('.enhance-btn');
        this.agent.plusBtn = document.querySelector('.plus-btn');
        this.agent.attachmentBtn = document.querySelector('.attachment-btn');
        this.agent.attachmentCount = document.querySelector('.attachment-count');
        this.agent.welcomeCentered = document.getElementById('welcomeCentered');
        this.agent.welcomeGreeting = document.getElementById('welcomeGreeting');
        this.agent.inputContainer = document.getElementById('inputContainer');
        
        // Re-setup event listeners (remove old ones first to avoid duplicates)
        if (this.agent.promptInput) {
            this.agent.promptInput.replaceWith(this.agent.promptInput.cloneNode(true));
            this.agent.promptInput = document.getElementById('promptInput');
        }
        if (this.agent.submitBtn) {
            this.agent.submitBtn.replaceWith(this.agent.submitBtn.cloneNode(true));
            this.agent.submitBtn = document.getElementById('submitBtn');
        }
        
        // Re-setup functionality
        this.setupTextareaResize();
        this.agent.initializeEventListeners();
        
        // Update attachment button
        this.agent.updateAttachmentButton();
    }

    // ================================
    // USER INTERFACE UTILITIES
    // ================================

    /**
     * Setup automatic textarea resizing functionality
     */
    setupTextareaResize() {
        this.agent.promptInput.addEventListener('input', () => {
            // Auto-resize textarea
            this.agent.promptInput.style.height = 'auto';
            this.agent.promptInput.style.height = Math.min(this.agent.promptInput.scrollHeight, 200) + 'px';
            
            // Update button visibility
            this.updateButtonVisibility();
        });
        
        // Initialize button visibility
        this.updateButtonVisibility();
    }

    /**
     * Update visibility of interface buttons based on input state
     */
    updateButtonVisibility() {
        const hasText = this.agent.promptInput.value.trim().length > 0;
        
        if (this.agent.enhanceBtn) {
            this.agent.enhanceBtn.style.display = hasText ? 'flex' : 'none';
        }
        
        if (this.agent.submitBtn) {
            this.agent.submitBtn.style.display = hasText ? 'flex' : 'none';
        }
    }

    /**
     * Set loading state for the submit button
     * @param {boolean} isLoading - Whether the interface is in loading state
     */
    setLoading(isLoading) {
        this.agent.submitBtn.disabled = isLoading;
        
        // Update button appearance
        if (isLoading) {
            this.agent.submitBtn.innerHTML = `
                <div class="loading-spinner small"></div>
            `;
        } else {
            this.agent.submitBtn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M15.854 7.146L1.5 1.293a.5.5 0 0 0-.48.064.5.5 0 0 0-.234.41v4.585l6.5 1.145L.786 8.642v4.585a.5.5 0 0 0 .234.41.5.5 0 0 0 .48.064L15.854 7.5a.5.5 0 0 0 0-1.354z"/>
                </svg>
            `;
        }
    }

    /**
     * Show an error message in the chat
     * @param {string} message - The error message to display
     */
    showError(message) {
        this.addErrorMessage(message);
    }

    // ================================
    // CONTENT PROCESSING UTILITIES
    // ================================

    /**
     * Escape HTML characters in text
     * @param {string} text - The text to escape
     * @returns {string} - HTML-escaped text
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Sanitize content by removing problematic characters
     * @param {string} content - The content to sanitize
     * @returns {string} - Sanitized content
     */
    sanitizeContent(content) {
        // Remove common invisible characters that can cause parsing issues
        let sanitized = content
            .replace(/\uFEFF/g, '') // Remove Byte Order Mark (BOM)
            .replace(/\u200B/g, '') // Remove Zero Width Space
            .replace(/\u200C/g, '') // Remove Zero Width Non-Joiner
            .replace(/\u200D/g, '') // Remove Zero Width Joiner
            .replace(/\u2060/g, '') // Remove Word Joiner
            .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '') // Remove other control characters
            .trim(); // Remove leading/trailing whitespace
        
        return sanitized;
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ChatUIManager;
}
