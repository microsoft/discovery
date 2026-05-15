/**
 * Clipboard and File Interaction Utilities
 * Utilities for copying content to clipboard, file downloads, and button interactions
 */

class ClipboardUtils {
    /**
     * Download a file from the server (unified endpoint)
     * @param {string} filename - The filename to download
     * @param {string} source - 'inputs' or 'outputs' (default: 'outputs')
     */
    static downloadFile(filename, source = 'outputs') {
        const link = document.createElement('a');
        // Encode each path segment to preserve '/' separators and handle special characters
        const safePath = filename.split('/').map(encodeURIComponent).join('/');
        const params = new URLSearchParams();
        params.set('source', source);
        params.set('download', 'true');
        // Get session context from global discoveryAgent if available
        if (window.discoveryAgent) {
            if (window.discoveryAgent.currentSessionId) {
                params.set('session_id', window.discoveryAgent.currentSessionId);
            }
            if (typeof window.discoveryAgent.getCurrentAgentName === 'function') {
                const agentName = window.discoveryAgent.getCurrentAgentName();
                if (agentName) params.set('agent_name', agentName);
            }
        }
        link.href = `/api/file/${safePath}?${params.toString()}`;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
    
    /**
     * Copy text content to clipboard with visual feedback
     * @param {string} code - The text content to copy
     * @param {HTMLElement} button - The button element to provide visual feedback
     */
    static async copyToClipboard(code, button) {
        try {
            await navigator.clipboard.writeText(code);
            
            // Visual feedback
            const originalText = button.textContent;
            button.textContent = 'Copied!';
            button.classList.add('copied');
            
            setTimeout(() => {
                button.textContent = originalText;
                button.classList.remove('copied');
            }, 2000);
        } catch (error) {
            console.error('Failed to copy to clipboard:', error);
            
            // Fallback for older browsers
            const textArea = document.createElement('textarea');
            textArea.value = code;
            document.body.appendChild(textArea);
            textArea.select();
            try {
                document.execCommand('copy');
                
                // Visual feedback
                const originalText = button.textContent;
                button.textContent = 'Copied!';
                button.classList.add('copied');
                
                setTimeout(() => {
                    button.textContent = originalText;
                    button.classList.remove('copied');
                }, 2000);
            } catch (fallbackError) {
                console.error('Fallback copy failed:', fallbackError);
                button.textContent = 'Copy failed';
                setTimeout(() => {
                    button.textContent = 'Copy';
                }, 2000);
            }
            document.body.removeChild(textArea);
        }
    }

    /**
     * Create HTML for a copy button
     * @param {string} targetElementSelector - CSS selector for the element to copy from
     * @param {string} buttonId - The ID for the copy button
     * @returns {string} - HTML string for the copy button
     */
    static createCopyButton(targetElementSelector, buttonId) {
        return `
            <button type="button" id="${buttonId}" role="button" aria-label="Copy content" class="copy-btn copy-btn-output" onclick="ClipboardUtils.copyElementContent('${targetElementSelector}', '${buttonId}')">
                <img src="images/clipboard_code.svg" alt="Copy" width="16" height="16" class="copy-btn-icon">
            </button>
        `;
    }

    /**
     * Copy content from a DOM element to clipboard with visual feedback
     * @param {string} targetElementSelector - CSS selector for the element to copy from
     * @param {string} buttonId - The ID of the copy button for visual feedback
     */
    static async copyElementContent(targetElementSelector, buttonId) {
        const targetElement = document.querySelector(targetElementSelector);
        const button = document.getElementById(buttonId);
        
        if (!targetElement || !button) {
            console.error('Target element or button not found:', targetElementSelector, buttonId);
            return;
        }
        
        let content = '';
        
        // Handle different element types
        if (targetElement.tagName === 'TEXTAREA' || targetElement.tagName === 'INPUT') {
            content = targetElement.value || '';
        } else if (targetElement.tagName === 'PRE') {
            content = targetElement.textContent || targetElement.innerText || '';
        } else {
            // Special handling for API docs - check for stored markdown content
            const markdownContent = targetElement.getAttribute('data-markdown-content');
            if (markdownContent) {
                content = markdownContent;
            } else {
                // If the target is or contains a chat message, convert HTML to Markdown
                let messageNode = null;
                if (targetElement.classList && targetElement.classList.contains('message-text')) {
                    messageNode = targetElement;
                } else if (targetElement.querySelector) {
                    messageNode = targetElement.querySelector('.message-text');
                }
                if (messageNode) {
                    content = ClipboardUtils.htmlToMarkdown(messageNode);
                } else {
                    // For other elements, try textContent first
                    content = targetElement.textContent || targetElement.innerText || '';
                }
            }
        }
        
        console.log('Copy operation:', { 
            selector: targetElementSelector, 
            buttonId: buttonId, 
            elementType: targetElement.tagName, 
            contentLength: content.length,
            usingMarkdown: !!targetElement.getAttribute('data-markdown-content'),
            content: content.substring(0, 100) + (content.length > 100 ? '...' : '')
        });
        
        if (!content.trim()) {
            console.warn('No content to copy from element:', targetElementSelector);
            // Still provide visual feedback even if empty
            const originalContent = button.innerHTML;
            button.innerHTML = '<img src="images/clipboard_code.svg" alt="No content" width="16" height="16" class="copy-btn-icon">';
            button.classList.add('copied');
            button.title = 'No content to copy';
            
            setTimeout(() => {
                button.innerHTML = originalContent;
                button.classList.remove('copied');
                button.title = 'Copy content';
            }, 2000);
            return;
        }
        
        try {
            await navigator.clipboard.writeText(content);
            
            // Visual feedback
            const originalContent = button.innerHTML;
            button.innerHTML = '<img src="images/clipboard_code.svg" alt="Copied" width="16" height="16" class="copy-btn-icon">';
            button.classList.add('copied');
            button.title = 'Copied!';
            
            setTimeout(() => {
                button.innerHTML = originalContent;
                button.classList.remove('copied');
                button.title = 'Copy content';
            }, 2000);
        } catch (error) {
            console.error('Failed to copy to clipboard:', error);
            
            // Fallback for older browsers
            const textArea = document.createElement('textarea');
            textArea.value = content;
            document.body.appendChild(textArea);
            textArea.select();
            try {
                document.execCommand('copy');
                
                // Visual feedback
                const originalContent = button.innerHTML;
                button.innerHTML = '<img src="images/clipboard_code.svg" alt="Copied" width="16" height="16" class="copy-btn-icon">';
                button.classList.add('copied');
                button.title = 'Copied!';
                
                setTimeout(() => {
                    button.innerHTML = originalContent;
                    button.classList.remove('copied');
                    button.title = 'Copy content';
                }, 2000);
            } catch (fallbackError) {
                console.error('Fallback copy failed:', fallbackError);
                button.innerHTML = '<img src="images/clipboard_code.svg" alt="Copy failed" width="16" height="16" class="copy-btn-icon">';
                button.title = 'Copy failed';
                setTimeout(() => {
                    button.innerHTML = '<img src="images/clipboard_code.svg" alt="Copy" width="16" height="16" class="copy-btn-icon">';
                    button.title = 'Copy content';
                }, 2000);
            }
            document.body.removeChild(textArea);
        }
    }
    
    // ------------------------- Markdown conversion helpers -------------------------
    static htmlToMarkdown(node) {
        if (!node) return '';
        // If node is a text node
        if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || '';

        const tag = (node.tagName || '').toLowerCase();
        switch (tag) {
            case 'br': return '  \n';
            case 'p': return ClipboardUtils.inlineChildrenToMarkdown(node).trim() + '\n\n';
            case 'h1': return '# ' + ClipboardUtils.inlineChildrenToMarkdown(node).trim() + '\n\n';
            case 'h2': return '## ' + ClipboardUtils.inlineChildrenToMarkdown(node).trim() + '\n\n';
            case 'h3': return '### ' + ClipboardUtils.inlineChildrenToMarkdown(node).trim() + '\n\n';
            case 'h4': return '#### ' + ClipboardUtils.inlineChildrenToMarkdown(node).trim() + '\n\n';
            case 'pre': {
                const code = node.querySelector ? node.querySelector('code') : null;
                const text = code ? code.textContent : node.textContent || '';
                return '```\n' + text.replace(/```/g, '\`\`\`') + '\n```\n\n';
            }
            case 'code': return '`' + (node.textContent || '') + '`';
            case 'strong':
            case 'b': return '**' + ClipboardUtils.inlineChildrenToMarkdown(node) + '**';
            case 'em':
            case 'i': return '*' + ClipboardUtils.inlineChildrenToMarkdown(node) + '*';
            case 'a': {
                const href = node.getAttribute('href') || '';
                const txt = ClipboardUtils.inlineChildrenToMarkdown(node).trim() || href;
                return `[${txt}](${href})`;
            }
            case 'img': return `![${node.getAttribute('alt')||''}](${node.getAttribute('src')||''})`;
            case 'ul': return ClipboardUtils.listToMarkdown(node, false) + '\n';
            case 'ol': return ClipboardUtils.listToMarkdown(node, true) + '\n';
            case 'blockquote': {
                const txt = ClipboardUtils.inlineChildrenToMarkdown(node).split('\n').map(l => '> ' + l).join('\n');
                return txt + '\n\n';
            }
            case 'details': {
                // Handle collapsible details sections
                const summary = node.querySelector('summary');
                const summaryText = summary ? ClipboardUtils.inlineChildrenToMarkdown(summary).trim() : '';
                
                // Get all children except summary
                const otherChildren = Array.from(node.children || []).filter(c => c.tagName.toLowerCase() !== 'summary');
                const content = otherChildren.map(c => ClipboardUtils.htmlToMarkdown(c)).join('');
                
                return (summaryText ? summaryText + '\n\n' : '') + content;
            }
            case 'summary': {
                // Summary is handled by details parent, but if standalone, treat as bold text
                return '**' + ClipboardUtils.inlineChildrenToMarkdown(node).trim() + '**\n\n';
            }
            case 'hr': return '\n---\n\n';
            case 'div': {
                // If div contains block-level children, join them, otherwise inline
                const blockChildren = Array.from(node.children || []).filter(c => ['P','DIV','UL','OL','PRE','BLOCKQUOTE','H1','H2','H3','H4','H5','H6','DETAILS'].includes(c.tagName));
                if (blockChildren.length) return blockChildren.map(c => ClipboardUtils.htmlToMarkdown(c)).join('');
                return ClipboardUtils.inlineChildrenToMarkdown(node);
            }
            default:
                // Inline elements: process children
                return ClipboardUtils.inlineChildrenToMarkdown(node);
        }
    }

    static inlineChildrenToMarkdown(node) {
        let out = '';
        node.childNodes.forEach(child => {
            if (child.nodeType === Node.TEXT_NODE) {
                out += child.nodeValue;
            } else if (child.nodeType === Node.ELEMENT_NODE) {
                const tag = child.tagName.toLowerCase();
                if (tag === 'code' && child.parentElement && child.parentElement.tagName.toLowerCase() === 'pre') {
                    // handled in pre
                    out += '';
                } else if (tag === 'a') {
                    const href = child.getAttribute('href') || '';
                    const txt = child.textContent || href;
                    out += `[${txt}](${href})`;
                } else if (tag === 'strong' || tag === 'b') {
                    out += `**${ClipboardUtils.inlineChildrenToMarkdown(child)}**`;
                } else if (tag === 'em' || tag === 'i') {
                    out += `*${ClipboardUtils.inlineChildrenToMarkdown(child)}*`;
                } else if (tag === 'code') {
                    out += '`' + (child.textContent || '') + '`';
                } else if (tag === 'img') {
                    out += `![${child.getAttribute('alt')||''}](${child.getAttribute('src')||''})`;
                } else {
                    out += ClipboardUtils.inlineChildrenToMarkdown(child);
                }
            }
        });
        return out;
    }

    static listToMarkdown(listNode, ordered) {
        const items = Array.from(listNode.children).filter(c => c.tagName && c.tagName.toLowerCase() === 'li');
        return items.map((li, idx) => {
            if (ordered) return `${idx+1}. ${ClipboardUtils.inlineChildrenToMarkdown(li).trim()}`;
            return `- ${ClipboardUtils.inlineChildrenToMarkdown(li).trim()}`;
        }).join('\n');
    }

}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ClipboardUtils;
}

// Also make available globally for onclick handlers in HTML
if (typeof window !== 'undefined') {
    window.ClipboardUtils = ClipboardUtils;
}
