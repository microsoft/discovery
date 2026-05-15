/**
 * 3DMol Molecular Viewer Extension
 * Provides 3D visualization of PDB, CIF, MOL molecular structure files using 3DMol.js
 */
class ThreeDMolExtension extends BaseExtension {
    constructor() {
        super('3DMol Molecular Viewer', ['.pdb', '.cif', '.mol', '.sdf', '.mol2'], {
            hasPreview: true,
            hasFullView: true,
            interactive: true,
            resizable: true
        });
        
        this.threeDMol = null;
        this.viewers = new Map();
    }

    getExtensionFolder() {
        return 'extensions/3dmol-viewer';
    }

    async initialize() {
        // Load 3DMol.js if not already loaded
        if (typeof $3Dmol === 'undefined') {
            await this.load3DMol();
        }
        this.threeDMol = $3Dmol;
        await super.initialize();
        return true;
    }

    async load3DMol() {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/3dmol@latest/build/3Dmol-min.js';
            script.onload = () => {
                console.log('3DMol.js loaded successfully');
                resolve();
            };
            script.onerror = () => {
                console.error('Failed to load 3DMol.js');
                reject(new Error('Failed to load 3DMol.js'));
            };
            document.head.appendChild(script);
        });
    }    async canHandle(filename, content) {
        const extension = filename.split('.').pop().toLowerCase();
        return this.supportedTypes.includes(`.${extension}`) && content.trim().length > 0;
    }

    async renderPreview(container, filename, content, options = {}) {
        const width = options.width || 300;
        const height = options.height || 200;
          try {
            const viewer = this.create3DMolViewer(container, content, filename, {
                width,
                height,
                interactive: false,
                style: 'stick',
                background: '#f8f9fa',
                mode: 'preview'
            });
            
            this.viewers.set(container, viewer);
            
            // Add simplified control panel for preview
            this.addPreviewControls(container, viewer);
            
            return { success: true };
        } catch (error) {
            this.createErrorDisplay(`Failed to render molecule: ${error.message}`, container);
            return { success: false, error: error.message };
        }
    }

    async renderFullView(container, filename, content, options = {}) {
        const width = options.width || 800;
        const height = options.height || 600;
        
        try {            const viewer = this.create3DMolViewer(container, content, filename, {
                width,
                height,
                interactive: true,
                style: 'stick',
                background: '#ffffff',
                mode: 'fullview'
            });
            
            this.viewers.set(container, viewer);
            
            // Add control panel for full view
            this.addControlPanel(container, viewer);
            
            return { success: true };
        } catch (error) {
            this.createErrorDisplay(`Failed to render molecule: ${error.message}`, container);
            return { success: false, error: error.message };
        }
    }

    create3DMolViewer(container, content, filename, options) {
        // Clear container
        container.innerHTML = '';
        
        // Set container to use 100% sizing for proper responsive behavior
        container.style.width = '100%';
        container.style.height = '100%';
        container.style.position = 'relative';
          // Create viewer container
        const viewerContainer = document.createElement('div');
        viewerContainer.style.width = '100%';
        viewerContainer.style.height = '100%';
        viewerContainer.style.position = 'relative';
        container.appendChild(viewerContainer);
        
        console.log(`Creating 3DMol viewer for ${filename}, mode: ${options.mode || 'default'}`);
        console.log(`Container dimensions: ${container.clientWidth}x${container.clientHeight}`);
        console.log(`Viewer container dimensions: ${viewerContainer.clientWidth}x${viewerContainer.clientHeight}`);
        
        // Initialize 3DMol viewer
        const viewer = this.threeDMol.createViewer(viewerContainer, {
            defaultcolors: this.threeDMol.elementColors.Jmol,
            backgroundColor: options.background || 'white'
        });
        
        console.log(`3DMol viewer initialized:`, viewer);
        
        // Determine file format and load accordingly
        const extension = filename.split('.').pop().toLowerCase();
        let format = this.getFileFormat(extension);        try {
            console.log(`Loading model with format: ${format}, content length: ${content.length}`);
            
            // Try to add the model with error handling for format issues
            try {
                viewer.addModel(content, format);
            } catch (formatError) {
                console.warn(`Failed to parse as ${format}, trying fallback formats:`, formatError.message);
                
                // Try common fallback formats
                const fallbackFormats = ['pdb', 'mol', 'sdf'];
                let loaded = false;
                
                for (const fallbackFormat of fallbackFormats) {
                    if (fallbackFormat !== format) {
                        try {
                            console.log(`Trying fallback format: ${fallbackFormat}`);
                            viewer.addModel(content, fallbackFormat);
                            format = fallbackFormat;
                            loaded = true;
                            console.log(`Successfully loaded with fallback format: ${fallbackFormat}`);
                            break;
                        } catch (fallbackError) {
                            console.warn(`Fallback ${fallbackFormat} also failed:`, fallbackError.message);
                        }
                    }
                }
                
                if (!loaded) {
                    throw new Error(`Unable to parse molecular file in any supported format. Original error: ${formatError.message}`);
                }
            }            // Apply default styling - always use stick as default
            this.applyMoleculeStyle(viewer, options.style || 'stick');
            
            // Center and zoom to fit - let 3DMol handle everything
            viewer.zoomTo();
            viewer.render();
            
            console.log(`3DMol viewer rendered for ${filename}`);
            console.log(`Viewer dimensions after render: ${viewerContainer.clientWidth}x${viewerContainer.clientHeight}`);
            
            // Check if viewer canvas was created
            const canvas = viewerContainer.querySelector('canvas');
            console.log(`Canvas found:`, canvas ? `${canvas.width}x${canvas.height}` : 'none');
            
            // Add resize handling
            this.setupResizeHandling(container, viewer);
            
            console.log(`3DMol viewer created successfully for ${filename}`);
            
            return {
                viewer: viewer,
                container: viewerContainer,
                filename: filename,
                format: format,
                resize: () => {
                    viewer.resize();
                    viewer.render();
                }
            };
            
        } catch (error) {
            console.error('Error creating 3DMol viewer:', error);
            throw error;
        }
    }    getFileFormat(extension) {
        const formatMap = {
            'pdb': 'pdb',
            'cif': 'cif',
            'mol': 'mol',
            'sdf': 'sdf',
            'mol2': 'mol2'
        };
        return formatMap[extension] || 'pdb';
    }applyMoleculeStyle(viewer, style) {
        console.log(`Applying 3DMol style: ${style}`);
        switch (style) {
            case 'cartoon':
                viewer.setStyle({}, {cartoon: {color: 'spectrum'}});
                break;
            case 'stick':
                viewer.setStyle({}, {stick: {radius: 0.2}});
                break;
            case 'sphere':
                viewer.setStyle({}, {sphere: {radius: 1.0}});
                break;
            case 'line':
                viewer.setStyle({}, {line: {}});
                break;
            case 'surface':
                viewer.setStyle({}, {cartoon: {color: 'spectrum'}});
                viewer.addSurface($3Dmol.SurfaceType.VDW, {opacity: 0.8, color: 'white'});
                break;
            default:
                viewer.setStyle({}, {cartoon: {color: 'spectrum'}});
        }
        console.log(`3DMol style ${style} applied`);
    }

    setupResizeHandling(container, viewer) {
        if (window.ResizeObserver) {
            const resizeObserver = new ResizeObserver(entries => {
                for (let entry of entries) {
                    const { width, height } = entry.contentRect;
                    if (width > 0 && height > 0) {
                        viewer.resize();
                        viewer.render();
                        console.log(`3DMol viewer resized to ${width}x${height}`);
                    }
                }
            });
            resizeObserver.observe(container);
            
            // Store observer for cleanup
            viewer._resizeObserver = resizeObserver;        }
    }

    addPreviewControls(container, viewerData) {
        const controlPanel = document.createElement('div');
        controlPanel.className = 'threeDmol-preview-controls';
        controlPanel.innerHTML = `
            <div class="preview-radio-group">
                <label class="preview-radio-label">
                    <input type="radio" name="preview-style-${Date.now()}" value="stick" checked>
                    <span>Stick</span>
                </label>
                <label class="preview-radio-label">
                    <input type="radio" name="preview-style-${Date.now()}" value="cartoon">
                    <span>Cartoon</span>
                </label>
            </div>
        `;
        
        container.appendChild(controlPanel);
        
        // Add event listeners for radio buttons
        const radioButtons = controlPanel.querySelectorAll('input[type="radio"]');
        radioButtons.forEach(radio => {
            radio.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.applyMoleculeStyle(viewerData.viewer, e.target.value);
                    viewerData.viewer.render();
                    console.log(`Preview style changed to: ${e.target.value}`);
                }
            });
        });
    }

    addControlPanel(container, viewerData) {
        const controlPanel = document.createElement('div');
        controlPanel.className = 'threeDmol-controls';
        controlPanel.innerHTML = `
            <div class="control-group">
                <label>Representation:</label>
                <div class="radio-group">
                    <label class="radio-label">
                        <input type="radio" name="style-${Date.now()}" value="stick" checked>
                        <span>Stick</span>
                    </label>
                    <label class="radio-label">
                        <input type="radio" name="style-${Date.now()}" value="cartoon">
                        <span>Cartoon</span>
                    </label>
                    <label class="radio-label">
                        <input type="radio" name="style-${Date.now()}" value="sphere">
                        <span>Sphere</span>
                    </label>
                    <label class="radio-label">
                        <input type="radio" name="style-${Date.now()}" value="line">
                        <span>Line</span>
                    </label>
                </div>
            </div>
            <div class="control-group">
                <button id="reset-view">Reset View</button>
                <button id="center-molecule">Center</button>
            </div>
        `;
        
        container.appendChild(controlPanel);
        
        // Add event listeners for radio buttons
        const radioButtons = controlPanel.querySelectorAll('input[type="radio"]');
        radioButtons.forEach(radio => {
            radio.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.applyMoleculeStyle(viewerData.viewer, e.target.value);
                    viewerData.viewer.render();
                    console.log(`Style changed to: ${e.target.value}`);
                }
            });
        });
        
        const resetButton = controlPanel.querySelector('#reset-view');
        resetButton.addEventListener('click', () => {
            viewerData.viewer.zoomTo();
            viewerData.viewer.render();
        });
        
        const centerButton = controlPanel.querySelector('#center-molecule');
        centerButton.addEventListener('click', () => {
            viewerData.viewer.center();
            viewerData.viewer.render();
        });
    }

    onResize(width, height) {
        // Individual viewers handle their own resizing via ResizeObserver
        console.log(`3DMol Extension onResize called with ${width}x${height} - individual viewers handle their own sizing`);
    }    async cleanup() {
        // Global cleanup - only dispose of viewers that haven't been individually cleaned up
        // The extension manager handles per-container cleanup, so this is only for final cleanup
        console.log(`3DMol Extension global cleanup - cleaning up ${this.viewers.size} remaining viewers`);
        
        this.viewers.forEach(viewerData => {
            if (viewerData.viewer) {
                if (viewerData.viewer._resizeObserver) {
                    viewerData.viewer._resizeObserver.disconnect();
                }
                // 3DMol cleanup
                viewerData.viewer.clear();
            }
        });
        this.viewers.clear();
        await super.cleanup();
    }    createErrorDisplay(message, container) {
        container.innerHTML = `
            <div class="extension-error">
                <div class="error-icon">⚠️</div>
                <div class="error-message">3DMol Viewer Error</div>
                <div class="error-details">${message}</div>
                <div class="error-suggestion">
                    This may be due to:
                    <ul>
                        <li>Unsupported or corrupted molecular file format</li>
                        <li>Invalid molecular structure data</li>
                        <li>3DMol.js library parsing limitations</li>
                    </ul>
                    Try converting the file to PDB format if possible.
                </div>
            </div>
        `;
    }
}

// Auto-register when script loads
if (typeof extensionRegistry !== 'undefined') {
    extensionRegistry.register(new ThreeDMolExtension());
    console.log('3DMol Molecular Viewer Extension registered');
}
