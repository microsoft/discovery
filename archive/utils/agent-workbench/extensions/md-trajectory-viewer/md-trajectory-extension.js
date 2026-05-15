/**
 * MD Trajectory Viewer Extension
 * State-of-the-Art Molecular Dynamics Visualization with WebGPU + WebAssembly
 * 
 * Supports: XYZ, LAMMPS dump (.lammpstrj), GSD, H5MD, XTC, TRR, and multi-model PDB
 * Features:
 * - WebGPU rendering with WebGL fallback
 * - Trajectory streaming and frame-by-frame playback
 * - Multiple representation styles
 * - Real-time analysis tools
 * - Fully offline operation
 * 
 * @author Discovery Agent Workbench
 * @version 1.0.0
 */

class MDTrajectoryExtension extends BaseExtension {
    constructor() {
        super('MD Trajectory Viewer', ['.xyz', '.lammpstrj', '.lammps', '.gsd', '.h5md', '.xtc', '.trr', '.dcd'], {
            hasPreview: true,
            hasFullView: true,
            interactive: true,
            resizable: true,
            // Priority 10: Higher than default (0) so we get first chance at trajectory files
            // For XYZ, we'll use smart detection in canHandle() to only claim multi-frame files
            priority: 10
        });
        
        // Rendering engine instances per container
        this.viewers = new Map();
        
        // Frame cache for progressive loading: Map<filename, Map<frameIndex, frameData>>
        this.frameCache = new Map();
        
        // Track pending frame fetches: Map<"filename:frameIndex", Promise>
        this.pendingFrames = new Map();
        
        // Trajectory metadata cache: Map<filename, {frameCount, atomCount, format, symbols, etc.}>
        this.trajectoryMetadata = new Map();
        
        // Geometry cache for pre-built ribbon/cartoon meshes: Map<filename, Map<frameIndex, THREE.Group>>
        this.geometryCache = new Map();
        
        // Background geometry builder state
        this.geometryBuilder = {
            isBuilding: false,
            cancelRequested: false,
            currentFilename: null,
            currentRepresentation: null,
            progress: 0
        };
        
        // WebGPU support flag
        this.webgpuSupported = false;
        this.webgpuChecked = false;
        
        // Element color scheme (CPK colors)
        this.atomColors = {
            'H':  0xFFFFFF, 'He': 0xD9FFFF, 'Li': 0xCC80FF, 'Be': 0xC2FF00,
            'B':  0xFFB5B5, 'C':  0x909090, 'N':  0x3050F8, 'O':  0xFF0D0D,
            'F':  0x90E050, 'Ne': 0xB3E3F5, 'Na': 0xAB5CF2, 'Mg': 0x8AFF00,
            'Al': 0xBFA6A6, 'Si': 0xF0C8A0, 'P':  0xFF8000, 'S':  0xFFFF30,
            'Cl': 0x1FF01F, 'Ar': 0x80D1E3, 'K':  0x8F40D4, 'Ca': 0x3DFF00,
            'Fe': 0xE06633, 'Cu': 0xC88033, 'Zn': 0x7D80B0, 'Br': 0xA62929,
            'I':  0x940094, 'default': 0xFF1493
        };
        
        // Atom radii (van der Waals, scaled)
        this.atomRadii = {
            'H':  0.31, 'He': 0.28, 'Li': 0.53, 'Be': 0.40,
            'B':  0.38, 'C':  0.40, 'N':  0.37, 'O':  0.36,
            'F':  0.32, 'Ne': 0.34, 'Na': 0.59, 'Mg': 0.52,
            'Al': 0.50, 'Si': 0.46, 'P':  0.44, 'S':  0.43,
            'Cl': 0.43, 'Ar': 0.40, 'K':  0.68, 'Ca': 0.62,
            'Fe': 0.48, 'Cu': 0.45, 'Zn': 0.46, 'Br': 0.47,
            'I':  0.53, 'default': 0.40
        };
        
        // Representation modes
        this.representationModes = [
            { id: 'ribbon', name: 'Ribbon', icon: '🎗️' },
            { id: 'cartoon', name: 'Cartoon', icon: '🎀' },
            { id: 'ball-stick', name: 'Ball & Stick', icon: '⚛️' },
            { id: 'spacefill', name: 'Spacefill', icon: '🔴' },
            { id: 'wireframe', name: 'Wireframe', icon: '🔗' },
            { id: 'points', name: 'Points', icon: '⬤' },
            { id: 'licorice', name: 'Licorice', icon: '📏' }
        ];

        // Initialize XTC parser utilities (based on NGL Viewer, MIT License)
        // https://github.com/nglviewer/ngl - Copyright (c) 2014-2017 Alexander S Rose
        this._initXtcParser();
    }

    /**
     * Initialize XTC parser constants and helper functions
     * Ported from NGL Viewer's xtc-parser.ts (MIT License)
     */
    _initXtcParser() {
        // Magic integer lookup table for XTC compression
        this._xtcMagicInts = new Uint32Array([
            0, 0, 0, 0, 0, 0, 0, 0, 0, 8, 10, 12, 16, 20, 25, 32, 40, 50, 64,
            80, 101, 128, 161, 203, 256, 322, 406, 512, 645, 812, 1024, 1290,
            1625, 2048, 2580, 3250, 4096, 5060, 6501, 8192, 10321, 13003,
            16384, 20642, 26007, 32768, 41285, 52015, 65536, 82570, 104031,
            131072, 165140, 208063, 262144, 330280, 416127, 524287, 660561,
            832255, 1048576, 1321122, 1664510, 2097152, 2642245, 3329021,
            4194304, 5284491, 6658042, 8388607, 10568983, 13316085, 16777216
        ]);
        this._xtcFirstIdx = 9;
        this._xtcTmpBytes = new Uint8Array(32);
        this._xtcTmpIntBytes = new Int32Array(32);
    }

    /**
     * Calculate bit size needed for an integer value
     */
    _xtcSizeOfInt(size) {
        let num = 1;
        let numOfBits = 0;
        while (size >= num && numOfBits < 32) {
            numOfBits++;
            num <<= 1;
        }
        return numOfBits;
    }

    /**
     * Calculate total bits needed for multiple integers
     */
    _xtcSizeOfInts(numOfInts, sizes) {
        let numOfBytes = 1;
        let numOfBits = 0;
        this._xtcTmpBytes[0] = 1;
        for (let i = 0; i < numOfInts; i++) {
            let bytecnt;
            let tmp = 0;
            for (bytecnt = 0; bytecnt < numOfBytes; bytecnt++) {
                tmp += this._xtcTmpBytes[bytecnt] * sizes[i];
                this._xtcTmpBytes[bytecnt] = tmp & 0xff;
                tmp >>= 8;
            }
            while (tmp !== 0) {
                this._xtcTmpBytes[bytecnt++] = tmp & 0xff;
                tmp >>= 8;
            }
            numOfBytes = bytecnt;
        }
        let num = 1;
        numOfBytes--;
        while (this._xtcTmpBytes[numOfBytes] >= num) {
            numOfBits++;
            num *= 2;
        }
        return numOfBits + numOfBytes * 8;
    }

    /**
     * Decode bits from compressed buffer
     */
    _xtcDecodeBits(buf, cbuf, numOfBits, buf2) {
        const mask = (1 << numOfBits) - 1;
        let lastBB0 = buf2[1];
        let lastBB1 = buf2[2];
        let cnt = buf[0];
        let num = 0;

        while (numOfBits >= 8) {
            lastBB1 = (lastBB1 << 8) | cbuf[cnt++];
            num |= (lastBB1 >> lastBB0) << (numOfBits - 8);
            numOfBits -= 8;
        }

        if (numOfBits > 0) {
            if (lastBB0 < numOfBits) {
                lastBB0 += 8;
                lastBB1 = (lastBB1 << 8) | cbuf[cnt++];
            }
            lastBB0 -= numOfBits;
            num |= (lastBB1 >> lastBB0) & ((1 << numOfBits) - 1);
        }

        num &= mask;
        buf[0] = cnt;
        buf[1] = lastBB0;
        buf[2] = lastBB1;

        return num;
    }

    /**
     * Decode multiple integers from compressed data
     */
    _xtcDecodeInts(buf, cbuf, numOfInts, numOfBits, sizes, nums, buf2) {
        let numOfBytes = 0;
        this._xtcTmpIntBytes[1] = 0;
        this._xtcTmpIntBytes[2] = 0;
        this._xtcTmpIntBytes[3] = 0;

        while (numOfBits > 8) {
            this._xtcTmpIntBytes[numOfBytes++] = this._xtcDecodeBits(buf, cbuf, 8, buf2);
            numOfBits -= 8;
        }

        if (numOfBits > 0) {
            this._xtcTmpIntBytes[numOfBytes++] = this._xtcDecodeBits(buf, cbuf, numOfBits, buf2);
        }

        for (let i = numOfInts - 1; i > 0; i--) {
            let num = 0;
            for (let j = numOfBytes - 1; j >= 0; j--) {
                num = (num << 8) | this._xtcTmpIntBytes[j];
                const p = (num / sizes[i]) | 0;
                this._xtcTmpIntBytes[j] = p;
                num = num - p * sizes[i];
            }
            nums[i] = num;
        }
        nums[0] = (
            this._xtcTmpIntBytes[0] |
            (this._xtcTmpIntBytes[1] << 8) |
            (this._xtcTmpIntBytes[2] << 16) |
            (this._xtcTmpIntBytes[3] << 24)
        );
    }

    /**
     * Parse TRR binary trajectory file (GROMACS full precision format)
     * Based on GROMACS fileio/trrio.cpp specification
     * Supports both single (magic 1987) and double (magic 1993) precision
     * @param {ArrayBuffer} buffer - The raw binary TRR data
     * @param {string} filename - The filename for logging
     * @param {number} magic - The magic number (1987 or 1993)
     * @returns {Object} Parsed trajectory in standard format
     */
    parseTrrBinary(buffer, filename, magic) {
        console.log(`[TRR Parser] Parsing binary TRR: ${filename} (${buffer.byteLength} bytes)`);

        const dv = new DataView(buffer);
        const frames = [];
        const times = [];
        const boxes = [];

        // Detect endianness by checking if values make sense
        let bigEndian = true;
        let offset = 4; // Skip magic

        const isDouble = (magic === MDTrajectoryExtension.MAGIC_TRR_DBL);
        const floatSize = isDouble ? 8 : 4;

        console.log(`[TRR Parser] Precision: ${isDouble ? 'double' : 'single'} (${floatSize} bytes/float)`);

        // Try to read version string length - should be a small positive number
        let slen = dv.getInt32(offset, false); // big-endian
        const slenLE = dv.getInt32(offset, true); // little-endian

        console.log(`[TRR Parser] Version string length candidates: BE=${slen}, LE=${slenLE}`);

        // Heuristic: valid slen should be 0-200 (typical is ~13 for "GMX_trn_file")
        let hasVersionString = true;
        if (slen >= 0 && slen <= 200) {
            // Big-endian slen is valid
            console.log(`[TRR Parser] Using big-endian, slen=${slen}`);
        } else if (slenLE >= 0 && slenLE <= 200) {
            // Little-endian slen is valid
            console.log(`[TRR Parser] Switching to little-endian, slen=${slenLE}`);
            bigEndian = false;
            slen = slenLE;
        } else {
            // Neither endianness gives valid slen - this file may not have a version string
            // Don't skip the slen field - treat offset 4 as start of frame headers
            console.warn(`[TRR Parser] No valid version string length found (BE=${slen}, LE=${slenLE})`);
            console.log(`[TRR Parser] Trying to parse without version string header...`);
            hasVersionString = false;
            // Don't advance offset - bytes at offset 4 might be frame header
        }

        if (hasVersionString) {
            offset += 4; // Skip slen field
            if (slen > 0) {
                const versionBytes = new Uint8Array(buffer, offset, Math.min(slen, buffer.byteLength - offset));
                const version = new TextDecoder().decode(versionBytes).replace(/\0/g, '');
                console.log(`[TRR Parser] Version string: "${version}"`);
                offset += slen;
            }
        }

        let frameIndex = 0;
        let natoms = 0;
        let hasVelocities = false;
        let hasForces = false;

        // Helper to validate frame header values
        const isValidFrameHeader = (ir, e, box, vir, pres, top, sym, x, v, f, atoms, step) => {
            // All sizes should be non-negative and reasonable
            if (ir < 0 || e < 0 || box < 0 || vir < 0 || pres < 0 || top < 0 || sym < 0 || x < 0 || v < 0 || f < 0) return false;
            // Sizes shouldn't be larger than the file
            const totalSize = ir + e + box + vir + pres + top + sym + x + v + f;
            if (totalSize > buffer.byteLength) return false;
            // Atom count should be positive and reasonable
            if (atoms <= 0 || atoms > 10000000) return false;
            // Step should be non-negative
            if (step < 0) return false;
            // x_size should match natoms * 3 * floatSize if coordinates are present
            if (x > 0 && x !== atoms * 3 * floatSize) return false;
            return true;
        };

        // Try reading first frame header to validate endianness
        const tryReadHeader = (endian) => {
            const read = endian ? (o) => dv.getInt32(o, false) : (o) => dv.getInt32(o, true);
            return {
                ir_size: read(offset), e_size: read(offset + 4), box_size: read(offset + 8),
                vir_size: read(offset + 12), pres_size: read(offset + 16), top_size: read(offset + 20),
                sym_size: read(offset + 24), x_size: read(offset + 28), v_size: read(offset + 32),
                f_size: read(offset + 36), natoms: read(offset + 40), step: read(offset + 44)
            };
        };

        // Test both endiannesses for first frame header
        let headerBE = tryReadHeader(true);
        let headerLE = tryReadHeader(false);

        const validBE = isValidFrameHeader(headerBE.ir_size, headerBE.e_size, headerBE.box_size,
            headerBE.vir_size, headerBE.pres_size, headerBE.top_size, headerBE.sym_size,
            headerBE.x_size, headerBE.v_size, headerBE.f_size, headerBE.natoms, headerBE.step);
        const validLE = isValidFrameHeader(headerLE.ir_size, headerLE.e_size, headerLE.box_size,
            headerLE.vir_size, headerLE.pres_size, headerLE.top_size, headerLE.sym_size,
            headerLE.x_size, headerLE.v_size, headerLE.f_size, headerLE.natoms, headerLE.step);

        console.log(`[TRR Parser] Frame header validation: BE=${validBE}, LE=${validLE}`);
        console.log(`[TRR Parser] BE header: natoms=${headerBE.natoms}, x_size=${headerBE.x_size}, step=${headerBE.step}`);
        console.log(`[TRR Parser] LE header: natoms=${headerLE.natoms}, x_size=${headerLE.x_size}, step=${headerLE.step}`);

        if (!validBE && !validLE) {
            throw new Error(`Cannot parse TRR file: frame header is invalid in both endiannesses. ` +
                `The file may be corrupted or in an unsupported format. ` +
                `(BE natoms=${headerBE.natoms}, LE natoms=${headerLE.natoms})`);
        }

        if (validLE && !validBE) {
            console.log(`[TRR Parser] Confirmed little-endian from frame header`);
            bigEndian = false;
        } else if (validBE) {
            console.log(`[TRR Parser] Confirmed big-endian from frame header`);
        }

        // Update read functions based on confirmed endianness
        const readInt32 = bigEndian
            ? (o) => dv.getInt32(o, false)
            : (o) => dv.getInt32(o, true);
        const readFloat = isDouble
            ? (bigEndian ? (o) => dv.getFloat64(o, false) : (o) => dv.getFloat64(o, true))
            : (bigEndian ? (o) => dv.getFloat32(o, false) : (o) => dv.getFloat32(o, true));

        try {
            // Parse frames
            while (offset < buffer.byteLength - 52) {
                try {
                    // Frame header: 13 int32 values
                    const ir_size = readInt32(offset);
                    const e_size = readInt32(offset + 4);
                    const box_size = readInt32(offset + 8);
                    const vir_size = readInt32(offset + 12);
                    const pres_size = readInt32(offset + 16);
                    const top_size = readInt32(offset + 20);
                    const sym_size = readInt32(offset + 24);
                    const x_size = readInt32(offset + 28);
                    const v_size = readInt32(offset + 32);
                    const f_size = readInt32(offset + 36);
                    natoms = readInt32(offset + 40);
                    const step = readInt32(offset + 44);
                    const nre = readInt32(offset + 48);
                    offset += 52;

                    // Validate atom count
                    if (natoms <= 0 || natoms > 100000000) {
                        if (frameIndex === 0) {
                            throw new Error(`Invalid atom count: ${natoms}`);
                        }
                        console.warn(`[TRR Parser] Invalid atom count ${natoms} at frame ${frameIndex}, stopping`);
                        break;
                    }

                    // Read time and lambda
                    const time = readFloat(offset);
                    offset += floatSize;
                    const lambda = readFloat(offset);
                    offset += floatSize;

                    times.push(time);

                    if (frameIndex === 0) {
                        console.log(`[TRR Parser] Frame 0: ${natoms} atoms, step ${step}, time ${time.toFixed(3)} ps`);
                        console.log(`[TRR Parser] Data: box=${box_size}, x=${x_size}, v=${v_size}, f=${f_size} bytes`);
                        hasVelocities = v_size > 0;
                        hasForces = f_size > 0;
                    }

                    // Read box (3x3 matrix in nm -> convert to Å)
                    const box = new Float32Array(9);
                    if (box_size > 0) {
                        for (let i = 0; i < 9; i++) {
                            box[i] = readFloat(offset) * 10;
                            offset += floatSize;
                        }
                    }
                    boxes.push(box);

                    // Read coordinates (nm -> Å)
                    const atoms = [];
                    if (x_size > 0) {
                        for (let i = 0; i < natoms; i++) {
                            atoms.push({
                                symbol: 'C',
                                atomname: '',
                                ss: 'C',
                                x: readFloat(offset) * 10,
                                y: readFloat(offset + floatSize) * 10,
                                z: readFloat(offset + floatSize * 2) * 10
                            });
                            offset += floatSize * 3;
                        }
                    }

                    // Skip velocities and forces (we don't visualize them currently)
                    if (v_size > 0) offset += v_size;
                    if (f_size > 0) offset += f_size;

                    frames.push({
                        frameIndex: frameIndex++,
                        time,
                        step,
                        atoms
                    });

                    // Progress logging
                    if (frameIndex % 100 === 0) {
                        console.log(`[TRR Parser] Parsed ${frameIndex} frames...`);
                    }

                } catch (frameError) {
                    console.warn(`[TRR Parser] Error at frame ${frameIndex}:`, frameError.message);
                    break;
                }
            }

            console.log(`[TRR Parser] Completed: ${frames.length} frames, ${natoms} atoms, velocities=${hasVelocities}, forces=${hasForces}`);

            return {
                format: 'trr',
                filename,
                atomCount: natoms,
                frameCount: frames.length,
                frames,
                times,
                boxes,
                hasVelocities,
                hasForces,
                serverParsed: false,
                clientParsed: true
            };

        } catch (error) {
            console.error(`[TRR Parser] Fatal error:`, error);
            throw new Error(`Failed to parse TRR file: ${error.message}`);
        }
    }

    /**
     * Parse DCD binary trajectory file (CHARMM/NAMD format)
     * Based on MDAnalysis DCD specification
     * @param {ArrayBuffer} buffer - The raw binary DCD data
     * @param {string} filename - The filename for logging
     * @returns {Object} Parsed trajectory in standard format
     */
    parseDcdBinary(buffer, filename) {
        console.log(`[DCD Parser] Parsing binary DCD: ${filename} (${buffer.byteLength} bytes)`);

        const dv = new DataView(buffer);
        const frames = [];
        const times = [];
        const boxes = [];

        let offset = 0;

        try {
            // DCD uses Fortran record markers (little-endian)
            let recLen = dv.getInt32(offset, true);
            offset += 4;

            if (recLen !== 84) {
                throw new Error(`Invalid DCD header: expected record length 84, got ${recLen}`);
            }

            // Signature check
            const sig = String.fromCharCode(dv.getUint8(offset), dv.getUint8(offset + 1),
                                           dv.getUint8(offset + 2), dv.getUint8(offset + 3));
            if (sig !== 'CORD') {
                throw new Error(`Invalid DCD signature: "${sig}"`);
            }
            offset += 4;

            // Header values
            const nframes = dv.getInt32(offset, true);
            const istart = dv.getInt32(offset + 4, true);
            const nsavc = dv.getInt32(offset + 8, true);
            offset += 36; // Skip to delta
            const delta = dv.getFloat32(offset, true);
            offset += 4;
            const hasUnitCell = dv.getInt32(offset, true);
            offset += 44; // Skip to end of first record

            // End marker + title record
            offset += 4;
            recLen = dv.getInt32(offset, true);
            offset += 4;
            const ntitle = dv.getInt32(offset, true);
            offset += 4 + ntitle * 80 + 4;

            // Atom count record
            offset += 4; // Start marker
            const natoms = dv.getInt32(offset, true);
            offset += 8; // natoms + end marker

            console.log(`[DCD Parser] Header: ${nframes} frames, ${natoms} atoms, delta=${delta.toFixed(4)} ps`);

            // Parse frames
            for (let frameIdx = 0; frameIdx < nframes && offset < buffer.byteLength - natoms * 12; frameIdx++) {
                try {
                    const time = (istart + frameIdx * nsavc) * delta;
                    times.push(time);

                    // Unit cell if present
                    const box = new Float32Array(9);
                    if (hasUnitCell) {
                        offset += 4; // Start marker
                        box[0] = dv.getFloat64(offset, true);      // A
                        box[4] = dv.getFloat64(offset + 16, true); // B
                        box[8] = dv.getFloat64(offset + 40, true); // C
                        offset += 48 + 4; // Data + end marker
                    }
                    boxes.push(box);

                    // X, Y, Z coordinates (separate arrays)
                    const atoms = new Array(natoms);

                    // X coordinates
                    offset += 4;
                    for (let i = 0; i < natoms; i++) {
                        atoms[i] = { symbol: 'C', atomname: '', ss: 'C', x: dv.getFloat32(offset, true), y: 0, z: 0 };
                        offset += 4;
                    }
                    offset += 4;

                    // Y coordinates
                    offset += 4;
                    for (let i = 0; i < natoms; i++) {
                        atoms[i].y = dv.getFloat32(offset, true);
                        offset += 4;
                    }
                    offset += 4;

                    // Z coordinates
                    offset += 4;
                    for (let i = 0; i < natoms; i++) {
                        atoms[i].z = dv.getFloat32(offset, true);
                        offset += 4;
                    }
                    offset += 4;

                    frames.push({ frameIndex: frameIdx, time, atoms });

                    if ((frameIdx + 1) % 100 === 0) {
                        console.log(`[DCD Parser] Parsed ${frameIdx + 1}/${nframes} frames...`);
                    }

                } catch (frameError) {
                    console.warn(`[DCD Parser] Error at frame ${frameIdx}:`, frameError.message);
                    break;
                }
            }

            console.log(`[DCD Parser] Completed: ${frames.length} frames, ${natoms} atoms`);

            return {
                format: 'dcd',
                filename,
                atomCount: natoms,
                frameCount: frames.length,
                frames,
                times,
                boxes,
                hasVelocities: false,
                hasForces: false,
                serverParsed: false,
                clientParsed: true
            };

        } catch (error) {
            console.error(`[DCD Parser] Fatal error:`, error);
            throw new Error(`Failed to parse DCD file: ${error.message}`);
        }
    }

    /**
     * Parse XTC binary trajectory file (GROMACS compressed format)
     * Based on NGL Viewer's xtc-parser.ts (MIT License)
     * @param {ArrayBuffer} buffer - The raw binary XTC data
     * @param {string} filename - The filename for logging
     * @returns {Object} Parsed trajectory in standard format
     */
    parseXtcBinary(buffer, filename) {
        console.log(`[XTC Parser] Parsing binary XTC: ${filename} (${buffer.byteLength} bytes)`);

        const dv = new DataView(buffer);
        const frames = [];
        const times = [];
        const boxes = [];

        const minMaxInt = new Int32Array(6);
        const sizeint = new Int32Array(3);
        const bitsizeint = new Int32Array(3);
        const sizesmall = new Uint32Array(3);
        const thiscoord = new Float32Array(3);
        const prevcoord = new Float32Array(3);

        let offset = 0;
        const buf = new Int32Array(3);
        const buf2 = new Uint32Array(buf.buffer);

        let natoms = 0;
        let frameIndex = 0;

        while (offset < buffer.byteLength) {
            try {
                // Read frame header
                // const magicnum = dv.getInt32(offset);
                natoms = dv.getInt32(offset + 4);
                // const step = dv.getInt32(offset + 8);
                offset += 12;

                if (natoms <= 0 || natoms > 10000000) {
                    console.warn(`[XTC Parser] Invalid atom count ${natoms} at offset ${offset - 12}`);
                    break;
                }

                const natoms3 = natoms * 3;

                times.push(dv.getFloat32(offset));
                offset += 4;

                // Read box vectors (3x3 matrix, in nm, convert to Å)
                const box = new Float32Array(9);
                for (let i = 0; i < 9; ++i) {
                    box[i] = dv.getFloat32(offset) * 10;
                    offset += 4;
                }
                boxes.push(box);

                let frameCoords;

                if (natoms <= 9) {
                    // No compression for small systems
                    frameCoords = new Float32Array(natoms3);
                    for (let i = 0; i < natoms3; ++i) {
                        frameCoords[i] = dv.getFloat32(offset) * 10; // nm to Å
                        offset += 4;
                    }
                } else {
                    // Compressed coordinates
                    buf[0] = buf[1] = buf[2] = 0;
                    sizeint[0] = sizeint[1] = sizeint[2] = 0;
                    sizesmall[0] = sizesmall[1] = sizesmall[2] = 0;
                    bitsizeint[0] = bitsizeint[1] = bitsizeint[2] = 0;
                    thiscoord[0] = thiscoord[1] = thiscoord[2] = 0;
                    prevcoord[0] = prevcoord[1] = prevcoord[2] = 0;

                    frameCoords = new Float32Array(natoms3);
                    let lfp = 0;

                    const lsize = dv.getInt32(offset);
                    offset += 4;
                    const precision = dv.getFloat32(offset);
                    offset += 4;

                    minMaxInt[0] = dv.getInt32(offset);
                    minMaxInt[1] = dv.getInt32(offset + 4);
                    minMaxInt[2] = dv.getInt32(offset + 8);
                    minMaxInt[3] = dv.getInt32(offset + 12);
                    minMaxInt[4] = dv.getInt32(offset + 16);
                    minMaxInt[5] = dv.getInt32(offset + 20);
                    sizeint[0] = minMaxInt[3] - minMaxInt[0] + 1;
                    sizeint[1] = minMaxInt[4] - minMaxInt[1] + 1;
                    sizeint[2] = minMaxInt[5] - minMaxInt[2] + 1;
                    offset += 24;

                    let bitsize;
                    if ((sizeint[0] | sizeint[1] | sizeint[2]) > 0xffffff) {
                        bitsizeint[0] = this._xtcSizeOfInt(sizeint[0]);
                        bitsizeint[1] = this._xtcSizeOfInt(sizeint[1]);
                        bitsizeint[2] = this._xtcSizeOfInt(sizeint[2]);
                        bitsize = 0;
                    } else {
                        bitsize = this._xtcSizeOfInts(3, sizeint);
                    }

                    let smallidx = dv.getInt32(offset);
                    offset += 4;

                    // Bounds check for initial smallidx
                    const lastIdx = this._xtcMagicInts.length - 1;
                    if (smallidx < this._xtcFirstIdx) smallidx = this._xtcFirstIdx;
                    if (smallidx > lastIdx) smallidx = lastIdx;

                    let tmpIdx = smallidx - 1;
                    tmpIdx = (this._xtcFirstIdx > tmpIdx) ? this._xtcFirstIdx : tmpIdx;
                    let smaller = (this._xtcMagicInts[tmpIdx] / 2) | 0;
                    let smallnum = (this._xtcMagicInts[smallidx] / 2) | 0;

                    sizesmall[0] = sizesmall[1] = sizesmall[2] = this._xtcMagicInts[smallidx];

                    let adz = Math.ceil(dv.getInt32(offset) / 4) * 4;
                    offset += 4;

                    const invPrecision = 1.0 / precision;
                    let i = 0;

                    const buf8 = new Uint8Array(buffer, offset);

                    thiscoord[0] = thiscoord[1] = thiscoord[2] = 0;

                    while (i < lsize) {
                        if (bitsize === 0) {
                            thiscoord[0] = this._xtcDecodeBits(buf, buf8, bitsizeint[0], buf2);
                            thiscoord[1] = this._xtcDecodeBits(buf, buf8, bitsizeint[1], buf2);
                            thiscoord[2] = this._xtcDecodeBits(buf, buf8, bitsizeint[2], buf2);
                        } else {
                            this._xtcDecodeInts(buf, buf8, 3, bitsize, sizeint, thiscoord, buf2);
                        }

                        i++;

                        thiscoord[0] += minMaxInt[0];
                        thiscoord[1] += minMaxInt[1];
                        thiscoord[2] += minMaxInt[2];

                        prevcoord[0] = thiscoord[0];
                        prevcoord[1] = thiscoord[1];
                        prevcoord[2] = thiscoord[2];

                        const flag = this._xtcDecodeBits(buf, buf8, 1, buf2);
                        let isSmaller = 0;

                        if (flag === 1) {
                            const run = this._xtcDecodeBits(buf, buf8, 5, buf2);
                            isSmaller = run % 3;
                            const runLen = run - isSmaller;
                            isSmaller--;

                            if (runLen > 0) {
                                thiscoord[0] = thiscoord[1] = thiscoord[2] = 0;

                                for (let k = 0; k < runLen; k += 3) {
                                    this._xtcDecodeInts(buf, buf8, 3, smallidx, sizesmall, thiscoord, buf2);
                                    i++;

                                    thiscoord[0] += prevcoord[0] - smallnum;
                                    thiscoord[1] += prevcoord[1] - smallnum;
                                    thiscoord[2] += prevcoord[2] - smallnum;

                                    if (k === 0) {
                                        // Swap for water molecule optimization
                                        let tmpSwap = thiscoord[0];
                                        thiscoord[0] = prevcoord[0];
                                        prevcoord[0] = tmpSwap;

                                        tmpSwap = thiscoord[1];
                                        thiscoord[1] = prevcoord[1];
                                        prevcoord[1] = tmpSwap;

                                        tmpSwap = thiscoord[2];
                                        thiscoord[2] = prevcoord[2];
                                        prevcoord[2] = tmpSwap;

                                        frameCoords[lfp++] = prevcoord[0] * invPrecision;
                                        frameCoords[lfp++] = prevcoord[1] * invPrecision;
                                        frameCoords[lfp++] = prevcoord[2] * invPrecision;
                                    } else {
                                        prevcoord[0] = thiscoord[0];
                                        prevcoord[1] = thiscoord[1];
                                        prevcoord[2] = thiscoord[2];
                                    }
                                    frameCoords[lfp++] = thiscoord[0] * invPrecision;
                                    frameCoords[lfp++] = thiscoord[1] * invPrecision;
                                    frameCoords[lfp++] = thiscoord[2] * invPrecision;
                                }
                            }
                        } else {
                            frameCoords[lfp++] = thiscoord[0] * invPrecision;
                            frameCoords[lfp++] = thiscoord[1] * invPrecision;
                            frameCoords[lfp++] = thiscoord[2] * invPrecision;
                        }

                        smallidx += isSmaller;

                        // Bounds check for smallidx (valid range: 9 to 72)
                        const lastIdx = this._xtcMagicInts.length - 1;
                        if (smallidx < this._xtcFirstIdx) smallidx = this._xtcFirstIdx;
                        if (smallidx > lastIdx) smallidx = lastIdx;

                        if (isSmaller < 0) {
                            smallnum = smaller;
                            if (smallidx > this._xtcFirstIdx) {
                                smaller = (this._xtcMagicInts[smallidx - 1] / 2) | 0;
                            } else {
                                smaller = 0;
                            }
                        } else if (isSmaller > 0) {
                            smaller = smallnum;
                            smallnum = (this._xtcMagicInts[smallidx] / 2) | 0;
                        }
                        sizesmall[0] = sizesmall[1] = sizesmall[2] = this._xtcMagicInts[smallidx];

                        if (sizesmall[0] === 0 || sizesmall[1] === 0 || sizesmall[2] === 0) {
                            console.warn(`[XTC Parser] Zero sizesmall at smallidx=${smallidx}, skipping rest of frame`);
                            break;
                        }
                    }
                    offset += adz;
                }

                // Convert coordinates from internal units to Å (multiply by 10)
                for (let c = 0; c < natoms3; c++) {
                    frameCoords[c] *= 10;
                }

                // Convert to atom array format expected by viewer
                const atoms = [];
                for (let a = 0; a < natoms; a++) {
                    atoms.push({
                        symbol: 'C', // XTC doesn't store atom types
                        atomname: '',
                        ss: 'C',
                        x: frameCoords[a * 3],
                        y: frameCoords[a * 3 + 1],
                        z: frameCoords[a * 3 + 2]
                    });
                }

                frames.push({
                    frameIndex: frameIndex++,
                    time: times[times.length - 1],
                    atoms: atoms
                });

            } catch (e) {
                console.warn(`[XTC Parser] Error parsing frame at offset ${offset}:`, e);
                break;
            }
        }

        console.log(`[XTC Parser] Parsed ${frames.length} frames, ${natoms} atoms`);

        // Return in standard trajectory format
        return {
            format: 'xtc',
            filename: filename,
            atomCount: natoms,
            frameCount: frames.length,
            frames: frames,
            times: times,
            boxes: boxes,
            hasVelocities: false,
            serverParsed: false,
            clientParsed: true
        };
    }

    /**
     * Convert compact array format [x, y, z] to object format {symbol, atomname, ss, x, y, z}
     * The server sends atoms as arrays to reduce JSON size by ~60%
     */
    expandCompactFrame(frame, symbols, atomnames = [], secondaryStructure = []) {
        if (!frame.atoms || frame.atoms.length === 0) return frame;
        
        // Check if already expanded (first atom is an object with 'symbol')
        if (typeof frame.atoms[0] === 'object' && !Array.isArray(frame.atoms[0])) {
            return frame; // Already in object format
        }
        
        // Convert from [x, y, z] arrays to {symbol, atomname, ss, x, y, z} objects
        const expandedAtoms = frame.atoms.map((pos, i) => ({
            symbol: symbols[i],
            atomname: atomnames[i] || '',
            ss: secondaryStructure[i] || 'C',  // H=helix, E=sheet, C=coil
            x: pos[0],
            y: pos[1],
            z: pos[2]
        }));
        
        return {
            ...frame,
            atoms: expandedAtoms
        };
    }

    getExtensionFolder() {
        return 'extensions/md-trajectory-viewer';
    }

    async initialize() {
        // Check WebGPU support
        await this.checkWebGPUSupport();
        
        // Load Three.js if not already loaded
        if (typeof THREE === 'undefined') {
            await this.loadThreeJS();
        }
        
        await super.initialize();
        console.log(`MD Trajectory Viewer initialized (WebGPU: ${this.webgpuSupported ? 'yes' : 'no, using WebGL fallback'})`);
        return true;
    }

    async checkWebGPUSupport() {
        if (this.webgpuChecked) return this.webgpuSupported;
        
        this.webgpuChecked = true;
        
        console.log('[WebGPU Check] Starting WebGPU capability detection...');
        console.log('[WebGPU Check] Browser:', navigator.userAgent.split(' ').slice(-2).join(' '));
        
        if (!navigator.gpu) {
            console.warn('[WebGPU Check] ❌ navigator.gpu is undefined');
            console.warn('[WebGPU Check] Possible reasons:');
            console.warn('  1. Browser does not support WebGPU (requires Chrome/Edge 113+, Firefox 121+)');
            console.warn('  2. WebGPU is disabled in browser flags');
            console.warn('  3. Page is not served over HTTPS/localhost');
            console.warn('[WebGPU Check] Solution: Use Chrome 113+ or Edge 113+ with chrome://flags/#enable-unsafe-webgpu');
            this.webgpuSupported = false;
            return false;
        }
        
        console.log('[WebGPU Check] ✓ navigator.gpu exists, requesting adapter...');
        
        try {
            const adapter = await navigator.gpu.requestAdapter();
            if (!adapter) {
                console.warn('[WebGPU Check] ❌ requestAdapter() returned null');
                console.warn('[WebGPU Check] Possible reasons:');
                console.warn('  1. No compatible GPU found');
                console.warn('  2. GPU drivers are outdated');
                console.warn('  3. GPU is blocklisted for WebGPU');
                this.webgpuSupported = false;
                return false;
            }
            
            console.log('[WebGPU Check] ✓ Adapter obtained:', {
                name: adapter.name || 'Unknown',
                features: Array.from(adapter.features || []),
                limits: adapter.limits ? {
                    maxTextureDimension2D: adapter.limits.maxTextureDimension2D,
                    maxBufferSize: adapter.limits.maxBufferSize
                } : 'N/A'
            });
            
            console.log('[WebGPU Check] Requesting device...');
            const device = await adapter.requestDevice();
            
            if (!device) {
                console.warn('[WebGPU Check] ❌ requestDevice() returned null');
                this.webgpuSupported = false;
                return false;
            }
            
            console.log('[WebGPU Check] ✅ WebGPU fully available! Device:', device.label || 'Default');
            this.webgpuSupported = true;
            
            // Clean up test device
            device.destroy();
            
        } catch (e) {
            console.error('[WebGPU Check] ❌ Exception during WebGPU initialization:', e.message);
            console.error('[WebGPU Check] Full error:', e);
            this.webgpuSupported = false;
        }
        
        return this.webgpuSupported;
    }

    async loadThreeJS() {
        return new Promise((resolve, reject) => {
            // Check if Three.js is already loaded
            if (typeof THREE !== 'undefined') {
                resolve();
                return;
            }

            const existingScript = document.querySelector('script[src*="three.min.js"]');
            if (existingScript) {
                const checkTHREE = () => {
                    if (typeof THREE !== 'undefined') {
                        this.loadOrbitControls().then(resolve);
                    } else {
                        setTimeout(checkTHREE, 50);
                    }
                };
                checkTHREE();
                return;
            }

            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
            script.onload = () => {
                this.loadOrbitControls().then(resolve);
            };
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    async loadOrbitControls() {
        return new Promise((resolve) => {
            if (THREE.OrbitControls) {
                resolve();
                return;
            }

            const existingScript = document.querySelector('script[src*="OrbitControls.js"]');
            if (existingScript) {
                resolve();
                return;
            }

            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js';
            script.onload = () => resolve();
            script.onerror = () => {
                console.warn('OrbitControls not loaded, using fallback controls');
                resolve();
            };
            document.head.appendChild(script);
        });
    }

    /**
     * Check if this extension can handle the given file
     * 
     * For XYZ files, we use smart detection:
     * - Multi-frame trajectories: we handle them (simpler viewer can't animate)
     * - Large systems (>500 atoms): we handle them (better performance)
     * - Small single-frame: defer to simpler XYZ viewer (priority fallback)
     */
    async canHandle(filename, content) {
        const ext = '.' + filename.split('.').pop().toLowerCase();
        
        if (!this.supportedTypes.includes(ext)) {
            return false;
        }

        if (!content || typeof content !== 'string' || content.trim().length === 0) {
            return false;
        }

        // Validate content based on format
        try {
            switch (ext) {
                case '.xyz':
                    return this.shouldHandleXYZ(content);
                case '.lammpstrj':
                    return this.validateLAMMPS(content);
                case '.gsd':
                    // GSD is binary, but we might receive base64
                    return content.length > 0;
                case '.h5md':
                    // H5MD is HDF5 binary
                    return content.length > 0;
                case '.xtc':
                case '.trr':
                    // Binary formats
                    return content.length > 0;
                default:
                    return true;
            }
        } catch (e) {
            console.warn('Content validation failed:', e);
            return false;
        }
    }

    /**
     * Determine if this extension should handle an XYZ file
     * We claim the file if:
     * - It has multiple frames (trajectory) - we're better at animation
     * - It has a large atom count (>500) - we have better performance
     * - It contains velocity/force data - we can display this
     * Otherwise, let simpler XYZ viewer handle it
     */
    shouldHandleXYZ(content) {
        const lines = content.trim().split('\n');
        if (lines.length < 3) return false;
        
        const atomCount = parseInt(lines[0].trim());
        if (isNaN(atomCount) || atomCount <= 0) return false;
        
        // Check if we have at least one valid frame
        if (lines.length < atomCount + 2) return false;
        
        // Count frames in the file
        const frameCount = this.countXYZFrames(content, atomCount);
        
        // Check for velocity/force data (extended XYZ format)
        const hasExtendedData = this.hasExtendedXYZData(lines.slice(2, Math.min(12, atomCount + 2)));
        
        // Claim the file if:
        // 1. Multiple frames (trajectory animation)
        // 2. Large system (>500 atoms - better performance)
        // 3. Extended XYZ with velocities/forces
        const shouldHandle = frameCount > 1 || atomCount > 500 || hasExtendedData;
        
        console.log(`MD Trajectory Viewer XYZ check: ${atomCount} atoms, ${frameCount} frames, extended=${hasExtendedData} -> ${shouldHandle ? 'handling' : 'deferring'}`);
        
        return shouldHandle;
    }

    /**
     * Count approximate number of frames in XYZ content
     */
    countXYZFrames(content, atomCount) {
        const frameSize = atomCount + 2; // atoms + count line + comment line
        const lines = content.trim().split('\n');
        
        // Quick estimate based on line count
        const estimatedFrames = Math.floor(lines.length / frameSize);
        
        // Verify by checking if subsequent frames start correctly
        let verifiedFrames = 1;
        let lineIndex = frameSize;
        
        while (lineIndex < lines.length && verifiedFrames < 100) { // Cap at 100 for performance
            const countLine = lines[lineIndex]?.trim();
            if (countLine && /^\d+$/.test(countLine) && parseInt(countLine) === atomCount) {
                verifiedFrames++;
                lineIndex += frameSize;
            } else {
                break;
            }
        }
        
        return verifiedFrames;
    }

    /**
     * Check if XYZ file has extended data (velocities, forces, etc.)
     */
    hasExtendedXYZData(atomLines) {
        for (const line of atomLines) {
            const parts = line.trim().split(/\s+/);
            // Standard XYZ: element x y z (4 columns)
            // Extended: element x y z vx vy vz or more columns
            if (parts.length > 4) {
                // Verify extra columns are numeric (velocities/forces)
                const extraValues = parts.slice(4);
                if (extraValues.every(v => !isNaN(parseFloat(v)))) {
                    return true;
                }
            }
        }
        return false;
    }

    validateXYZ(content) {
        const lines = content.trim().split('\n');
        if (lines.length < 3) return false;
        
        const atomCount = parseInt(lines[0].trim());
        if (isNaN(atomCount) || atomCount <= 0) return false;
        
        // Check if we have at least one frame worth of data
        return lines.length >= atomCount + 2;
    }

    validateLAMMPS(content) {
        const lines = content.trim().split('\n');
        // LAMMPS dump files start with ITEM: TIMESTEP
        return lines.some(line => line.trim().startsWith('ITEM:'));
    }

    /**
     * Render preview mode (compact inline view)
     */
    async renderPreview(container, filename, content, options = {}) {
        console.log(`[MD Preview] Starting preview for ${filename}, source: ${options.source || 'unknown'}`);
        console.log(`[MD Preview] Container:`, container);
        console.log(`[MD Preview] Content length: ${content?.length || 0} bytes`);
        console.log(`[MD Preview] Options:`, options);

        // Store source for file fetching - prefer the one passed in options
        this._currentSource = options.source || 'outputs';

        try {
            console.log(`[MD Preview] Calling parseTrajectory...`);
            const trajectory = await this.parseTrajectory(filename, content);
            console.log(`[MD Preview] Trajectory parsed:`, {
                format: trajectory.format,
                frameCount: trajectory.frameCount,
                atomCount: trajectory.atomCount,
                hasVelocities: trajectory.hasVelocities,
                serverParsed: trajectory.serverParsed
            });

            console.log(`[MD Preview] Creating viewer...`);
            const viewer = await this.createViewer(container, trajectory, {
                ...options,
                mode: 'preview',
                interactive: true,
                showControls: true,
                showPlayback: trajectory.frameCount > 1,
                autoPlay: false
            });
            console.log(`[MD Preview] Viewer created successfully`);

            // Add compact warning for XTC/TRR files without topology
            const ext = '.' + filename.split('.').pop().toLowerCase();
            if ((ext === '.xtc' || ext === '.trr') && !trajectory._hasTopology) {
                this.addNoTopologyWarning(container);
            }

            this.viewers.set(container, viewer);
            return { success: true };
        } catch (error) {
            console.error('[MD Preview] ERROR:', error);
            console.error('[MD Preview] Stack:', error.stack);
            this.createErrorDisplay(error.message, container);
            return { success: false, error: error.message };
        }
    }

    /**
     * Render full view mode (expanded modal view)
     */
    async renderFullView(container, filename, content, options = {}) {
        try {
            console.log(`[MD Full View] Starting render for ${filename}, source: ${options.source || 'unknown'}`);
            // Store source for file fetching - prefer the one passed in options
            this._currentSource = options.source || 'outputs';
            let trajectory = await this.parseTrajectory(filename, content);
            console.log(`[MD Full View] Trajectory parsed: ${trajectory.frameCount} frames, ${trajectory.atomCount} atoms, hasTopology=${trajectory._hasTopology}`);

            // Check if this is an XTC/TRR file without topology
            const ext = '.' + filename.split('.').pop().toLowerCase();
            const needsTopology = (ext === '.xtc' || ext === '.trr') && !trajectory._hasTopology;
            console.log(`[MD Full View] Extension: ${ext}, needsTopology: ${needsTopology}`);

            if (needsTopology) {
                // Show topology selector dialog
                console.log('[MD Full View] No topology found, showing selector...');
                const selection = await this.showTopologySelector(container);
                console.log('[MD Full View] Selector result:', selection);

                if (selection && selection.cancelled) {
                    // User cancelled - don't render
                    console.log('[MD Full View] User cancelled');
                    return { success: false, error: 'Cancelled by user' };
                }

                if (selection && selection.filename) {
                    // User selected a topology file - load and apply it
                    console.log(`[MD Full View] Loading selected topology: ${selection.filename} from ${selection.source}`);
                    const topology = await this.loadSpecificTopologyFile(selection.filename, selection.source);
                    if (topology) {
                        this.applyTopologyToTrajectory(trajectory, topology);
                        trajectory._hasTopology = true;
                        console.log(`[MD Full View] Applied topology with ${topology.atoms.length} atoms`);
                    } else {
                        console.error('[MD Full View] Failed to load selected topology file - topology is null');
                    }
                } else {
                    console.log('[MD Full View] User chose to continue without topology');
                }
            }

            const viewer = await this.createViewer(container, trajectory, {
                ...options,
                mode: 'fullview',
                interactive: true,
                showControls: true,
                showPlayback: trajectory.frameCount > 1,
                showAnalysis: true,
                autoPlay: false
            });

            // Add warning banner if still no topology
            if ((ext === '.xtc' || ext === '.trr') && !trajectory._hasTopology) {
                this.addNoTopologyWarning(container);
            }

            this.viewers.set(container, viewer);
            return { success: true };
        } catch (error) {
            console.error('[MD Full View] ERROR:', error);
            console.error('[MD Full View] Stack:', error.stack);
            this.createErrorDisplay(error.message, container);
            return { success: false, error: error.message };
        }
    }

    /**
     * Parse trajectory data from various formats
     */
    async parseTrajectory(filename, content) {
        const ext = '.' + filename.split('.').pop().toLowerCase();
        console.log(`[MD Parse] Parsing ${filename} with extension ${ext}`);

        // For binary formats, don't try to preview content as it may contain null bytes
        const binaryFormats = ['.xtc', '.trr', '.dcd', '.gsd', '.h5md'];
        const isBinary = binaryFormats.includes(ext);

        if (isBinary) {
            console.log(`[MD Parse] Binary format detected, content length: ${content ? content.length : 0}`);
        } else if (typeof content === 'string' && content.length > 0) {
            console.log(`[MD Parse] Text content, length: ${content.length}, preview: ${content.substring(0, 100)}`);
        } else {
            console.log(`[MD Parse] Content is ${content ? 'non-string' : 'empty/null'}`);
        }

        console.log(`[MD Parse] Selecting parser for extension: ${ext}`);

        switch (ext) {
            case '.xyz':
                console.log(`[MD Parse] Using XYZ parser`);
                return this.parseXYZ(content, filename);
            case '.lammpstrj':
                console.log(`[MD Parse] Using LAMMPS parser`);
                return this.parseLAMMPS(content, filename);
            case '.gsd':
                console.log(`[MD Parse] Using GSD parser`);
                return this.parseGSD(content, filename);
            case '.h5md':
                console.log(`[MD Parse] Using H5MD parser`);
                return this.parseH5MD(content, filename);
            case '.xtc':
            case '.trr':
                console.log(`[MD Parse] Using GROMACS parser for ${ext}`);
                return this.parseGromacsTrajectory(content, filename, ext);
            default:
                throw new Error(`Unsupported trajectory format: ${ext}`);
        }
    }

    /**
     * Parse multi-frame XYZ format
     */
    parseXYZ(content, filename) {
        const lines = content.trim().split('\n');
        const frames = [];
        let i = 0;

        while (i < lines.length) {
            const atomCountLine = lines[i].trim();
            const atomCount = parseInt(atomCountLine);
            
            if (isNaN(atomCount) || atomCount <= 0) {
                i++;
                continue;
            }

            const comment = lines[i + 1] || '';
            const atoms = [];

            for (let j = 0; j < atomCount && i + 2 + j < lines.length; j++) {
                const parts = lines[i + 2 + j].trim().split(/\s+/);
                if (parts.length >= 4) {
                    atoms.push({
                        symbol: parts[0],
                        x: parseFloat(parts[1]),
                        y: parseFloat(parts[2]),
                        z: parseFloat(parts[3]),
                        // Optional: velocity or other properties
                        vx: parts.length > 4 ? parseFloat(parts[4]) : 0,
                        vy: parts.length > 5 ? parseFloat(parts[5]) : 0,
                        vz: parts.length > 6 ? parseFloat(parts[6]) : 0
                    });
                }
            }

            if (atoms.length > 0) {
                frames.push({
                    atoms,
                    comment,
                    time: frames.length
                });
            }

            i += atomCount + 2;
        }

        if (frames.length === 0) {
            throw new Error('No valid frames found in XYZ file');
        }

        return {
            format: 'xyz',
            filename,
            frameCount: frames.length,
            atomCount: frames[0].atoms.length,
            frames,
            box: this.calculateBoundingBox(frames[0].atoms)
        };
    }

    /**
     * Parse LAMMPS dump format (.lammpstrj)
     */
    parseLAMMPS(content, filename) {
        const lines = content.trim().split('\n');
        const frames = [];
        let i = 0;

        while (i < lines.length) {
            // Look for ITEM: TIMESTEP
            if (!lines[i].startsWith('ITEM: TIMESTEP')) {
                i++;
                continue;
            }

            const timestep = parseInt(lines[++i]);
            
            // ITEM: NUMBER OF ATOMS
            while (i < lines.length && !lines[i].startsWith('ITEM: NUMBER OF ATOMS')) i++;
            const atomCount = parseInt(lines[++i]);

            // ITEM: BOX BOUNDS
            while (i < lines.length && !lines[i].startsWith('ITEM: BOX BOUNDS')) i++;
            i++;
            const boxX = lines[i++].split(/\s+/).map(parseFloat);
            const boxY = lines[i++].split(/\s+/).map(parseFloat);
            const boxZ = lines[i++].split(/\s+/).map(parseFloat);

            // ITEM: ATOMS
            while (i < lines.length && !lines[i].startsWith('ITEM: ATOMS')) i++;
            const atomsHeader = lines[i++];
            const columns = atomsHeader.replace('ITEM: ATOMS', '').trim().split(/\s+/);

            // Find column indices
            const idIdx = columns.indexOf('id');
            const typeIdx = columns.indexOf('type');
            const xIdx = columns.findIndex(c => c === 'x' || c === 'xu' || c === 'xs');
            const yIdx = columns.findIndex(c => c === 'y' || c === 'yu' || c === 'ys');
            const zIdx = columns.findIndex(c => c === 'z' || c === 'zu' || c === 'zs');
            const elementIdx = columns.indexOf('element');

            const atoms = [];
            for (let j = 0; j < atomCount && i < lines.length; j++, i++) {
                const parts = lines[i].trim().split(/\s+/);
                if (parts.length >= 4) {
                    const type = typeIdx >= 0 ? parseInt(parts[typeIdx]) : 1;
                    atoms.push({
                        id: idIdx >= 0 ? parseInt(parts[idIdx]) : j + 1,
                        symbol: elementIdx >= 0 ? parts[elementIdx] : this.typeToElement(type),
                        type: type,
                        x: parseFloat(parts[xIdx >= 0 ? xIdx : 2]),
                        y: parseFloat(parts[yIdx >= 0 ? yIdx : 3]),
                        z: parseFloat(parts[zIdx >= 0 ? zIdx : 4])
                    });
                }
            }

            if (atoms.length > 0) {
                frames.push({
                    atoms,
                    timestep,
                    time: timestep,
                    box: {
                        min: { x: boxX[0], y: boxY[0], z: boxZ[0] },
                        max: { x: boxX[1], y: boxY[1], z: boxZ[1] }
                    }
                });
            }
        }

        if (frames.length === 0) {
            throw new Error('No valid frames found in LAMMPS dump file');
        }

        return {
            format: 'lammps',
            filename,
            frameCount: frames.length,
            atomCount: frames[0].atoms.length,
            frames,
            box: frames[0].box
        };
    }

    /**
     * Parse GSD format (HOOMD-blue) using server-side API
     */
    async parseGSD(content, filename) {
        // Check if server indicated binary format
        if (content.includes('Binary trajectory file')) {
            return await this.fetchTrajectoryFromServer(filename, '.gsd');
        }
        
        // Try parsing as simplified text/JSON format
        try {
            const data = JSON.parse(content);
            if (data.frames && Array.isArray(data.frames)) {
                return {
                    format: 'gsd',
                    filename,
                    frameCount: data.frames.length,
                    atomCount: data.frames[0]?.particles?.N || 0,
                    frames: data.frames.map((f, idx) => ({
                        atoms: this.gsdParticlesToAtoms(f.particles),
                        time: idx,
                        box: f.configuration?.box
                    })),
                    box: data.frames[0]?.configuration?.box
                };
            }
        } catch (e) {
            // Not JSON format
        }
        
        throw new Error('GSD format parsing failed. Ensure MDAnalysis is installed on server.');
    }

    /**
     * Parse H5MD format (HDF5 for molecular data) using server-side API
     */
    async parseH5MD(content, filename) {
        // H5MD is HDF5 binary, use server-side parsing
        if (content.includes('Binary trajectory file')) {
            return await this.fetchTrajectoryFromServer(filename, '.h5md');
        }
        
        throw new Error('H5MD format requires server-side parsing. Ensure MDAnalysis is installed.');
    }

    // ==================== TRAJECTORY FORMAT CONSTANTS ====================
    static MAGIC_XTC = 1995;      // XTC compressed coordinates
    static MAGIC_TRR = 1987;      // TRR full precision with velocities/forces
    static MAGIC_TRR_DBL = 1993;  // TRR double precision variant

    /**
     * Detect trajectory format from binary data based on magic numbers
     * @param {ArrayBuffer} buffer - The raw binary data
     * @returns {Object} Format info: { format, magic, description, canParse }
     */
    detectTrajectoryFormat(buffer) {
        if (buffer.byteLength < 8) {
            return { format: 'unknown', magic: 0, description: 'File too small', canParse: false };
        }

        const dv = new DataView(buffer);
        const magic = dv.getInt32(0, false); // Big-endian (GROMACS default)

        // Check GROMACS formats
        if (magic === MDTrajectoryExtension.MAGIC_XTC) {
            return { format: 'xtc', magic, description: 'GROMACS XTC (compressed)', canParse: true };
        }
        if (magic === MDTrajectoryExtension.MAGIC_TRR) {
            return { format: 'trr', magic, description: 'GROMACS TRR (full precision, single)', canParse: true };
        }
        if (magic === MDTrajectoryExtension.MAGIC_TRR_DBL) {
            return { format: 'trr', magic, description: 'GROMACS TRR (full precision, double)', canParse: true };
        }

        // Check DCD format (CHARMM/NAMD) - little-endian, starts with 84
        const firstIntLE = dv.getInt32(0, true);
        if (firstIntLE === 84) {
            const sig = String.fromCharCode(dv.getUint8(4), dv.getUint8(5), dv.getUint8(6), dv.getUint8(7));
            if (sig === 'CORD') {
                return { format: 'dcd', magic: firstIntLE, description: 'DCD (CHARMM/NAMD)', canParse: true };
            }
        }

        return {
            format: 'unknown',
            magic,
            description: `Unknown format (magic: ${magic} / 0x${magic.toString(16).toUpperCase()})`,
            canParse: false
        };
    }

    /**
     * Parse GROMACS/binary trajectory formats (XTC, TRR, DCD)
     * Auto-detects format from magic number, not file extension
     */
    async parseGromacsTrajectory(content, filename, ext) {
        console.log(`[MD GROMACS] Parsing ${filename} (extension: ${ext})`);
        console.log(`[MD GROMACS] Using smart binary parser with auto-format detection`);

        // Use the unified binary parser that auto-detects format
        return await this.parseBinaryTrajectoryFromFile(filename, ext);
    }

    /**
     * Fetch and parse binary trajectory file with auto-format detection
     * Supports XTC, TRR, and DCD formats based on magic number detection
     * @param {string} filename - The trajectory filename
     * @param {string} expectedExt - The expected extension (for fallback/logging)
     */
    async parseBinaryTrajectoryFromFile(filename, expectedExt) {
        console.log(`[Binary Parser] Fetching: ${filename}`);

        // Extract just the filename (basename) for the API
        const basename = filename.split(/[/\\]/).pop();
        const nameWithoutExt = basename.replace(/\.(xtc|trr|dcd)$/i, '');

        // Build session context for API calls
        const params = new URLSearchParams();
        if (window.discoveryAgent?.currentSessionId) {
            params.set('session_id', window.discoveryAgent.currentSessionId);
        }
        if (window.discoveryAgent?.getCurrentAgentName) {
            const agentName = window.discoveryAgent.getCurrentAgentName();
            if (agentName) params.set('agent_name', agentName);
        }
        const outputParams = new URLSearchParams(params);
        outputParams.set('source', 'outputs');
        outputParams.set('raw', 'true');  // CRITICAL: Request raw binary, not text/plain preview
        const inputParams = new URLSearchParams(params);
        inputParams.set('source', 'inputs');
        inputParams.set('raw', 'true');  // CRITICAL: Request raw binary, not text/plain preview

        // Build endpoint list based on which source the file is from
        const primarySource = this._currentSource || 'outputs';
        const primaryParams = primarySource === 'inputs' ? inputParams : outputParams;
        const secondaryParams = primarySource === 'inputs' ? outputParams : inputParams;

        console.log(`[Binary Parser] Primary source: ${primarySource}, fetching as raw binary`);

        const endpoints = [
            `/api/file/${encodeURIComponent(basename)}?${primaryParams.toString()}`,
            `/api/file/${encodeURIComponent(basename)}?${secondaryParams.toString()}`,
            `/api/file/${encodeURIComponent(filename)}?${primaryParams.toString()}`,
        ];

        let lastError = null;
        let trajectory = null;
        let detectedFormat = null;

        for (const url of endpoints) {
            console.log(`[Binary Parser] Trying: ${url}`);
            try {
                const response = await fetch(url);

                if (response.ok) {
                    const buffer = await response.arrayBuffer();
                    console.log(`[Binary Parser] Received ${buffer.byteLength} bytes`);

                    // Auto-detect format from magic number
                    detectedFormat = this.detectTrajectoryFormat(buffer);
                    console.log(`[Binary Parser] Detected format: ${detectedFormat.format} - ${detectedFormat.description}`);

                    if (detectedFormat.format !== expectedExt.replace('.', '')) {
                        console.warn(`[Binary Parser] File extension ${expectedExt} doesn't match detected format ${detectedFormat.format}`);
                    }

                    // Route to appropriate parser based on detected format
                    switch (detectedFormat.format) {
                        case 'xtc':
                            trajectory = this.parseXtcBinary(buffer, filename);
                            break;
                        case 'trr':
                            trajectory = this.parseTrrBinary(buffer, filename, detectedFormat.magic);
                            break;
                        case 'dcd':
                            trajectory = this.parseDcdBinary(buffer, filename);
                            break;
                        default:
                            throw new Error(`Unsupported trajectory format: ${detectedFormat.description}. ` +
                                `This file may be corrupted or in an unsupported format.`);
                    }
                    break;
                }

                lastError = `${response.status} ${response.statusText}`;
                console.log(`[Binary Parser] ${url} failed: ${lastError}`);

            } catch (error) {
                lastError = error.message;
                console.log(`[Binary Parser] ${url} error: ${lastError}`);
            }
        }

        if (!trajectory) {
            throw new Error(`Failed to fetch trajectory file. Last error: ${lastError}`);
        }

        // Try to auto-load topology from available .gro or .pdb files
        const topology = await this.autoLoadTopologyFile(nameWithoutExt);
        let hasTopology = false;
        if (topology) {
            console.log(`[Binary Parser] Loaded topology with ${topology.atoms.length} atoms`);
            this.applyTopologyToTrajectory(trajectory, topology);
            hasTopology = true;
        } else {
            console.log(`[Binary Parser] No topology file found, will prompt user for selection`);
        }

        // Add topology status to trajectory for later use
        trajectory._hasTopology = hasTopology;
        return trajectory;
    }

    /**
     * Auto-load topology ONLY if there's an exact name match with the trajectory.
     * For example: trajectory-10.xtc -> trajectory-10.gro or trajectory-10.pdb
     * If no exact match, returns null so the user can pick from available files.
     * @param {string} nameWithoutExt - Base name of the trajectory file without extension
     * @returns {Promise<Object|null>} Parsed topology or null if no exact match
     */
    async autoLoadTopologyFile(nameWithoutExt) {
        console.log(`[XTC Topology] Looking for exact match topology for: ${nameWithoutExt}`);

        // Get list of available topology files first
        const { inputs, outputs } = await this.fetchAvailableTopologyFiles();
        const primarySource = this._currentSource || 'outputs';

        // Combine files with source info, prioritizing same source as trajectory
        const primaryFiles = primarySource === 'inputs' ? inputs : outputs;
        const secondaryFiles = primarySource === 'inputs' ? outputs : inputs;

        const allFiles = [
            ...primaryFiles.map(f => ({ name: f.name, source: primarySource })),
            ...secondaryFiles.map(f => ({ name: f.name, source: primarySource === 'inputs' ? 'outputs' : 'inputs' }))
        ];

        if (allFiles.length === 0) {
            console.log(`[XTC Topology] No topology files available in session`);
            return null;
        }

        console.log(`[XTC Topology] Found ${allFiles.length} topology files: ${allFiles.map(f => f.name).join(', ')}`);

        // ONLY auto-load if there's an exact name match (same base name as trajectory)
        // This ensures the user is prompted to select if there's no obvious match
        const exactMatches = [
            `${nameWithoutExt}.gro`,
            `${nameWithoutExt}.pdb`
        ];

        let exactMatch = null;
        for (const matchName of exactMatches) {
            const match = allFiles.find(f => f.name.toLowerCase() === matchName.toLowerCase());
            if (match) {
                exactMatch = match;
                break;
            }
        }

        if (!exactMatch) {
            // No exact match - let the user pick from available files
            console.log(`[XTC Topology] No exact name match found, user will be prompted to select`);
            return null;
        }

        console.log(`[XTC Topology] Found exact match: ${exactMatch.name} from ${exactMatch.source}`);
        return await this.loadSpecificTopologyFile(exactMatch.name, exactMatch.source);
    }

    /**
     * Legacy method - kept for compatibility but now just calls autoLoadTopologyFile
     * @deprecated Use autoLoadTopologyFile instead
     */
    async loadTopologyFile(filenames) {
        // Extract base name from first filename if available
        const nameWithoutExt = filenames[0]?.replace(/\.(gro|pdb)$/i, '') || 'trajectory';
        return await this.autoLoadTopologyFile(nameWithoutExt);
    }

    /**
     * Parse GROMACS .gro file for atom information
     */
    parseGroTopology(content) {
        const lines = content.trim().split('\n');
        if (lines.length < 3) return null;

        const atoms = [];
        const atomCount = parseInt(lines[1].trim());

        for (let i = 2; i < 2 + atomCount && i < lines.length; i++) {
            const line = lines[i];
            if (line.length < 20) continue;

            // GRO format: residue number (5), residue name (5), atom name (5), atom number (5), x, y, z
            const atomName = line.substring(10, 15).trim();

            // Extract element from atom name (first 1-2 characters)
            let element = atomName.replace(/[0-9]/g, '').substring(0, 2);
            // Common fixes
            if (element.length > 1) {
                element = element[0].toUpperCase() + element[1].toLowerCase();
                // Check if it's a valid 2-letter element
                const twoLetter = ['He', 'Li', 'Be', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'Cl', 'Ar', 'Ca', 'Fe', 'Cu', 'Zn', 'Br'];
                if (!twoLetter.includes(element)) {
                    element = element[0]; // Use single letter
                }
            }

            atoms.push({
                atomName: atomName,
                element: element || 'C',
                residueName: line.substring(5, 10).trim()
            });
        }

        return { atoms };
    }

    /**
     * Parse PDB file for atom information
     */
    parsePdbTopology(content) {
        const lines = content.trim().split('\n');
        const atoms = [];

        for (const line of lines) {
            if (line.startsWith('ATOM') || line.startsWith('HETATM')) {
                const atomName = line.substring(12, 16).trim();
                // Element is in columns 77-78, or derive from atom name
                let element = line.length >= 78 ? line.substring(76, 78).trim() : '';
                if (!element) {
                    element = atomName.replace(/[0-9]/g, '').substring(0, 1);
                }

                atoms.push({
                    atomName: atomName,
                    element: element || 'C',
                    residueName: line.substring(17, 20).trim()
                });
            }
        }

        return atoms.length > 0 ? { atoms } : null;
    }

    /**
     * Apply topology atom types to all frames in a trajectory
     */
    applyTopologyToTrajectory(trajectory, topology) {
        if (!topology || !topology.atoms || topology.atoms.length === 0) return;

        const topoAtoms = topology.atoms;

        for (const frame of trajectory.frames) {
            for (let i = 0; i < frame.atoms.length && i < topoAtoms.length; i++) {
                frame.atoms[i].symbol = topoAtoms[i].element;
                frame.atoms[i].atomname = topoAtoms[i].atomName;
                frame.atoms[i].residue = topoAtoms[i].residueName;
            }
        }

        console.log(`[XTC Topology] Applied ${topoAtoms.length} atom types to ${trajectory.frames.length} frames`);
    }

    /**
     * Fetch list of available topology files from the server
     * Uses the generic /api/files/list endpoint with extension filtering
     * Falls back to /api/inputs if the new endpoint fails
     * @returns {Promise<{inputs: Array, outputs: Array}>}
     */
    async fetchAvailableTopologyFiles() {
        const topologyExtensions = ['.pdb', '.gro', '.psf', '.tpr'];

        // Build session params
        const sessionParams = new URLSearchParams();
        if (window.discoveryAgent?.currentSessionId) {
            sessionParams.set('session_id', window.discoveryAgent.currentSessionId);
        }
        if (window.discoveryAgent?.getCurrentAgentName) {
            const agentName = window.discoveryAgent.getCurrentAgentName();
            if (agentName) sessionParams.set('agent_name', agentName);
        }

        let inputs = [];
        let outputs = [];

        // Try the new generic /api/files/list endpoint first
        try {
            const params = new URLSearchParams(sessionParams);
            params.set('extensions', topologyExtensions.join(','));
            params.set('source', 'both');

            console.log('[Topology] Trying /api/files/list...');
            const response = await fetch(`/api/files/list?${params.toString()}`);
            if (response.ok) {
                const data = await response.json();
                inputs = data.inputs || [];
                outputs = data.outputs || [];
                console.log(`[Topology] Found ${inputs.length} input files, ${outputs.length} output files`);
                return { inputs, outputs };
            }
            console.warn('[Topology] /api/files/list returned', response.status);
        } catch (e) {
            console.warn('[Topology] /api/files/list failed:', e.message);
        }

        // Fallback: use existing /api/inputs and filter client-side
        try {
            console.log('[Topology] Falling back to /api/inputs...');
            const response = await fetch('/api/inputs');
            if (response.ok) {
                const data = await response.json();
                const allFiles = data.files || [];
                // Filter for topology files
                inputs = allFiles.filter(f =>
                    topologyExtensions.some(ext => f.name.toLowerCase().endsWith(ext))
                );
                console.log(`[Topology] Found ${inputs.length} topology files in inputs`);
            }
        } catch (e) {
            console.warn('[Topology] /api/inputs fallback failed:', e.message);
        }

        return { inputs, outputs };
    }

    /**
     * Show topology selector dialog and wait for user selection
     * @param {HTMLElement} container - Parent container for the dialog
     * @returns {Promise<{filename: string, source: string}|null>} Selected file info or null if cancelled
     */
    async showTopologySelector(container) {
        return new Promise(async (resolve) => {
            // Fetch available files
            const { inputs, outputs } = await this.fetchAvailableTopologyFiles();

            // Order files based on the current source (same location as trajectory first)
            const primarySource = this._currentSource || 'outputs';
            const primaryFiles = primarySource === 'inputs' ? inputs : outputs;
            const secondaryFiles = primarySource === 'inputs' ? outputs : inputs;

            const allFiles = [
                ...primaryFiles.map(f => ({ ...f, source: primarySource })),
                ...secondaryFiles.map(f => ({ ...f, source: primarySource === 'inputs' ? 'outputs' : 'inputs' }))
            ];

            // If no topology files available, resolve with null
            if (allFiles.length === 0) {
                console.log('[Topology] No topology files available');
                resolve(null);
                return;
            }

            // Create overlay
            const overlay = document.createElement('div');
            overlay.className = 'topology-selector-overlay';
            overlay.style.cssText = `
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.7);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 1000;
            `;

            // Create dialog
            const dialog = document.createElement('div');
            dialog.className = 'topology-selector-dialog';
            dialog.style.cssText = `
                background: #1e1e1e;
                border-radius: 8px;
                padding: 20px;
                min-width: 350px;
                max-width: 500px;
                max-height: 80%;
                overflow: hidden;
                display: flex;
                flex-direction: column;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
            `;

            // Header
            const header = document.createElement('div');
            header.innerHTML = `
                <h3 style="margin: 0 0 8px 0; color: #fff; font-size: 16px;">Select Topology File</h3>
                <p style="margin: 0 0 16px 0; color: #aaa; font-size: 13px;">
                    XTC trajectory files require a topology file (.pdb, .gro) to identify atom types.
                    Select a file below or continue without topology (all atoms will appear as Carbon).
                </p>
            `;
            dialog.appendChild(header);

            // File list container
            const listContainer = document.createElement('div');
            listContainer.style.cssText = `
                flex: 1;
                overflow-y: auto;
                max-height: 300px;
                border: 1px solid #333;
                border-radius: 4px;
                margin-bottom: 16px;
            `;

            // Group files by source
            const createFileGroup = (title, files, source) => {
                if (files.length === 0) return '';
                const fileItems = files.map(f => `
                    <div class="topology-file-item" data-filename="${f.name}" data-source="${source}"
                         style="padding: 10px 12px; cursor: pointer; border-bottom: 1px solid #333;
                                display: flex; align-items: center; gap: 10px; transition: background 0.15s;"
                         onmouseover="this.style.background='#2a2a2a'"
                         onmouseout="this.style.background='transparent'">
                        <span style="flex: 1; color: #fff;">${f.name}</span>
                        <span style="color: #888; font-size: 12px;">${f.size ? this.formatFileSize(f.size) : ''}</span>
                    </div>
                `).join('');
                return `
                    <div style="padding: 8px 12px; background: #252525; color: #0078d4; font-size: 12px; font-weight: 500; text-transform: uppercase;">
                        ${title}
                    </div>
                    ${fileItems}
                `;
            };

            listContainer.innerHTML =
                createFileGroup('Input Files', inputs, 'inputs') +
                createFileGroup('Output Files', outputs, 'outputs');

            dialog.appendChild(listContainer);

            // Buttons
            const buttons = document.createElement('div');
            buttons.style.cssText = 'display: flex; gap: 10px; justify-content: flex-end;';
            buttons.innerHTML = `
                <button class="topology-btn-skip" style="
                    padding: 8px 16px; border: 1px solid #555; background: transparent;
                    color: #aaa; border-radius: 4px; cursor: pointer; font-size: 13px;
                ">Continue Without Topology</button>
                <button class="topology-btn-cancel" style="
                    padding: 8px 16px; border: none; background: #444;
                    color: #fff; border-radius: 4px; cursor: pointer; font-size: 13px;
                ">Cancel</button>
            `;
            dialog.appendChild(buttons);

            overlay.appendChild(dialog);
            container.appendChild(overlay);

            // Event handlers
            const cleanup = () => {
                overlay.remove();
            };

            // File selection
            listContainer.addEventListener('click', (e) => {
                const item = e.target.closest('.topology-file-item');
                if (item) {
                    const filename = item.dataset.filename;
                    const source = item.dataset.source;
                    cleanup();
                    resolve({ filename, source });
                }
            });

            // Skip button
            buttons.querySelector('.topology-btn-skip').addEventListener('click', () => {
                cleanup();
                resolve(null);
            });

            // Cancel button
            buttons.querySelector('.topology-btn-cancel').addEventListener('click', () => {
                cleanup();
                resolve({ cancelled: true });
            });

            // Click outside to cancel
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    cleanup();
                    resolve({ cancelled: true });
                }
            });
        });
    }

    /**
     * Format file size for display
     */
    formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    /**
     * Load a specific topology file by name and source
     * @param {string} filename - The topology filename
     * @param {string} source - 'inputs' or 'outputs'
     * @returns {Promise<Object|null>} Parsed topology or null
     */
    async loadSpecificTopologyFile(filename, source) {
        const params = new URLSearchParams();
        params.set('source', source);
        if (window.discoveryAgent?.currentSessionId) {
            params.set('session_id', window.discoveryAgent.currentSessionId);
        }
        if (window.discoveryAgent?.getCurrentAgentName) {
            const agentName = window.discoveryAgent.getCurrentAgentName();
            if (agentName) params.set('agent_name', agentName);
        }

        const url = `/api/file/${encodeURIComponent(filename)}?${params.toString()}`;
        console.log(`[Topology] Loading specific file: ${url}`);

        try {
            const response = await fetch(url);
            console.log(`[Topology] Response status: ${response.status}`);

            if (!response.ok) {
                console.error(`[Topology] Failed to load ${filename}: HTTP ${response.status}`);
                return null;
            }

            const content = await response.text();
            console.log(`[Topology] Received ${content.length} bytes`);

            if (!content || content.length === 0) {
                console.warn(`[Topology] Empty content for ${filename}`);
                return null;
            }

            let topology = null;
            const lowerName = filename.toLowerCase();
            if (lowerName.endsWith('.gro')) {
                console.log('[Topology] Parsing as GRO format...');
                topology = this.parseGroTopology(content);
            } else if (lowerName.endsWith('.pdb')) {
                console.log('[Topology] Parsing as PDB format...');
                topology = this.parsePdbTopology(content);
            } else {
                console.warn(`[Topology] Unknown topology format: ${filename}`);
            }

            if (topology) {
                console.log(`[Topology] Successfully parsed ${topology.atoms?.length || 0} atoms`);
            } else {
                console.warn(`[Topology] Parser returned null for ${filename}`);
            }

            return topology;
        } catch (e) {
            console.error(`[Topology] Exception loading ${filename}:`, e);
            return null;
        }
    }

    /**
     * Create a warning banner for missing topology
     * @param {HTMLElement} container - Container to add banner to
     */
    addNoTopologyWarning(container) {
        // Check if warning already exists
        if (container.querySelector('.topology-warning-banner')) return;

        const banner = document.createElement('div');
        banner.className = 'topology-warning-banner';
        banner.style.cssText = `
            position: absolute;
            top: 10px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(202, 80, 16, 0.9);
            color: white;
            padding: 8px 16px;
            border-radius: 4px;
            font-size: 12px;
            z-index: 100;
            display: flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
        `;
        banner.innerHTML = `
            <span>No topology loaded - all atoms shown as Carbon</span>
            <button class="topology-warning-close" style="
                background: none; border: none; color: white; cursor: pointer;
                font-size: 16px; padding: 0 4px; opacity: 0.7;
            ">&times;</button>
        `;

        banner.querySelector('.topology-warning-close').addEventListener('click', () => {
            banner.remove();
        });

        container.appendChild(banner);
    }

    /**
     * Fetch trajectory metadata and initial frame from server-side parser
     */
    async fetchTrajectoryFromServer(filename, ext) {
        const timing = { client: {}, server: {} };
        const t_start = performance.now();
        
        console.log(`[MD Server] Fetching trajectory metadata from server: ${filename}`);
        // Only fetch metadata + first frame initially (max_frames=1)
        const url = `/api/inputs/trajectory/${encodeURIComponent(filename)}?max_frames=1`;
        console.log(`[MD Server] API URL: ${url}`);
        
        try {
            const t_fetch_start = performance.now();
            console.log(`[MD Server] Sending fetch request...`);
            const response = await fetch(url);
            timing.client.network = performance.now() - t_fetch_start;
            
            console.log(`[MD Server] Response status: ${response.status} ${response.statusText}`);
            console.log(`[MD Server] Response headers:`, Object.fromEntries(response.headers));
            
            // Get raw response text for debugging
            const t_download_start = performance.now();
            const rawText = await response.text();
            timing.client.download = performance.now() - t_download_start;
            timing.client.bytes_received = rawText.length;
            
            console.log(`[MD Server] Raw response length: ${rawText.length} chars (${(rawText.length/1024/1024).toFixed(2)} MB)`);
            console.log(`[MD Server] Raw response preview:`, rawText.substring(0, 500));
            
            if (!response.ok) {
                let error;
                try {
                    error = JSON.parse(rawText);
                } catch (e) {
                    error = { message: rawText || 'Server-side parsing failed' };
                }
                console.error(`[MD Server] Error response:`, error);
                throw new Error(error.message || error.error || 'Server-side parsing failed');
            }
            
            console.log(`[MD Server] Parsing JSON response...`);
            const t_json_start = performance.now();
            let data;
            try {
                data = JSON.parse(rawText);
            } catch (e) {
                console.error(`[MD Server] JSON parse failed:`, e);
                console.error(`[MD Server] Full response text:`, rawText);
                throw new Error(`Invalid JSON response: ${e.message}`);
            }
            timing.client.json_parse = performance.now() - t_json_start;
            timing.server = data.timing || {};
            
            // Check if using compact format and get symbols
            const isCompact = data.compact === true;
            const symbols = data.symbols || [];
            
            console.log(`[MD Server] Received data:`, {
                format: data.format,
                filename: data.filename,
                frameCount: data.frameCount,
                atomCount: data.atomCount,
                framesReceived: data.frames?.length,
                hasVelocities: data.hasVelocities,
                compact: isCompact
            });
            
            if (!data.frames || data.frames.length === 0) {
                throw new Error('No frames received from server');
            }
            
            // Expand compact format if needed
            const atomnames = data.atomnames || [];
            const secondaryStructure = data.secondaryStructure || [];
            const firstFrame = isCompact ? this.expandCompactFrame(data.frames[0], symbols, atomnames, secondaryStructure) : data.frames[0];
            
            console.log(`[MD Server] First frame has ${firstFrame.atoms?.length || 0} atoms`);
            
            // Filter water molecules and solvents by default (scientific best practice)
            // Water/solvents typically comprise 90-96% of atoms in solvated MD simulations
            let filteredFrame = firstFrame;
            const resnames = data.resnames || [];
            let waterFiltered = false;
            let filterMask = null;  // Store which atoms were kept (for toggle)
            
            if (resnames.length > 0) {
                // Common water models
                const waterResidues = new Set([
                    'SOL', 'WAT', 'HOH',           // Standard water
                    'TIP3', 'TIP3P', 'TIP4', 'TIP4P', 'TIP5', 'TIP5P',  // TIP water models
                    'SPC', 'SPCE', 'SPC/E',        // SPC water models
                    'OPC', 'OPC3',                 // OPC water models
                    'T3P', 'T4P', 'T5P'            // Alternative naming
                ]);
                
                // Common ions
                const ionResidues = new Set([
                    'NA', 'NA+', 'SOD',            // Sodium
                    'CL', 'CL-', 'CLA',            // Chloride
                    'K', 'K+', 'POT',              // Potassium
                    'MG', 'MG2+',                  // Magnesium
                    'CA', 'CA2+', 'CAL',           // Calcium
                    'ZN', 'ZN2+',                  // Zinc
                    'FE', 'FE2+', 'FE3+'           // Iron
                ]);
                
                // Common organic solvents (often used in MD simulations)
                const organicSolvents = new Set([
                    'DMSO', 'DMS',                 // Dimethyl sulfoxide
                    'ETH', 'ETOH', 'EOH',          // Ethanol
                    'MEOH', 'MOH',                 // Methanol
                    'ACN', 'ACET',                 // Acetonitrile
                    'CHCl3', 'CHCL',               // Chloroform
                    'DCM', 'CH2CL2',               // Dichloromethane
                    'THF',                         // Tetrahydrofuran
                    'TFE', 'TFET'                  // Trifluoroethanol
                ]);
                
                const nonSoluteIndices = [];  // Solute = protein/ligand/lipid
                const soluteIndices = [];
                
                resnames.forEach((resname, i) => {
                    const isWater = waterResidues.has(resname);
                    const isIon = ionResidues.has(resname);
                    const isSolvent = organicSolvents.has(resname);
                    
                    if (!isWater && !isIon && !isSolvent) {
                        soluteIndices.push(i);
                    } else {
                        nonSoluteIndices.push(i);
                    }
                });
                
                if (soluteIndices.length > 0 && soluteIndices.length < firstFrame.atoms.length) {
                    // Filter atoms to solute only (protein/lipid/ligand)
                    filteredFrame = {
                        ...firstFrame,
                        atoms: soluteIndices.map(i => firstFrame.atoms[i])
                    };
                    filterMask = soluteIndices;  // Store which atoms were kept
                    waterFiltered = true;
                    console.log(`[MD Server] Filtered solvents: ${firstFrame.atoms.length} -> ${filteredFrame.atoms.length} atoms (${soluteIndices.length} solute, ${nonSoluteIndices.length} solvent/ions)`);
                }
            }
            
            console.log(`[MD Server] Using ${waterFiltered ? 'protein-only' : 'all atoms'} for rendering`);
            
            // Calculate bounding box from filtered frame
            // Calculate bounding box from filtered frame
            const t_bbox_start = performance.now();
            const box = filteredFrame.box || this.calculateBoundingBox(filteredFrame.atoms);
            timing.client.bbox_calc = performance.now() - t_bbox_start;
            console.log(`[MD Server] Bounding box:`, box);
            
            // Extract time information from trajectory
            // XTC files contain simulation time in picoseconds (ps)
            const firstFrameTime = data.frames[0]?.time || 0;
            const secondFrameTime = data.frames[1]?.time || (firstFrameTime + 1);
            const timestep = secondFrameTime - firstFrameTime; // ps per frame
            const totalTime = data.frameCount > 1 ? (data.frameCount - 1) * timestep : 0;
            
            console.log(`[MD Time] Timestep: ${timestep} ps, Total simulation time: ${totalTime} ps (${(totalTime/1000).toFixed(2)} ns)`);
            
            // Cache metadata including symbols and resnames for filtering
            this.trajectoryMetadata.set(filename, {
                format: data.format,
                frameCount: data.frameCount,
                atomCount: data.atomCount,
                hasVelocities: data.hasVelocities,
                box: box,
                symbols: symbols,  // Element symbols for proper coloring
                resnames: resnames,  // Residue names for protein/water filtering
                atomnames: data.atomnames || [],  // Atom names for backbone identification
                secondaryStructure: data.secondaryStructure || [],  // H/E/C for helix/sheet/coil
                compact: isCompact,
                waterFiltered: waterFiltered,
                proteinAtomCount: filteredFrame.atoms.length,
                // Time information
                timestep: timestep,           // ps per frame
                totalTime: totalTime,         // Total simulation time in ps
                timeUnit: 'ps',               // Time unit (picoseconds)
                firstFrameTime: firstFrameTime
            });
            
            // Initialize frame cache for this file
            if (!this.frameCache.has(filename)) {
                this.frameCache.set(filename, new Map());
            }
            
            // Cache filtered first frame
            const cache = this.frameCache.get(filename);
            cache.set(0, filteredFrame);
            
            timing.client.total = performance.now() - t_start;
            
            const result = {
                format: data.format,
                filename: data.filename,
                frameCount: data.frameCount,
                atomCount: data.atomCount,
                // Store BOTH filtered and unfiltered frames
                frames: [{
                    ...filteredFrame,
                    metadata: {
                        symbols: symbols,
                        residueNames: resnames,
                        atomNames: atomnames,
                        secondaryStructure: secondaryStructure
                    }
                }], // Filtered frame (solute only) - used by default
                unfilteredFrames: [{
                    ...firstFrame,
                    metadata: {
                        symbols: symbols,
                        residueNames: resnames,
                        atomNames: atomnames,
                        secondaryStructure: secondaryStructure
                    }
                }], // Unfiltered frame (all atoms including water/solvents)
                box: box,
                serverParsed: true,
                hasVelocities: data.hasVelocities,
                progressive: true,  // Flag to indicate progressive loading
                timing: timing,
                waterFiltered: waterFiltered,
                filterMask: filterMask,  // Which atoms were kept in filtered version
                showWater: false  // Initial state: water/solvents hidden
            };
            console.log(`[MD Server] Returning trajectory metadata`);
            return result;
        } catch (error) {
            console.error('[MD Server] ERROR:', error);
            console.error('[MD Server] Stack:', error.stack);
            throw new Error(`Failed to parse ${ext.toUpperCase()}: ${error.message}. Ensure MDAnalysis is installed on server or convert to XYZ format.`);
        }
    }
    
    /**
     * Fetch a range of frames on-demand
     */
    async fetchFrameRange(filename, startFrame, endFrame, stride = 1) {
        console.log(`[MD Frames] Fetching frames ${startFrame}-${endFrame} (stride ${stride}) for ${filename}`);
        
        // Ensure cache exists for this file
        if (!this.frameCache.has(filename)) {
            this.frameCache.set(filename, new Map());
        }
        const cache = this.frameCache.get(filename);
        
        // Determine which frames we actually need to fetch
        const framesToFetch = [];
        const pendingPromises = [];
        
        for (let i = startFrame; i <= endFrame; i += stride) {
            const frameKey = `${filename}:${i}`;
            
            if (cache.has(i)) {
                // Already cached, skip
                continue;
            }
            
            if (this.pendingFrames.has(frameKey)) {
                // Already being fetched, wait for it
                pendingPromises.push(this.pendingFrames.get(frameKey));
                continue;
            }
            
            framesToFetch.push(i);
        }
        
        // If some frames are pending, wait for them
        if (pendingPromises.length > 0) {
            console.log(`[MD Frames] Waiting for ${pendingPromises.length} pending frames...`);
            await Promise.all(pendingPromises);
        }
        
        if (framesToFetch.length === 0) {
            console.log(`[MD Frames] All frames already cached or pending`);
            return true;
        }
        
        // Determine actual fetch range (contiguous from first needed frame)
        const fetchStart = framesToFetch[0];
        const fetchEnd = framesToFetch[framesToFetch.length - 1];
        
        console.log(`[MD Frames] Need to fetch ${framesToFetch.length} frames: ${fetchStart}-${fetchEnd}`);
        
        // Create a shared promise for all frames in this fetch
        let resolvePromise;
        const fetchPromise = new Promise(resolve => { resolvePromise = resolve; });
        
        // Mark all frames in range as pending
        for (let i = fetchStart; i <= fetchEnd; i += stride) {
            const frameKey = `${filename}:${i}`;
            if (!cache.has(i) && !this.pendingFrames.has(frameKey)) {
                this.pendingFrames.set(frameKey, fetchPromise);
            }
        }
        
        console.log(`[MD Frames] Need to fetch ${framesToFetch.length} frames: ${framesToFetch.slice(0, 10).join(', ')}${framesToFetch.length > 10 ? '...' : ''}`);
        
        try {
            const url = `/api/inputs/trajectory/${encodeURIComponent(filename)}?start=${fetchStart}&end=${fetchEnd + 1}&stride=${stride}`;
            console.log(`[MD Frames] API URL: ${url}`);
            
            const response = await fetch(url);
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || error.error || 'Frame fetch failed');
            }
            
            const data = await response.json();
            console.log(`[MD Frames] Received ${data.frames?.length || 0} frames`);
            
            // Get symbols from metadata for compact format expansion
            const metadata = this.trajectoryMetadata.get(filename);
            const symbols = data.symbols || metadata?.symbols || [];
            const atomnames = data.atomnames || metadata?.atomnames || [];
            const secondaryStructure = data.secondaryStructure || metadata?.secondaryStructure || [];
            const resnames = data.resnames || metadata?.resnames || [];
            const isCompact = data.compact === true;
            
            // Cache the received frames (expanding and filtering if needed)
            if (data.frames) {
                for (const frame of data.frames) {
                    // Expand compact format if needed
                    let expandedFrame = isCompact ? this.expandCompactFrame(frame, symbols, atomnames, secondaryStructure) : frame;
                    
                    // Filter water if metadata indicates we should (same as initial load)
                    if (metadata?.waterFiltered && resnames.length > 0) {
                        const waterResidues = new Set(['SOL', 'WAT', 'HOH', 'TIP3', 'TIP4', 'SPC']);
                        const ionResidues = new Set(['NA', 'CL', 'K', 'MG', 'CA', 'ZN']);
                        const proteinAtomIndices = [];
                        
                        resnames.forEach((resname, i) => {
                            if (!waterResidues.has(resname) && !ionResidues.has(resname)) {
                                proteinAtomIndices.push(i);
                            }
                        });
                        
                        if (proteinAtomIndices.length > 0) {
                            expandedFrame = {
                                ...expandedFrame,
                                atoms: proteinAtomIndices.map(i => expandedFrame.atoms[i])
                            };
                        }
                    }
                    
                    cache.set(frame.frame, expandedFrame);
                    // Remove from pending
                    this.pendingFrames.delete(`${filename}:${frame.frame}`);
                }
                console.log(`[MD Frames] Cached ${data.frames.length} frames. Total cached: ${cache.size}`);
            }
            
            // Clear any remaining pending markers for this range
            for (let i = fetchStart; i <= fetchEnd; i += stride) {
                this.pendingFrames.delete(`${filename}:${i}`);
            }
            
            resolvePromise(true);
            return true;
        } catch (error) {
            console.error(`[MD Frames] ERROR fetching frames:`, error);
            // Clear pending markers on error
            for (let i = fetchStart; i <= fetchEnd; i += stride) {
                this.pendingFrames.delete(`${filename}:${i}`);
            }
            resolvePromise(false);
            return false;
        }
    }
    
    /**
     * Get a cached frame or fetch it on-demand
     */
    async getFrame(filename, frameIndex) {
        let cache = this.frameCache.get(filename);
        
        if (cache && cache.has(frameIndex)) {
            return cache.get(frameIndex);
        }
        
        // Frame not cached, fetch it
        console.log(`[MD Frame] Frame ${frameIndex} not cached, fetching...`);
        await this.fetchFrameRange(filename, frameIndex, frameIndex);
        
        // Re-get cache after fetch (may have been created)
        cache = this.frameCache.get(filename);
        return cache?.get(frameIndex) || null;
    }

    /**
     * Convert LAMMPS atom type to element symbol
     */
    typeToElement(type) {
        const elements = ['H', 'C', 'N', 'O', 'S', 'P', 'Fe', 'Cu', 'Zn', 'Na', 'Cl', 'Ca', 'Mg', 'K'];
        return elements[(type - 1) % elements.length] || 'C';
    }

    /**
     * Convert GSD particles to atom array
     */
    gsdParticlesToAtoms(particles) {
        if (!particles || !particles.position) return [];
        
        const atoms = [];
        const N = particles.N || particles.position.length / 3;
        
        for (let i = 0; i < N; i++) {
            atoms.push({
                symbol: particles.types ? particles.types[particles.typeid?.[i] || 0] : 'C',
                x: particles.position[i * 3],
                y: particles.position[i * 3 + 1],
                z: particles.position[i * 3 + 2]
            });
        }
        
        return atoms;
    }

    /**
     * Calculate bounding box from atoms (handles both object and array format)
     */
    calculateBoundingBox(atoms) {
        if (!atoms || atoms.length === 0) {
            return { min: { x: 0, y: 0, z: 0 }, max: { x: 10, y: 10, z: 10 } };
        }

        const min = { x: Infinity, y: Infinity, z: Infinity };
        const max = { x: -Infinity, y: -Infinity, z: -Infinity };

        // Check if compact format (array) or object format
        const isCompact = Array.isArray(atoms[0]);

        atoms.forEach(atom => {
            const x = isCompact ? atom[0] : atom.x;
            const y = isCompact ? atom[1] : atom.y;
            const z = isCompact ? atom[2] : atom.z;
            min.x = Math.min(min.x, x);
            min.y = Math.min(min.y, y);
            min.z = Math.min(min.z, z);
            max.x = Math.max(max.x, x);
            max.y = Math.max(max.y, y);
            max.z = Math.max(max.z, z);
        });

        return { min, max };
    }

    /**
     * Create the main viewer component
     */
    async createViewer(container, trajectory, options) {
        // Clear container
        container.innerHTML = '';
        container.style.width = '100%';
        container.style.height = '100%';
        container.style.position = 'relative';

        // Create main container structure
        const mainContainer = document.createElement('div');
        mainContainer.className = `md-trajectory-container ${options.mode}-mode`;
        container.appendChild(mainContainer);

        // Create viewport for 3D rendering
        const viewport = document.createElement('div');
        viewport.className = 'md-viewport';
        mainContainer.appendChild(viewport);

        // Create loading overlay (hidden by default)
        const loadingOverlay = this.createLoadingOverlay();
        viewport.appendChild(loadingOverlay);

        // Create renderer badge
        const statusBadge = document.createElement('div');
        statusBadge.className = `md-status-badge ${this.webgpuSupported ? 'webgpu' : 'webgl'}`;
        statusBadge.innerHTML = `
            <span class="md-status-dot"></span>
            ${this.webgpuSupported ? 'WebGPU' : 'WebGL'}
        `;
        viewport.appendChild(statusBadge);

        // Create format info
        const formatInfo = this.createFormatInfo(trajectory);
        viewport.appendChild(formatInfo);

        // Create control panel
        if (options.showControls) {
            const controlPanel = this.createControlPanel(options);
            viewport.appendChild(controlPanel);
        }

        // Initialize Three.js renderer
        const renderer = await this.initializeRenderer(viewport, trajectory, options);

        // Create playback controls if multi-frame
        if (options.showPlayback && trajectory.frameCount > 1) {
            const playbackControls = this.createPlaybackControls(trajectory, renderer);
            mainContainer.appendChild(playbackControls);
        }

        // Create analysis panel (hidden by default)
        if (options.showAnalysis) {
            const analysisPanel = this.createAnalysisPanel(trajectory);
            viewport.appendChild(analysisPanel);
        }

        // Create atom tooltip
        const tooltip = this.createAtomTooltip();
        viewport.appendChild(tooltip);

        // Setup resize observer
        this.setupResizeObserver(container, renderer);

        // Update loading overlay message (keep visible during initial render)
        const loadingText = loadingOverlay.querySelector('.md-loading-text');
        if (loadingText) {
            loadingText.textContent = 'Rendering first frame...';
        }
        
        // Hide loading overlay after first frame renders (done in renderer's animate loop)
        // Store reference for renderer to access
        renderer.loadingOverlay = loadingOverlay;

        // Auto-detect best representation based on molecule type
        const defaultRepresentation = this.detectBestRepresentation(trajectory);
        
        // Store representation reference that can be updated
        const viewerState = {
            representation: defaultRepresentation
        };
        
        // Pass viewerState to playback handlers so they can access current representation
        if (renderer.playbackState) {
            renderer.playbackState.viewerState = viewerState;
        }
        
        return {
            container: mainContainer,
            viewport,
            renderer,
            trajectory,
            options,
            currentFrame: 0,
            isPlaying: false,
            playbackSpeed: 1,
            representation: defaultRepresentation,
            _viewerState: viewerState,  // Internal reference for updates
            dispose: () => this.disposeViewer(container)
        };
    }

    /**
     * Create loading overlay element
     */
    createLoadingOverlay() {
        const overlay = document.createElement('div');
        overlay.className = 'md-loading-overlay';
        overlay.innerHTML = `
            <div class="md-loading-spinner"></div>
            <div class="md-loading-text">Loading trajectory...</div>
            <div class="md-loading-progress">
                <div class="md-loading-progress-bar" style="width: 0%"></div>
            </div>
        `;
        return overlay;
    }

    /**
     * Create format info badge with simulation time details
     */
    createFormatInfo(trajectory) {
        const info = document.createElement('div');
        info.className = 'md-format-info';
        
        // Get metadata for time information
        const metadata = this.trajectoryMetadata.get(trajectory.filename);
        const timestep = metadata?.timestep || 0;
        const totalTime = metadata?.totalTime || 0;
        
        // Format total simulation time
        let timeStr = '';
        if (totalTime > 0) {
            if (totalTime >= 1000000) {
                timeStr = `${(totalTime / 1000000).toFixed(1)} μs`;
            } else if (totalTime >= 1000) {
                timeStr = `${(totalTime / 1000).toFixed(1)} ns`;
            } else {
                timeStr = `${totalTime.toFixed(0)} ps`;
            }
        }
        
        // Format timestep
        let dtStr = '';
        if (timestep > 0) {
            if (timestep >= 1000) {
                dtStr = `Δt = ${(timestep / 1000).toFixed(1)} ns`;
            } else {
                dtStr = `Δt = ${timestep.toFixed(1)} ps`;
            }
        }
        
        info.innerHTML = `
            <span class="md-format-badge ${trajectory.format}">${trajectory.format.toUpperCase()}</span>
            <span class="md-atom-count">${trajectory.atomCount.toLocaleString()} atoms</span>
            <span class="md-frame-count">${trajectory.frameCount} frame${trajectory.frameCount > 1 ? 's' : ''}</span>
            ${timeStr ? `<span class="md-sim-time" title="Total simulation time">${timeStr}</span>` : ''}
            ${dtStr ? `<span class="md-timestep" title="Time between frames">${dtStr}</span>` : ''}
        `;
        return info;
    }

    /**
     * Create control panel (right side)
     */
    createControlPanel(options) {
        const panel = document.createElement('div');
        panel.className = 'md-control-panel';
        
        // Representation button
        const repBtn = document.createElement('button');
        repBtn.className = 'md-control-btn';
        repBtn.title = 'Representation';
        repBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"/>
                <circle cx="6" cy="6" r="2"/>
                <circle cx="18" cy="6" r="2"/>
                <circle cx="6" cy="18" r="2"/>
                <circle cx="18" cy="18" r="2"/>
                <line x1="8" y1="8" x2="10" y2="10"/>
                <line x1="14" y1="10" x2="16" y2="8"/>
            </svg>
        `;
        panel.appendChild(repBtn);

        // Create representation popup
        const repPopup = this.createRepresentationPopup();
        repBtn.appendChild(repPopup);
        
        repBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            repPopup.classList.toggle('show');
        });

        // Water toggle button (show/hide solvent)
        const waterBtn = document.createElement('button');
        waterBtn.className = 'md-control-btn';
        waterBtn.title = 'Toggle Water/Solvent';
        waterBtn.setAttribute('data-water-visible', 'false');
        waterBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/>
                <line x1="2" y1="2" x2="22" y2="22" stroke-width="2" class="water-hidden-indicator"/>
            </svg>
        `;
        waterBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isVisible = waterBtn.getAttribute('data-water-visible') === 'true';
            waterBtn.setAttribute('data-water-visible', !isVisible);
            // Hide/show the slash indicator
            const slash = waterBtn.querySelector('.water-hidden-indicator');
            if (slash) {
                slash.style.display = !isVisible ? 'none' : 'block';
            }
            // Trigger water toggle in all viewers
            this.toggleWater(!isVisible);
        });
        panel.appendChild(waterBtn);

        // Measurement button
        const measureBtn = document.createElement('button');
        measureBtn.className = 'md-control-btn';
        measureBtn.title = 'Measure Distance';
        measureBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M4 4l16 16"/>
                <path d="M4 4v6h6"/>
                <path d="M20 20v-6h-6"/>
            </svg>
        `;
        measureBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleMeasurementMode();
        });
        panel.appendChild(measureBtn);

        // Center view button
        const centerBtn = document.createElement('button');
        centerBtn.className = 'md-control-btn';
        centerBtn.title = 'Center View';
        centerBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <circle cx="12" cy="12" r="3"/>
                <line x1="12" y1="2" x2="12" y2="6"/>
                <line x1="12" y1="18" x2="12" y2="22"/>
                <line x1="2" y1="12" x2="6" y2="12"/>
                <line x1="18" y1="12" x2="22" y2="12"/>
            </svg>
        `;
        centerBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.centerView();
        });
        panel.appendChild(centerBtn);

        // Screenshot button
        if (options.mode === 'fullview') {
            const screenshotBtn = document.createElement('button');
            screenshotBtn.className = 'md-control-btn';
            screenshotBtn.title = 'Screenshot';
            screenshotBtn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="3" y="3" width="18" height="18" rx="2"/>
                    <circle cx="8.5" cy="8.5" r="1.5"/>
                    <path d="M21 15l-5-5L5 21"/>
                </svg>
            `;
            screenshotBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.takeScreenshot();
            });
            panel.appendChild(screenshotBtn);
        }

        // Close popups when clicking outside
        document.addEventListener('click', () => {
            repPopup.classList.remove('show');
        });

        return panel;
    }

    /**
     * Create representation selection popup
     */
    createRepresentationPopup() {
        const popup = document.createElement('div');
        popup.className = 'md-control-popup';
        
        let html = '<div class="md-popup-title">Representation</div><div class="md-representation-options">';
        
        this.representationModes.forEach((mode, idx) => {
            html += `
                <div class="md-representation-option ${idx === 0 ? 'selected' : ''}" data-rep="${mode.id}">
                    <div class="md-representation-radio"></div>
                    <span class="md-representation-label">${mode.icon} ${mode.name}</span>
                </div>
            `;
        });
        
        html += '</div>';
        popup.innerHTML = html;

        // Add click handlers
        popup.querySelectorAll('.md-representation-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                popup.querySelectorAll('.md-representation-option').forEach(o => o.classList.remove('selected'));
                opt.classList.add('selected');
                const rep = opt.dataset.rep;
                this.changeRepresentation(rep);
            });
        });

        return popup;
    }

    /**
     * Create playback controls (timeline)
     */
    createPlaybackControls(trajectory, renderer) {
        const controls = document.createElement('div');
        controls.className = 'md-playback-controls';

        controls.innerHTML = `
            <button class="md-playback-btn" data-action="first" title="First Frame">
                <svg viewBox="0 0 24 24"><path d="M6 6h2v12H6zM9.5 12l8.5 6V6z"/></svg>
            </button>
            <button class="md-playback-btn" data-action="prev" title="Previous Frame">
                <svg viewBox="0 0 24 24"><path d="M15 6l-8 6 8 6z"/></svg>
            </button>
            <button class="md-playback-btn primary" data-action="play" title="Play/Pause">
                <svg viewBox="0 0 24 24" class="play-icon"><path d="M8 5v14l11-7z"/></svg>
                <svg viewBox="0 0 24 24" class="pause-icon" style="display:none"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>
            </button>
            <button class="md-playback-btn" data-action="next" title="Next Frame">
                <svg viewBox="0 0 24 24"><path d="M9 18l8-6-8-6z"/></svg>
            </button>
            <button class="md-playback-btn" data-action="last" title="Last Frame">
                <svg viewBox="0 0 24 24"><path d="M16 6h2v12h-2zM6 18l8.5-6L6 6z"/></svg>
            </button>
            <div class="md-timeline-container">
                <input type="range" class="md-timeline-slider" min="0" max="${trajectory.frameCount - 1}" value="0">
                <div class="md-timeline-info">
                    <span class="md-frame-counter">Frame: <span class="current-frame">1</span> / ${trajectory.frameCount}</span>
                    <span class="md-time-display" title="Simulation time">t = 0 ps</span>
                </div>
            </div>
            <div class="md-speed-control">
                <span class="md-speed-label">Speed:</span>
                <select class="md-speed-select" title="Playback speed multiplier">
                    <option value="0.1">0.1x</option>
                    <option value="0.25">0.25x</option>
                    <option value="0.5">0.5x</option>
                    <option value="1" selected>1x</option>
                    <option value="2">2x</option>
                    <option value="4">4x</option>
                    <option value="10">10x</option>
                    <option value="30">30x</option>
                </select>
            </div>
        `;

        // Wire up event handlers
        this.setupPlaybackHandlers(controls, trajectory, renderer);

        return controls;
    }

    /**
     * Setup playback control event handlers with progressive loading support
     */
    setupPlaybackHandlers(controls, trajectory, renderer) {
        const slider = controls.querySelector('.md-timeline-slider');
        const currentFrameSpan = controls.querySelector('.current-frame');
        const timeDisplay = controls.querySelector('.md-time-display');
        const playBtn = controls.querySelector('[data-action="play"]');
        const playIcon = playBtn.querySelector('.play-icon');
        const pauseIcon = playBtn.querySelector('.pause-icon');
        const speedSelect = controls.querySelector('.md-speed-select');
        
        // Store playback state on renderer for access by viewer
        renderer.playbackState = {
            viewerState: null  // Will be set by createViewer
        };
        
        // Get loading overlay from viewport (created in createViewer)
        const loadingOverlay = document.querySelector('.md-loading-overlay');

        let isPlaying = false;
        let animationId = null;
        let playbackSpeed = 1;
        let lastFrameTime = 0;
        let firstFrameRendered = false;
        let playStartTime = 0;

        // Helper to format simulation time with appropriate units
        const formatSimTime = (timePs) => {
            if (timePs >= 1000000) {
                return `${(timePs / 1000000).toFixed(2)} μs`; // microseconds
            } else if (timePs >= 1000) {
                return `${(timePs / 1000).toFixed(2)} ns`;  // nanoseconds
            } else if (timePs >= 1) {
                return `${timePs.toFixed(1)} ps`;           // picoseconds
            } else {
                return `${(timePs * 1000).toFixed(1)} fs`;  // femtoseconds
            }
        };

        // Progressive loading: Fetch and display frame
        const updateFrame = async (frameIndex) => {
            const frame = Math.max(0, Math.min(frameIndex, trajectory.frameCount - 1));
            slider.value = frame;
            currentFrameSpan.textContent = frame + 1;
            
            // Get frame data (from cache or fetch)
            let frameData;
            if (trajectory.progressive) {
                frameData = await this.getFrame(trajectory.filename, frame);
                if (!frameData) {
                    console.warn(`[MD Playback] Failed to fetch frame ${frame}`);
                    return false;
                }
            } else {
                frameData = trajectory.frames[frame];
            }
            
            // Get simulation time and format it properly
            const simTime = frameData.time !== undefined ? frameData.time : frame;
            timeDisplay.textContent = `t = ${formatSimTime(simTime)}`;
            
            // Update 3D view
            if (renderer && renderer.updateFrame) {
                const currentRepresentation = renderer.playbackState?.viewerState?.representation || 'ball-stick';
                renderer.updateFrame(frameData, currentRepresentation);
            }
            
            return true; // Success
        };

        // Preload frames ahead for smooth playback
        const preloadFrames = async (currentFrame, count = 5) => {
            if (!trajectory.progressive) return;
            
            const endFrame = Math.min(currentFrame + count, trajectory.frameCount - 1);
            await this.fetchFrameRange(trajectory.filename, currentFrame, endFrame);
        };
        
        // Check if we have enough frames buffered ahead
        const getBufferSize = (currentFrame) => {
            if (!trajectory.progressive) return Infinity;
            
            const cache = this.frameCache.get(trajectory.filename);
            if (!cache) return 0;
            
            let buffered = 0;
            for (let i = currentFrame; i < Math.min(currentFrame + 30, trajectory.frameCount); i++) {
                if (cache.has(i)) {
                    buffered++;
                } else {
                    break; // Count only continuous buffer
                }
            }
            return buffered;
        };

        const animate = async (timestamp) => {
            if (!isPlaying) return;

            const elapsed = timestamp - lastFrameTime;
            const frameInterval = 1000 / (30 * playbackSpeed); // Target 30 fps base

            if (elapsed >= frameInterval) {
                lastFrameTime = timestamp;
                const currentFrame = parseInt(slider.value);
                let nextFrame = currentFrame + 1;
                
                if (nextFrame >= trajectory.frameCount) {
                    nextFrame = 0; // Loop
                }
                
                // Check if next frame is cached or pending (for progressive loading)
                if (trajectory.progressive) {
                    const cache = this.frameCache.get(trajectory.filename);
                    const isFrameCached = cache && cache.has(nextFrame);
                    const frameKey = `${trajectory.filename}:${nextFrame}`;
                    const isPending = this.pendingFrames.has(frameKey);
                    
                    if (!isFrameCached) {
                        // Show buffering indicator if we need to wait
                        if (loadingOverlay) {
                            loadingOverlay.style.display = 'flex';
                            const loadingText = loadingOverlay.querySelector('.md-loading-text');
                            if (loadingText) loadingText.textContent = isPending 
                                ? `Waiting for frame ${nextFrame}...` 
                                : `Loading frame ${nextFrame}...`;
                        }
                        
                        if (isPending) {
                            // Frame is being fetched, wait for it
                            console.log(`[MD Playback] Frame ${nextFrame} pending, waiting...`);
                            await this.pendingFrames.get(frameKey);
                        } else {
                            // Fetch a batch starting from this frame
                            console.log(`[MD Playback] Frame ${nextFrame} not cached, fetching...`);
                            await this.fetchFrameRange(trajectory.filename, nextFrame, Math.min(nextFrame + 20, trajectory.frameCount - 1));
                        }
                        
                        // Hide loading indicator
                        if (loadingOverlay) {
                            loadingOverlay.style.display = 'none';
                        }
                    }
                    
                    // Background preload - stay FAR ahead (non-blocking)
                    const bufferSize = getBufferSize(nextFrame);
                    if (bufferSize < 15 && nextFrame % 5 === 0) {
                        // Trigger background preload every 5 frames if buffer getting low
                        // Preload 30 frames ahead from current position + 10
                        preloadFrames(nextFrame + 10, 30); // Don't await
                    }
                }
                
                const t_frame_start = performance.now();
                await updateFrame(nextFrame);
                
                // Log first frame timing
                if (!firstFrameRendered) {
                    firstFrameRendered = true;
                    const t_first_render = performance.now();
                }
            }

            animationId = requestAnimationFrame(animate);
        };

        const togglePlay = async () => {
            if (!isPlaying) {
                const t_play_start = performance.now();
                console.log(`[MD Timing] ▶️ PLAY pressed at ${new Date().toISOString()}`);
                
                // Starting playback - preload some frames ahead
                const currentFrame = parseInt(slider.value);
                
                if (trajectory.progressive) {
                    console.log(`[MD Timing] Preloading frames...`);
                    // Show brief loading
                    if (loadingOverlay) {
                        loadingOverlay.style.display = 'flex';
                        const loadingText = loadingOverlay.querySelector('.md-loading-text');
                        if (loadingText) loadingText.textContent = 'Preparing playback...';
                    }
                    
                    const t_preload_start = performance.now();
                    // Preload 30 frames ahead for smooth initial playback
                    await preloadFrames(currentFrame, 30);
                    const t_preload_end = performance.now();
                    
                    if (loadingOverlay) {
                        loadingOverlay.style.display = 'none';
                    }
                    console.log(`[MD Timing] Preload complete: ${(t_preload_end - t_preload_start).toFixed(1)}ms`);
                    
                    // Background: preload entire trajectory for seamless looping
                    // Split into batches to avoid overloading the server
                    const batchSize = 30;
                    const preloadAll = async () => {
                        for (let start = currentFrame + 30; start < trajectory.frameCount; start += batchSize) {
                            if (!isPlaying) break; // Stop if paused
                            const end = Math.min(start + batchSize, trajectory.frameCount - 1);
                            console.log(`[MD Preload] Background loading frames ${start}-${end}`);
                            await this.fetchFrameRange(trajectory.filename, start, end);
                        }
                        // Also preload frames before current position for seamless looping
                        for (let start = 0; start < currentFrame; start += batchSize) {
                            if (!isPlaying) break;
                            const end = Math.min(start + batchSize, currentFrame - 1);
                            console.log(`[MD Preload] Background loading frames ${start}-${end}`);
                            await this.fetchFrameRange(trajectory.filename, start, end);
                        }
                        console.log(`[MD Preload] ✅ All frames preloaded`);
                    };
                    preloadAll(); // Don't await - run in background
                }
                
                isPlaying = true;
                firstFrameRendered = false;
                playStartTime = performance.now();
                playIcon.style.display = 'none';
                pauseIcon.style.display = 'block';
                lastFrameTime = performance.now();
                
                const t_play_ready = performance.now();
                console.log(`[MD Timing] 🎬 PLAYBACK STARTING - Time from play press: ${(t_play_ready - t_play_start).toFixed(1)}ms`);
                
                animationId = requestAnimationFrame(animate);
            } else {
                // Pausing
                console.log(`[MD Timing] ⏸️ PAUSE pressed`);
                isPlaying = false;
                playIcon.style.display = 'block';
                pauseIcon.style.display = 'none';
                if (animationId) {
                    cancelAnimationFrame(animationId);
                }
            }
        };

        // Button handlers
        controls.querySelectorAll('.md-playback-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                switch (action) {
                    case 'play':
                        togglePlay();
                        break;
                    case 'first':
                        updateFrame(0);
                        break;
                    case 'last':
                        updateFrame(trajectory.frameCount - 1);
                        break;
                    case 'prev':
                        updateFrame(parseInt(slider.value) - 1);
                        break;
                    case 'next':
                        updateFrame(parseInt(slider.value) + 1);
                        break;
                }
            });
        });

        // Slider handler
        slider.addEventListener('input', () => {
            updateFrame(parseInt(slider.value));
        });

        // Speed control
        speedSelect.addEventListener('change', () => {
            playbackSpeed = parseFloat(speedSelect.value);
        });

        // Store cleanup function
        controls._cleanup = () => {
            if (animationId) {
                cancelAnimationFrame(animationId);
            }
        };
    }

    /**
     * Create analysis panel
     */
    createAnalysisPanel(trajectory) {
        const panel = document.createElement('div');
        panel.className = 'md-analysis-panel';
        
        const frame = trajectory.frames[0];
        const box = trajectory.box;
        
        // Calculate basic statistics
        const stats = this.calculateFrameStatistics(frame, box);
        
        panel.innerHTML = `
            <div class="md-analysis-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 3v18h18"/>
                    <path d="M18 9l-5 5-4-4-3 3"/>
                </svg>
                Frame Analysis
            </div>
            <div class="md-analysis-grid">
                <div class="md-analysis-item">
                    <div class="md-analysis-label">Center of Mass</div>
                    <div class="md-analysis-value">${stats.com.x.toFixed(2)}, ${stats.com.y.toFixed(2)}, ${stats.com.z.toFixed(2)}</div>
                </div>
                <div class="md-analysis-item">
                    <div class="md-analysis-label">Box Size</div>
                    <div class="md-analysis-value">${stats.boxSize.x.toFixed(1)} × ${stats.boxSize.y.toFixed(1)} × ${stats.boxSize.z.toFixed(1)}<span class="md-analysis-unit">Å</span></div>
                </div>
                <div class="md-analysis-item">
                    <div class="md-analysis-label">Density</div>
                    <div class="md-analysis-value">${stats.density.toFixed(4)}<span class="md-analysis-unit">atoms/Å³</span></div>
                </div>
                <div class="md-analysis-item">
                    <div class="md-analysis-label">Max Distance</div>
                    <div class="md-analysis-value">${stats.maxDist.toFixed(2)}<span class="md-analysis-unit">Å</span></div>
                </div>
            </div>
        `;
        
        return panel;
    }

    /**
     * Calculate frame statistics
     */
    calculateFrameStatistics(frame, box) {
        const atoms = frame.atoms;
        const n = atoms.length;
        
        // Center of mass (assuming equal masses)
        // Handle both object and compact array format
        const isCompact = Array.isArray(atoms[0]);
        const getX = isCompact ? (a) => a[0] : (a) => a.x;
        const getY = isCompact ? (a) => a[1] : (a) => a.y;
        const getZ = isCompact ? (a) => a[2] : (a) => a.z;
        
        const com = { x: 0, y: 0, z: 0 };
        atoms.forEach(a => {
            com.x += getX(a);
            com.y += getY(a);
            com.z += getZ(a);
        });
        com.x /= n;
        com.y /= n;
        com.z /= n;
        
        // Box size - handle both object {min, max} and array [x, y, z] format
        let boxSize;
        if (Array.isArray(box)) {
            // Compact format: [x, y, z]
            boxSize = { x: box[0], y: box[1], z: box[2] };
        } else if (box && box.max && box.min) {
            // Object format: {min: {x,y,z}, max: {x,y,z}}
            boxSize = {
                x: box.max.x - box.min.x,
                y: box.max.y - box.min.y,
                z: box.max.z - box.min.z
            };
        } else {
            // Fallback: calculate from atoms
            const atomBox = this.calculateBoundingBox(atoms);
            boxSize = {
                x: atomBox.max.x - atomBox.min.x,
                y: atomBox.max.y - atomBox.min.y,
                z: atomBox.max.z - atomBox.min.z
            };
        }
        
        // Density
        const volume = boxSize.x * boxSize.y * boxSize.z;
        const density = volume > 0 ? n / volume : 0;
        
        // Max distance from COM
        let maxDist = 0;
        atoms.forEach(a => {
            const d = Math.sqrt(
                Math.pow(getX(a) - com.x, 2) +
                Math.pow(getY(a) - com.y, 2) +
                Math.pow(getZ(a) - com.z, 2)
            );
            maxDist = Math.max(maxDist, d);
        });
        
        return { com, boxSize, density, maxDist };
    }

    /**
     * Create atom info tooltip
     */
    createAtomTooltip() {
        const tooltip = document.createElement('div');
        tooltip.className = 'md-atom-tooltip';
        tooltip.innerHTML = `
            <div class="md-atom-symbol">C</div>
            <div class="md-atom-details">Carbon</div>
            <div class="md-atom-coords">x: 0.00, y: 0.00, z: 0.00</div>
        `;
        return tooltip;
    }

    /**
     * Initialize Three.js renderer
     */
    async initializeRenderer(viewport, trajectory, options) {
        const scene = new THREE.Scene();
        
        // Professional dark gradient background (like PyMOL/Chimera)
        // Create gradient texture for background
        const bgCanvas = document.createElement('canvas');
        bgCanvas.width = 2;
        bgCanvas.height = 512;
        const bgCtx = bgCanvas.getContext('2d');
        const gradient = bgCtx.createLinearGradient(0, 0, 0, 512);
        gradient.addColorStop(0, '#1a1a2e');    // Dark blue-gray at top
        gradient.addColorStop(0.5, '#16213e');  // Deep navy in middle
        gradient.addColorStop(1, '#0f0f1a');    // Near black at bottom
        bgCtx.fillStyle = gradient;
        bgCtx.fillRect(0, 0, 2, 512);
        
        const bgTexture = new THREE.CanvasTexture(bgCanvas);
        bgTexture.needsUpdate = true;
        scene.background = bgTexture;

        // Get viewport dimensions
        const rect = viewport.getBoundingClientRect();
        const width = rect.width || 400;
        const height = rect.height || 300;

        // Create camera
        const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 1000);

        // Create renderer
        const renderer = new THREE.WebGLRenderer({ 
            antialias: true,
            alpha: true,
            powerPreference: 'high-performance'
        });
        renderer.setSize(width, height);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        
        // Professional tone mapping for better color reproduction
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.2;
        renderer.outputColorSpace = THREE.SRGBColorSpace;

        const canvas = renderer.domElement;
        canvas.className = 'webgl-canvas';
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        viewport.insertBefore(canvas, viewport.firstChild);

        // Add subtle depth fog for atmospheric perspective (enhances 3D perception)
        scene.fog = new THREE.Fog(0x0f0f1a, 50, 200);

        // Professional 3-point lighting setup (key, fill, rim) for publication-quality rendering
        // Slightly warm ambient for depth
        const ambientLight = new THREE.AmbientLight(0x404050, 0.4);
        scene.add(ambientLight);

        // Hemisphere light for natural sky/ground illumination
        const hemiLight = new THREE.HemisphereLight(0xffffff, 0x444466, 0.3);
        hemiLight.position.set(0, 1, 0);
        scene.add(hemiLight);

        // Key light - main illumination (warm white, upper right)
        const keyLight = new THREE.DirectionalLight(0xfffaf0, 1.0);
        keyLight.position.set(2, 3, 2);
        scene.add(keyLight);

        // Fill light - softer, from opposite side (cool tint)
        const fillLight = new THREE.DirectionalLight(0xe0e8ff, 0.4);
        fillLight.position.set(-2, 0, 1);
        scene.add(fillLight);

        // Rim/back light - edge definition (subtle warm)
        const rimLight = new THREE.DirectionalLight(0xfff0e0, 0.3);
        rimLight.position.set(0, -1, -2);
        scene.add(rimLight);

        // Bottom fill to reduce harsh shadows
        const bottomLight = new THREE.DirectionalLight(0x8090a0, 0.15);
        bottomLight.position.set(0, -2, 0);
        scene.add(bottomLight);

        // Create molecule group
        const moleculeGroup = new THREE.Group();
        scene.add(moleculeGroup);

        // Auto-detect best representation BEFORE building geometry
        const defaultRepresentation = this.detectBestRepresentation(trajectory);
        console.log(`[MD Renderer] Using auto-detected representation: ${defaultRepresentation}`);

        // Add atoms and bonds
        console.log(`[MD Renderer] Building geometry for ${trajectory.frames[0].atoms.length} atoms`);
        const t_build_start = performance.now();
        this.buildMoleculeGeometry(moleculeGroup, trajectory.frames[0], defaultRepresentation);
        const t_build_end = performance.now();
        console.log(`[MD Renderer] Geometry built in ${(t_build_end - t_build_start).toFixed(1)}ms, group has ${moleculeGroup.children.length} children`);
        
        // Start background pre-building of geometry for smooth animation (ribbon/cartoon only)
        if (trajectory.frameCount > 1) {
            this.startGeometryPreBuild(trajectory, defaultRepresentation);
        }

        // Calculate bounding box from atom positions (Box3.setFromObject doesn't work with InstancedMesh)
        const positions = trajectory.frames[0].atoms;
        const isCompact = Array.isArray(positions[0]);
        let minX = Infinity, minY = Infinity, minZ = Infinity;
        let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
        
        positions.forEach(atom => {
            const x = isCompact ? atom[0] : atom.x;
            const y = isCompact ? atom[1] : atom.y;
            const z = isCompact ? atom[2] : atom.z;
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            minZ = Math.min(minZ, z);
            maxX = Math.max(maxX, x);
            maxY = Math.max(maxY, y);
            maxZ = Math.max(maxZ, z);
        });
        
        const center = new THREE.Vector3(
            (minX + maxX) / 2,
            (minY + maxY) / 2,
            (minZ + maxZ) / 2
        );
        const size = new THREE.Vector3(
            maxX - minX,
            maxY - minY,
            maxZ - minZ
        );
        const maxDim = Math.max(size.x, size.y, size.z);
        
        console.log(`[MD Renderer] Bounding box - center: (${center.x.toFixed(1)}, ${center.y.toFixed(1)}, ${center.z.toFixed(1)}), size: (${size.x.toFixed(1)}, ${size.y.toFixed(1)}, ${size.z.toFixed(1)}), maxDim: ${maxDim.toFixed(1)}`);

        // Center molecule at origin
        moleculeGroup.position.sub(center);

        // Position camera
        const distance = maxDim / Math.tan(camera.fov * Math.PI / 360) / 1.5;
        camera.position.set(distance * 0.6, distance * 0.4, distance * 0.7);
        camera.lookAt(0, 0, 0);
        
        // Store initial camera state for centerView()
        this.initialCameraPosition = camera.position.clone();
        this.initialCameraTarget = new THREE.Vector3(0, 0, 0);
        
        if (moleculeGroup.children.length > 0) {
            moleculeGroup.children.forEach((child, i) => {
                console.log(`[MD Renderer] Child ${i}: ${child.type}, visible: ${child.visible}, geometry: ${child.geometry?.type}, count: ${child.count || 'N/A'}`);
            });
        }

        // Add orbit controls
        let controls = null;
        const OrbitControls = THREE.OrbitControls || window.THREE?.OrbitControls;
        if (OrbitControls) {
            controls = new OrbitControls(camera, renderer.domElement);
            controls.target.set(0, 0, 0);
            controls.enableDamping = true;
            controls.dampingFactor = 0.05;
            controls.minDistance = distance * 0.3;
            controls.maxDistance = distance * 4;
        }

        // Animation loop
        let animationId;
        let isRunning = true;
        let frameCount = 0;
        let firstFrameRendered = false;

        const animate = () => {
            if (!isRunning) return;
            
            animationId = requestAnimationFrame(animate);
            
            if (!document.body.contains(viewport)) {
                isRunning = false;
                return;
            }

            if (controls) {
                controls.update();
            }

            renderer.render(scene, camera);
            
            // Hide loading overlay after first frame is rendered
            if (!firstFrameRendered) {
                firstFrameRendered = true;
                const loadingOverlay = viewport.querySelector('.md-loading-overlay');
                if (loadingOverlay) {
                    loadingOverlay.style.display = 'none';
                    console.log('[MD Renderer] First frame rendered, loading overlay hidden');
                }
            }
            
            frameCount++;
            
            // Log first few frames
            if (frameCount < 3) {
                console.log(`[MD Renderer] Frame ${frameCount} rendered, scene children: ${scene.children.length}`);
            }
            frameCount++;
        };

        console.log(`[MD Renderer] Starting animation loop...`);
        animate();

        // Return renderer object with update methods
        return {
            scene,
            camera,
            renderer,
            controls,
            moleculeGroup,
            trajectory,
            viewport,
            animationId,
            isRunning: () => isRunning,
            stopAnimation: () => {
                isRunning = false;
                if (animationId) {
                    cancelAnimationFrame(animationId);
                }
            },
            updateFrame: (frame, representation) => {
                this.updateMoleculeGeometry(moleculeGroup, frame, representation);
            },
            changeRepresentation: (rep) => {
                this.clearMoleculeGroup(moleculeGroup);
                // Expand frame if in compact format before building geometry
                const metadata = this.trajectoryMetadata.get(trajectory.filename);
                const frame = metadata?.compact ? 
                    this.expandCompactFrame(
                        trajectory.frames[0], 
                        metadata.symbols,
                        metadata.atomnames || [],
                        metadata.secondaryStructure || []
                    ) : 
                    trajectory.frames[0];
                this.buildMoleculeGeometry(moleculeGroup, frame, rep);
                
                // Update stored representation
                const viewerEntry = Array.from(this.viewers.values()).find(v => v.renderer?.moleculeGroup === moleculeGroup);
                if (viewerEntry) {
                    // Also update internal state reference
                    if (viewerEntry._viewerState) {
                        viewerEntry._viewerState.representation = rep;
                    }
                    viewerEntry.representation = rep;
                }
                
                // Start background pre-build for ribbon/cartoon
                if (trajectory.frameCount > 1) {
                    this.startGeometryPreBuild(trajectory, rep);
                }
            },
            resize: (w, h) => {
                camera.aspect = w / h;
                camera.updateProjectionMatrix();
                renderer.setSize(w, h);
            }
        };
    }

    /**
     * Build molecule 3D geometry
     * Note: atoms must be in expanded object format {x, y, z, symbol}
     * Compact format [x,y,z] must be expanded using expandCompactFrame() before calling
     */
    buildMoleculeGeometry(group, frame, representation) {
        const t_start = performance.now();
        const atoms = frame.atoms;
        const THREE = window.THREE;

        // Create instanced geometry for better performance with many atoms
        const atomCount = atoms.length;
        
        if (representation === 'ribbon') {
            // RIBBON: Flat twisting ribbon through backbone (GROMACS/VMD style)
            const backbone = this.extractBackbone(atoms);
            
            if (backbone.length < 2) {
                console.warn('[MD Geometry] Not enough backbone atoms for ribbon, falling back to ball-stick');
                return this.buildMoleculeGeometry(group, frame, 'ball-stick');
            }
            
            // Create one continuous spline through all backbone atoms
            const points = backbone.map(atom => new THREE.Vector3(atom.x, atom.y, atom.z));
            const curve = new THREE.CatmullRomCurve3(points);
            
            // FLAT RIBBON GEOMETRY - wide and thin like a tape
            const ribbonWidth = 1.6;       // Width of the ribbon (visible flat surface)
            const ribbonThickness = 0.15;  // Thickness (thin like paper)
            const segments = Math.max(backbone.length * 8, 300); // High resolution for smoothness
            
            // Get points along the curve
            const curvePoints = curve.getPoints(segments);
            const tangents = [];
            const normals = [];
            const binormals = [];
            
            // Compute Frenet-Serret frame along the curve
            for (let i = 0; i < curvePoints.length; i++) {
                const t = i / (curvePoints.length - 1);
                tangents.push(curve.getTangent(t).normalize());
            }
            
            // Compute initial normal - try to align with local helix/sheet plane
            // Use a vector based on the curve's initial curvature
            const up = new THREE.Vector3(0, 1, 0);
            let lastNormal = new THREE.Vector3().crossVectors(tangents[0], up).normalize();
            if (lastNormal.length() < 0.1) {
                lastNormal = new THREE.Vector3().crossVectors(tangents[0], new THREE.Vector3(1, 0, 0)).normalize();
            }
            
            // Propagate normal along curve using parallel transport (minimizes twist)
            for (let i = 0; i < curvePoints.length; i++) {
                const tangent = tangents[i];
                // Project last normal onto plane perpendicular to current tangent
                const normal = lastNormal.clone().sub(tangent.clone().multiplyScalar(lastNormal.dot(tangent))).normalize();
                normals.push(normal);
                binormals.push(new THREE.Vector3().crossVectors(tangent, normal).normalize());
                lastNormal = normal;
            }
            
            // Create ribbon vertices (4 vertices per curve point for rectangular cross-section)
            const vertices = [];
            const colors = [];
            const indices = [];
            const uvs = [];
            
            const hw = ribbonWidth * 0.5;   // Half-width
            const ht = ribbonThickness * 0.5; // Half-thickness
            
            for (let i = 0; i < curvePoints.length; i++) {
                const p = curvePoints[i];
                const n = normals[i];     // Points across the ribbon (width direction)
                const b = binormals[i];   // Points up/down (thickness direction)
                
                // Calculate rainbow color for this position
                const t = i / (curvePoints.length - 1);
                const hue = (1 - t) * 0.65; // blue(0.65) → red(0)
                const saturation = 0.85;
                const lightness = 0.55;
                const color = new THREE.Color().setHSL(hue, saturation, lightness);
                
                // 4 vertices for rectangular cross-section:
                // 0: top-right, 1: top-left, 2: bottom-left, 3: bottom-right
                vertices.push(
                    p.x + n.x * hw + b.x * ht, p.y + n.y * hw + b.y * ht, p.z + n.z * hw + b.z * ht,  // 0: top-right
                    p.x - n.x * hw + b.x * ht, p.y - n.y * hw + b.y * ht, p.z - n.z * hw + b.z * ht,  // 1: top-left
                    p.x - n.x * hw - b.x * ht, p.y - n.y * hw - b.y * ht, p.z - n.z * hw - b.z * ht,  // 2: bottom-left
                    p.x + n.x * hw - b.x * ht, p.y + n.y * hw - b.y * ht, p.z + n.z * hw - b.z * ht   // 3: bottom-right
                );
                
                // Same color for all 4 vertices at this position
                for (let v = 0; v < 4; v++) {
                    colors.push(color.r, color.g, color.b);
                }
                
                // UVs for potential texturing
                const u = t;
                uvs.push(u, 0, u, 0.33, u, 0.66, u, 1);
            }
            
            // Create faces connecting adjacent cross-sections
            for (let i = 0; i < curvePoints.length - 1; i++) {
                const base = i * 4;
                const next = (i + 1) * 4;
                
                // Top face (main visible surface)
                indices.push(base + 0, next + 0, next + 1);
                indices.push(base + 0, next + 1, base + 1);
                
                // Left edge
                indices.push(base + 1, next + 1, next + 2);
                indices.push(base + 1, next + 2, base + 2);
                
                // Bottom face
                indices.push(base + 2, next + 2, next + 3);
                indices.push(base + 2, next + 3, base + 3);
                
                // Right edge
                indices.push(base + 3, next + 3, next + 0);
                indices.push(base + 3, next + 0, base + 0);
            }
            
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
            geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
            geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
            geometry.setIndex(indices);
            geometry.computeVertexNormals();
            
            // Physically-based material for realistic appearance
            const material = new THREE.MeshStandardMaterial({
                vertexColors: true,
                roughness: 0.3,       // Glossy surface
                metalness: 0.05,      // Slight sheen
                side: THREE.DoubleSide,
                flatShading: false    // Smooth shading
            });
            
            const mesh = new THREE.Mesh(geometry, material);
            mesh.userData = { type: 'ribbon' };
            group.add(mesh);
            
            // Rounded end caps (small spheres at N and C terminus)
            const capRadius = Math.max(ribbonWidth, ribbonThickness) * 0.3;
            
            // N-terminus cap (blue)
            const nCapMaterial = new THREE.MeshStandardMaterial({
                color: new THREE.Color().setHSL(0.65, 0.85, 0.55),
                roughness: 0.3,
                metalness: 0.05
            });
            const capGeometry = new THREE.SphereGeometry(capRadius, 12, 12);
            const nCap = new THREE.Mesh(capGeometry, nCapMaterial);
            nCap.position.copy(points[0]);
            group.add(nCap);
            
            // C-terminus cap (red)
            const cCapMaterial = new THREE.MeshStandardMaterial({
                color: new THREE.Color().setHSL(0, 0.85, 0.55),
                roughness: 0.3,
                metalness: 0.05
            });
            const cCap = new THREE.Mesh(capGeometry, cCapMaterial);
            cCap.position.copy(points[points.length - 1]);
            group.add(cCap);
            
        } else if (representation === 'cartoon') {
            // Cartoon representation - extract backbone and render as ribbon
            const backbone = this.extractBackbone(atoms);
            
            if (backbone.length < 2) {
                console.warn('[MD Geometry] Not enough backbone atoms for cartoon, falling back to ball-stick');
                return this.buildMoleculeGeometry(group, frame, 'ball-stick');
            }
            
            // Group backbone by secondary structure for different rendering
            const segments = this.segmentBySecondaryStructure(backbone);
            
            // Professional secondary structure colors (PyMOL/Chimera style)
            const ssColors = {
                'H': new THREE.Color(0xCC44CC),  // Deep magenta for α-helices
                'E': new THREE.Color(0xFFC107),  // Amber gold for β-sheets  
                'C': new THREE.Color(0x66CCCC)   // Soft cyan for coils/loops
            };
            
            // Slightly different materials per structure type for visual distinction
            const ssMaterials = {
                'H': new THREE.MeshStandardMaterial({
                    color: ssColors['H'],
                    roughness: 0.3,
                    metalness: 0.1,
                    side: THREE.DoubleSide
                }),
                'E': new THREE.MeshStandardMaterial({
                    color: ssColors['E'],
                    roughness: 0.4,
                    metalness: 0.05,
                    side: THREE.DoubleSide
                }),
                'C': new THREE.MeshStandardMaterial({
                    color: ssColors['C'],
                    roughness: 0.5,
                    metalness: 0.0,
                    side: THREE.DoubleSide
                })
            };
            
            segments.forEach((segment, segIdx) => {
                const { type, atoms: segAtoms, startOverlap, endOverlap } = segment;
                
                console.log(`[MD Cartoon] Segment ${segIdx}: type=${type}, atoms=${segAtoms.length}, hasStart=${!!startOverlap}, hasEnd=${!!endOverlap}`);
                
                // Build curve atoms with overlap for smooth connections
                let curveAtoms = [];
                
                // Add start overlap atom if available (from previous segment)
                if (startOverlap) {
                    curveAtoms.push(startOverlap);
                }
                
                // Add all segment atoms
                curveAtoms.push(...segAtoms);
                
                // Add end overlap atom if available (first atom of next segment)
                if (endOverlap) {
                    curveAtoms.push(endOverlap);
                }
                
                // Handle very short segments
                if (curveAtoms.length < 2) {
                    const idx = backbone.indexOf(segAtoms[0]);
                    if (idx > 0 && idx < backbone.length - 1) {
                        curveAtoms = [backbone[idx - 1], segAtoms[0], backbone[idx + 1]];
                    } else if (idx === 0 && backbone.length > 1) {
                        curveAtoms = [segAtoms[0], backbone[1]];
                    } else if (idx === backbone.length - 1 && idx > 0) {
                        curveAtoms = [backbone[idx - 1], segAtoms[0]];
                    }
                }
                
                if (curveAtoms.length < 2) {
                    console.log(`[MD Cartoon] Skipping segment ${segIdx}: not enough atoms`);
                    return;
                }
                
                const points = curveAtoms.map(atom => new THREE.Vector3(atom.x, atom.y, atom.z));
                const curve = new THREE.CatmullRomCurve3(points);
                
                // Different geometry for each secondary structure type (PyMOL/Chimera style)
                let geometry;
                const numPoints = curveAtoms.length;
                
                if (type === 'H') {
                    // HELIX: Wide helical ribbon (PyMOL-style spiral ribbon)
                    geometry = this.createHelixRibbonGeometry(curve, numPoints, backbone, curveAtoms);
                } else if (type === 'E') {
                    // SHEET: Flat arrow with arrowhead at C-terminus
                    geometry = this.createSheetArrowGeometry(curve, numPoints);
                } else {
                    // COIL: Smooth tube for loops/turns (more visible)
                    const coilSegments = Math.max(numPoints * 6, 32);
                    geometry = new THREE.TubeGeometry(
                        curve,
                        coilSegments,
                        0.3,   // Slightly thicker for visibility
                        10,    // Smooth tube
                        false
                    );
                }
                
                // Use PBR material for this structure type
                const mesh = new THREE.Mesh(geometry, ssMaterials[type]);
                mesh.userData = { type: 'cartoon', ssType: type };
                group.add(mesh);
            });
            
        } else if (representation === 'points') {
            // Points representation - fastest
            const positions = new Float32Array(atomCount * 3);
            const colors = new Float32Array(atomCount * 3);
            
            // Note: atoms must be in object format {x, y, z, symbol} - expand before calling if needed
            atoms.forEach((atom, i) => {
                positions[i * 3] = atom.x;
                positions[i * 3 + 1] = atom.y;
                positions[i * 3 + 2] = atom.z;
                
                const color = new THREE.Color(this.atomColors[atom.symbol] || this.atomColors.default);
                colors[i * 3] = color.r;
                colors[i * 3 + 1] = color.g;
                colors[i * 3 + 2] = color.b;
            });
            
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
            geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
            
            const material = new THREE.PointsMaterial({
                size: 0.3,
                vertexColors: true,
                sizeAttenuation: true
            });
            
            const points = new THREE.Points(geometry, material);
            group.add(points);
            
        } else if (representation === 'wireframe') {
            // Wireframe - bonds only
            const bonds = this.detectBonds(atoms);
            bonds.forEach(bond => {
                const [i, j] = bond;
                const a1 = atoms[i], a2 = atoms[j];
                
                const geometry = new THREE.BufferGeometry().setFromPoints([
                    new THREE.Vector3(a1.x, a1.y, a1.z),
                    new THREE.Vector3(a2.x, a2.y, a2.z)
                ]);
                
                const material = new THREE.LineBasicMaterial({ color: 0x888888 });
                const line = new THREE.Line(geometry, material);
                group.add(line);
            });
            
        } else if (representation === 'spacefill') {
            // Spacefill - large spheres, no bonds
            atoms.forEach(atom => {
                const radius = (this.atomRadii[atom.symbol] || this.atomRadii.default) * 1.5;
                const color = this.atomColors[atom.symbol] || this.atomColors.default;
                
                const geometry = new THREE.SphereGeometry(radius, 24, 16);
                const material = new THREE.MeshPhongMaterial({ 
                    color,
                    shininess: 80
                });
                
                const sphere = new THREE.Mesh(geometry, material);
                sphere.position.set(atom.x, atom.y, atom.z);
                sphere.userData = { atom };
                group.add(sphere);
            });
            
        } else if (representation === 'licorice') {
            // Licorice - thin cylinders for bonds, small spheres at atoms
            const bonds = this.detectBonds(atoms);
            const bondRadius = 0.15;
            
            // Add atoms as small spheres
            atoms.forEach(atom => {
                const radius = bondRadius * 1.1;
                const color = this.atomColors[atom.symbol] || this.atomColors.default;
                
                const geometry = new THREE.SphereGeometry(radius, 12, 8);
                const material = new THREE.MeshPhongMaterial({ color, shininess: 80 });
                const sphere = new THREE.Mesh(geometry, material);
                sphere.position.set(atom.x, atom.y, atom.z);
                group.add(sphere);
            });
            
            // Add bonds
            bonds.forEach(bond => {
                const [i, j] = bond;
                const a1 = atoms[i], a2 = atoms[j];
                
                this.createCylinderBond(group, a1, a2, bondRadius, 0x888888);
            });
            
        } else {
            // Ball and stick (default) - USE INSTANCED RENDERING for performance
            const t_atoms_start = performance.now();
            
            // Create instanced geometry for atoms
            const atomGeometry = new THREE.SphereGeometry(0.4, 16, 12); // Base size, lower poly for performance
            const atomMaterial = new THREE.MeshPhongMaterial({ 
                shininess: 100,
                specular: 0x444444
            });
            
            const atomInstances = new THREE.InstancedMesh(atomGeometry, atomMaterial, atomCount);
            atomInstances.instanceMatrix.setUsage(THREE.DynamicDrawUsage); // Will update for animation
            
            const atomColor = new THREE.Color();
            const atomMatrix = new THREE.Matrix4();
            const atomScale = new THREE.Vector3();
            
            atoms.forEach((atom, i) => {
                // Set position and scale
                const radius = this.atomRadii[atom.symbol] || this.atomRadii.default;
                atomScale.set(radius/0.4, radius/0.4, radius/0.4); // Scale from base size
                atomMatrix.compose(
                    new THREE.Vector3(atom.x, atom.y, atom.z),
                    new THREE.Quaternion(),
                    atomScale
                );
                atomInstances.setMatrixAt(i, atomMatrix);
                
                // Set color
                atomColor.setHex(this.atomColors[atom.symbol] || this.atomColors.default);
                atomInstances.setColorAt(i, atomColor);
            });
            
            // CRITICAL: Mark matrices and colors as needing GPU upload
            atomInstances.instanceMatrix.needsUpdate = true;
            if (atomInstances.instanceColor) {
                atomInstances.instanceColor.needsUpdate = true;
            }
            
            atomInstances.userData = { type: 'atoms', frame };
            group.add(atomInstances);
            
            const t_atoms_end = performance.now();
            console.log(`[MD Geometry] Atoms created: ${(t_atoms_end - t_atoms_start).toFixed(1)}ms (instanced)`);
            
            // Add bonds (also instanced for large systems)
            const t_bonds_start = performance.now();
            const bonds = this.detectBonds(atoms);
            console.log(`[MD Geometry] Detected ${bonds.length} bonds`);
            
            if (bonds.length > 0) {
                // Use instanced rendering for bonds too
                const bondGeometry = new THREE.CylinderGeometry(0.08, 0.08, 1, 8, 1);
                const bondMaterial = new THREE.MeshPhongMaterial({ 
                    color: 0x888888,
                    shininess: 60
                });
                
                const bondInstances = new THREE.InstancedMesh(bondGeometry, bondMaterial, bonds.length);
                bondInstances.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
                
                // Reuse objects to avoid GC pressure
                const bondMatrix = new THREE.Matrix4();
                const bondQuaternion = new THREE.Quaternion();
                const midpoint = new THREE.Vector3();
                const direction = new THREE.Vector3();
                const bondScale = new THREE.Vector3();
                const bondAxis = new THREE.Vector3(0, 1, 0);
                
                for (let idx = 0; idx < bonds.length; idx++) {
                    const [i, j] = bonds[idx];
                    const a1 = atoms[i], a2 = atoms[j];
                    
                    // Compute midpoint inline
                    midpoint.x = (a1.x + a2.x) * 0.5;
                    midpoint.y = (a1.y + a2.y) * 0.5;
                    midpoint.z = (a1.z + a2.z) * 0.5;
                    
                    // Compute direction and length
                    direction.x = a2.x - a1.x;
                    direction.y = a2.y - a1.y;
                    direction.z = a2.z - a1.z;
                    const length = Math.sqrt(direction.x * direction.x + direction.y * direction.y + direction.z * direction.z);
                    
                    // Normalize direction
                    const invLen = 1.0 / length;
                    direction.x *= invLen;
                    direction.y *= invLen;
                    direction.z *= invLen;
                    
                    // Set orientation
                    bondQuaternion.setFromUnitVectors(bondAxis, direction);
                    
                    // Set scale
                    bondScale.set(1, length, 1);
                    
                    // Compose and set matrix
                    bondMatrix.compose(midpoint, bondQuaternion, bondScale);
                    bondInstances.setMatrixAt(idx, bondMatrix);
                }
                
                // CRITICAL: Mark matrices as needing GPU upload
                bondInstances.instanceMatrix.needsUpdate = true;
                
                // Store bond connectivity for fast updates
                bondInstances.userData = { type: 'bonds', bonds: bonds };
                group.add(bondInstances);
            }
            
            const t_bonds_end = performance.now();
            console.log(`[MD Geometry] Bonds created: ${(t_bonds_end - t_bonds_start).toFixed(1)}ms (instanced)`);
        }
        
        const t_end = performance.now();
    }

    /**
     * Extract backbone atoms (C-alpha) for cartoon representation
     */
    extractBackbone(atoms) {
        // For proteins, extract C-alpha atoms (CA)
        // C-alpha is the central carbon in each amino acid residue
        const backbone = [];
        
        for (let i = 0; i < atoms.length; i++) {
            const atom = atoms[i];
            // Check if atom has atomname property and it's CA (C-alpha)
            if (atom.atomname === 'CA') {
                backbone.push(atom);
            }
        }
        
        // If no CA atoms found, use simple heuristic: sample carbons uniformly
        if (backbone.length < 10) {
            for (let i = 0; i < atoms.length; i++) {
                const atom = atoms[i];
                // Sample every ~15 atoms (approximate amino acid size)
                if (i % 15 === 0 || (atom.symbol === 'C' && i % 5 === 0)) {
                    backbone.push(atom);
                }
            }
        }
        
        // If still too few, just sample uniformly
        if (backbone.length < 10) {
            backbone.length = 0;
            const step = Math.max(1, Math.floor(atoms.length / 100));
            for (let i = 0; i < atoms.length; i += step) {
                backbone.push(atoms[i]);
            }
        }
        
        return backbone;
    }

    /**
     * Segment backbone atoms by secondary structure (H/E/C)
     * Each segment includes overlap atoms at boundaries for smooth connections
     */
    segmentBySecondaryStructure(backbone) {
        const segments = [];
        if (backbone.length === 0) return segments;
        
        let currentType = backbone[0].ss || 'C';
        let currentSegment = [backbone[0]];
        
        for (let i = 1; i < backbone.length; i++) {
            const ssType = backbone[i].ss || 'C';
            
            if (ssType === currentType) {
                currentSegment.push(backbone[i]);
            } else {
                // Include last atom of current segment for overlap with next
                segments.push({ 
                    type: currentType, 
                    atoms: currentSegment,
                    endOverlap: backbone[i]  // First atom of next segment
                });
                currentType = ssType;
                // Start new segment with overlap from previous
                currentSegment = [backbone[i]];
            }
        }
        
        // Add final segment (no end overlap needed)
        segments.push({ type: currentType, atoms: currentSegment, endOverlap: null });
        
        // Add start overlap to each segment (except first)
        for (let i = 1; i < segments.length; i++) {
            segments[i].startOverlap = segments[i - 1].atoms[segments[i - 1].atoms.length - 1];
        }
        segments[0].startOverlap = null;
        
        return segments;
    }

    /**
     * Create helical ribbon geometry for α-helices (PyMOL/Chimera style)
     * Creates a wide ribbon that follows the helix backbone with proper curvature
     */
    createHelixRibbonGeometry(curve, numPoints, backbone, curveAtoms) {
        const THREE = window.THREE;
        
        // Helix parameters
        const ribbonWidth = 1.4;      // Wide ribbon
        const ribbonThickness = 0.3;  // Some thickness for 3D look
        const segments = Math.max(numPoints * 10, 80);
        
        // Get points along the curve
        const curvePoints = curve.getPoints(segments);
        const tangents = [];
        const normals = [];
        const binormals = [];
        
        // Compute Frenet-Serret frame along the curve
        for (let i = 0; i < curvePoints.length; i++) {
            const t = i / (curvePoints.length - 1);
            tangents.push(curve.getTangent(t).normalize());
        }
        
        // Compute initial normal (perpendicular to first tangent)
        const up = new THREE.Vector3(0, 1, 0);
        let lastNormal = new THREE.Vector3().crossVectors(tangents[0], up).normalize();
        if (lastNormal.length() < 0.1) {
            lastNormal = new THREE.Vector3().crossVectors(tangents[0], new THREE.Vector3(1, 0, 0)).normalize();
        }
        
        // Propagate normal along curve (minimize twist)
        for (let i = 0; i < curvePoints.length; i++) {
            const tangent = tangents[i];
            // Project last normal onto plane perpendicular to current tangent
            const normal = lastNormal.clone().sub(tangent.clone().multiplyScalar(lastNormal.dot(tangent))).normalize();
            normals.push(normal);
            binormals.push(new THREE.Vector3().crossVectors(tangent, normal).normalize());
            lastNormal = normal;
        }
        
        // Create ribbon vertices (2 vertices per curve point - left and right edges)
        const vertices = [];
        const indices = [];
        const uvs = [];
        
        for (let i = 0; i < curvePoints.length; i++) {
            const p = curvePoints[i];
            const n = normals[i];
            const b = binormals[i];
            
            // Create 4 vertices for a rectangular cross-section
            // Top-left, top-right, bottom-left, bottom-right
            const hw = ribbonWidth * 0.5;
            const ht = ribbonThickness * 0.5;
            
            vertices.push(
                p.x + n.x * hw + b.x * ht, p.y + n.y * hw + b.y * ht, p.z + n.z * hw + b.z * ht,  // top-right
                p.x - n.x * hw + b.x * ht, p.y - n.y * hw + b.y * ht, p.z - n.z * hw + b.z * ht,  // top-left
                p.x - n.x * hw - b.x * ht, p.y - n.y * hw - b.y * ht, p.z - n.z * hw - b.z * ht,  // bottom-left
                p.x + n.x * hw - b.x * ht, p.y + n.y * hw - b.y * ht, p.z + n.z * hw - b.z * ht   // bottom-right
            );
            
            const u = i / (curvePoints.length - 1);
            uvs.push(u, 0, u, 0.33, u, 0.66, u, 1);
        }
        
        // Create faces connecting adjacent cross-sections
        for (let i = 0; i < curvePoints.length - 1; i++) {
            const base = i * 4;
            const next = (i + 1) * 4;
            
            // Top face
            indices.push(base + 0, next + 0, next + 1);
            indices.push(base + 0, next + 1, base + 1);
            
            // Left face
            indices.push(base + 1, next + 1, next + 2);
            indices.push(base + 1, next + 2, base + 2);
            
            // Bottom face
            indices.push(base + 2, next + 2, next + 3);
            indices.push(base + 2, next + 3, base + 3);
            
            // Right face
            indices.push(base + 3, next + 3, next + 0);
            indices.push(base + 3, next + 0, base + 0);
        }
        
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
        geometry.setIndex(indices);
        geometry.computeVertexNormals();
        
        return geometry;
    }

    /**
     * Create flat arrow geometry for β-sheets (PyMOL/Chimera style)
     * Wide flat ribbon with arrowhead pointing to C-terminus
     */
    createSheetArrowGeometry(curve, numPoints) {
        const THREE = window.THREE;
        
        // Sheet parameters
        const ribbonWidth = 1.8;       // Wide flat ribbon
        const ribbonThickness = 0.15;  // Very flat
        const arrowHeadLength = 0.25;  // 25% of ribbon is arrowhead
        const arrowHeadWidth = 2.5;    // Arrow wider than ribbon
        const segments = Math.max(numPoints * 8, 60);
        
        // Get points along the curve
        const curvePoints = curve.getPoints(segments);
        const tangents = [];
        const normals = [];
        const binormals = [];
        
        // Compute Frenet-Serret frame
        for (let i = 0; i < curvePoints.length; i++) {
            const t = i / (curvePoints.length - 1);
            tangents.push(curve.getTangent(t).normalize());
        }
        
        // Compute initial normal
        const up = new THREE.Vector3(0, 1, 0);
        let lastNormal = new THREE.Vector3().crossVectors(tangents[0], up).normalize();
        if (lastNormal.length() < 0.1) {
            lastNormal = new THREE.Vector3().crossVectors(tangents[0], new THREE.Vector3(1, 0, 0)).normalize();
        }
        
        // Propagate normal along curve
        for (let i = 0; i < curvePoints.length; i++) {
            const tangent = tangents[i];
            const normal = lastNormal.clone().sub(tangent.clone().multiplyScalar(lastNormal.dot(tangent))).normalize();
            normals.push(normal);
            binormals.push(new THREE.Vector3().crossVectors(tangent, normal).normalize());
            lastNormal = normal;
        }
        
        // Create ribbon vertices with arrowhead at C-terminus
        const vertices = [];
        const indices = [];
        
        const arrowStartIndex = Math.floor(curvePoints.length * (1 - arrowHeadLength));
        
        for (let i = 0; i < curvePoints.length; i++) {
            const p = curvePoints[i];
            const n = normals[i];
            const b = binormals[i];
            
            // Calculate width at this point (wider at arrowhead start, narrowing to point)
            let width;
            if (i < arrowStartIndex) {
                width = ribbonWidth;
            } else if (i === curvePoints.length - 1) {
                width = 0; // Arrow tip
            } else {
                // Linear interpolation from arrow start width to tip
                const arrowProgress = (i - arrowStartIndex) / (curvePoints.length - 1 - arrowStartIndex);
                // First expand to arrowhead width, then contract to point
                if (arrowProgress < 0.1) {
                    width = ribbonWidth + (arrowHeadWidth - ribbonWidth) * (arrowProgress / 0.1);
                } else {
                    width = arrowHeadWidth * (1 - (arrowProgress - 0.1) / 0.9);
                }
            }
            
            const hw = width * 0.5;
            const ht = ribbonThickness * 0.5;
            
            // 4 vertices per cross-section (rectangular)
            vertices.push(
                p.x + n.x * hw + b.x * ht, p.y + n.y * hw + b.y * ht, p.z + n.z * hw + b.z * ht,
                p.x - n.x * hw + b.x * ht, p.y - n.y * hw + b.y * ht, p.z - n.z * hw + b.z * ht,
                p.x - n.x * hw - b.x * ht, p.y - n.y * hw - b.y * ht, p.z - n.z * hw - b.z * ht,
                p.x + n.x * hw - b.x * ht, p.y + n.y * hw - b.y * ht, p.z + n.z * hw - b.z * ht
            );
        }
        
        // Create faces
        for (let i = 0; i < curvePoints.length - 1; i++) {
            const base = i * 4;
            const next = (i + 1) * 4;
            
            // Top face
            indices.push(base + 0, next + 0, next + 1);
            indices.push(base + 0, next + 1, base + 1);
            
            // Left face  
            indices.push(base + 1, next + 1, next + 2);
            indices.push(base + 1, next + 2, base + 2);
            
            // Bottom face
            indices.push(base + 2, next + 2, next + 3);
            indices.push(base + 2, next + 3, base + 3);
            
            // Right face
            indices.push(base + 3, next + 3, next + 0);
            indices.push(base + 3, next + 0, base + 0);
        }
        
        // Add end cap at arrow tip (triangle)
        const lastBase = (curvePoints.length - 1) * 4;
        // The tip vertices are at width=0, so they converge to a point
        
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
        geometry.setIndex(indices);
        geometry.computeVertexNormals();
        
        return geometry;
    }

    /**
     * Create flat ribbon geometry for simple flat representation (fallback)
     */
    createFlatRibbonGeometry(curve, numPoints) {
        const THREE = window.THREE;
        
        // Higher resolution for smoother appearance
        const curveSegments = Math.max(numPoints * 6, 48);
        const ribbonWidth = 1.2;   // Wide for sheets
        const ribbonThickness = 0.15; // Thin/flat
        
        // Create a custom ExtrudeGeometry along the curve path
        // Use TubeGeometry with rectangular-like cross-section simulation
        const geometry = new THREE.TubeGeometry(
            curve,
            curveSegments,
            ribbonWidth * 0.5,  // Radius = half width
            8,    // Radial segments
            false
        );
        
        // Transform to flat ribbon by scaling Y and adjusting normals
        const positions = geometry.attributes.position.array;
        const normals = geometry.attributes.normal.array;
        
        for (let i = 0; i < positions.length; i += 3) {
            // Flatten in local Y direction (tube's radial direction)
            positions[i + 1] *= ribbonThickness / ribbonWidth;
        }
        geometry.attributes.position.needsUpdate = true;
        geometry.computeVertexNormals(); // Recompute for proper lighting
        
        return geometry;
    }

    /**
     * Create a cylinder bond between two atoms
     */
    createCylinderBond(group, atom1, atom2, radius, color) {
        const THREE = window.THREE;
        
        const start = new THREE.Vector3(atom1.x, atom1.y, atom1.z);
        const end = new THREE.Vector3(atom2.x, atom2.y, atom2.z);
        
        const direction = new THREE.Vector3().subVectors(end, start);
        const length = direction.length();
        
        const geometry = new THREE.CylinderGeometry(radius, radius, length, 8, 1);
        const material = new THREE.MeshPhongMaterial({ color, shininess: 60 });
        
        const bond = new THREE.Mesh(geometry, material);
        
        // Position at midpoint
        bond.position.copy(start).add(end).multiplyScalar(0.5);
        
        // Align with bond direction
        bond.quaternion.setFromUnitVectors(
            new THREE.Vector3(0, 1, 0),
            direction.clone().normalize()
        );
        
        group.add(bond);
    }

    /**
     * Detect bonds between atoms based on distance
     */
    detectBonds(atoms, maxBondLength = 1.8) {
        const bonds = [];
        const n = atoms.length;
        
        // Use spatial hashing for large systems
        if (n > 1000) {
            return this.detectBondsSpatialHash(atoms, maxBondLength);
        }
        
        for (let i = 0; i < n; i++) {
            for (let j = i + 1; j < n; j++) {
                const a1 = atoms[i], a2 = atoms[j];
                const dx = a1.x - a2.x;
                const dy = a1.y - a2.y;
                const dz = a1.z - a2.z;
                const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
                
                if (dist <= maxBondLength && dist > 0.5) {
                    bonds.push([i, j]);
                }
            }
        }
        
        return bonds;
    }

    /**
     * Detect bonds using spatial hashing (for large systems)
     */
    detectBondsSpatialHash(atoms, maxBondLength) {
        const bonds = [];
        const cellSize = maxBondLength * 1.1;
        const cells = new Map();
        
        // Hash atoms into cells
        atoms.forEach((atom, i) => {
            const cx = Math.floor(atom.x / cellSize);
            const cy = Math.floor(atom.y / cellSize);
            const cz = Math.floor(atom.z / cellSize);
            const key = `${cx},${cy},${cz}`;
            
            if (!cells.has(key)) {
                cells.set(key, []);
            }
            cells.get(key).push(i);
        });
        
        // Check neighbors
        atoms.forEach((atom, i) => {
            const cx = Math.floor(atom.x / cellSize);
            const cy = Math.floor(atom.y / cellSize);
            const cz = Math.floor(atom.z / cellSize);
            
            for (let dx = -1; dx <= 1; dx++) {
                for (let dy = -1; dy <= 1; dy++) {
                    for (let dz = -1; dz <= 1; dz++) {
                        const key = `${cx + dx},${cy + dy},${cz + dz}`;
                        const cellAtoms = cells.get(key);
                        
                        if (cellAtoms) {
                            cellAtoms.forEach(j => {
                                if (j > i) {
                                    const a2 = atoms[j];
                                    const dist = Math.sqrt(
                                        Math.pow(atom.x - a2.x, 2) +
                                        Math.pow(atom.y - a2.y, 2) +
                                        Math.pow(atom.z - a2.z, 2)
                                    );
                                    
                                    if (dist <= maxBondLength && dist > 0.5) {
                                        bonds.push([i, j]);
                                    }
                                }
                            });
                        }
                    }
                }
            }
        });
        
        return bonds;
    }

    /**
     * Update molecule geometry for frame change
     */
    updateMoleculeGeometry(group, frame, representationType) {
        const atoms = frame.atoms;
        const THREE = window.THREE;
        
        // Check representation type from mesh userData or geometry type
        let ribbonMesh = null;
        let atomInstances = null;
        let bondInstances = null;
        let hasNonInstancedMeshes = false;
        let hasPointsObject = false;
        
        group.children.forEach(child => {
            // Check for ribbon/cartoon by userData type (more reliable than geometry type)
            if (child.isMesh && child.userData?.type === 'ribbon') {
                ribbonMesh = child;
            } else if (child.isMesh && child.userData?.type === 'cartoon') {
                ribbonMesh = child;
            } else if (child.isMesh && child.geometry?.type === 'TubeGeometry') {
                // Fallback for tube-based representations
                ribbonMesh = child;
            } else if (child.isInstancedMesh) {
                if (child.geometry.type === 'SphereGeometry') {
                    atomInstances = child;
                } else if (child.geometry.type === 'CylinderGeometry') {
                    bondInstances = child;
                }
            } else if (child.isPoints) {
                // Points representation
                hasPointsObject = true;
            } else if (child.isMesh || child.isLine) {
                // Detect non-instanced representations (spacefill, licorice, wireframe)
                hasNonInstancedMeshes = true;
            }
        });
        
        // For non-instanced representations (spacefill, licorice, wireframe, points),
        // we need to rebuild geometry since individual meshes can't be efficiently updated
        if ((hasNonInstancedMeshes || hasPointsObject) && !atomInstances && !ribbonMesh) {
            
            // Clear old geometry
            while (group.children.length > 0) {
                const child = group.children[0];
                if (child.geometry) child.geometry.dispose();
                if (child.material) child.material.dispose();
                group.remove(child);
            }
            
            // Rebuild with new frame (use passed representation or fall back to ball-stick)
            this.buildMoleculeGeometry(group, frame, representationType || 'ball-stick');
            return;
        }
        
        // Update ribbon/cartoon representation - check cache first!
        if (ribbonMesh || representationType === 'ribbon' || representationType === 'cartoon') {
            
            // Try to use pre-built geometry from cache
            const frameIndex = frame.index;
            const filename = this.geometryBuilder.currentFilename;
            
            if (filename && frameIndex !== undefined) {
                const cache = this.geometryCache.get(filename);
                const cachedGroup = cache?.get(frameIndex);
                
                if (cachedGroup) {
                    
                    // Clear old geometry
                    while (group.children.length > 0) {
                        const child = group.children[0];
                        group.remove(child);
                        // Don't dispose - it's shared with cache
                    }
                    
                    // Clone cached meshes into group
                    cachedGroup.children.forEach(child => {
                        group.add(child.clone());
                    });
                    
                    return;
                }
            }
            
            // No cache hit - rebuild from scratch
            console.log(`[MD Update] Cache miss, rebuilding geometry...`);
            
            // Clear old geometry
            while (group.children.length > 0) {
                const child = group.children[0];
                if (child.geometry) child.geometry.dispose();
                if (child.material) child.material.dispose();
                group.remove(child);
            }
            
            // Rebuild with new frame (use passed representation type)
            this.buildMoleculeGeometry(group, frame, representationType || 'ribbon');
            return;
        }
        
        // Update instanced atom/bond representation
        if (!atomInstances) {
            console.warn('[MD Update] No atom InstancedMesh found');
            return;
        }
        
        // Reusable objects to avoid GC pressure
        const matrix = new THREE.Matrix4();
        const position = new THREE.Vector3();
        const quaternion = new THREE.Quaternion();
        const scale = new THREE.Vector3();
        
        // Update atom positions with element-specific radii
        for (let i = 0; i < atoms.length; i++) {
            const atom = atoms[i];
            position.set(atom.x, atom.y, atom.z);
            const radius = this.atomRadii[atom.symbol] || this.atomRadii.default;
            const s = radius / 0.4; // Scale from base geometry size
            scale.set(s, s, s);
            matrix.compose(position, quaternion, scale);
            atomInstances.setMatrixAt(i, matrix);
        }
        atomInstances.instanceMatrix.needsUpdate = true;
        
        const t_atoms_updated = performance.now();
        
        // Update bond positions using STORED connectivity
        if (bondInstances && bondInstances.userData.bonds) {
            const bonds = bondInstances.userData.bonds;
            
            // Reuse vectors for bond calculations
            const start = new THREE.Vector3();
            const end = new THREE.Vector3();
            const midpoint = new THREE.Vector3();
            const direction = new THREE.Vector3();
            const bondAxis = new THREE.Vector3(0, 1, 0);
            
            for (let idx = 0; idx < bonds.length; idx++) {
                const [i, j] = bonds[idx];
                const a1 = atoms[i];
                const a2 = atoms[j];
                
                start.set(a1.x, a1.y, a1.z);
                end.set(a2.x, a2.y, a2.z);
                
                // Compute midpoint: (start + end) / 2
                midpoint.x = (a1.x + a2.x) * 0.5;
                midpoint.y = (a1.y + a2.y) * 0.5;
                midpoint.z = (a1.z + a2.z) * 0.5;
                
                // Compute direction and length
                direction.x = a2.x - a1.x;
                direction.y = a2.y - a1.y;
                direction.z = a2.z - a1.z;
                const length = Math.sqrt(direction.x * direction.x + direction.y * direction.y + direction.z * direction.z);
                
                // Normalize direction
                const invLen = 1.0 / length;
                direction.x *= invLen;
                direction.y *= invLen;
                direction.z *= invLen;
                
                // Set orientation
                quaternion.setFromUnitVectors(bondAxis, direction);
                
                // Set scale (length along Y axis for cylinder)
                scale.set(1, length, 1);
                
                // Compose and set matrix
                matrix.compose(midpoint, quaternion, scale);
                bondInstances.setMatrixAt(idx, matrix);
            }
            
            bondInstances.instanceMatrix.needsUpdate = true;
        }
        
    }

    /**
     * Pre-build geometry for all frames in the background (for ribbon/cartoon)
     * This significantly improves animation performance by caching pre-built meshes
     */
    async preBuildRibbonGeometry(trajectory, representation) {
        const filename = trajectory.filename;
        const frameCount = trajectory.frameCount;
        
        // Initialize cache for this file
        if (!this.geometryCache.has(filename)) {
            this.geometryCache.set(filename, new Map());
        }
        const cache = this.geometryCache.get(filename);
        
        // Update builder state
        this.geometryBuilder.isBuilding = true;
        this.geometryBuilder.cancelRequested = false;
        this.geometryBuilder.currentFilename = filename;
        this.geometryBuilder.currentRepresentation = representation;
        this.geometryBuilder.progress = 0;
        
        const t_start = performance.now();
        let builtCount = 0;
        
        try {
            // STEP 1: Batch-fetch ALL missing frames in one go (progressive loading only)
            if (trajectory.progressive) {
                // Determine which frames need to be fetched
                const frameCache = this.frameCache.get(filename);
                const needsFetch = [];
                for (let i = 0; i < frameCount; i++) {
                    if (!frameCache || !frameCache.has(i)) {
                        needsFetch.push(i);
                    }
                }
                
                if (needsFetch.length > 0) {
                    const t_fetch_start = performance.now();
                    
                    // Fetch all missing frames in one batch call
                    await this.fetchFrameRange(filename, 0, frameCount - 1, 1);
                    
                    const t_fetch_end = performance.now();
                }
            }
            
            // STEP 2: Build geometry for all frames (now all frame data is cached)
            for (let frameIndex = 0; frameIndex < frameCount; frameIndex++) {
                // Check if cancelled
                if (this.geometryBuilder.cancelRequested) {
                    break;
                }
                
                // Skip if geometry already cached
                if (cache.has(frameIndex)) {
                    continue;
                }
                
                // Get frame data (should be cached now from batch fetch)
                let frameData;
                if (trajectory.progressive) {
                    const frameCache = this.frameCache.get(filename);
                    frameData = frameCache?.get(frameIndex);
                    if (!frameData) {
                        // Frame not cached - this can happen if batch fetch didn't include all frames
                        // due to 3-second time limit. Skip silently and fetch on-demand later.
                        continue;
                    }
                } else {
                    frameData = trajectory.frames[frameIndex];
                }
                
                // Expand compact format if needed
                const metadata = this.trajectoryMetadata.get(filename);
                if (metadata?.compact) {
                    frameData = this.expandCompactFrame(
                        frameData,
                        metadata.symbols,
                        metadata.atomnames || [],
                        metadata.secondaryStructure || []
                    );
                }
                
                // Add frame index for cache lookups
                frameData.index = frameIndex;
                
                // Build geometry into a temporary group
                const THREE = window.THREE;
                const tempGroup = new THREE.Group();
                this.buildMoleculeGeometry(tempGroup, frameData, representation);
                
                // Store in cache
                cache.set(frameIndex, tempGroup);
                builtCount++;
                
                // Update progress
                this.geometryBuilder.progress = ((frameIndex + 1) / frameCount) * 100;
                
                // Log progress every 10%
                if ((frameIndex + 1) % Math.max(1, Math.floor(frameCount / 10)) === 0) {
                    console.log(`[MD Geometry Cache] 📊 Progress: ${Math.round(this.geometryBuilder.progress)}% (${frameIndex + 1}/${frameCount} frames)`);
                }
                
                // Yield to browser every 5 frames to keep UI responsive
                if (frameIndex % 5 === 0) {
                    await new Promise(resolve => setTimeout(resolve, 0));
                }
            }
            
            const t_end = performance.now();
            const avgTime = builtCount > 0 ? (t_end - t_start) / builtCount : 0;
            console.log(`[MD Geometry Cache] ✅ Pre-build complete: ${builtCount} frames in ${((t_end - t_start) / 1000).toFixed(1)}s (avg ${avgTime.toFixed(1)}ms/frame)`);
            
        } catch (error) {
            console.error('[MD Geometry Cache] ❌ Pre-build error:', error);
        } finally {
            this.geometryBuilder.isBuilding = false;
        }
    }

    /**
     * Detect best representation based on molecule type
     */
    detectBestRepresentation(trajectory) {
        // Get first frame metadata
        const frame = trajectory.frames[0];
        
        if (!frame || !frame.metadata) {
            return 'ball-stick'; // Safe default
        }

        const metadata = frame.metadata;
        
        // Standard amino acid 3-letter codes
        const proteinResidues = [
            'ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 'HIS', 'ILE',
            'LEU', 'LYS', 'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL',
            'HIE', 'HID', 'HIP', 'CYX', 'HSD', 'HSE', 'HSP'  // Common variants
        ];
        
        // Check if system contains protein residues
        const hasProtein = metadata.residueNames && 
                          metadata.residueNames.some(res => proteinResidues.includes(res));
        
        // Check if it's mostly water/ions/lipids (common residues)
        const nonProteinResidues = ['TIP3', 'TIP4', 'TIP5', 'SOL', 'WAT', 'HOH', 'SOD', 'CLA', 'NA', 'CL', 'K', 'MG', 'CA',
                                     'POPC', 'POPE', 'POPS', 'DOPC', 'DPPC', 'DLPC', 'DMPC', 'TOCL2', 'CARD', 'CHOL'];
        const hasLipidOrWater = metadata.residueNames && 
                               metadata.residueNames.some(res => nonProteinResidues.includes(res));
        
        // Protein systems: use ribbon for better visualization
        if (hasProtein) {
            console.log('[MD Trajectory] Auto-selected RIBBON representation (protein detected)');
            return 'ribbon';
        }
        
        // Lipid/surfactant/water/ion systems: use ball-stick for better performance
        console.log('[MD Trajectory] Auto-selected BALL-STICK representation (non-protein system)');
        return 'ball-stick';
    }

    /**
     * Start background geometry pre-building for smooth animation
     */
    startGeometryPreBuild(trajectory, representation) {
        // Only pre-build for ribbon/cartoon (other representations update fast enough)
        if (representation !== 'ribbon' && representation !== 'cartoon') {
            return;
        }
        
        // Cancel any existing build
        if (this.geometryBuilder.isBuilding) {
            this.geometryBuilder.cancelRequested = true;
        }
        
        // Start building in background (don't await)
        this.preBuildRibbonGeometry(trajectory, representation);
    }

    /**
     * Clear molecule group
     */
    clearMoleculeGroup(group) {
        while (group.children.length > 0) {
            const child = group.children[0];
            if (child.geometry) child.geometry.dispose();
            if (child.material) child.material.dispose();
            group.remove(child);
        }
    }

    /**
     * Toggle water/solvent visibility
     */
    async toggleWater(showWater) {
        console.log(`[MD Trajectory] Toggling water/solvents: ${showWater ? 'show' : 'hide'}`);
        
        this.viewers.forEach(async (viewer) => {
            const trajectory = viewer.trajectory;
            if (!trajectory || !trajectory.unfilteredFrames) {
                console.warn('[MD Trajectory] No unfiltered data available for water toggle');
                return;
            }
            
            if (!trajectory.waterFiltered) {
                console.log('[MD Trajectory] No filtering was applied (no water/solvents detected), toggle has no effect');
                return;
            }
            
            // Switch between filtered and unfiltered frames
            // frames[0] = filtered (solute only)
            // unfilteredFrames[0] = unfiltered (all atoms)
            const newFrame = showWater ? trajectory.unfilteredFrames[0] : trajectory.frames[0];
            
            console.log(`[MD Trajectory] Switching to ${showWater ? 'unfiltered' : 'filtered'} frame: ${newFrame.atoms.length} atoms`);
            
            // Update trajectory state
            trajectory.showWater = showWater;
            
            // Rebuild geometry with new frame
            if (viewer.renderer && viewer.renderer.moleculeGroup) {
                const group = viewer.renderer.moleculeGroup;
                
                // Clear existing geometry
                this.clearMoleculeGroup(group);
                
                // Build new geometry with appropriate representation
                const representation = viewer.representation || 'ball-stick';
                this.buildMoleculeGeometry(group, newFrame, representation);
                
                console.log(`[MD Trajectory] Water toggled - atoms: ${newFrame.atoms.length}, representation: ${representation}`);
            }
        });
    }

    /**
     * Change representation mode
     */
    changeRepresentation(rep) {
        this.viewers.forEach(viewer => {
            if (viewer.renderer && viewer.renderer.changeRepresentation) {
                viewer.renderer.changeRepresentation(rep);
            }
        });
    }

    /**
     * Center view - reset camera to initial position and target
     */
    centerView() {
        console.log('[MD Trajectory] Centering view');
        
        this.viewers.forEach(viewer => {
            if (viewer.renderer && viewer.renderer.controls && viewer.renderer.camera) {
                const controls = viewer.renderer.controls;
                const camera = viewer.renderer.camera;
                
                // Restore initial camera position and target if stored
                if (this.initialCameraPosition && this.initialCameraTarget) {
                    camera.position.copy(this.initialCameraPosition);
                    controls.target.copy(this.initialCameraTarget);
                } else {
                    // Fallback to origin if initial state wasn't saved
                    controls.target.set(0, 0, 0);
                }
                
                camera.lookAt(controls.target);
                
                // Update controls
                controls.update();
                
                console.log('[MD Trajectory] View centered');
            }
        });
    }

    /**
     * Toggle measurement mode - enable/disable distance measurement between atoms
     */
    toggleMeasurementMode() {
        console.log('[MD Trajectory] Toggling measurement mode');
        
        this.viewers.forEach(viewer => {
            // Store measurement state
            if (!viewer.measurementMode) {
                viewer.measurementMode = {
                    enabled: false,
                    selectedAtoms: [],
                    measurementLines: []
                };
            }
            
            const measureMode = viewer.measurementMode;
            measureMode.enabled = !measureMode.enabled;
            
            if (measureMode.enabled) {
                console.log('[MD Trajectory] Measurement mode ENABLED - click atoms to measure distance');
                // TODO: Add visual indicator that measurement mode is active
                // TODO: Add click handler to select atoms
                // TODO: Draw line between selected atoms and show distance
                alert('Measurement mode enabled! Click two atoms to measure distance.\n(Full implementation coming soon)');
            } else {
                console.log('[MD Trajectory] Measurement mode DISABLED');
                // Clear any existing measurements
                measureMode.selectedAtoms = [];
                // TODO: Remove measurement lines from scene
            }
        });
    }

    /**
     * Take screenshot of the current view and copy to clipboard
     */
    async takeScreenshot() {
        console.log('[MD Trajectory] Taking screenshot - viewers count:', this.viewers.size);
        
        this.viewers.forEach(async (viewer) => {
            console.log('[MD Trajectory] Checking viewer:', viewer);
            
            if (!viewer.renderer || !viewer.renderer.renderer) {
                console.log('[MD Trajectory] Skipping viewer - no renderer');
                return;
            }
            
            const threeRenderer = viewer.renderer.renderer;
            const camera = viewer.renderer.camera;
            const scene = viewer.renderer.scene;
            
            console.log('[MD Trajectory] Renderer found, rendering frame...');
            
            // Render one frame to ensure we capture the current state
            threeRenderer.render(scene, camera);
            
            try {
                console.log('[MD Trajectory] Converting canvas to blob...');
                
                // Convert canvas to blob
                const blob = await new Promise((resolve, reject) => {
                    threeRenderer.domElement.toBlob((b) => {
                        console.log('[MD Trajectory] toBlob callback, blob:', b);
                        if (b) resolve(b);
                        else reject(new Error('Failed to create blob from canvas'));
                    }, 'image/png');
                });
                
                console.log('[MD Trajectory] Blob created, size:', blob.size);
                
                // Try to copy to clipboard first
                if (navigator.clipboard && navigator.clipboard.write) {
                    console.log('[MD Trajectory] Attempting clipboard write...');
                    try {
                        await navigator.clipboard.write([
                            new ClipboardItem({ 'image/png': blob })
                        ]);
                        console.log('[MD Trajectory] Screenshot copied to clipboard successfully');
                        
                        // Show temporary success message
                        const msg = document.createElement('div');
                        msg.textContent = 'Screenshot copied to clipboard!';
                        msg.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #4CAF50; color: white; padding: 12px 20px; border-radius: 4px; z-index: 10000; font-family: system-ui; box-shadow: 0 2px 8px rgba(0,0,0,0.3);';
                        document.body.appendChild(msg);
                        setTimeout(() => document.body.removeChild(msg), 3000);
                        
                        return; // Success - exit early
                    } catch (clipboardError) {
                        console.warn('[MD Trajectory] Clipboard copy failed, falling back to download:', clipboardError);
                    }
                } else {
                    console.log('[MD Trajectory] Clipboard API not available, using download fallback');
                }
                
                // Fallback: download the image
                console.log('[MD Trajectory] Creating download link...');
                const dataURL = threeRenderer.domElement.toDataURL('image/png');
                const link = document.createElement('a');
                const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
                link.download = `md-trajectory-${timestamp}.png`;
                link.href = dataURL;
                link.style.display = 'none';
                
                document.body.appendChild(link);
                console.log('[MD Trajectory] Triggering download click...');
                link.click();
                
                // Clean up after a delay to ensure download completes
                setTimeout(() => {
                    if (document.body.contains(link)) {
                        document.body.removeChild(link);
                    }
                }, 100);
                
                console.log('[MD Trajectory] Screenshot download triggered');
                
            } catch (error) {
                console.error('[MD Trajectory] Error taking screenshot:', error);
                alert('Failed to take screenshot: ' + error.message);
            }
        });
        
        console.log('[MD Trajectory] Screenshot function completed');
    }

    /**
     * Setup resize observer
     */
    setupResizeObserver(container, renderer) {
        if (!window.ResizeObserver) return;

        const observer = new ResizeObserver(entries => {
            for (const entry of entries) {
                const { width, height } = entry.contentRect;
                if (width > 0 && height > 0 && renderer && renderer.resize) {
                    renderer.resize(width, height);
                }
            }
        });

        observer.observe(container);

        // Store for cleanup
        if (this.viewers.has(container)) {
            const viewer = this.viewers.get(container);
            viewer.resizeObserver = observer;
        }
    }

    /**
     * Dispose viewer and cleanup resources
     */
    disposeViewer(container) {
        const viewer = this.viewers.get(container);
        if (!viewer) return;

        console.log('MD Trajectory: Disposing viewer');

        // Stop animation
        if (viewer.renderer && viewer.renderer.stopAnimation) {
            viewer.renderer.stopAnimation();
        }

        // Dispose resize observer
        if (viewer.resizeObserver) {
            viewer.resizeObserver.disconnect();
        }

        // Dispose Three.js resources
        if (viewer.renderer) {
            const r = viewer.renderer;
            
            // Clear molecule group
            if (r.moleculeGroup) {
                this.clearMoleculeGroup(r.moleculeGroup);
            }

            // Dispose controls
            if (r.controls && r.controls.dispose) {
                r.controls.dispose();
            }

            // Clear scene and dispose all objects
            if (r.scene) {
                r.scene.clear();
            }

            // Dispose renderer
            if (r.renderer) {
                r.renderer.dispose();
                // Force WebGL context loss to free GPU memory
                const gl = r.renderer.getContext();
                if (gl && gl.getExtension('WEBGL_lose_context')) {
                    gl.getExtension('WEBGL_lose_context').loseContext();
                }
            }
        }

        // Cleanup playback
        const playbackControls = viewer.container?.querySelector('.md-playback-controls');
        if (playbackControls && playbackControls._cleanup) {
            playbackControls._cleanup();
        }

        this.viewers.delete(container);
    }

    /**
     * Handle resize events
     */
    onResize(width, height) {
        this.viewers.forEach(viewer => {
            if (viewer.renderer && viewer.renderer.resize) {
                viewer.renderer.resize(width, height);
            }
        });
    }

    /**
     * Cleanup all resources
     */
    async cleanup() {
        console.log(`MD Trajectory Extension: Cleaning up ${this.viewers.size} viewers`);

        this.viewers.forEach((viewer, container) => {
            this.disposeViewer(container);
        });

        this.viewers.clear();
        await super.cleanup();
    }
}

// Auto-register when script loads
if (typeof extensionRegistry !== 'undefined') {
    extensionRegistry.register(new MDTrajectoryExtension());
    console.log('MD Trajectory Viewer Extension registered');
}
