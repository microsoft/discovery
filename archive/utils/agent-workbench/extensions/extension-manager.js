/**
 * Extension Manager handles the rendering and lifecycle of file extensions
 */
class ExtensionManager {
    constructor() {
        this.activeExtensions = new Map();
        this.fullViewModal = null;
        this.currentFullViewExtension = null;
    }

    /**
     * Render a file using the appropriate extension
     */    async renderFile(container, filename, content, mode = 'preview', options = {}) {
        try {
            const extension = await extensionRegistry.findExtension(filename, content);
            
            if (!extension) {
                return this.renderFallback(container, filename, content, mode);
            }

            console.log(`Rendering ${filename} with ${extension.name} in ${mode} mode`);

            // Calculate container dimensions dynamically
            const containerRect = container.getBoundingClientRect();
            const width = options.width || containerRect.width || container.clientWidth || 300;
            const height = options.height || containerRect.height || container.clientHeight || 200;

            const renderOptions = {
                mode,
                width: Math.max(width, 200), // Minimum width
                height: Math.max(height, 150), // Minimum height
                interactive: extension.capabilities.interactive && mode === 'preview',
                fullInteractive: extension.capabilities.interactive && mode === 'full',
                theme: options.theme || 'light',
                filePath: filename,
                container: container,
                ...options
            };

            let result;
            if (mode === 'preview') {
                result = await extension.renderPreview(container, filename, content, renderOptions);
            } else {
                result = await extension.renderFullView(container, filename, content, renderOptions);
            }

            this.activeExtensions.set(container, {
                extension,
                filename,
                content,
                mode,
                options: renderOptions
            });

            // Set up resize observer for dynamic resizing
            if (extension.capabilities.resizable) {
                this.setupResizeObserver(container, extension);
            }

            return {
                success: true,
                extension: extension.name,
                capabilities: extension.capabilities,
                iconPath: extension.iconPath
            };

        } catch (error) {
            console.error(`Error rendering file ${filename}:`, error);
            return this.renderError(container, filename, error.message);
        }
    }

    /**
     * Show file in full view modal
     * @param {string} filename - The file name
     * @param {string} content - The file content
     * @param {Object} options - Options including source ('inputs' or 'outputs')
     */
    async showFullView(filename, content, options = {}) {
        try {
            if (this.fullViewModal) {
                this.closeFullView();
            }

            // Store source for extensions that need to re-fetch files
            this._currentFileSource = options.source || 'outputs';

            this.createFullViewModal();
            const modalContent = this.fullViewModal.querySelector('.modal-content');
              // Set explicit dimensions on the modal content container
            // Use a larger percentage of the screen for better space utilization
            const modalWidth = Math.min(window.innerWidth * 0.95, 1400);  // Cap at 1400px like CSS max-width
            const modalHeight = Math.min(window.innerHeight * 0.85, 900); // Cap at 900px like CSS max-height
            modalContent.style.width = `${modalWidth}px`;
            modalContent.style.height = `${modalHeight}px`;
            // Remove min constraints to allow proper responsive behavior
            modalContent.style.minWidth = 'auto';
            modalContent.style.minHeight = 'auto';
            
            // Show the modal first so container has proper dimensions
            this.fullViewModal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
            
            // Wait for layout to settle and modal transition to complete
            // Increased delay to ensure modal is fully rendered
            await new Promise(resolve => setTimeout(resolve, 150));
            
            // Force a reflow to ensure all CSS has been applied
            modalContent.offsetHeight;
            
            const actualWidth = modalContent.clientWidth;
            const actualHeight = modalContent.clientHeight;

            // Use a tolerance to avoid infinite adjustment loops due to browser rounding
            const tolerance = 2; // pixels
            const widthDiff = Math.abs(actualWidth - modalWidth);
            const heightDiff = Math.abs(actualHeight - modalHeight);

            if (widthDiff > tolerance || heightDiff > tolerance) {
                console.log(`Modal content dimensions differ: set ${modalWidth}x${modalHeight}, actual ${actualWidth}x${actualHeight} (diff: ${widthDiff}x${heightDiff})`);
                // Only log significant differences, don't adjust - let CSS handle it
                // Adjusting here can cause resize observer loops
            }
            
            const result = await this.renderFile(modalContent, filename, content, 'full', {
                width: modalWidth,  // Use the intended width, not actual
                height: modalHeight, // Use the intended height, not actual
                source: options.source || 'outputs' // Pass source to extension
            });            if (result.success) {
                this.fullViewModal.querySelector('.modal-filename').textContent = filename;
                
                const extensionInfo = this.fullViewModal.querySelector('.modal-extension-info');
                extensionInfo.textContent = `Rendered by ${result.extension}`;
                
                this.currentFullViewExtension = this.activeExtensions.get(modalContent);
                
                // Force a resize event to ensure all extensions update to full size
                // This is particularly important for canvas-based extensions
                const activeExtension = this.activeExtensions.get(modalContent);
                if (activeExtension && activeExtension.extension.onResize) {
                    try {
                        await activeExtension.extension.onResize(modalWidth, modalHeight);
                        console.log(`Triggered resize for ${activeExtension.extension.name} to ${modalWidth}x${modalHeight}`);
                    } catch (resizeError) {
                        console.warn(`Resize failed for ${activeExtension.extension.name}:`, resizeError);
                    }
                }
            } else {
                this.closeFullView();
            }

            return result;

        } catch (error) {
            console.error(`Error showing full view for ${filename}:`, error);
            this.closeFullView();
            return { success: false, error: error.message };
        }
    }    /**
     * Close full view modal
     */
    closeFullView() {
        if (this.fullViewModal) {
            this.fullViewModal.style.display = 'none';
            document.body.style.overflow = '';
            
            const modalContent = this.fullViewModal.querySelector('.modal-content');
            if (this.activeExtensions.has(modalContent)) {
                // Use per-container cleanup instead of global cleanup
                this.cleanupContainer(modalContent);
            }
            
            this.currentFullViewExtension = null;
        }
    }

    /**
     * Show full view modal with loading state immediately (for large trajectory files)
     */
    async showFullViewWithLoading(filename) {
        try {
            if (this.fullViewModal) {
                this.closeFullView();
            }

            this.createFullViewModal();
            const modalContent = this.fullViewModal.querySelector('.modal-content');
            
            // Show loading state
            modalContent.innerHTML = `
                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; padding: 40px;">
                    <div class="spinner" style="border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 60px; height: 60px; animation: spin 1s linear infinite; margin-bottom: 20px;"></div>
                    <h3 style="margin: 0 0 10px 0; color: #333;">Loading ${filename}</h3>
                    <p style="margin: 0; color: #666;">Parsing trajectory data, this may take a moment for large files...</p>
                </div>
                <style>
                    @keyframes spin {
                        0% { transform: rotate(0deg); }
                        100% { transform: rotate(360deg); }
                    }
                </style>
            `;
            
            // Show the modal
            this.fullViewModal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
            
            // Update modal filename
            this.fullViewModal.querySelector('.modal-filename').textContent = filename;
            this.fullViewModal.querySelector('.modal-extension-info').textContent = 'Loading...';
            
            return { success: true };
        } catch (error) {
            console.error(`Error showing loading modal for ${filename}:`, error);
            return { success: false, error: error.message };
        }
    }

    /**
     * Update loading modal with actual content (called after data is fetched)
     */
    async updateLoadingModal(filename, content) {
        try {
            if (!this.fullViewModal || this.fullViewModal.style.display !== 'flex') {
                // Modal not open, fall back to normal showFullView
                return this.showFullView(filename, content);
            }

            const modalContent = this.fullViewModal.querySelector('.modal-content');
            
            // Clear loading state
            modalContent.innerHTML = '';
            
            // Set explicit dimensions on the modal content container
            const modalWidth = Math.min(window.innerWidth * 0.95, 1400);
            const modalHeight = Math.min(window.innerHeight * 0.85, 900);
            modalContent.style.width = `${modalWidth}px`;
            modalContent.style.height = `${modalHeight}px`;
            modalContent.style.minWidth = 'auto';
            modalContent.style.minHeight = 'auto';
            
            // Wait for layout to settle
            await new Promise(resolve => setTimeout(resolve, 50));
            
            // Render the actual content
            const result = await this.renderFile(modalContent, filename, content, 'full', {
                width: modalWidth,
                height: modalHeight
            });
            
            if (result.success) {
                this.fullViewModal.querySelector('.modal-filename').textContent = filename;
                
                const extensionInfo = this.fullViewModal.querySelector('.modal-extension-info');
                extensionInfo.textContent = `Rendered by ${result.extension}`;
                
                this.currentFullViewExtension = this.activeExtensions.get(modalContent);
                
                // Force a resize event
                const activeExtension = this.activeExtensions.get(modalContent);
                if (activeExtension && activeExtension.extension.onResize) {
                    try {
                        await activeExtension.extension.onResize(modalWidth, modalHeight);
                        console.log(`Triggered resize for ${activeExtension.extension.name} to ${modalWidth}x${modalHeight}`);
                    } catch (resizeError) {
                        console.warn(`Resize failed for ${activeExtension.extension.name}:`, resizeError);
                    }
                }
            } else {
                this.closeFullView();
            }

            return result;
        } catch (error) {
            console.error(`Error updating loading modal for ${filename}:`, error);
            this.closeFullView();
            return { success: false, error: error.message };
        }
    }

    /**
     * Create full view modal DOM structure
     */
    createFullViewModal() {
        if (this.fullViewModal) {
            return;
        }

        this.fullViewModal = document.createElement('div');
        this.fullViewModal.className = 'extension-modal';
        this.fullViewModal.innerHTML = `
            <div class="modal-overlay" onclick="extensionManager.closeFullView()"></div>
            <div class="modal-container">
                <div class="modal-header">
                    <div class="modal-title">
                        <span class="modal-filename"></span>
                        <span class="modal-extension-info"></span>
                    </div>
                    <div class="modal-controls">
                        <button class="modal-btn" onclick="extensionManager.closeFullView()" title="Close">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                        </button>
                    </div>
                </div>
                <div class="modal-content"></div>
            </div>
        `;

        document.body.appendChild(this.fullViewModal);

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.fullViewModal.style.display === 'flex') {
                this.closeFullView();
            }
        });
    }

    /**
     * Handle container resize for active extensions
     */
    handleResize(container, width, height) {
        const extensionInfo = this.activeExtensions.get(container);
        if (extensionInfo && extensionInfo.extension.capabilities.resizable) {
            extensionInfo.extension.onResize(width, height);
        }
    }

    /**
     * Check if a file can be handled by any extension
     */
    async canHandle(filename, content) {
        const extension = await extensionRegistry.findExtension(filename, content);
        return extension !== null;
    }

    /**
     * Get extension info for a file
     */
    async getExtensionInfo(filename, content) {
        const extension = await extensionRegistry.findExtension(filename, content);
        return extension ? extension.getMetadata() : null;
    }

    /**
     * Render fallback view for unsupported files
     */
    renderFallback(container, filename, content, mode) {
        const extension = filename.split('.').pop().toLowerCase();
        
        if (['txt', 'log', 'out', 'xyz', 'pdb', 'mol', 'sdf', 'dat', 'inp', 'cfg'].includes(extension)) {
            container.innerHTML = `<pre class="fallback-text">${content}</pre>`;
        } else {
            const lines = content.split('\n');
            const preview = lines.length > 50 ? 
                lines.slice(0, 50).join('\n') + '\n\n... (truncated, download file to see full content)' : 
                content;
            container.innerHTML = `<pre class="fallback-text">${preview}</pre>`;
        }

        return {
            success: true,
            extension: 'fallback',
            capabilities: { hasPreview: true, hasFullView: false, interactive: false }
        };
    }

    /**
     * Render error display
     */
    renderError(container, filename, errorMessage) {
        container.innerHTML = `
            <div class="extension-error">
                <div class="error-icon">⚠️</div>
                <div class="error-message">Failed to render ${filename}</div>
                <div class="error-details">${errorMessage}</div>
            </div>
        `;

        return {
            success: false,
            error: errorMessage,
            extension: 'error'
        };
    }

    /**
     * Cleanup all active extensions
     */    async cleanup() {
        console.log('Cleaning up extension manager...');

        for (const [container, extensionInfo] of this.activeExtensions) {
            try {
                // Cleanup resize observer
                if (extensionInfo.resizeObserver) {
                    extensionInfo.resizeObserver.disconnect();
                }

                // Cleanup resize timeout
                if (extensionInfo.resizeTimeout) {
                    clearTimeout(extensionInfo.resizeTimeout);
                }

                // Cleanup extension
                await extensionInfo.extension.cleanup();
            } catch (error) {
                console.warn(`Error cleaning up extension ${extensionInfo.extension.name}:`, error);
            }
        }
        
        this.activeExtensions.clear();
        this.closeFullView();
        
        if (this.fullViewModal) {
            document.body.removeChild(this.fullViewModal);
            this.fullViewModal = null;
        }
    }

    /**
     * Cleanup extension for a specific container
     */
    async cleanupContainer(container) {
        const extensionInfo = this.activeExtensions.get(container);
        if (extensionInfo) {
            try {
                console.log(`Cleaning up extension for container: ${extensionInfo.extension.name}`);

                // Cleanup resize observer
                if (extensionInfo.resizeObserver) {
                    extensionInfo.resizeObserver.disconnect();
                }

                // Cleanup resize timeout
                if (extensionInfo.resizeTimeout) {
                    clearTimeout(extensionInfo.resizeTimeout);
                }                // For XYZ extension, remove the specific renderer
                if (extensionInfo.extension.renderers && extensionInfo.extension.renderers.has(container)) {
                    const renderer = extensionInfo.extension.renderers.get(container);
                    
                    // Stop animation loop
                    if (renderer.stopAnimation) {
                        renderer.stopAnimation();
                    }
                    
                    // Dispose of Three.js resources
                    if (renderer.renderer) {
                        renderer.renderer.dispose();
                    }
                    if (renderer.scene) {
                        renderer.scene.children.forEach(child => {
                            if (child.geometry) child.geometry.dispose();
                            if (child.material) child.material.dispose();
                        });
                    }
                    extensionInfo.extension.renderers.delete(container);
                }                // For 3DMol extension, remove the specific viewer
                if (extensionInfo.extension.viewers && extensionInfo.extension.viewers.has(container)) {
                    const viewerData = extensionInfo.extension.viewers.get(container);
                    console.log(`3DMol: Cleaning up specific container viewer for ${viewerData.filename || 'unknown'}`);
                    
                    // Disconnect resize observer if present
                    if (viewerData.viewer && viewerData.viewer._resizeObserver) {
                        viewerData.viewer._resizeObserver.disconnect();
                    }
                    
                    // Cleanup 3DMol viewer
                    if (viewerData.viewer) {
                        viewerData.viewer.clear();
                    }
                    
                    extensionInfo.extension.viewers.delete(container);
                    console.log(`3DMol: Container cleaned up. Remaining viewers: ${extensionInfo.extension.viewers.size}`);
                }
                
                // For Image extension, remove the specific viewer
                if (extensionInfo.extension.viewers && extensionInfo.extension.viewers.has(container)) {
                    const viewerData = extensionInfo.extension.viewers.get(container);
                    console.log(`Image: Cleaning up specific container viewer for ${viewerData.filename || 'unknown'}`);
                    
                    // Revoke blob URLs to prevent memory leaks
                    if (viewerData.originalUrl && viewerData.originalUrl.startsWith('blob:')) {
                        URL.revokeObjectURL(viewerData.originalUrl);
                    }
                    
                    extensionInfo.extension.viewers.delete(container);
                    console.log(`Image: Container cleaned up. Remaining viewers: ${extensionInfo.extension.viewers.size}`);
                }
                  // Clear container content to force reload on reopen
                console.log(`Clearing container content for ${extensionInfo.extension.name}`);
                container.innerHTML = '';
                
                // Remove from active extensions
                this.activeExtensions.delete(container);
                
            } catch (error) {
                console.warn(`Error cleaning up container for extension ${extensionInfo.extension.name}:`, error);
            }
        }
    }

    setupResizeObserver(container, extension) {
        // Set up ResizeObserver for dynamic container resizing
        if (typeof ResizeObserver !== 'undefined') {
            let resizeTimeout;
            let lastWidth = 0;
            let lastHeight = 0;
            const tolerance = 2; // Ignore size changes smaller than this

            const resizeObserver = new ResizeObserver(entries => {
                for (const entry of entries) {
                    const { width, height } = entry.contentRect;

                    // Ignore invalid sizes
                    if (width <= 0 || height <= 0) continue;

                    // Ignore tiny changes that are likely due to rounding
                    const widthDiff = Math.abs(width - lastWidth);
                    const heightDiff = Math.abs(height - lastHeight);
                    if (widthDiff < tolerance && heightDiff < tolerance) continue;

                    // Debounce resize calls to avoid rapid firing
                    clearTimeout(resizeTimeout);
                    resizeTimeout = setTimeout(() => {
                        lastWidth = width;
                        lastHeight = height;
                        if (extension.onResize) {
                            extension.onResize(width, height);
                        }
                    }, 100); // Wait 100ms after last resize before calling onResize
                }
            });

            resizeObserver.observe(container);

            // Store observer and timeout for cleanup
            const extensionInfo = this.activeExtensions.get(container);
            if (extensionInfo) {
                extensionInfo.resizeObserver = resizeObserver;
                extensionInfo.resizeTimeout = resizeTimeout;
            }
        }
    }
}

// Create singleton instance
const extensionManager = new ExtensionManager();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = extensionManager;
} else if (typeof window !== 'undefined') {
    window.extensionManager = extensionManager;
}
