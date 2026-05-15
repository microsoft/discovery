/**
 * XYZ Molecular Viewer Extension
 * Provides 3D visualization of XYZ molecular structure files
 */
class XYZExtension extends BaseExtension {
    constructor() {
        super('XYZ Molecular Viewer', ['.xyz'], {
            hasPreview: true,
            hasFullView: true,
            interactive: true,
            resizable: true
        });
        
        this.three = null;
        this.renderers = new Map();
    }

    getExtensionFolder() {
        return 'extensions/xyz-viewer';
    }

    async initialize() {
        // Load Three.js if not already loaded
        if (typeof THREE === 'undefined') {
            await this.loadThreeJS();
        }
        this.three = THREE;
        await super.initialize();
        return true;
    }    async loadThreeJS() {
        return new Promise((resolve, reject) => {
            // Check if Three.js script is already in the DOM
            const existingScript = document.querySelector('script[src*="three.min.js"]');
            if (existingScript) {
                // Script already exists, just wait for THREE to be available
                if (typeof THREE !== 'undefined') {
                    resolve();
                    return;
                } else {
                    // Script exists but THREE not ready yet, wait for it
                    const checkTHREE = () => {
                        if (typeof THREE !== 'undefined') {
                            resolve();
                        } else {
                            setTimeout(checkTHREE, 50);
                        }
                    };
                    checkTHREE();
                    return;
                }
            }

            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
            script.onload = () => {
                // Check if OrbitControls script already exists
                const existingControlsScript = document.querySelector('script[src*="OrbitControls.js"]');
                if (existingControlsScript) {
                    console.log('OrbitControls script already loaded');
                    resolve();
                    return;
                }

                // Load OrbitControls after Three.js using a more reliable source
                const controlsScript = document.createElement('script');
                controlsScript.src = 'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js';
                controlsScript.onload = () => {
                    console.log('OrbitControls loaded successfully');
                    resolve();
                };
                controlsScript.onerror = () => {
                    console.warn('OrbitControls failed to load from jsdelivr, trying alternative...');
                    // Try alternative CDN
                    const altControlsScript = document.createElement('script');
                    altControlsScript.src = 'https://unpkg.com/three@0.128.0/examples/js/controls/OrbitControls.js';
                    altControlsScript.onload = () => {
                        console.log('OrbitControls loaded from alternative CDN');
                        resolve();
                    };
                    altControlsScript.onerror = () => {
                        console.warn('OrbitControls not loaded from any CDN, controls will be disabled');
                        resolve();
                    };
                    document.head.appendChild(altControlsScript);
                };
                document.head.appendChild(controlsScript);
            };
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    async canHandle(filename, content) {
        if (!filename.toLowerCase().endsWith('.xyz')) {
            return false;
        }
        
        // Check if content is valid before processing
        if (!content || typeof content !== 'string') {
            return false;
        }
        
        // Basic XYZ format validation
        const lines = content.trim().split('\n');
        if (lines.length < 3) return false;
        
        const atomCount = parseInt(lines[0]);
        if (isNaN(atomCount) || atomCount <= 0) return false;
        
        // Check if we have the expected number of atom lines
        return lines.length >= atomCount + 2;
    }    async renderPreview(container, filename, content, options = {}) {
        // Use container dimensions for responsive sizing
        const width = options.width || 300;
        const height = options.height || 200;
        
        try {
            const molecule = this.parseXYZ(content);
            const renderer = this.create3DViewer(container, molecule, {
                width,
                height,
                interactive: true,     // Enable interaction like full view
                background: '#ffffff', // Use same white background as full view
                controls: true,        // Enable controls like full view
                autoRotate: false,     // Disable auto-rotate like full view
                mode: 'preview'        // Add mode indicator
            });
            
            this.renderers.set(container, renderer);
            return { success: true };
        } catch (error) {
            this.createErrorDisplay(`Failed to render molecule: ${error.message}`, container);
            return { success: false, error: error.message };
        }
    }    async renderFullView(container, filename, content, options = {}) {
        // Use container dimensions for responsive sizing
        const width = options.width || 800;
        const height = options.height || 600;
        
        try {
            const molecule = this.parseXYZ(content);
            const renderer = this.create3DViewer(container, molecule, {
                width,
                height,
                interactive: true,  // Always enable interaction for full view
                background: '#ffffff',
                controls: true,     // Always enable controls for full view
                autoRotate: false,  // Disable auto-rotate so user can control
                mode: 'fullview'    // Add mode indicator
            });
            
            this.renderers.set(container, renderer);
            
            // Add control panel
            this.addControlPanel(container, renderer);
            
            return { success: true };
        } catch (error) {
            this.createErrorDisplay(`Failed to render molecule: ${error.message}`, container);
            return { success: false, error: error.message };
        }
    }

    parseXYZ(content) {
        const lines = content.trim().split('\n');
        const atomCount = parseInt(lines[0]);
        const title = lines[1] || 'Untitled Molecule';
        
        const atoms = [];
        for (let i = 2; i < atomCount + 2; i++) {
            const parts = lines[i].trim().split(/\s+/);
            if (parts.length >= 4) {
                atoms.push({
                    symbol: parts[0],
                    x: parseFloat(parts[1]),
                    y: parseFloat(parts[2]),
                    z: parseFloat(parts[3])
                });
            }
        }
        
        return { title, atomCount, atoms };
    }    create3DViewer(container, molecule, options) {        // Clear container
        container.innerHTML = '';
        
        // Set container to use 100% sizing for proper responsive behavior
        container.style.width = '100%';
        container.style.height = '100%';
        container.style.position = 'relative';
        
        // Ensure container has proper dimensions by waiting for layout if needed
        const getContainerDimensions = () => {
            // Force a reflow to ensure CSS has been applied
            container.offsetHeight;
            
            const rect = container.getBoundingClientRect();
            const computedStyle = window.getComputedStyle(container);
            
            // Account for padding and borders in the available space
            const paddingWidth = parseFloat(computedStyle.paddingLeft) + parseFloat(computedStyle.paddingRight);
            const paddingHeight = parseFloat(computedStyle.paddingTop) + parseFloat(computedStyle.paddingBottom);
            
            return {
                width: Math.max(rect.width - paddingWidth, 300), // Minimum width fallback
                height: Math.max(rect.height - paddingHeight, 200) // Minimum height fallback
            };
        };
        
        // Wait for container layout if dimensions are not available
        let containerWidth, containerHeight;
        const dimensions = getContainerDimensions();
        if (dimensions.width <= 300 && dimensions.height <= 200) {
            // Container likely not ready, wait for layout
            console.log('Container dimensions not ready, waiting for layout...');
            setTimeout(() => {
                const newDimensions = getContainerDimensions();
                console.log(`Container dimensions updated: ${newDimensions.width}x${newDimensions.height}`);
                // Trigger a re-render if dimensions changed significantly
                if (Math.abs(newDimensions.width - dimensions.width) > 50 || 
                    Math.abs(newDimensions.height - dimensions.height) > 50) {
                    return this.create3DViewer(container, molecule, options);
                }
            }, 100);
            // Return early to prevent double rendering
            return null;
        }
        
        containerWidth = dimensions.width;
        containerHeight = dimensions.height;
        console.log(`Creating responsive 3D viewer in ${containerWidth}x${containerHeight} container, mode: ${options.mode || 'default'}`);
        
        // Create Three.js scene
        const scene = new this.three.Scene();
        scene.background = new this.three.Color(options.background);          // Create camera with initial aspect ratio
        const camera = new this.three.PerspectiveCamera(
            50,  // Reduced FOV from 75 to 50 degrees for less distortion and more natural perspective
            containerWidth / containerHeight, 
            0.1, 
            1000
        );
        
        // Create renderer with initial size
        const renderer = new this.three.WebGLRenderer({ antialias: true });
        renderer.setSize(containerWidth, containerHeight);
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = this.three.PCFSoftShadowMap;
        
        // Set canvas to use 100% sizing - let CSS handle the dimensions
        const canvas = renderer.domElement;
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        canvas.style.display = 'block';
        canvas.style.maxWidth = 'none';
        canvas.style.maxHeight = 'none';
        
        container.appendChild(canvas);
          // Add improved lighting for consistent illumination
        const ambientLight = new this.three.AmbientLight(0x404040, 0.4);
        scene.add(ambientLight);
        
        // Add multiple directional lights for better coverage
        const light1 = new this.three.DirectionalLight(0xffffff, 0.6);
        light1.position.set(1, 1, 1);
        scene.add(light1);
        
        const light2 = new this.three.DirectionalLight(0xffffff, 0.4);
        light2.position.set(-1, -1, -1);
        scene.add(light2);
        
        const light3 = new this.three.DirectionalLight(0xffffff, 0.3);
        light3.position.set(1, -1, 1);
        scene.add(light3);
        
        // Store lights for potential camera-following updates
        const lights = [light1, light2, light3];
          // Create molecule
        const moleculeGroup = this.createMoleculeGroup(molecule);
        
        // Reuse objects to avoid creating multiple instances
        const tempBox = new this.three.Box3();
        const tempVector = new this.three.Vector3();
        const tempSize = new this.three.Vector3();
        
        // Calculate the original bounding box to determine centering offset
        tempBox.setFromObject(moleculeGroup);
        const originalCenter = tempBox.getCenter(tempVector);
        const originalSize = tempBox.getSize(tempSize);
        
        console.log(`Original molecule bounds: center=(${originalCenter.x.toFixed(3)}, ${originalCenter.y.toFixed(3)}, ${originalCenter.z.toFixed(3)}), size=(${originalSize.x.toFixed(3)}, ${originalSize.y.toFixed(3)}, ${originalSize.z.toFixed(3)})`);
        
        // Center the molecule group at the origin for predictable camera positioning
        // This ensures consistent centering regardless of the original molecule position
        moleculeGroup.position.set(-originalCenter.x, -originalCenter.y, -originalCenter.z);
        
        scene.add(moleculeGroup);
        
        // Verify that the molecule is now centered at origin (reuse the same objects)
        tempBox.setFromObject(moleculeGroup);
        const centeredCenter = tempBox.getCenter(tempVector); // Reuses tempVector
        const centeredSize = tempBox.getSize(tempSize); // Reuses tempSize
        
        console.log(`Centered molecule bounds: center=(${centeredCenter.x.toFixed(3)}, ${centeredCenter.y.toFixed(3)}, ${centeredCenter.z.toFixed(3)}), size=(${centeredSize.x.toFixed(3)}, ${centeredSize.y.toFixed(3)}, ${centeredSize.z.toFixed(3)})`);
        
        // Use the maximum dimension for camera distance calculations
        const maxDim = Math.max(centeredSize.x, centeredSize.y, centeredSize.z);
        
        // Calculate optimal distance to fill viewport efficiently
        const fov = camera.fov * (Math.PI / 180); // Convert to radians
        
        // Use conservative fill factors to ensure entire molecule is visible
        // Use the same fill factor for both preview and full view for identical experience
        const fillFactor = 0.8; // Conservative - show complete molecule with margin
        
        const distance = (maxDim / 2) / Math.tan(fov / 2) / fillFactor;
        
        // Since molecule is now centered at origin, camera should target origin
        // Reuse the tempVector for target (reset it to origin)
        const target = tempVector.set(0, 0, 0); // Always target the origin where molecule is centered
        
        console.log(`Camera positioning: target=(0, 0, 0), maxDim=${maxDim.toFixed(2)}, fillFactor=${fillFactor}, distance=${distance.toFixed(2)}, mode=${options.mode || 'default'}`);
        
        // Position camera at optimal distance with more standard molecular viewing angles
        // Use different standard views depending on options or default to a balanced perspective
        const viewMode = options.viewMode || 'perspective';
        
        switch (viewMode) {
            case 'front':
                // Front view - looking along Z-axis
                camera.position.set(0, 0, distance);
                break;
            case 'side':
                // Side view - looking along X-axis  
                camera.position.set(distance, 0, 0);
                break;
            case 'top':
                // Top view - looking down along Y-axis
                camera.position.set(0, distance, 0);
                break;
            case 'perspective':
            default:
                // Balanced perspective view - less distorted than the original
                // Use a more balanced ratio with gentler angles
                camera.position.set(
                    distance * 0.5,   // Reduced from 0.7 for less extreme angle
                    distance * 0.3,   // Reduced from 0.4 for more natural height
                    distance * 0.8    // Increased from 0.7 for better depth perspective
                );
                break;
        }
        
        camera.lookAt(target); // Look at the origin where the molecule is centered
        
        // Adjust camera bounds for better zoom range
        camera.near = distance / 100;
        camera.far = distance * 10;
        camera.updateProjectionMatrix();        // Add controls if interactive
        let controls = null;
        if (options.interactive && options.controls) {
            // Check for OrbitControls availability
            const OrbitControls = this.three.OrbitControls || THREE.OrbitControls || window.THREE?.OrbitControls;
            if (OrbitControls) {
                controls = new OrbitControls(camera, renderer.domElement);
                // Set the target to the origin where the molecule is now centered
                controls.target.set(0, 0, 0);
                console.log(`Controls target set to: (0, 0, 0) - molecule center`);
                controls.enableDamping = true;
                controls.dampingFactor = 0.05;
                
                // Set reasonable zoom limits
                controls.minDistance = distance * 0.5;
                controls.maxDistance = distance * 3;
                
                // Enable auto-rotate for interactive views if specified
                if (options.autoRotate) {
                    controls.autoRotate = true;
                    controls.autoRotateSpeed = 1.0;
                }
                
                console.log(`OrbitControls enabled for ${options.mode || 'default'} mode`);
            } else {
                console.warn('OrbitControls not available - implementing basic mouse interaction');
                // Implement basic mouse interaction as fallback
                controls = this.createBasicControls(camera, renderer.domElement);
            }
        }// Animation loop with cancellable frame
        let animationId;
        let isRunning = true;
        
        // Reusable objects for animation to avoid creating new objects every frame
        const cameraPositionNorm = new this.three.Vector3();
        const lightOffset1 = new this.three.Vector3(2, 2, 0);
        const lightOffset2 = new this.three.Vector3(-1, 2, 1);
        
        const animate = () => {
            if (!isRunning) return;
            
            animationId = requestAnimationFrame(animate);
            
            // Check if container is still in DOM and visible
            if (!document.body.contains(container)) {
                isRunning = false;
                return;
            }
              if (controls) {
                controls.update();
            } else if (options.autoRotate) {
                // Auto-rotate for preview - ensure rotation continues
                moleculeGroup.rotation.y += 0.01;
            }
            
            // Update light positions relative to camera for consistent illumination
            if (lights && lights.length > 0) {
                // Reuse cameraPositionNorm object instead of cloning every frame
                cameraPositionNorm.copy(camera.position).normalize();
                
                // Primary light follows camera direction
                lights[0].position.copy(cameraPositionNorm).multiplyScalar(10);
                
                // Secondary lights for fill lighting
                if (lights[1]) {
                    lights[1].position.copy(cameraPositionNorm).multiplyScalar(-8).add(lightOffset1);
                }
                if (lights[2]) {
                    lights[2].position.copy(cameraPositionNorm).multiplyScalar(6).add(lightOffset2);
                }
            }
            
            renderer.render(scene, camera);};
        animate();
        
        // Add ResizeObserver for responsive behavior
        let resizeObserver = null;
        if (window.ResizeObserver) {
            resizeObserver = new ResizeObserver(entries => {
                for (let entry of entries) {
                    const { width, height } = entry.contentRect;
                    if (width > 0 && height > 0) {
                        // Update camera aspect ratio
                        camera.aspect = width / height;
                        camera.updateProjectionMatrix();
                        
                        // Update renderer size (this updates the canvas buffer)
                        renderer.setSize(width, height);
                        
                        console.log(`XYZ viewer resized to ${width}x${height}`);
                    }
                }
            });
            resizeObserver.observe(container);
        }
        
        return {
            scene,
            camera,
            renderer,
            controls,
            moleculeGroup,
            container,
            width: containerWidth,
            height: containerHeight,
            animationId: animationId,
            resizeObserver: resizeObserver,
            isRunning: () => isRunning,
            stopAnimation: () => {
                isRunning = false;
                if (animationId) {
                    cancelAnimationFrame(animationId);
                    animationId = null;
                }
                if (resizeObserver) {
                    resizeObserver.disconnect();
                    resizeObserver = null;
                }
            }
        };
    }

    createBasicControls(camera, domElement) {
        const controls = {
            target: new this.three.Vector3(0, 0, 0),
            update: () => {},
            enabled: true
        };
        
        let isMouseDown = false;
        let lastMouseX = 0;
        let lastMouseY = 0;
        let spherical = new this.three.Spherical();
        
        // Reusable offset vector to avoid creating new objects
        const offsetVector = new this.three.Vector3();
        
        // Convert camera position to spherical coordinates
        const updateSpherical = () => {
            offsetVector.copy(camera.position).sub(controls.target);
            spherical.setFromVector3(offsetVector);
        };
        
        updateSpherical();
        
        const onMouseDown = (event) => {
            isMouseDown = true;
            lastMouseX = event.clientX;
            lastMouseY = event.clientY;
            domElement.style.cursor = 'grabbing';
        };
        
        const onMouseMove = (event) => {
            if (!isMouseDown) return;
            
            const deltaX = event.clientX - lastMouseX;
            const deltaY = event.clientY - lastMouseY;
            
            // Adjust spherical coordinates based on mouse movement
            spherical.theta -= deltaX * 0.01;
            spherical.phi += deltaY * 0.01;
            
            // Limit phi to avoid flipping
            spherical.phi = Math.max(0.1, Math.min(Math.PI - 0.1, spherical.phi));
            
            // Update camera position (reuse offsetVector)
            offsetVector.setFromSpherical(spherical);
            camera.position.copy(controls.target).add(offsetVector);
            camera.lookAt(controls.target);
            
            lastMouseX = event.clientX;
            lastMouseY = event.clientY;
        };
        
        const onMouseUp = () => {
            isMouseDown = false;
            domElement.style.cursor = 'grab';
        };
        
        const onWheel = (event) => {
            event.preventDefault();
            spherical.radius += event.deltaY * 0.01;
            spherical.radius = Math.max(1, Math.min(50, spherical.radius));
            
            // Update camera position (reuse offsetVector)
            offsetVector.setFromSpherical(spherical);
            camera.position.copy(controls.target).add(offsetVector);
            camera.lookAt(controls.target);
        };
        
        // Add event listeners
        domElement.addEventListener('mousedown', onMouseDown);
        domElement.addEventListener('mousemove', onMouseMove);
        domElement.addEventListener('mouseup', onMouseUp);
        domElement.addEventListener('wheel', onWheel);
        domElement.style.cursor = 'grab';
        
        // Cleanup function
        controls.dispose = () => {
            domElement.removeEventListener('mousedown', onMouseDown);
            domElement.removeEventListener('mousemove', onMouseMove);
            domElement.removeEventListener('mouseup', onMouseUp);
            domElement.removeEventListener('wheel', onWheel);
            domElement.style.cursor = 'default';
        };
        
        console.log('Basic mouse controls initialized');
        return controls;
    }

    createMoleculeGroup(molecule) {
        const group = new this.three.Group();
        
        // Atom colors (CPK coloring scheme)
        const atomColors = {
            'H': 0xffffff,   // White
            'C': 0x909090,   // Dark gray
            'N': 0x3050f8,   // Blue
            'O': 0xff0d0d,   // Red
            'F': 0x90e050,   // Green
            'P': 0xff8000,   // Orange
            'S': 0xffff30,   // Yellow
            'Cl': 0x1ff01f,  // Green
            'Br': 0xa62929,  // Dark red
            'I': 0x940094,   // Purple
            'default': 0xff1493  // Deep pink
        };
        
        // Atom sizes (van der Waals radii scaled)
        const atomSizes = {
            'H': 0.3,
            'C': 0.4,
            'N': 0.35,
            'O': 0.35,
            'F': 0.3,
            'P': 0.45,
            'S': 0.45,
            'Cl': 0.45,
            'Br': 0.5,
            'I': 0.55,
            'default': 0.4
        };
        
        // Create atoms
        molecule.atoms.forEach(atom => {
            const color = atomColors[atom.symbol] || atomColors.default;
            const radius = atomSizes[atom.symbol] || atomSizes.default;
            
            const geometry = new this.three.SphereGeometry(radius, 16, 12);
            const material = new this.three.MeshPhongMaterial({ 
                color: color,
                shininess: 100
            });
            
            const sphere = new this.three.Mesh(geometry, material);
            sphere.position.set(atom.x, atom.y, atom.z);
            sphere.castShadow = true;
            sphere.receiveShadow = true;
            
            group.add(sphere);
        });
        
        // Create bonds (simple distance-based)
        this.createBonds(group, molecule);
        
        return group;
    }

    createBonds(group, molecule) {
        const bondDistance = 1.8; // Maximum bond distance
        
        for (let i = 0; i < molecule.atoms.length; i++) {
            for (let j = i + 1; j < molecule.atoms.length; j++) {
                const atom1 = molecule.atoms[i];
                const atom2 = molecule.atoms[j];
                
                const distance = Math.sqrt(
                    Math.pow(atom1.x - atom2.x, 2) +
                    Math.pow(atom1.y - atom2.y, 2) +
                    Math.pow(atom1.z - atom2.z, 2)
                );
                
                if (distance <= bondDistance) {
                    const bondGeometry = new this.three.CylinderGeometry(0.05, 0.05, distance);
                    const bondMaterial = new this.three.MeshPhongMaterial({ color: 0x888888 });
                    const bond = new this.three.Mesh(bondGeometry, bondMaterial);
                    
                    // Position and orient the bond
                    const midpoint = new this.three.Vector3(
                        (atom1.x + atom2.x) / 2,
                        (atom1.y + atom2.y) / 2,
                        (atom1.z + atom2.z) / 2
                    );
                    
                    bond.position.copy(midpoint);
                    bond.lookAt(new this.three.Vector3(atom2.x, atom2.y, atom2.z));
                    bond.rotateX(Math.PI / 2);
                    
                    group.add(bond);
                }
            }
        }
    }

    addControlPanel(container, renderer) {
        const controlPanel = document.createElement('div');
        controlPanel.className = 'xyz-controls';
        controlPanel.innerHTML = `
            <div class="control-group">
                <label>Background:</label>
                <select id="background-select">
                    <option value="#ffffff">White</option>
                    <option value="#000000">Black</option>
                    <option value="#f0f0f0">Light Gray</option>
                </select>
            </div>
            <div class="control-group">
                <button id="reset-view">Reset View</button>
                <button id="toggle-wireframe">Wireframe</button>
            </div>
        `;
        
        container.appendChild(controlPanel);
        
        // Add event listeners
        const backgroundSelect = controlPanel.querySelector('#background-select');
        backgroundSelect.addEventListener('change', (e) => {
            renderer.scene.background = new this.three.Color(e.target.value);
        });
        
        const resetButton = controlPanel.querySelector('#reset-view');
        resetButton.addEventListener('click', () => {
            if (renderer.controls) {
                renderer.controls.reset();
            }
        });
        
        const wireframeButton = controlPanel.querySelector('#toggle-wireframe');
        wireframeButton.addEventListener('click', () => {
            renderer.moleculeGroup.children.forEach(child => {
                if (child.material) {
                    child.material.wireframe = !child.material.wireframe;
                }
            });
        });
    }    onResize(width, height) {
        // Note: Individual renderers now handle their own resizing via ResizeObserver
        // This method is kept for compatibility but individual viewers are self-managing
    }    async cleanup() {
        // Global cleanup - only dispose of renderers that haven't been individually cleaned up
        // The extension manager handles per-container cleanup, so this is only for final cleanup
        console.log(`XYZ Extension global cleanup - cleaning up ${this.renderers.size} remaining renderers`);
        
        this.renderers.forEach(renderer => {
            // Stop animation loop
            if (renderer.stopAnimation) {
                renderer.stopAnimation();
            }
            
            // Dispose of controls
            if (renderer.controls && renderer.controls.dispose) {
                renderer.controls.dispose();
            }
            
            // Dispose of renderer
            if (renderer.renderer) {
                renderer.renderer.dispose();
            }
            
            // Dispose of scene objects
            if (renderer.scene) {
                renderer.scene.children.forEach(child => {
                    if (child.geometry) child.geometry.dispose();
                    if (child.material) child.material.dispose();
                });
            }
        });
        this.renderers.clear();
        await super.cleanup();
    }

    getActiveRenderersInfo() {
        const info = [];
        this.renderers.forEach((renderer, container) => {
            info.push({
                containerId: container.id || 'unknown',
                isRunning: renderer.isRunning ? renderer.isRunning() : 'unknown',
                autoRotate: renderer.moleculeGroup ? 'active' : 'inactive',
                width: renderer.width,
                height: renderer.height
            });
        });
        return info;
    }
}

// Auto-register when script loads
if (typeof extensionRegistry !== 'undefined') {
    extensionRegistry.register(new XYZExtension());
    console.log('XYZ Molecular Viewer Extension registered');
}
