/**
 * NGL Molecular Viewer Extension
 * Provides 3D molecular visualization using NGL Viewer for additional file formats
 * Supports formats not covered by existing viewers like GRO, MMC, MMTF, etc.
 */
class NGLExtension extends BaseExtension {
    constructor() {
        // Support additional molecular formats not covered by existing viewers
        // Note: .xtc and .trr are trajectory formats handled by md-trajectory-viewer extension
        super('NGL Molecular Viewer', ['.gro', '.mmcif', '.mmtf', '.mrc', '.dcd', '.psf', '.top', '.prmtop'], {
            hasPreview: true,
            hasFullView: true,
            interactive: true,
            resizable: true
        });
        
        this.ngl = null;
        this.viewers = new Map();
    }

    getExtensionFolder() {
        return 'extensions/ngl-viewer';
    }

    async initialize() {
        // Load NGL if not already loaded
        if (typeof NGL === 'undefined') {
            await this.loadNGL();
        }
        this.ngl = NGL;
        await super.initialize();
        return true;
    }

    async loadNGL() {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/ngl@2.0.0-dev.39/dist/ngl.js';
            script.onload = () => {
                console.log('NGL.js loaded successfully');
                resolve();
            };
            script.onerror = () => {
                console.error('Failed to load NGL.js');
                reject(new Error('Failed to load NGL.js'));
            };
            document.head.appendChild(script);
        });
    }

    async canHandle(filename, content) {
        const extension = filename.split('.').pop().toLowerCase();
        return this.supportedTypes.includes(`.${extension}`) && content.trim().length > 0;
    }

    async renderPreview(container, filename, content, options = {}) {
        const width = options.width || 300;
        const height = options.height || 200;
        
        try {
            const viewer = this.createNGLViewer(container, content, filename, {
                width,
                height,
                interactive: false,
                background: '#f8f9fa',
                mode: 'preview'
            });
            
            this.viewers.set(container, viewer);
            
            return { success: true };
        } catch (error) {
            this.createErrorDisplay(`Failed to render molecule: ${error.message}`, container);
            return { success: false, error: error.message };
        }
    }

    async renderFullView(container, filename, content, options = {}) {
        const width = options.width || 800;
        const height = options.height || 600;
        
        try {
            const viewer = this.createNGLViewer(container, content, filename, {
                width,
                height,
                interactive: true,
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

    createNGLViewer(container, content, filename, options) {
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
        viewerContainer.style.backgroundColor = options.background || '#ffffff';
        container.appendChild(viewerContainer);
        
        console.log(`Creating NGL viewer for ${filename}, mode: ${options.mode || 'default'}`);
        console.log(`Container dimensions: ${container.clientWidth}x${container.clientHeight}`);
        
        try {
            // Initialize NGL stage
            const stage = new this.ngl.Stage(viewerContainer, {
                backgroundColor: options.background || 'white',
                quality: 'medium',
                sampleLevel: 1,
                impostor: true,
                workerDefault: true,
                fogNear: 50,
                fogFar: 100
            });
            
            console.log(`NGL stage initialized:`, stage);
            
            // Create blob for NGL to load the content
            const blob = new Blob([content], { type: 'text/plain' });
            const extension = filename.split('.').pop().toLowerCase();
            const ext = this.getFileExtension(extension);
            
            console.log(`Loading structure with extension: ${ext}, content length: ${content.length}`);
            
            // Load structure from blob
            stage.loadFile(blob, { ext: ext, name: filename })
                .then(component => {
                    console.log('Structure loaded successfully:', component);
                    
                    // Apply default representation based on file type
                    this.applyDefaultRepresentation(component, extension);
                    
                    // Center and auto-view
                    component.autoView();
                    stage.viewer.renderPicking = true;
                    
                    console.log(`NGL viewer rendered for ${filename}`);
                })
                .catch(error => {
                    console.error('Error loading structure:', error);
                    this.createErrorDisplay(`Failed to load structure: ${error.message}`, container);
                });
            
            // Add resize handling
            this.setupResizeHandling(container, stage);
            
            console.log(`NGL viewer created successfully for ${filename}`);
            
            return {
                stage: stage,
                container: viewerContainer,
                filename: filename,
                extension: extension,
                resize: () => {
                    stage.handleResize();
                }
            };
            
        } catch (error) {
            console.error('Error creating NGL viewer:', error);
            throw error;
        }
    }

    getFileExtension(extension) {
        // Map file extensions to NGL-compatible formats
        const formatMap = {
            'gro': 'gro',
            'mmcif': 'mmcif',
            'mmtf': 'mmtf',
            'mrc': 'mrc',
            'dcd': 'dcd',
            'xtc': 'xtc',
            'trr': 'trr',
            'psf': 'psf',
            'top': 'top',
            'prmtop': 'prmtop'
        };
        return formatMap[extension] || extension;
    }

    applyDefaultRepresentation(component, extension) {
        console.log(`Applying default representation for: ${extension}`);
        
        // Clear existing representations
        component.removeAllRepresentations();
        
        // Apply appropriate representation based on file type
        switch (extension) {
            case 'gro':
            case 'psf':
            case 'top':
            case 'prmtop':
                // For topology/coordinate files, use simple ball+stick
                component.addRepresentation('ball+stick', {
                    radius: 0.3,
                    scale: 0.7,
                    aspectRatio: 1.5
                });
                break;
            case 'mmcif':
            case 'mmtf':
                // For protein structures, use cartoon + sidechains
                component.addRepresentation('cartoon', {
                    colorScheme: 'chainid'
                });
                component.addRepresentation('ball+stick', {
                    sele: 'hetero',
                    radius: 0.3
                });
                break;
            case 'mrc':
                // For density maps, use surface
                component.addRepresentation('surface', {
                    opacity: 0.6,
                    isolevelType: 'sigma',
                    isolevel: 1.0,
                    smooth: 1
                });
                break;
            case 'dcd':
            case 'xtc':
            case 'trr':
                // For trajectory files, use simple representation
                component.addRepresentation('ball+stick', {
                    radius: 0.2,
                    scale: 0.5
                });
                break;
            default:
                // Default to ball+stick
                component.addRepresentation('ball+stick', {
                    radius: 0.3,
                    scale: 0.7
                });
        }
        
        console.log(`NGL representation applied for ${extension}`);
    }

    setupResizeHandling(container, stage) {
        if (window.ResizeObserver) {
            const resizeObserver = new ResizeObserver(entries => {
                for (let entry of entries) {
                    const { width, height } = entry.contentRect;
                    if (width > 0 && height > 0) {
                        stage.handleResize();
                        console.log(`NGL viewer resized to ${width}x${height}`);
                    }
                }
            });
            resizeObserver.observe(container);
            
            // Store observer for cleanup
            stage._resizeObserver = resizeObserver;
        }
    }

    addControlPanel(container, viewerData) {
        const controlPanel = document.createElement('div');
        controlPanel.className = 'ngl-controls';
        controlPanel.innerHTML = `
            <div class="control-group">
                <label>Representation:</label>
                <div class="radio-group">
                    <label class="radio-label">
                        <input type="radio" name="style-${Date.now()}" value="ball+stick" checked>
                        <span>Ball & Stick</span>
                    </label>
                    <label class="radio-label">
                        <input type="radio" name="style-${Date.now()}" value="cartoon">
                        <span>Cartoon</span>
                    </label>
                    <label class="radio-label">
                        <input type="radio" name="style-${Date.now()}" value="spacefill">
                        <span>Spacefill</span>
                    </label>
                    <label class="radio-label">
                        <input type="radio" name="style-${Date.now()}" value="surface">
                        <span>Surface</span>
                    </label>
                    <label class="radio-label">
                        <input type="radio" name="style-${Date.now()}" value="ribbon">
                        <span>Ribbon</span>
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
                    this.changeRepresentation(viewerData.stage, e.target.value);
                    console.log(`Style changed to: ${e.target.value}`);
                }
            });
        });
        
        const resetButton = controlPanel.querySelector('#reset-view');
        resetButton.addEventListener('click', () => {
            viewerData.stage.autoView();
        });
        
        const centerButton = controlPanel.querySelector('#center-molecule');
        centerButton.addEventListener('click', () => {
            viewerData.stage.viewer.center();
        });
    }

    changeRepresentation(stage, representationType) {
        console.log(`Changing NGL representation to: ${representationType}`);
        
        // Get all components and change their representations
        stage.eachComponent(component => {
            component.removeAllRepresentations();
            
            switch (representationType) {
                case 'cartoon':
                    component.addRepresentation('cartoon', {
                        colorScheme: 'chainid'
                    });
                    break;
                case 'ball+stick':
                    component.addRepresentation('ball+stick', {
                        radius: 0.3,
                        scale: 0.7
                    });
                    break;
                case 'spacefill':
                    component.addRepresentation('spacefill', {
                        radius: 'vdw'
                    });
                    break;
                case 'surface':
                    component.addRepresentation('surface', {
                        opacity: 0.7,
                        colorScheme: 'chainid'
                    });
                    break;
                case 'ribbon':
                    component.addRepresentation('ribbon', {
                        colorScheme: 'chainid'
                    });
                    break;
                default:
                    component.addRepresentation('ball+stick', {
                        radius: 0.3,
                        scale: 0.7
                    });
            }
        });
        
        console.log(`NGL representation ${representationType} applied`);
    }

    onResize(width, height) {
        // Individual viewers handle their own resizing via ResizeObserver
        console.log(`NGL Extension onResize called with ${width}x${height} - individual viewers handle their own sizing`);
    }

    async cleanup() {
        // Global cleanup - only dispose of viewers that haven't been individually cleaned up
        console.log(`NGL Extension global cleanup - cleaning up ${this.viewers.size} remaining viewers`);
        
        this.viewers.forEach(viewerData => {
            if (viewerData.stage) {
                if (viewerData.stage._resizeObserver) {
                    viewerData.stage._resizeObserver.disconnect();
                }
                // NGL cleanup
                viewerData.stage.dispose();
            }
        });
        this.viewers.clear();
        await super.cleanup();
    }

    createErrorDisplay(message, container) {
        container.innerHTML = `
            <div class="extension-error">
                <div class="error-icon">⚠️</div>
                <div class="error-message">NGL Viewer Error</div>
                <div class="error-details">${message}</div>
                <div class="error-suggestion">
                    This may be due to:
                    <ul>
                        <li>Unsupported or corrupted molecular file format</li>
                        <li>Invalid molecular structure data</li>
                        <li>NGL.js library parsing limitations</li>
                    </ul>
                    Try converting the file to a standard format if possible.
                </div>
            </div>
        `;
    }
}

// Auto-register when script loads
if (typeof extensionRegistry !== 'undefined') {
    extensionRegistry.register(new NGLExtension());
    console.log('NGL Molecular Viewer Extension registered');
}
