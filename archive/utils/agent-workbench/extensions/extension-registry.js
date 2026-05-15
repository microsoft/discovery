/**
 * Central registry for managing file viewer extensions
 */
class ExtensionRegistry {
    constructor() {
        this.extensions = new Map();
        this.fileTypeMap = new Map();
        this.initialized = false;
    }

    /**
     * Register a new extension
     */
    register(extension) {
        if (!(extension instanceof BaseExtension)) {
            throw new Error('Extension must inherit from BaseExtension');
        }

        this.extensions.set(extension.name, extension);
        
        extension.supportedTypes.forEach(type => {
            if (!this.fileTypeMap.has(type)) {
                this.fileTypeMap.set(type, []);
            }
            this.fileTypeMap.get(type).push(extension);
        });

        return true;
    }

    /**
     * Unregister an extension
     */
    unregister(extensionName) {
        const extension = this.extensions.get(extensionName);
        if (!extension) {
            return false;
        }

        extension.supportedTypes.forEach(type => {
            const extensions = this.fileTypeMap.get(type);
            if (extensions) {
                const index = extensions.indexOf(extension);
                if (index > -1) {
                    extensions.splice(index, 1);
                }
                if (extensions.length === 0) {
                    this.fileTypeMap.delete(type);
                }
            }
        });

        this.extensions.delete(extensionName);
        extension.cleanup();
        
        console.log(`Unregistered extension: ${extensionName}`);
        return true;
    }

    /**
     * Find the best extension for a given file
     * Extensions are checked in priority order (highest first)
     * Each extension's canHandle() determines if it can process the file
     */
    async findExtension(filename, content) {
        const extension = '.' + filename.split('.').pop().toLowerCase();
        const candidates = this.fileTypeMap.get(extension) || [];

        // Sort candidates by priority (highest first)
        const sortedCandidates = [...candidates].sort((a, b) => {
            const priorityA = a.priority ?? 0;
            const priorityB = b.priority ?? 0;
            return priorityB - priorityA;
        });

        for (const candidate of sortedCandidates) {
            try {
                const canHandle = await candidate.canHandle(filename, content);
                if (canHandle) {
                    if (!candidate.initialized) {
                        await candidate.initialize();
                    }
                    return candidate;
                }
            } catch (error) {
                console.warn(`Extension ${candidate.name} failed canHandle check:`, error);
            }
        }

        return null;
    }

    /**
     * Get all registered extensions
     */
    getAllExtensions() {
        return Array.from(this.extensions.values());
    }

    /**
     * Get extensions for a specific file type
     */
    getExtensionsForType(fileType) {
        return this.fileTypeMap.get(fileType) || [];
    }

    /**
     * Get extension by name
     */
    getExtension(name) {
        return this.extensions.get(name);
    }

    /**
     * Check if any extension can handle a file type
     */
    hasExtensionForType(fileType) {
        return this.fileTypeMap.has(fileType) && this.fileTypeMap.get(fileType).length > 0;
    }

    /**
     * Initialize all registered extensions
     */
    async initializeAll() {
        console.log('Initializing all extensions...');
        const initPromises = Array.from(this.extensions.values()).map(async ext => {
            try {
                if (!ext.initialized) {
                    await ext.initialize();
                    console.log(`Initialized extension: ${ext.name}`);
                }
            } catch (error) {
                console.error(`Failed to initialize extension ${ext.name}:`, error);
            }
        });

        await Promise.all(initPromises);
        this.initialized = true;
        console.log('Extension registry initialization complete');
    }

    /**
     * Get registry statistics
     */
    getStats() {
        return {
            totalExtensions: this.extensions.size,
            supportedFileTypes: this.fileTypeMap.size,
            initialized: this.initialized,
            extensions: this.getAllExtensions().map(ext => ext.getMetadata())
        };
    }

    /**
     * Cleanup all extensions
     */
    async cleanup() {
        console.log('Cleaning up extension registry...');
        const cleanupPromises = Array.from(this.extensions.values()).map(ext => ext.cleanup());
        await Promise.all(cleanupPromises);
        
        this.extensions.clear();
        this.fileTypeMap.clear();
        this.initialized = false;
    }
}

// Create singleton instance
const extensionRegistry = new ExtensionRegistry();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = extensionRegistry;
} else if (typeof window !== 'undefined') {
    window.extensionRegistry = extensionRegistry;
}
