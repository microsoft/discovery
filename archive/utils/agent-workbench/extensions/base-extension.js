/**
 * Base class for all file viewer extensions
 * Provides the interface that all extensions must implement
 */
class BaseExtension {    constructor(name, supportedTypes, capabilities = {}) {
        this.name = name;
        this.supportedTypes = Array.isArray(supportedTypes) ? supportedTypes : [supportedTypes];
        this.capabilities = {
            hasPreview: true,
            hasFullView: true,
            interactive: false,
            resizable: true,
            ...capabilities
        };
        // Priority determines which extension handles a file when multiple match
        // Higher priority wins. Default is 0. Use negative for fallback extensions.
        // Range: -100 (lowest) to 100 (highest)
        this.priority = capabilities.priority ?? 0;
        this.initialized = false;
        this.iconPath = this.getIconPath();
    }    getIconPath() {
        // Try to find icon in extension folder, fallback to default
        const extensionFolder = this.getExtensionFolder();
        if (extensionFolder) {
            // First try SVG, then other common formats
            const iconPaths = [
                `${extensionFolder}/icon.svg`,
                `${extensionFolder}/icon.png`,
                `${extensionFolder}/icon.jpg`
            ];
            // Return the first one (SVG preferred)
            return iconPaths[0];
        }
        return 'extensions/icon.svg'; // Default icon
    }

    getExtensionFolder() {
        // Override in subclasses for specific folder paths
        return null;
    }

    /**
     * Check if this extension can handle the given file
     */
    async canHandle(filename, content) {
        const extension = '.' + filename.split('.').pop().toLowerCase();
        return this.supportedTypes.includes(extension);
    }

    /**
     * Render content in preview mode (small, inline view)
     */
    async renderPreview(container, filename, content, options = {}) {
        throw new Error(`${this.name} must implement renderPreview method`);
    }

    /**
     * Render content in full view mode (expanded, detailed view)
     */
    async renderFullView(container, filename, content, options = {}) {
        throw new Error(`${this.name} must implement renderFullView method`);
    }

    /**
     * Initialize extension resources (optional)
     */
    async initialize() {
        this.initialized = true;
        return true;
    }

    /**
     * Cleanup extension resources (optional)
     */
    async cleanup() {
        this.initialized = false;
    }

    /**
     * Get custom context menu items (optional)
     */
    getMenuItems(filename, content) {
        return [];
    }

    /**
     * Get extension metadata
     */    getMetadata() {
        return {
            name: this.name,
            supportedTypes: this.supportedTypes,
            capabilities: this.capabilities,
            initialized: this.initialized,
            iconPath: this.iconPath
        };
    }

    /**
     * Handle container resize events (optional)
     */
    onResize(width, height) {
        // Override in subclasses if needed
    }

    /**
     * Create a standard error display
     */
    createErrorDisplay(message, container) {
        container.innerHTML = `
            <div class="extension-error">
                <div class="error-icon">⚠️</div>
                <div class="error-message">${message}</div>
                <div class="error-extension">Extension: ${this.name}</div>
            </div>
        `;
    }

    /**
     * Create a loading display
     */
    createLoadingDisplay(container, message = 'Loading...') {
        container.innerHTML = `
            <div class="extension-loading">
                <div class="loading-spinner"></div>
                <div class="loading-message">${message}</div>
            </div>
        `;
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = BaseExtension;
} else if (typeof window !== 'undefined') {
    window.BaseExtension = BaseExtension;
}
