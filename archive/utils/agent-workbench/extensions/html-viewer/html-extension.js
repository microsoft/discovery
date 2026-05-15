/**
 * HTML Viewer Extension
 * Provides display of HTML content in a sandboxed iframe
 */
class HtmlExtension extends BaseExtension {
    constructor() {
        super('HTML Viewer', ['.html', '.htm'], {
            hasPreview: true,
            hasFullView: true,
            interactive: true,
            resizable: true
        });
        
        this.viewers = new Map();
    }

    getExtensionFolder() {
        return 'extensions/html-viewer';
    }

    async initialize() {
        await super.initialize();
        return true;
    }

    async canHandle(filename, content) {
        const extension = filename.split('.').pop().toLowerCase();
        const isHtmlFile = this.supportedTypes.includes(`.${extension}`);
        
        // Also check if content looks like HTML (even without extension)
        const looksLikeHtml = typeof content === 'string' && 
                             (content.trim().startsWith('<!DOCTYPE') || 
                              content.trim().startsWith('<html') ||
                              content.trim().startsWith('<HTML') ||
                              /<html[>\s]/i.test(content.substring(0, 100)));
        
        return isHtmlFile || looksLikeHtml;
    }

    async renderPreview(container, filename, content, options = {}) {
        const width = options.width || 400;
        const height = options.height || 300;
        
        try {
            const viewer = this.createHtmlViewer(container, filename, content, {
                width,
                height,
                mode: 'preview'
            });
            
            this.viewers.set(container, viewer);
            
            return { success: true };
        } catch (error) {
            this.createErrorDisplay(`Failed to display HTML: ${error.message}`, container);
            return { success: false, error: error.message };
        }
    }

    async renderFullView(container, filename, content, options = {}) {
        try {
            const viewer = this.createHtmlViewer(container, filename, content, {
                width: '100%',
                height: options.height || 600,
                mode: 'full'
            });
            
            this.viewers.set(container, viewer);
            
            return { success: true };
        } catch (error) {
            this.createErrorDisplay(`Failed to display HTML: ${error.message}`, container);
            return { success: false, error: error.message };
        }
    }

    createHtmlViewer(container, filename, content, options) {
        const { width, height, mode } = options;
        
        // Clear container
        container.innerHTML = '';
        container.style.width = typeof width === 'number' ? `${width}px` : width;
        container.style.height = typeof height === 'number' ? `${height}px` : height;
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
        container.style.gap = '10px';
        
        // Create header with filename and controls
        const header = document.createElement('div');
        header.className = 'html-viewer-header';
        header.style.display = 'flex';
        header.style.justifyContent = 'space-between';
        header.style.alignItems = 'center';
        header.style.padding = '8px 12px';
        header.style.background = '#f8f9fa';
        header.style.borderRadius = '4px';
        header.style.fontSize = '12px';
        header.style.color = '#495057';
        
        const filenameSpan = document.createElement('span');
        filenameSpan.textContent = filename;
        filenameSpan.style.fontWeight = '500';
        
        const controls = document.createElement('div');
        controls.style.display = 'flex';
        controls.style.gap = '8px';
        
        // Add refresh button
        const refreshBtn = document.createElement('button');
        refreshBtn.innerHTML = '🔄';
        refreshBtn.title = 'Reload HTML';
        refreshBtn.style.padding = '4px 8px';
        refreshBtn.style.border = '1px solid #ced4da';
        refreshBtn.style.borderRadius = '4px';
        refreshBtn.style.background = 'white';
        refreshBtn.style.cursor = 'pointer';
        refreshBtn.onclick = () => this.refreshViewer(container, filename, content, options);
        
        // Add open in new window button
        const newWindowBtn = document.createElement('button');
        newWindowBtn.innerHTML = '🗗';
        newWindowBtn.title = 'Open in new window';
        newWindowBtn.style.padding = '4px 8px';
        newWindowBtn.style.border = '1px solid #ced4da';
        newWindowBtn.style.borderRadius = '4px';
        newWindowBtn.style.background = 'white';
        newWindowBtn.style.cursor = 'pointer';
        newWindowBtn.onclick = () => this.openInNewWindow(content);
        
        controls.appendChild(refreshBtn);
        controls.appendChild(newWindowBtn);
        
        header.appendChild(filenameSpan);
        header.appendChild(controls);
        
        // Create iframe container
        const iframeContainer = document.createElement('div');
        iframeContainer.style.flex = '1';
        iframeContainer.style.border = '1px solid #dee2e6';
        iframeContainer.style.borderRadius = '4px';
        iframeContainer.style.overflow = 'hidden';
        iframeContainer.style.background = 'white';
        iframeContainer.style.position = 'relative';
        
        // Create sandboxed iframe
        const iframe = document.createElement('iframe');
        iframe.style.width = '100%';
        iframe.style.height = '100%';
        iframe.style.border = 'none';
        iframe.style.display = 'block';
        
        // Sandbox attributes for security while allowing scripts
        // Remove 'allow-same-origin' to truly sandbox (but this prevents some features)
        iframe.sandbox = 'allow-scripts allow-forms allow-modals allow-popups';
        
        // Set the HTML content
        // Use srcdoc for better security (content is treated as separate origin)
        iframe.srcdoc = content;
        
        iframeContainer.appendChild(iframe);
        
        container.appendChild(header);
        container.appendChild(iframeContainer);
        
        return {
            container,
            iframe,
            header,
            controls
        };
    }

    refreshViewer(container, filename, content, options) {
        const viewer = this.viewers.get(container);
        if (viewer && viewer.iframe) {
            // Reload by setting srcdoc again
            viewer.iframe.srcdoc = content;
        }
    }

    openInNewWindow(content) {
        const newWindow = window.open('', '_blank', 'width=800,height=600');
        if (newWindow) {
            newWindow.document.write(content);
            newWindow.document.close();
        } else {
            alert('Pop-up blocked. Please allow pop-ups for this site.');
        }
    }

    createErrorDisplay(message, container) {
        container.innerHTML = '';
        container.style.display = 'flex';
        container.style.alignItems = 'center';
        container.style.justifyContent = 'center';
        container.style.padding = '20px';
        container.style.color = '#dc3545';
        container.style.textAlign = 'center';
        
        const errorDiv = document.createElement('div');
        errorDiv.innerHTML = `
            <div style="font-size: 48px; margin-bottom: 10px;">⚠️</div>
            <div style="font-weight: 500; margin-bottom: 5px;">HTML Viewer Error</div>
            <div style="font-size: 12px; color: #6c757d;">${message}</div>
        `;
        
        container.appendChild(errorDiv);
    }

    getMenuItems(filename, content) {
        return [
            {
                label: 'Open in New Window',
                icon: '🗗',
                action: () => this.openInNewWindow(content)
            },
            {
                label: 'View Source',
                icon: '📄',
                action: () => this.viewSource(content)
            }
        ];
    }

    viewSource(content) {
        // Create a modal or new window to show HTML source
        const sourceWindow = window.open('', '_blank', 'width=800,height=600');
        if (sourceWindow) {
            sourceWindow.document.write(`
                <!DOCTYPE html>
                <html>
                <head>
                    <title>HTML Source</title>
                    <style>
                        body { 
                            margin: 0; 
                            padding: 20px; 
                            font-family: 'Courier New', monospace; 
                            background: #f8f9fa;
                        }
                        pre { 
                            background: white; 
                            padding: 20px; 
                            border-radius: 4px; 
                            border: 1px solid #dee2e6;
                            overflow: auto;
                            font-size: 12px;
                            line-height: 1.5;
                        }
                        code {
                            color: #e83e8c;
                        }
                    </style>
                </head>
                <body>
                    <h2>HTML Source Code</h2>
                    <pre><code>${this.escapeHtml(content)}</code></pre>
                </body>
                </html>
            `);
            sourceWindow.document.close();
        } else {
            alert('Pop-up blocked. Please allow pop-ups for this site.');
        }
    }

    escapeHtml(html) {
        const div = document.createElement('div');
        div.textContent = html;
        return div.innerHTML;
    }

    async cleanup() {
        this.viewers.clear();
        await super.cleanup();
    }
}

// Register the extension
if (typeof extensionRegistry !== 'undefined') {
    extensionRegistry.register(new HtmlExtension());
}
