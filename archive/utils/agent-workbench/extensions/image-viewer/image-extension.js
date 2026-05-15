/**
 * Image Viewer Extension
 * Provides display of images (PNG, JPEG, GIF, SVG) with zoom and pan controls
 */
class ImageExtension extends BaseExtension {    constructor() {
        super('Image Viewer', ['.png', '.jpg', '.jpeg', '.gif', '.svg'], {
            hasPreview: true,
            hasFullView: true,
            interactive: false,
            resizable: true
        });
        
        this.viewers = new Map();
    }

    getExtensionFolder() {
        return 'extensions/image-viewer';
    }

    async initialize() {
        await super.initialize();
        return true;
    }

    async canHandle(filename, content) {
        const extension = filename.split('.').pop().toLowerCase();
        return this.supportedTypes.includes(`.${extension}`);
    }

    async renderPreview(container, filename, content, options = {}) {
        const width = options.width || 300;
        const height = options.height || 200;
        
        try {
            const viewer = this.createImageViewer(container, filename, content, {
                width,
                height,
                mode: 'preview',
                interactive: false
            });
            
            this.viewers.set(container, viewer);
            
            return { success: true };
        } catch (error) {
            this.createErrorDisplay(`Failed to display image: ${error.message}`, container);
            return { success: false, error: error.message };
        }
    }

    async renderFullView(container, filename, content, options = {}) {
        const width = options.width || 800;
        const height = options.height || 600;
        
        try {
            const viewer = this.createImageViewer(container, filename, content, {
                width,
                height,
                mode: 'fullview',
                interactive: true
            });
            
            this.viewers.set(container, viewer);
            
            // Add control panel for full view
            this.addControlPanel(container, viewer);
            
            return { success: true };
        } catch (error) {
            this.createErrorDisplay(`Failed to display image: ${error.message}`, container);
            return { success: false, error: error.message };
        }
    }

    createImageViewer(container, filename, content, options) {
        // Clear container
        container.innerHTML = '';
        
        // Set container styling
        container.style.width = '100%';
        container.style.height = '100%';
        container.style.position = 'relative';
        container.style.overflow = 'hidden';
        container.style.background = '#f8f9fa';
        
        console.log(`Creating image viewer for ${filename}, mode: ${options.mode || 'default'}`);
        
        // Create image container
        const imageContainer = document.createElement('div');
        imageContainer.className = 'image-container';
        imageContainer.style.width = '100%';
        imageContainer.style.height = '100%';
        imageContainer.style.display = 'flex';
        imageContainer.style.alignItems = 'center';
        imageContainer.style.justifyContent = 'center';
        imageContainer.style.position = 'relative';
        imageContainer.style.overflow = 'hidden';
        
        // Create image element
        const img = document.createElement('img');
        img.style.maxWidth = '100%';
        img.style.maxHeight = '100%';
        img.style.objectFit = 'contain';
        img.style.transition = 'transform 0.3s ease';
        img.style.cursor = options.interactive ? 'grab' : 'default';        // Determine if content is base64 or raw
        const extension = filename.split('.').pop().toLowerCase();
        const mimeType = this.getMimeType(extension);
        
        let imageUrl;
        if (extension === 'svg') {
            // For SVG, create blob URL from text content (might be URL-encoded)
            let svgContent = content;
            try {
                // Try to decode if it looks like URL-encoded content
                if (content.includes('%3C') || content.includes('%3E')) {
                    svgContent = decodeURIComponent(content);
                }
            } catch (e) {
                console.warn('Failed to decode SVG content, using as-is');
            }
            const blob = new Blob([svgContent], { type: 'image/svg+xml' });
            imageUrl = URL.createObjectURL(blob);
        } else {
            // For binary images, check if it's valid base64 first
            if (this.isBase64(content)) {
                imageUrl = `data:${mimeType};base64,${content}`;
            } else {
                // If not base64, use the unified file API endpoint with raw=true
                // This avoids corruption of binary data through text processing
                const params = new URLSearchParams();
                params.set('source', 'outputs');
                params.set('raw', 'true');
                if (window.discoveryAgent?.currentSessionId) {
                    params.set('session_id', window.discoveryAgent.currentSessionId);
                }
                if (window.discoveryAgent?.getCurrentAgentName) {
                    const agentName = window.discoveryAgent.getCurrentAgentName();
                    if (agentName) params.set('agent_name', agentName);
                }
                imageUrl = `/api/file/${filename}?${params.toString()}`;
            }
        }
        
        img.src = imageUrl;
        img.alt = filename;
        
        // Add loading and error handling
        img.onload = () => {
            console.log(`Image loaded successfully: ${filename}`);
            this.setupImageInteraction(img, imageContainer, options);
        };
        
        img.onerror = () => {
            console.error(`Failed to load image: ${filename}`);
            this.createErrorDisplay(`Failed to load image: ${filename}`, container);
        };
        
        imageContainer.appendChild(img);
        container.appendChild(imageContainer);
        
        // Create viewer data object
        const viewerData = {
            container: imageContainer,
            image: img,
            filename: filename,
            mode: options.mode,
            scale: 1,
            translateX: 0,
            translateY: 0,
            originalUrl: imageUrl
        };
        
        console.log(`Image viewer created successfully for ${filename}`);
        
        return viewerData;
    }

    getMimeType(extension) {
        const mimeMap = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'svg': 'image/svg+xml'
        };
        return mimeMap[extension] || 'image/png';
    }    isBase64(str) {
        try {
            // Check if string is valid base64
            if (!str || typeof str !== 'string') return false;
            
            // Remove any whitespace
            const cleaned = str.replace(/\s/g, '');
            
            // Check if it matches base64 pattern
            const base64Pattern = /^[A-Za-z0-9+/]*={0,2}$/;
            if (!base64Pattern.test(cleaned)) return false;
            
            // Check if length is valid (must be multiple of 4)
            if (cleaned.length % 4 !== 0) return false;
            
            // Try to decode and re-encode
            return btoa(atob(cleaned)) === cleaned;
        } catch (err) {
            return false;
        }
    }

    setupImageInteraction(img, container, options) {
        if (!options.interactive) return;
        
        let isDragging = false;
        let startX, startY;
        let scale = 1;
        let translateX = 0;
        let translateY = 0;
        
        // Zoom with mouse wheel
        container.addEventListener('wheel', (e) => {
            e.preventDefault();
            const rect = container.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            const newScale = Math.max(0.1, Math.min(5, scale * delta));
            
            if (newScale !== scale) {
                // Zoom relative to mouse position
                const scaleChange = newScale / scale;
                translateX = x - scaleChange * (x - translateX);
                translateY = y - scaleChange * (y - translateY);
                scale = newScale;
                
                this.updateImageTransform(img, scale, translateX, translateY);
            }
        });
        
        // Pan with mouse drag
        container.addEventListener('mousedown', (e) => {
            isDragging = true;
            startX = e.clientX - translateX;
            startY = e.clientY - translateY;
            img.style.cursor = 'grabbing';
            e.preventDefault();
        });
        
        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            
            translateX = e.clientX - startX;
            translateY = e.clientY - startY;
            
            this.updateImageTransform(img, scale, translateX, translateY);
        });
        
        document.addEventListener('mouseup', () => {
            isDragging = false;
            img.style.cursor = 'grab';
        });
        
        // Double-click to reset
        container.addEventListener('dblclick', () => {
            scale = 1;
            translateX = 0;
            translateY = 0;
            this.updateImageTransform(img, scale, translateX, translateY);
        });
        
        // Store transform state
        img._imageState = { scale, translateX, translateY };
    }

    updateImageTransform(img, scale, translateX, translateY) {
        img.style.transform = `scale(${scale}) translate(${translateX / scale}px, ${translateY / scale}px)`;
        img._imageState = { scale, translateX, translateY };
    }

    addControlPanel(container, viewerData) {
        const controlPanel = document.createElement('div');
        controlPanel.className = 'image-controls';
        controlPanel.innerHTML = `
            <div class="control-group">
                <button id="zoom-in" title="Zoom In">🔍+</button>
                <button id="zoom-out" title="Zoom Out">🔍−</button>
                <button id="zoom-fit" title="Fit to Window">📏</button>
                <button id="zoom-100" title="100% Size">1:1</button>
            </div>
            <div class="control-group">
                <button id="download-image" title="Download Image">💾</button>
            </div>
        `;
        
        container.appendChild(controlPanel);
        
        // Add event listeners
        const zoomInBtn = controlPanel.querySelector('#zoom-in');
        const zoomOutBtn = controlPanel.querySelector('#zoom-out');
        const zoomFitBtn = controlPanel.querySelector('#zoom-fit');
        const zoom100Btn = controlPanel.querySelector('#zoom-100');
        const downloadBtn = controlPanel.querySelector('#download-image');
        
        zoomInBtn.addEventListener('click', () => {
            const state = viewerData.image._imageState || { scale: 1, translateX: 0, translateY: 0 };
            const newScale = Math.min(5, state.scale * 1.2);
            this.updateImageTransform(viewerData.image, newScale, state.translateX, state.translateY);
        });
        
        zoomOutBtn.addEventListener('click', () => {
            const state = viewerData.image._imageState || { scale: 1, translateX: 0, translateY: 0 };
            const newScale = Math.max(0.1, state.scale * 0.8);
            this.updateImageTransform(viewerData.image, newScale, state.translateX, state.translateY);
        });
        
        zoomFitBtn.addEventListener('click', () => {
            this.updateImageTransform(viewerData.image, 1, 0, 0);
        });
        
        zoom100Btn.addEventListener('click', () => {
            // Calculate scale for 100% size
            const img = viewerData.image;
            const container = viewerData.container;
            const imgRect = img.getBoundingClientRect();
            const containerRect = container.getBoundingClientRect();
            
            const scaleX = img.naturalWidth / imgRect.width;
            const scaleY = img.naturalHeight / imgRect.height;
            const actualScale = Math.min(scaleX, scaleY);
            
            this.updateImageTransform(img, actualScale, 0, 0);
        });
          downloadBtn.addEventListener('click', () => {
            const link = document.createElement('a');
            const params = new URLSearchParams();
            params.set('source', 'outputs');
            params.set('download', 'true');
            if (window.discoveryAgent?.currentSessionId) {
                params.set('session_id', window.discoveryAgent.currentSessionId);
            }
            if (window.discoveryAgent?.getCurrentAgentName) {
                const agentName = window.discoveryAgent.getCurrentAgentName();
                if (agentName) params.set('agent_name', agentName);
            }
            link.href = `/api/file/${viewerData.filename}?${params.toString()}`;
            link.download = viewerData.filename;
            link.click();
        });
    }

    async cleanup() {
        console.log(`Image Extension global cleanup - cleaning up ${this.viewers.size} remaining viewers`);
        
        this.viewers.forEach(viewerData => {
            // Revoke blob URLs to prevent memory leaks
            if (viewerData.originalUrl && viewerData.originalUrl.startsWith('blob:')) {
                URL.revokeObjectURL(viewerData.originalUrl);
            }
        });
        this.viewers.clear();
        await super.cleanup();
    }

    createErrorDisplay(message, container) {
        container.innerHTML = `
            <div class="extension-error">
                <div class="error-icon">🖼️</div>
                <div class="error-message">Image Viewer Error</div>
                <div class="error-details">${message}</div>
                <div class="error-suggestion">
                    This may be due to:
                    <ul>
                        <li>Unsupported image format</li>
                        <li>Corrupted image data</li>
                        <li>Invalid base64 encoding</li>
                    </ul>
                    Supported formats: PNG, JPEG, GIF, SVG
                </div>
            </div>
        `;
    }
}

// Auto-register when script loads
if (typeof extensionRegistry !== 'undefined') {
    extensionRegistry.register(new ImageExtension());
    console.log('Image Viewer Extension registered');
}
