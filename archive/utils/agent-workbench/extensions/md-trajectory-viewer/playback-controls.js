/**
 * MD Trajectory Playback Controls
 * 
 * Provides animation and playback functionality for trajectory visualization:
 * - Play/pause/stop controls
 * - Frame-by-frame navigation
 * - Adjustable playback speed
 * - Loop modes (once, loop, bounce)
 * - Timeline scrubbing
 * - Keyboard shortcuts
 * - Touch gesture support
 */

class TrajectoryPlaybackController {
    constructor(options = {}) {
        this.frames = [];
        this.currentFrame = 0;
        this.isPlaying = false;
        this.playbackSpeed = 1.0; // Frames per update
        this.fps = options.fps || 30;
        this.loopMode = 'loop'; // 'once', 'loop', 'bounce'
        this.direction = 1; // 1 = forward, -1 = backward
        
        // Callbacks
        this.onFrameChange = options.onFrameChange || (() => {});
        this.onPlayStateChange = options.onPlayStateChange || (() => {});
        this.onSpeedChange = options.onSpeedChange || (() => {});
        
        // Animation state
        this.animationId = null;
        this.lastTime = 0;
        this.accumulator = 0;
        this.frameInterval = 1000 / this.fps;
        
        // UI elements
        this.container = null;
        this.elements = {};
        
        // Keyboard shortcuts enabled by default
        this.keyboardEnabled = options.keyboardEnabled !== false;
        this.keyHandler = this.handleKeyDown.bind(this);
    }

    /**
     * Initialize with trajectory data
     */
    setTrajectory(frames) {
        this.frames = frames;
        this.currentFrame = 0;
        this.stop();
        this.updateUI();
    }

    /**
     * Create and mount playback UI
     */
    createUI(container) {
        this.container = container;
        
        const controls = document.createElement('div');
        controls.className = 'md-playback-controls';
        
        controls.innerHTML = `
            <div class="md-playback-row">
                <button class="md-playback-btn md-play-btn" title="Play/Pause (Space)">
                    <svg viewBox="0 0 24 24" width="24" height="24">
                        <path class="play-icon" d="M8 5v14l11-7z" fill="currentColor"/>
                        <g class="pause-icon" style="display:none">
                            <rect x="6" y="4" width="4" height="16" fill="currentColor"/>
                            <rect x="14" y="4" width="4" height="16" fill="currentColor"/>
                        </g>
                    </svg>
                </button>
                <button class="md-playback-btn md-stop-btn" title="Stop (S)">
                    <svg viewBox="0 0 24 24" width="20" height="20">
                        <rect x="6" y="6" width="12" height="12" fill="currentColor"/>
                    </svg>
                </button>
                <button class="md-playback-btn md-prev-btn" title="Previous Frame (←)">
                    <svg viewBox="0 0 24 24" width="20" height="20">
                        <path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" fill="currentColor"/>
                    </svg>
                </button>
                <button class="md-playback-btn md-next-btn" title="Next Frame (→)">
                    <svg viewBox="0 0 24 24" width="20" height="20">
                        <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" fill="currentColor"/>
                    </svg>
                </button>
                <div class="md-playback-speed">
                    <label title="Playback Speed">
                        <span class="speed-label">Speed:</span>
                        <select class="md-speed-select">
                            <option value="0.1">0.1x</option>
                            <option value="0.25">0.25x</option>
                            <option value="0.5">0.5x</option>
                            <option value="1" selected>1x</option>
                            <option value="2">2x</option>
                            <option value="4">4x</option>
                            <option value="8">8x</option>
                        </select>
                    </label>
                </div>
                <div class="md-loop-mode">
                    <button class="md-playback-btn md-loop-btn" title="Loop Mode (L)">
                        <svg viewBox="0 0 24 24" width="20" height="20">
                            <path class="loop-icon" d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0020 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 004 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z" fill="currentColor"/>
                        </svg>
                    </button>
                </div>
            </div>
            <div class="md-playback-row">
                <div class="md-timeline-container">
                    <input type="range" class="md-timeline" min="0" max="100" value="0" />
                    <div class="md-timeline-labels">
                        <span class="md-frame-current">Frame 1</span>
                        <span class="md-frame-total">/ 1</span>
                    </div>
                </div>
            </div>
        `;
        
        container.appendChild(controls);
        
        // Store element references
        this.elements = {
            controls,
            playBtn: controls.querySelector('.md-play-btn'),
            stopBtn: controls.querySelector('.md-stop-btn'),
            prevBtn: controls.querySelector('.md-prev-btn'),
            nextBtn: controls.querySelector('.md-next-btn'),
            speedSelect: controls.querySelector('.md-speed-select'),
            loopBtn: controls.querySelector('.md-loop-btn'),
            timeline: controls.querySelector('.md-timeline'),
            frameCurrent: controls.querySelector('.md-frame-current'),
            frameTotal: controls.querySelector('.md-frame-total'),
            playIcon: controls.querySelector('.play-icon'),
            pauseIcon: controls.querySelector('.pause-icon')
        };
        
        this.bindEvents();
        this.updateUI();
        
        return controls;
    }

    /**
     * Bind UI events
     */
    bindEvents() {
        const { playBtn, stopBtn, prevBtn, nextBtn, speedSelect, loopBtn, timeline } = this.elements;
        
        playBtn.addEventListener('click', () => this.togglePlay());
        stopBtn.addEventListener('click', () => this.stop());
        prevBtn.addEventListener('click', () => this.previousFrame());
        nextBtn.addEventListener('click', () => this.nextFrame());
        
        speedSelect.addEventListener('change', (e) => {
            this.setSpeed(parseFloat(e.target.value));
        });
        
        loopBtn.addEventListener('click', () => this.cycleLoopMode());
        
        // Timeline scrubbing with debouncing for large trajectories
        let scrubDebounceTimer = null;
        let lastScrubValue = null;
        
        timeline.addEventListener('input', (e) => {
            const value = parseInt(e.target.value);
            lastScrubValue = value;
            
            // For large trajectories (>10000 frames), debounce to prevent overwhelming the system
            if (this.frames.length > 10000) {
                // Update UI immediately for responsiveness
                const frame = Math.round((value / 100) * (this.frames.length - 1));
                const { frameCurrent } = this.elements;
                if (frameCurrent) {
                    frameCurrent.textContent = frame;
                }
                
                // Debounce the actual frame rendering (300ms delay)
                if (scrubDebounceTimer) {
                    clearTimeout(scrubDebounceTimer);
                }
                scrubDebounceTimer = setTimeout(() => {
                    const finalFrame = Math.round((lastScrubValue / 100) * (this.frames.length - 1));
                    this.goToFrame(finalFrame);
                    scrubDebounceTimer = null;
                }, 300);
            } else {
                // For smaller trajectories, respond immediately
                const frame = Math.round((value / 100) * (this.frames.length - 1));
                this.goToFrame(frame);
            }
        });
        
        // On mouseup/touchend, ensure we render the final frame immediately
        timeline.addEventListener('change', (e) => {
            if (scrubDebounceTimer) {
                clearTimeout(scrubDebounceTimer);
                scrubDebounceTimer = null;
            }
            const frame = Math.round((parseInt(e.target.value) / 100) * (this.frames.length - 1));
            this.goToFrame(frame);
        });
        
        // Keyboard shortcuts
        if (this.keyboardEnabled) {
            document.addEventListener('keydown', this.keyHandler);
        }
        
        // Touch swipe for mobile
        this.setupTouchGestures();
    }

    /**
     * Setup touch gestures for mobile
     */
    setupTouchGestures() {
        if (!this.container) return;
        
        let touchStartX = 0;
        let touchStartY = 0;
        
        this.container.addEventListener('touchstart', (e) => {
            touchStartX = e.touches[0].clientX;
            touchStartY = e.touches[0].clientY;
        }, { passive: true });
        
        this.container.addEventListener('touchend', (e) => {
            const touchEndX = e.changedTouches[0].clientX;
            const touchEndY = e.changedTouches[0].clientY;
            const dx = touchEndX - touchStartX;
            const dy = touchEndY - touchStartY;
            
            // Horizontal swipe
            if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 50) {
                if (dx > 0) {
                    this.previousFrame();
                } else {
                    this.nextFrame();
                }
            }
        }, { passive: true });
    }

    /**
     * Handle keyboard shortcuts
     */
    handleKeyDown(e) {
        // Don't handle if focused on input
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        
        switch (e.code) {
            case 'Space':
                e.preventDefault();
                this.togglePlay();
                break;
            case 'ArrowLeft':
                e.preventDefault();
                this.previousFrame();
                break;
            case 'ArrowRight':
                e.preventDefault();
                this.nextFrame();
                break;
            case 'KeyS':
                this.stop();
                break;
            case 'KeyL':
                this.cycleLoopMode();
                break;
            case 'Home':
                this.goToFrame(0);
                break;
            case 'End':
                this.goToFrame(this.frames.length - 1);
                break;
            case 'BracketLeft': // [
                this.slowDown();
                break;
            case 'BracketRight': // ]
                this.speedUp();
                break;
        }
    }

    /**
     * Update UI state
     */
    updateUI() {
        if (!this.elements.controls) return;
        
        const { timeline, frameCurrent, frameTotal, playIcon, pauseIcon, loopBtn, speedSelect } = this.elements;
        
        // Update timeline
        if (this.frames.length > 1) {
            timeline.max = 100;
            timeline.value = (this.currentFrame / (this.frames.length - 1)) * 100;
        } else {
            timeline.value = 0;
        }
        
        // Update frame labels
        frameCurrent.textContent = `Frame ${this.currentFrame + 1}`;
        frameTotal.textContent = `/ ${this.frames.length}`;
        
        // Update play/pause icon
        if (this.isPlaying) {
            playIcon.style.display = 'none';
            pauseIcon.style.display = 'block';
        } else {
            playIcon.style.display = 'block';
            pauseIcon.style.display = 'none';
        }
        
        // Update loop button appearance
        loopBtn.classList.toggle('active', this.loopMode !== 'once');
        loopBtn.title = `Loop: ${this.loopMode} (L)`;
        
        // Update speed select
        speedSelect.value = this.playbackSpeed.toString();
    }

    // ===========================
    // PLAYBACK CONTROLS
    // ===========================

    play() {
        if (this.frames.length < 2) return;
        
        this.isPlaying = true;
        this.lastTime = performance.now();
        this.accumulator = 0;
        this.animate();
        this.onPlayStateChange(true);
        this.updateUI();
    }

    pause() {
        this.isPlaying = false;
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        this.onPlayStateChange(false);
        this.updateUI();
    }

    togglePlay() {
        if (this.isPlaying) {
            this.pause();
        } else {
            this.play();
        }
    }

    stop() {
        this.pause();
        this.goToFrame(0);
        this.direction = 1;
    }

    nextFrame() {
        this.goToFrame(this.currentFrame + 1);
    }

    previousFrame() {
        this.goToFrame(this.currentFrame - 1);
    }

    goToFrame(frame) {
        if (this.frames.length === 0) return;
        
        // Handle wrapping
        if (frame >= this.frames.length) {
            if (this.loopMode === 'loop') {
                frame = 0;
            } else if (this.loopMode === 'bounce') {
                frame = this.frames.length - 2;
                this.direction = -1;
            } else {
                frame = this.frames.length - 1;
                if (this.isPlaying) {
                    this.pause();
                }
            }
        } else if (frame < 0) {
            if (this.loopMode === 'loop') {
                frame = this.frames.length - 1;
            } else if (this.loopMode === 'bounce') {
                frame = 1;
                this.direction = 1;
            } else {
                frame = 0;
                if (this.isPlaying) {
                    this.pause();
                }
            }
        }
        
        this.currentFrame = frame;
        this.onFrameChange(frame, this.frames[frame]);
        this.updateUI();
    }

    /**
     * Animation loop
     */
    animate() {
        if (!this.isPlaying) return;
        
        const currentTime = performance.now();
        const deltaTime = currentTime - this.lastTime;
        this.lastTime = currentTime;
        
        this.accumulator += deltaTime * this.playbackSpeed;
        
        if (this.accumulator >= this.frameInterval) {
            const framesToAdvance = Math.floor(this.accumulator / this.frameInterval);
            this.accumulator %= this.frameInterval;
            
            let newFrame = this.currentFrame + (framesToAdvance * this.direction);
            this.goToFrame(newFrame);
        }
        
        this.animationId = requestAnimationFrame(() => this.animate());
    }

    // ===========================
    // SPEED CONTROLS
    // ===========================

    setSpeed(speed) {
        this.playbackSpeed = Math.max(0.1, Math.min(10, speed));
        this.onSpeedChange(this.playbackSpeed);
        this.updateUI();
    }

    speedUp() {
        const speeds = [0.1, 0.25, 0.5, 1, 2, 4, 8];
        const currentIdx = speeds.indexOf(this.playbackSpeed);
        if (currentIdx < speeds.length - 1) {
            this.setSpeed(speeds[currentIdx + 1]);
        } else if (currentIdx === -1) {
            this.setSpeed(speeds[speeds.length - 1]);
        }
    }

    slowDown() {
        const speeds = [0.1, 0.25, 0.5, 1, 2, 4, 8];
        const currentIdx = speeds.indexOf(this.playbackSpeed);
        if (currentIdx > 0) {
            this.setSpeed(speeds[currentIdx - 1]);
        } else if (currentIdx === -1) {
            this.setSpeed(speeds[0]);
        }
    }

    // ===========================
    // LOOP MODE
    // ===========================

    setLoopMode(mode) {
        this.loopMode = mode;
        this.updateUI();
    }

    cycleLoopMode() {
        const modes = ['once', 'loop', 'bounce'];
        const currentIdx = modes.indexOf(this.loopMode);
        this.loopMode = modes[(currentIdx + 1) % modes.length];
        this.updateUI();
    }

    // ===========================
    // CLEANUP
    // ===========================

    destroy() {
        this.pause();
        
        if (this.keyboardEnabled) {
            document.removeEventListener('keydown', this.keyHandler);
        }
        
        if (this.elements.controls && this.elements.controls.parentNode) {
            this.elements.controls.parentNode.removeChild(this.elements.controls);
        }
        
        this.elements = {};
        this.frames = [];
    }

    // ===========================
    // STATE GETTERS
    // ===========================

    get frameCount() {
        return this.frames.length;
    }

    get progress() {
        return this.frames.length > 1 
            ? this.currentFrame / (this.frames.length - 1) 
            : 0;
    }

    getFrameData(frame = this.currentFrame) {
        return this.frames[frame] || null;
    }
}

/**
 * Frame Interpolator for smooth animation
 */
class FrameInterpolator {
    constructor(options = {}) {
        this.interpolationMethod = options.method || 'linear';
    }

    /**
     * Interpolate between two frames
     */
    interpolate(frame1, frame2, t) {
        if (!frame1 || !frame2) return frame1 || frame2;
        if (frame1.atoms.length !== frame2.atoms.length) return frame1;
        
        const result = {
            atoms: [],
            box: this.interpolateBox(frame1.box, frame2.box, t),
            time: this.lerp(frame1.time || 0, frame2.time || 0, t)
        };

        for (let i = 0; i < frame1.atoms.length; i++) {
            const a1 = frame1.atoms[i];
            const a2 = frame2.atoms[i];
            
            result.atoms.push({
                symbol: a1.symbol,
                x: this.lerp(a1.x, a2.x, t),
                y: this.lerp(a1.y, a2.y, t),
                z: this.lerp(a1.z, a2.z, t),
                vx: this.lerp(a1.vx || 0, a2.vx || 0, t),
                vy: this.lerp(a1.vy || 0, a2.vy || 0, t),
                vz: this.lerp(a1.vz || 0, a2.vz || 0, t)
            });
        }

        return result;
    }

    /**
     * Linear interpolation
     */
    lerp(a, b, t) {
        return a + (b - a) * t;
    }

    /**
     * Smooth step interpolation
     */
    smoothstep(a, b, t) {
        t = t * t * (3 - 2 * t);
        return this.lerp(a, b, t);
    }

    /**
     * Interpolate box dimensions
     */
    interpolateBox(box1, box2, t) {
        if (!box1 || !box2) return box1 || box2;
        
        return {
            min: {
                x: this.lerp(box1.min.x, box2.min.x, t),
                y: this.lerp(box1.min.y, box2.min.y, t),
                z: this.lerp(box1.min.z, box2.min.z, t)
            },
            max: {
                x: this.lerp(box1.max.x, box2.max.x, t),
                y: this.lerp(box1.max.y, box2.max.y, t),
                z: this.lerp(box1.max.z, box2.max.z, t)
            }
        };
    }
}

/**
 * Frame Streamer for large trajectories
 * Loads frames on-demand to reduce memory usage
 */
class TrajectoryStreamer {
    constructor(options = {}) {
        this.chunkSize = options.chunkSize || 100;
        this.maxCached = options.maxCached || 500;
        this.parser = options.parser || null;
        
        this.frameCache = new Map();
        this.totalFrames = 0;
        this.loadedChunks = new Set();
        
        this.onProgress = options.onProgress || (() => {});
    }

    /**
     * Initialize streamer with raw file content
     */
    async initialize(content, format) {
        // Quick scan to count frames
        const framePositions = this.scanFramePositions(content, format);
        this.totalFrames = framePositions.length;
        this.framePositions = framePositions;
        this.content = content;
        this.format = format;
        
        // Preload first chunk
        await this.loadChunk(0);
        
        return this.totalFrames;
    }

    /**
     * Scan content to find frame start positions
     */
    scanFramePositions(content, format) {
        const positions = [];
        const lines = content.split('\n');
        
        let lineIndex = 0;
        
        if (format === 'xyz') {
            while (lineIndex < lines.length) {
                const countLine = lines[lineIndex].trim();
                if (/^\d+$/.test(countLine)) {
                    positions.push(lineIndex);
                    const atomCount = parseInt(countLine);
                    lineIndex += atomCount + 2; // Count + comment + atoms
                } else {
                    lineIndex++;
                }
            }
        } else if (format === 'lammpstrj') {
            for (let i = 0; i < lines.length; i++) {
                if (lines[i].trim() === 'ITEM: TIMESTEP') {
                    positions.push(i);
                }
            }
        } else if (format === 'pdb') {
            for (let i = 0; i < lines.length; i++) {
                if (lines[i].startsWith('MODEL') || 
                    (lines[i].startsWith('ATOM') && (i === 0 || lines[i-1].startsWith('END')))) {
                    positions.push(i);
                }
            }
        }
        
        return positions;
    }

    /**
     * Load a chunk of frames
     */
    async loadChunk(chunkIndex) {
        if (this.loadedChunks.has(chunkIndex)) return;
        
        const startFrame = chunkIndex * this.chunkSize;
        const endFrame = Math.min(startFrame + this.chunkSize, this.totalFrames);
        
        for (let f = startFrame; f < endFrame; f++) {
            if (!this.frameCache.has(f)) {
                const frame = this.parseFrame(f);
                this.frameCache.set(f, frame);
            }
        }
        
        this.loadedChunks.add(chunkIndex);
        
        // Evict old chunks if cache is too large
        this.evictIfNeeded();
        
        this.onProgress({
            loaded: this.frameCache.size,
            total: this.totalFrames
        });
    }

    /**
     * Parse a single frame from content
     */
    parseFrame(frameIndex) {
        if (!this.content || frameIndex >= this.framePositions.length) {
            return null;
        }
        
        const startLine = this.framePositions[frameIndex];
        const endLine = frameIndex < this.framePositions.length - 1 
            ? this.framePositions[frameIndex + 1]
            : undefined;
        
        const lines = this.content.split('\n');
        const frameLines = lines.slice(startLine, endLine).join('\n');
        
        // Use parser to parse single frame
        if (this.parser) {
            const result = this.parser.parse(frameLines, this.format);
            return result.frames[0] || null;
        }
        
        return null;
    }

    /**
     * Get a frame (loads if not cached)
     */
    async getFrame(frameIndex) {
        if (this.frameCache.has(frameIndex)) {
            return this.frameCache.get(frameIndex);
        }
        
        const chunkIndex = Math.floor(frameIndex / this.chunkSize);
        await this.loadChunk(chunkIndex);
        
        return this.frameCache.get(frameIndex);
    }

    /**
     * Preload frames around current position
     */
    async preloadAround(frameIndex, range = 50) {
        const startChunk = Math.floor(Math.max(0, frameIndex - range) / this.chunkSize);
        const endChunk = Math.floor(Math.min(this.totalFrames - 1, frameIndex + range) / this.chunkSize);
        
        for (let c = startChunk; c <= endChunk; c++) {
            await this.loadChunk(c);
        }
    }

    /**
     * Evict old frames if cache is too large
     */
    evictIfNeeded() {
        if (this.frameCache.size <= this.maxCached) return;
        
        // Remove oldest entries (simple LRU would be better)
        const toRemove = this.frameCache.size - this.maxCached;
        let removed = 0;
        
        for (const key of this.frameCache.keys()) {
            if (removed >= toRemove) break;
            this.frameCache.delete(key);
            removed++;
        }
        
        // Update loaded chunks
        this.loadedChunks.clear();
        for (const key of this.frameCache.keys()) {
            this.loadedChunks.add(Math.floor(key / this.chunkSize));
        }
    }

    /**
     * Clear all cached data
     */
    clear() {
        this.frameCache.clear();
        this.loadedChunks.clear();
        this.content = null;
        this.framePositions = [];
    }
}

// Export
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        TrajectoryPlaybackController,
        FrameInterpolator,
        TrajectoryStreamer
    };
} else if (typeof window !== 'undefined') {
    window.TrajectoryPlaybackController = TrajectoryPlaybackController;
    window.FrameInterpolator = FrameInterpolator;
    window.TrajectoryStreamer = TrajectoryStreamer;
}
