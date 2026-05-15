/**
 * Default Text Extension - handles text files with enhanced formatting for structured data
 */
class DefaultTextExtension extends BaseExtension {
    constructor() {
        super('Default Text Viewer', ['.txt', '.log', '.out', '.dat', '.cfg', '.json', '.csv', '.xml', '.yaml', '.yml', '.md', '.ini', '.conf'], {
            hasPreview: true,
            hasFullView: true,
            interactive: false,
            resizable: true
        });
    }

    getExtensionFolder() {
        return 'extensions/default-text';
    }

    async canHandle(filename, content) {
        // Always return true as fallback, but with lower priority
        return true;
    }    async renderPreview(container, filename, content, options = {}) {
        const extension = filename.split('.').pop().toLowerCase();
        
        // Don't truncate JSON files - show full content in preview
        if (extension === 'json') {
            const formattedContent = await this.formatContent(filename, content, 'preview');
            container.innerHTML = formattedContent;
            
            // Apply syntax highlighting if Prism is available
            if (typeof Prism !== 'undefined') {
                Prism.highlightAllUnder(container);
            }
            
            return { success: true };
        }
        
        // For other file types, truncate to first 20 lines
        const maxLines = 20;
        const lines = content.split('\n');
        const preview = lines.length > maxLines ? 
            lines.slice(0, maxLines).join('\n') + '\n\n... (truncated, expand to see full content)' : 
            content;

        const formattedContent = await this.formatContent(filename, preview, 'preview');
        container.innerHTML = formattedContent;
        
        // Apply syntax highlighting if Prism is available
        if (typeof Prism !== 'undefined') {
            Prism.highlightAllUnder(container);
        }
        
        return { success: true };
    }

    async renderFullView(container, filename, content, options = {}) {
        const formattedContent = await this.formatContent(filename, content, 'full');
        container.innerHTML = formattedContent;
        
        // Apply syntax highlighting if Prism is available
        if (typeof Prism !== 'undefined') {
            Prism.highlightAllUnder(container);
        }
        
        return { success: true };
    }

    async formatContent(filename, content, mode = 'full') {
        const extension = filename.split('.').pop().toLowerCase();
        
        switch (extension) {
            case 'json':
                return this.formatJson(content, mode);
            case 'csv':
                return this.formatCsv(content);
            case 'xml':
                return this.formatXml(content);
            case 'yaml':
            case 'yml':
                return this.formatYaml(content);
            case 'md':
                return this.formatMarkdown(content);
            default:
                return this.formatPlainText(content);
        }
    }    formatJson(content, mode = 'full') {
        // Format and validate JSON for both preview and full view
        try {
            const parsed = JSON.parse(content);
            const formatted = JSON.stringify(parsed, null, 2);
            return `<pre class="text-content"><code class="language-json">${this.escapeHtml(formatted)}</code></pre>`;
        } catch (e) {
            // If JSON is invalid, show as plain text with error indicator
            // Limit display size to prevent browser freeze from syntax highlighting large invalid content
            const maxChars = 50000;
            const truncated = content.length > maxChars;
            const displayContent = truncated ? content.substring(0, maxChars) : content;
            const truncateNote = truncated ? `\n\n... (content truncated at ${maxChars.toLocaleString()} characters)` : '';
            return `
                <div class="format-error">⚠️ Invalid JSON format: ${this.escapeHtml(e.message)}</div>
                <pre class="text-content"><code class="language-plaintext">${this.escapeHtml(displayContent + truncateNote)}</code></pre>
            `;
        }
    }formatCsv(content) {
        try {
            const lines = content.trim().split('\n');
            if (lines.length === 0) return this.formatPlainText(content);
            
            // Parse CSV (simple implementation)
            const rows = lines.map(line => {
                // Simple CSV parsing - doesn't handle quoted fields with commas
                return line.split(',').map(cell => cell.trim());
            });
            
            let html = '<div class="csv-container"><table class="csv-table">';
            
            // Header row
            if (rows.length > 0) {
                html += '<thead><tr>';
                rows[0].forEach(cell => {
                    html += `<th title="${this.escapeHtml(cell)}">${this.escapeHtml(cell)}</th>`;
                });
                html += '</tr></thead>';
            }
            
            // Data rows
            if (rows.length > 1) {
                html += '<tbody>';
                for (let i = 1; i < rows.length; i++) {
                    html += '<tr>';
                    rows[i].forEach(cell => {
                        // Add title attribute for full content on hover
                        html += `<td title="${this.escapeHtml(cell)}">${this.escapeHtml(cell)}</td>`;
                    });
                    html += '</tr>';
                }
                html += '</tbody>';
            }
            
            html += '</table></div>';
            return html;
        } catch (e) {
            return this.formatPlainText(content);
        }
    }

    formatXml(content) {
        try {
            // Simple XML formatting - just add syntax highlighting
            return `<pre class="text-content"><code class="language-xml">${this.escapeHtml(content)}</code></pre>`;
        } catch (e) {
            return this.formatPlainText(content);
        }
    }

    formatYaml(content) {
        return `<pre class="text-content"><code class="language-yaml">${this.escapeHtml(content)}</code></pre>`;
    }

    formatMarkdown(content) {
        return `<pre class="text-content"><code class="language-markdown">${this.escapeHtml(content)}</code></pre>`;
    }

    formatPlainText(content) {
        return `<pre class="text-content">${this.escapeHtml(content)}</pre>`;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Auto-register when script loads
if (typeof extensionRegistry !== 'undefined') {
    extensionRegistry.register(new DefaultTextExtension());
    console.log('Default Text Extension registered');
}
