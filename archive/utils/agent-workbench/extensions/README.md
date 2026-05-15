# Extension System for MS Discovery Agent Test Environment

## Overview

The extension system allows custom file viewers to be registered for specific file types, providing enhanced visualization and interaction capabilities beyond basic text display. This system supports responsive design, custom icons, and both preview and full-view modal rendering.

## Architecture

- **Base Extension Class** (`extensions/base-extension.js`): Abstract base class all extensions inherit from
- **Extension Registry** (`extensions/extension-registry.js`): Central registry managing all extensions
- **Extension Manager** (`extensions/extension-manager.js`): Handles rendering and lifecycle
- **Extension Styles** (`extensions/extension-styles.css`): Common styling for the extension system

## Current Extensions

### 1. Default Text Extension
- **File**: `extensions/default-text-extension.js`
- **Icon**: `extensions/default-text/icon.svg`
- **Styles**: `extensions/default-text/default-text-styles.css`
- **Supports**: `.txt`, `.log`, `.out`, `.dat`, `.cfg`, `.json`, `.csv`, `.xml`, `.yaml`, `.yml`, `.md`, `.ini`, `.conf`
- **Features**:
  - **JSON files**: Automatic formatting, syntax highlighting, validation with error indicators
  - **CSV files**: Formatted HTML table with sticky headers, responsive design, hover effects
  - **XML/YAML/Markdown**: Syntax highlighting via Prism.js
  - **Plain text**: Basic text display with preview/full view modes
  - **Smart formatting**: Detects file format and applies appropriate rendering
  - **Modal optimization**: Different styling for preview vs. full view modes

### 2. XYZ Molecular Viewer
- **File**: `extensions/xyz-viewer/xyz-extension.js`
- **Icon**: `extensions/xyz-viewer/icon.svg`
- **Styles**: `extensions/xyz-viewer/xyz-styles.css`
- **Supports**: `.xyz` molecular structure files
- **Features**:
  - 3D molecular visualization using Three.js
  - Interactive controls (rotate, zoom, pan)
  - Atom coloring (CPK scheme)
  - Bond detection and rendering
  - Preview and full-view modes
  - Control panel with options
  - Responsive canvas sizing with ResizeObserver
  - Dynamic lighting and smooth animations
  - Per-container cleanup to prevent interference

### 3. 3DMol Molecular Viewer
- **File**: `extensions/3dmol-viewer/3dmol-extension.js`
- **Icon**: `extensions/3dmol-viewer/icon.svg`
- **Styles**: `extensions/3dmol-viewer/3dmol-styles.css`
- **Supports**: `.pdb`, `.sdf`, `.mol2`, `.cif` molecular structure files
- **Features**:
  - Advanced molecular visualization using 3DMol.js
  - Multiple rendering styles (cartoon, stick, sphere, surface)
  - Interactive style switching via radio controls
  - Secondary structure visualization for proteins
  - High-quality rendering with anti-aliasing
  - Responsive design with automatic centering
  - Robust error handling for unsupported formats
  - Per-container cleanup preventing modal interference

### 4. NGL Molecular Viewer
- **File**: `extensions/ngl-viewer/ngl-extension.js`
- **Icon**: `extensions/ngl-viewer/icon.svg`
- **Styles**: `extensions/ngl-viewer/ngl-styles.css`
- **Supports**: `.gro`, `.mmcif`, `.mmtf`, `.mrc`, `.dcd`, `.xtc`, `.trr`, `.psf`, `.top`, `.prmtop` molecular files
- **Features**:
  - WebGL-based molecular visualization using NGL Viewer
  - Support for additional file formats not covered by other viewers
  - Multiple representation styles (ball+stick, cartoon, spacefill, surface, ribbon)
  - Specialized handling for different molecular file types
  - Optimized for GROMACS, trajectory, and topology files
  - Interactive controls with well-centered molecular views
  - Responsive design with automatic resizing
  - Error handling with format-specific suggestions
  - Per-container cleanup and resource management

### 5. Image Viewer Extension
- **File**: `extensions/image-viewer/image-extension.js`
- **Icon**: `extensions/image-viewer/icon.svg`
- **Styles**: `extensions/image-viewer/image-styles.css`
- **Supports**: `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg` image files
- **Features**:
  - High-quality image display with zoom and pan
  - Interactive control panel (zoom in/out, fit to window, 100% size)
  - Support for base64 encoded and binary image data
  - SVG support with proper text content handling
  - Robust error handling with user-friendly error messages
  - Resource management with blob URL cleanup
  - Responsive design for different container sizes

### 6. HTML Viewer Extension
- **File**: `extensions/html-viewer/html-extension.js`
- **Icon**: `extensions/html-viewer/icon.svg`
- **Styles**: `extensions/html-viewer/html-styles.css`
- **Supports**: `.html`, `.htm` files, auto-detects HTML content
- **Features**:
  - Secure HTML rendering in sandboxed iframe
  - JavaScript execution support with security restrictions
  - Interactive controls (refresh, open in new window)
  - View source functionality
  - Auto-detection of HTML content even without file extension
  - Responsive design for preview and full-view modes
  - Context menu with additional options
  - Security sandbox: allows scripts, forms, modals, and popups but prevents same-origin access

### 7. MD Trajectory Viewer Extension
- **File**: `extensions/md-trajectory-viewer/md-trajectory-extension.js`
- **Icon**: `extensions/md-trajectory-viewer/icon.svg`
- **Styles**: `extensions/md-trajectory-viewer/md-trajectory-styles.css`
- **Supports**: `.xyz`, `.lammpstrj`, `.lammps`, `.gsd`, `.h5md`, `.xtc`, `.trr` molecular trajectory files
- **Features**:
  - **High-performance rendering**: WebGPU rendering engine with WebGL fallback
  - **Multi-format support**: XYZ, LAMMPS dump, GSD, H5MD, XTC, TRR, multi-model PDB
  - **Trajectory playback**: Play/pause/stop, frame-by-frame navigation, adjustable speed
  - **Loop modes**: Once, loop, and bounce modes for trajectory animation
  - **Multiple representations**: Ball-and-stick, spacefill, wireframe, points, licorice
  - **Real-time analysis**: Center of mass, bounding box, density calculations
  - **Advanced analysis tools**: RDF, RMSD, MSD, coordination numbers, hydrogen bonds
  - **Bond detection**: Automatic bond detection with spatial hashing for large systems
  - **Interactive controls**: Timeline scrubbing, keyboard shortcuts (Space, Arrow keys)
  - **Responsive design**: Works in both preview and fullview modes
  - **Frame streaming**: Memory-efficient handling of large trajectories
  - **CPK color scheme**: Standard atomic coloring with van der Waals radii
- **Modules**:
  - `trajectory-parsers.js`: Multi-format trajectory parsing
  - `analysis-tools.js`: Molecular analysis algorithms
  - `playback-controls.js`: Animation and playback management
  - `webgpu-renderer.js`: High-performance WebGPU rendering
- **Keyboard Shortcuts**:
  - `Space`: Play/Pause
  - `←/→`: Previous/Next frame
  - `S`: Stop
  - `L`: Cycle loop mode
  - `Home/End`: First/Last frame
  - `[/]`: Slow down/Speed up

## Creating New Extensions

### 1. Extend Base Class

```javascript
class MyExtension extends BaseExtension {
    constructor() {
        super('My Extension Name', ['.ext1', '.ext2'], {
            hasPreview: true,
            hasFullView: true,
            interactive: false,
            resizable: true,
            // Priority determines which extension handles files when multiple match
            // Higher priority wins. Default is 0. Range: -100 to 100.
            priority: 0
        });
    }

    getExtensionFolder() {
        return 'extensions/my-extension';
    }

    async canHandle(filename, content) {
        // Return true if this extension can handle the file
        // Use content inspection for smarter decisions
        return filename.endsWith('.myext');
    }

    async renderPreview(container, filename, content, options) {
        // Render small preview
        container.innerHTML = '<div>Preview content</div>';
        return { success: true };
    }

    async renderFullView(container, filename, content, options) {
        // Render full view
        container.innerHTML = '<div>Full view content</div>';
        return { success: true };
    }

    onResize(width, height) {
        // Handle container resize events (optional)
        console.log(`Extension resized to ${width}x${height}`);
    }

    async cleanup() {
        // Clean up resources when extension is destroyed
        await super.cleanup();
    }
}
```

### 2. Create Extension Directory Structure

```
extensions/my-extension/
├── my-extension.js     # Main extension code
├── my-styles.css       # Extension-specific styles (optional)
└── icon.svg           # Extension icon (16x16 SVG)
```

### 3. Register Extension

```javascript
// Auto-register when script loads
if (typeof extensionRegistry !== 'undefined') {
    extensionRegistry.register(new MyExtension());
}
```

### 4. Add to HTML

```html
<script src="extensions/my-extension/my-extension.js"></script>
```

### 5. Add CSS (if needed)

```html
<link rel="stylesheet" href="extensions/my-extension/my-styles.css">
```

## Extension Capabilities

- **hasPreview**: Extension can render in preview mode (inline)
- **hasFullView**: Extension can render in full-view modal
- **interactive**: Extension supports user interaction
- **resizable**: Extension handles container resize events
- **priority**: Determines which extension handles files when multiple can (higher wins)

## Extension Priority System

When multiple extensions register for the same file type (e.g., both XYZ Viewer and MD Trajectory Viewer handle `.xyz`), the registry uses a priority system:

1. **Priority values**: Range from -100 (lowest) to 100 (highest). Default is 0.
2. **Higher wins**: Extensions are checked in descending priority order.
3. **Smart canHandle()**: Higher-priority extensions can inspect content and return `false` to defer to lower-priority extensions.

### Example: XYZ File Handling

| Extension | Priority | Claims File When |
|-----------|----------|------------------|
| MD Trajectory Viewer | 10 | Multi-frame trajectory OR >500 atoms OR extended XYZ |
| XYZ Viewer | 0 | Single-frame, small molecule |

```javascript
// In MD Trajectory Viewer's canHandle():
async canHandle(filename, content) {
    // Only claim XYZ files with multiple frames or large systems
    const frameCount = this.countFrames(content);
    const atomCount = this.getAtomCount(content);
    
    // Claim trajectories and large systems, defer simple molecules
    return frameCount > 1 || atomCount > 500;
}
```

This allows specialized extensions to handle complex cases while simpler viewers handle basic files.

## Responsive Design Best Practices

### Canvas and Visualization Components

When building extensions with canvases or complex visualizations:

#### 1. Use 100% Sizing with CSS
```css
.extension-container canvas {
    width: 100% !important;
    height: 100% !important;
    display: block !important;
}

/* Ensure containers fill modal content */
.modal-content .extension-container {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
}
```

#### 2. Implement ResizeObserver for Responsiveness
```javascript
// Add ResizeObserver for responsive behavior
if (window.ResizeObserver) {
    const resizeObserver = new ResizeObserver(entries => {
        for (let entry of entries) {
            const { width, height } = entry.contentRect;
            if (width > 0 && height > 0) {
                // Update renderer size
                renderer.setSize(width, height);
                camera.aspect = width / height;
                camera.updateProjectionMatrix();
            }
        }
    });
    resizeObserver.observe(container);
}
```

#### 3. Proper Resource Cleanup
```javascript
async cleanup() {
    // Stop animations
    if (this.animationId) {
        cancelAnimationFrame(this.animationId);
    }
    
    // Disconnect observers
    if (this.resizeObserver) {
        this.resizeObserver.disconnect();
    }
    
    // Dispose renderer resources
    if (this.renderer) {
        this.renderer.dispose();
    }
    
    await super.cleanup();
}
```

### Container Sizing Strategy

#### Problem: Hardcoded Pixel Dimensions
❌ **Don't do this:**
```javascript
const width = 800;  // Hardcoded dimensions
const height = 600;
renderer.setSize(width, height);
canvas.style.width = `${width}px`;
canvas.style.height = `${height}px`;
```

#### Solution: Responsive Container-Based Sizing
✅ **Do this instead:**
```javascript
// Get container dimensions dynamically
const getContainerDimensions = () => {
    const rect = container.getBoundingClientRect();
    return {
        width: Math.max(rect.width, 300),  // With fallback
        height: Math.max(rect.height, 200)
    };
};

const { width, height } = getContainerDimensions();

// Set CSS to 100% and let container control sizing
canvas.style.width = '100%';
canvas.style.height = '100%';

// Initialize renderer with container size
renderer.setSize(width, height);
```

### Centering and Camera Positioning

For 3D viewers, ensure proper centering:

```javascript
// Center object at origin for predictable camera positioning
const tempBox = new THREE.Box3().setFromObject(object);
const tempCenter = tempBox.getCenter(new THREE.Vector3());
object.position.set(-tempCenter.x, -tempCenter.y, -tempCenter.z);

// Position camera relative to origin
const distance = calculateOptimalDistance();
camera.position.set(distance * 0.7, distance * 0.4, distance * 0.7);
camera.lookAt(0, 0, 0);  // Look at origin
```

### Icon Guidelines

- **Format**: SVG (16x16 viewBox recommended)
- **Style**: Simple, clear, monochromatic
- **Location**: `extensions/[extension-name]/icon.svg`
- **Fallback**: System uses `extensions/icon.svg` if extension icon missing

```svg
<!-- Example icon.svg -->
<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
    <path d="M2 2h12v12H2z" fill="#666"/>
</svg>
```

### Key Learnings for Extension Developers

#### 1. **Preview vs Modal Design Philosophy**
- **Preview mode**: Should be compact, fit within container bounds, prioritize readability over completeness
- **Modal mode**: Can use more space, show complete data, allow horizontal scrolling if needed
- **Different CSS rules**: Use `.modal-content` selectors to apply different styling for modal view

#### 2. **Resource Management Patterns**
```javascript
// Always use Map to track resources by container
this.activeViewers = new Map();

// Store cleanup functions, not just objects
this.activeViewers.set(container, {
    dispose: () => { /* cleanup logic */ },
    element: viewerElement
});

// Clean up on container removal
async cleanup() {
    this.activeViewers.forEach(viewer => {
        if (viewer.dispose) viewer.dispose();
    });
    this.activeViewers.clear();
}
```

#### 3. **Data Format Detection Best Practices**
```javascript
// Don't just check file extension, validate content too
async canHandle(filename, content) {
    const extension = filename.split('.').pop().toLowerCase();
    
    if (extension === 'json') {
        try {
            JSON.parse(content);
            return true;
        } catch (e) {
            return false; // Let text viewer handle malformed JSON
        }
    }
    
    return this.supportedTypes.includes(`.${extension}`);
}
```

#### 4. **Performance Optimization**
- **Lazy load heavy libraries**: Only load Three.js/3DMol.js when actually needed
- **Debounce resize events**: Prevent excessive re-rendering during window resize
- **Use requestAnimationFrame**: For smooth animations and proper timing
- **Dispose resources**: Always clean up geometries, textures, observers

#### 5. **Error Handling Strategies**
```javascript
// Provide user-friendly error messages
createErrorDisplay(message, container) {
    container.innerHTML = `
        <div class="extension-error">
            <div class="error-icon">⚠️</div>
            <div class="error-message">Extension Error</div>
            <div class="error-details">${message}</div>
            <div class="error-suggestion">
                Possible solutions:
                <ul>
                    <li>Check file format</li>
                    <li>Verify file integrity</li>
                    <li>Try downloading the file</li>
                </ul>
            </div>
        </div>
    `;
}
```

#### 6. **Responsive Design Patterns**
```css
/* Base styles for all screen sizes */
.extension-container {
    width: 100%;
    height: 100%;
    position: relative;
}

/* Modal-specific overrides */
.modal-content .extension-container {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
}

/* Responsive breakpoints */
@media (max-width: 768px) {
    .extension-container {
        font-size: smaller;
        padding: reduced;
    }
}
```

## File Types Supported

- **Text files**: `.txt`, `.log`, `.out`, `.dat`, `.cfg`
- **Structured data**: `.json`, `.csv`, `.xml`, `.yaml`, `.yml`, `.md`, `.ini`, `.conf`
- **Molecular structures**: 
  - `.xyz` (XYZ format)
  - `.pdb` (Protein Data Bank)
  - `.sdf` (Structure Data Format)
  - `.mol2` (Tripos MOL2)
  - `.cif` (Crystallographic Information Format)
- **Images**: `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`
- **Extensible**: Easy to add support for new formats

## Common Pitfalls and Solutions

### 1. Canvas Not Filling Modal
**Problem**: Canvas appears small in modal despite container being large.
**Solution**: Use 100% CSS sizing and ResizeObserver instead of hardcoded pixels.

### 2. Multiple Viewers Interfering
**Problem**: Opening/closing one viewer affects others.
**Solution**: Use unique container IDs and individual ResizeObserver instances. Implement per-container cleanup.

### 3. Memory Leaks from Animations
**Problem**: Animation loops continue after viewer is closed.
**Solution**: Implement proper cleanup with `cancelAnimationFrame()` and disconnect observers.

### 4. Poor Camera Positioning
**Problem**: Objects appear off-center or at wrong zoom level.
**Solution**: Center objects at origin and calculate camera distance from bounding box.

### 5. Icons Not Loading
**Problem**: Extension icons don't appear in file listings.
**Solution**: Ensure `getExtensionFolder()` returns correct path and icon.svg exists.

### 6. CSV Tables Too Wide in Modal
**Problem**: CSV tables with long content expand modal beyond screen bounds.
**Solution**: Use `table-layout: fixed`, `max-width` constraints, and `text-overflow: ellipsis`.

### 7. Binary Image Data Corruption
**Problem**: Binary image files fail to load when fetched as text.
**Solution**: Use `/api/file/{filename}?source=outputs&raw=true` endpoint directly for binary formats instead of text processing.

### 8. Extension Selection Issues
**Problem**: Wrong extension handles certain file types.
**Solution**: Check file extension matching in `canHandle()` method and ensure proper registration order.

### 9. Modal Breaking After Multiple Opens
**Problem**: Full-view modal stops working after opening/closing multiple files.
**Solution**: Implement proper per-container cleanup and avoid global state conflicts.

## Testing Your Extension

1. **Run the web application**: `start_web_app.bat`
2. **Create test files** in the `docker-shared/output/` directory
3. **Check Results tab** for your file type
4. **Verify icon display** in file listings
5. **Test preview mode** (inline rendering)
6. **Test full-view modal** (if supported)
7. **Test responsiveness** by resizing modal
8. **Verify cleanup** by opening/closing multiple times

## Debugging Tips

### Browser Console Commands
```javascript
// Check registered extensions
extensionRegistry.getAllExtensions();

// Check active renderers
extensionManager.activeExtensions;

// Test icon loading
new Image().src = 'extensions/my-extension/icon.svg';
```

### Common Console Errors
- **"Extension not found"**: Check registration and file loading order
- **"Icon failed to load"**: Verify SVG file path and syntax
- **"Canvas context lost"**: Check for memory leaks and proper cleanup

## Performance Considerations

- **Lazy loading**: Only load heavy libraries (Three.js) when needed
- **Efficient rendering**: Use `requestAnimationFrame` for smooth animations
- **Memory management**: Dispose of geometries, materials, and textures
- **Resize debouncing**: Avoid excessive resize events

```javascript
// Debounced resize handling
let resizeTimeout;
const handleResize = () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
        updateRendererSize();
    }, 100);
};
```

## Testing

1. **Run the web application**: `start_web_app.bat` or `start_web_app.sh`
2. **Generate or upload test files** to the `docker-shared/output/` directory
3. **Check the Results tab** for enhanced viewing options
4. **Verify extension selection**:
   - Text files show "View" button with text icon
   - Molecular files show "View (3D)" button with molecule icon
   - Images show "View" button with image icon
5. **Test preview mode** (inline rendering) by clicking file previews
6. **Test full-view modal** by clicking "View" or "View (3D)" buttons
7. **Test responsiveness** by resizing modal windows
8. **Verify cleanup** by opening/closing multiple files without interference
9. **Test with different data**:
   - Valid and invalid JSON files
   - CSV files with varying column counts and content lengths
   - Different molecular file formats
   - Various image formats and sizes

### Sample Test Files Available
- `sample-data.json` - Complex nested JSON with scientific data
- `compounds-data.csv` - Chemical compound data with long SMILES strings
- `experiment-config.xml` - XML configuration file
- `config.yaml` - YAML workflow configuration
- `sample_protein.pdb` - Protein structure file
- `cholesterol.xyz` - Molecular structure file
- `sample-graphic.svg` - SVG image file

## Future Extensions Ideas

- **Enhanced PDB Viewer**: Advanced protein visualization with sequence alignment and mutation analysis
- **Chemical Reaction Viewer**: Display reaction mechanisms and pathways
- **Spectroscopy Viewer**: NMR, IR, UV-Vis spectra visualization with peak picking
- **Crystal Structure Viewer**: Unit cell visualization and symmetry operations
- **Log Analyzer**: Enhanced log parsing with syntax highlighting, search, and filtering
- **PDF Viewer**: Embedded PDF display with page navigation and text search
- **Audio/Video Player**: Media playback with waveform visualization
- **Jupyter Notebook Viewer**: Render .ipynb files with cell output and plots
- **Graph/Network Viewer**: Network visualization with force-directed layouts
- **Workflow Diagram Viewer**: Scientific workflow visualization
- **Data Table Viewer**: Advanced CSV/Excel viewer with sorting, filtering, and charting
- **SMILES/InChI Viewer**: Chemical structure rendering from text notation
- **Sequence Alignment Viewer**: Protein/DNA sequence alignment visualization
- **Pharmacophore Viewer**: Drug design feature visualization

## Version History

- **v1.0**: Initial extension system with basic text and XYZ viewers
- **v1.1**: Added responsive design and proper canvas sizing
- **v1.2**: Improved centering and camera positioning for 3D viewers
- **v1.3**: Added icon support and cleaned up debug files
- **v1.4**: Enhanced default text extension with JSON, CSV, XML, YAML support
- **v1.5**: Added 3DMol molecular viewer for advanced protein/molecular visualization
- **v1.6**: Implemented image viewer extension with zoom/pan capabilities
- **v1.7**: Fixed CSV table responsive design and modal width constraints
- **v1.8**: Added per-container cleanup and resource management
- **v1.9**: Improved binary data handling and extension selection logic
- **v2.0**: Added NGL molecular viewer for additional file formats (GRO, MMCIF, MMTF, MRC, etc.)

## Contributing

When adding new extensions:

1. Follow the established patterns in existing extensions
2. Test thoroughly across different file sizes and modal sizes
3. Implement proper cleanup to prevent memory leaks
4. Add appropriate documentation and examples
5. Consider both preview and full-view modes
6. Ensure responsive design works on different screen sizes

### Advanced Extension Patterns

#### 1. Handling Different Data Formats
```javascript
async formatContent(filename, content) {
    const extension = filename.split('.').pop().toLowerCase();
    
    switch (extension) {
        case 'json':
            return this.formatJson(content);
        case 'csv':
            return this.formatCsv(content);
        case 'xml':
            return this.formatXml(content);
        default:
            return this.formatPlainText(content);
    }
}

formatJson(content) {
    try {
        const parsed = JSON.parse(content);
        const formatted = JSON.stringify(parsed, null, 2);
        return `<pre><code class="language-json">${this.escapeHtml(formatted)}</code></pre>`;
    } catch (e) {
        return `<div class="format-error">⚠️ Invalid JSON format</div>
                <pre><code class="language-json">${this.escapeHtml(content)}</code></pre>`;
    }
}
```

#### 2. Responsive Table Design for Wide Data
```css
/* Different behavior for preview vs modal */
.csv-table th,
.csv-table td {
    word-wrap: break-word;
    max-width: 200px; /* Constrain in preview */
}

.modal-content .csv-table {
    table-layout: fixed;
    width: 100%;
}

.modal-content .csv-table th,
.modal-content .csv-table td {
    white-space: nowrap;
    text-overflow: ellipsis;
    overflow: hidden;
    max-width: 300px; /* Larger in modal */
}

/* Show full content on hover */
.modal-content .csv-table td:hover {
    overflow: visible;
    white-space: normal;
    position: relative;
    z-index: 10;
    background: #fff;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
```

#### 3. Per-Container Resource Management
```javascript
class MyExtension extends BaseExtension {
    constructor() {
        super(...);
        this.activeViewers = new Map(); // Track viewers by container
    }

    async renderPreview(container, filename, content, options) {
        // Create viewer instance
        const viewer = this.createViewer(container, content, options);
        
        // Store for cleanup
        this.activeViewers.set(container, viewer);
        
        return { success: true };
    }

    async cleanup() {
        // Clean up all active viewers
        this.activeViewers.forEach(viewer => {
            if (viewer.dispose) viewer.dispose();
        });
        this.activeViewers.clear();
        
        await super.cleanup();
    }
}
```

#### 4. Binary vs Text Data Handling
```javascript
async canHandle(filename, content) {
    const extension = filename.split('.').pop().toLowerCase();
    
    // Handle binary image formats differently
    if (['png', 'jpg', 'jpeg', 'gif'].includes(extension)) {
        // For binary images, we'll use direct download URL
        return true;
    }
    
    // For text-based formats, process content normally
    if (['svg', 'json', 'csv'].includes(extension)) {
        return true;
    }
    
    return false;
}

createImageViewer(filename, content, options) {
    const extension = filename.split('.').pop().toLowerCase();
    
    let imageUrl;
    if (extension === 'svg') {
        // Text-based format - process content
        const blob = new Blob([content], { type: 'image/svg+xml' });
        imageUrl = URL.createObjectURL(blob);
    } else {
        // Binary format - use raw file endpoint
        const params = new URLSearchParams();
        params.set('source', 'outputs');
        params.set('raw', 'true');
        imageUrl = `/api/file/${filename}?${params.toString()}`;
    }
    
    const img = document.createElement('img');
    img.src = imageUrl;
    return img;
}
```
