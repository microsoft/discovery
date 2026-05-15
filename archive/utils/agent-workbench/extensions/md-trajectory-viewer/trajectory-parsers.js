/**
 * Trajectory Parsers Module
 * Comprehensive parsing library for molecular dynamics trajectory formats
 * 
 * Supports:
 * - XYZ (single and multi-frame)
 * - LAMMPS dump (.lammpstrj)
 * - GSD (HOOMD-blue, text-based)
 * - H5MD (simplified text export)
 * - XTC/TRR (GROMACS, with guidance for conversion)
 * - Multi-model PDB
 * 
 * All parsing is performed offline in the browser
 */

class TrajectoryParser {
    constructor() {
        // Element data for mass calculations and validation
        this.elementData = {
            'H':  { mass: 1.008,   name: 'Hydrogen' },
            'He': { mass: 4.003,   name: 'Helium' },
            'Li': { mass: 6.941,   name: 'Lithium' },
            'Be': { mass: 9.012,   name: 'Beryllium' },
            'B':  { mass: 10.811,  name: 'Boron' },
            'C':  { mass: 12.011,  name: 'Carbon' },
            'N':  { mass: 14.007,  name: 'Nitrogen' },
            'O':  { mass: 15.999,  name: 'Oxygen' },
            'F':  { mass: 18.998,  name: 'Fluorine' },
            'Ne': { mass: 20.180,  name: 'Neon' },
            'Na': { mass: 22.990,  name: 'Sodium' },
            'Mg': { mass: 24.305,  name: 'Magnesium' },
            'Al': { mass: 26.982,  name: 'Aluminum' },
            'Si': { mass: 28.086,  name: 'Silicon' },
            'P':  { mass: 30.974,  name: 'Phosphorus' },
            'S':  { mass: 32.065,  name: 'Sulfur' },
            'Cl': { mass: 35.453,  name: 'Chlorine' },
            'Ar': { mass: 39.948,  name: 'Argon' },
            'K':  { mass: 39.098,  name: 'Potassium' },
            'Ca': { mass: 40.078,  name: 'Calcium' },
            'Fe': { mass: 55.845,  name: 'Iron' },
            'Cu': { mass: 63.546,  name: 'Copper' },
            'Zn': { mass: 65.380,  name: 'Zinc' },
            'Br': { mass: 79.904,  name: 'Bromine' },
            'I':  { mass: 126.904, name: 'Iodine' }
        };

        // Common LAMMPS atom type to element mappings
        this.lammpsTypeMap = {
            1: 'H', 2: 'C', 3: 'N', 4: 'O', 5: 'S', 
            6: 'P', 7: 'Fe', 8: 'Cu', 9: 'Zn', 10: 'Na',
            11: 'Cl', 12: 'Ca', 13: 'Mg', 14: 'K', 15: 'Si'
        };
    }

    /**
     * Detect file format from filename and content
     */
    detectFormat(filename, content) {
        const ext = filename.split('.').pop().toLowerCase();
        
        // Try extension first
        const formatMap = {
            'xyz': 'xyz',
            'lammpstrj': 'lammps',
            'dump': 'lammps',
            'gsd': 'gsd',
            'h5md': 'h5md',
            'xtc': 'xtc',
            'trr': 'trr',
            'pdb': 'pdb'
        };

        if (formatMap[ext]) {
            return formatMap[ext];
        }

        // Try to detect from content
        const firstLines = content.slice(0, 2000).toLowerCase();

        if (firstLines.includes('item: timestep') || firstLines.includes('item: atoms')) {
            return 'lammps';
        }

        if (firstLines.startsWith('atom') || /^\d+\s*\n/.test(content.trim())) {
            // Check if second line is a number or text (XYZ format)
            const lines = content.trim().split('\n');
            if (!isNaN(parseInt(lines[0]))) {
                return 'xyz';
            }
        }

        if (firstLines.includes('model') && firstLines.includes('endmdl')) {
            return 'pdb';
        }

        if (firstLines.includes('header') && firstLines.includes('frame')) {
            return 'gsd';
        }

        return 'unknown';
    }

    /**
     * Parse trajectory based on detected or specified format
     */
    async parse(filename, content, options = {}) {
        const format = options.format || this.detectFormat(filename, content);
        
        console.log(`Parsing ${filename} as ${format} format`);

        switch (format) {
            case 'xyz':
                return this.parseXYZ(content, filename, options);
            case 'lammps':
                return this.parseLAMMPS(content, filename, options);
            case 'gsd':
                return this.parseGSD(content, filename, options);
            case 'h5md':
                return this.parseH5MD(content, filename, options);
            case 'pdb':
                return this.parsePDB(content, filename, options);
            case 'xtc':
            case 'trr':
                return this.parseGromacsBinary(content, filename, format, options);
            default:
                throw new Error(`Unknown trajectory format: ${format}`);
        }
    }

    /**
     * Parse XYZ format (single or multi-frame)
     * 
     * Format:
     * <atom count>
     * <comment/title line>
     * <element> <x> <y> <z> [<vx> <vy> <vz>] [<fx> <fy> <fz>]
     * ...
     */
    parseXYZ(content, filename, options = {}) {
        const lines = content.trim().split('\n');
        const frames = [];
        let i = 0;

        while (i < lines.length) {
            const atomCountLine = lines[i].trim();
            
            // Skip empty lines
            if (!atomCountLine) {
                i++;
                continue;
            }

            const atomCount = parseInt(atomCountLine);
            
            if (isNaN(atomCount) || atomCount <= 0) {
                // Not a valid frame start, skip line
                i++;
                continue;
            }

            // Ensure we have enough lines for this frame
            if (i + atomCount + 1 >= lines.length && lines.length > 2) {
                // Might be truncated, try to parse what we have
                console.warn(`Frame ${frames.length + 1} appears truncated`);
            }

            const comment = lines[i + 1] || '';
            const atoms = [];

            for (let j = 0; j < atomCount && i + 2 + j < lines.length; j++) {
                const line = lines[i + 2 + j].trim();
                if (!line) continue;

                const parts = line.split(/\s+/);
                if (parts.length >= 4) {
                    const atom = {
                        symbol: this.normalizeElement(parts[0]),
                        x: parseFloat(parts[1]),
                        y: parseFloat(parts[2]),
                        z: parseFloat(parts[3])
                    };

                    // Optional velocity
                    if (parts.length >= 7) {
                        atom.vx = parseFloat(parts[4]);
                        atom.vy = parseFloat(parts[5]);
                        atom.vz = parseFloat(parts[6]);
                    }

                    // Optional force
                    if (parts.length >= 10) {
                        atom.fx = parseFloat(parts[7]);
                        atom.fy = parseFloat(parts[8]);
                        atom.fz = parseFloat(parts[9]);
                    }

                    // Validate coordinates
                    if (!isNaN(atom.x) && !isNaN(atom.y) && !isNaN(atom.z)) {
                        atoms.push(atom);
                    }
                }
            }

            if (atoms.length > 0) {
                // Try to parse timestep from comment
                const timestepMatch = comment.match(/t\s*=\s*([\d.eE+-]+)/i) ||
                                     comment.match(/time\s*=\s*([\d.eE+-]+)/i) ||
                                     comment.match(/step\s*=\s*(\d+)/i);
                
                frames.push({
                    atoms,
                    comment,
                    time: timestepMatch ? parseFloat(timestepMatch[1]) : frames.length,
                    atomCount: atoms.length
                });
            }

            i += atomCount + 2;
        }

        if (frames.length === 0) {
            throw new Error('No valid frames found in XYZ file');
        }

        return this.createTrajectoryObject('xyz', filename, frames);
    }

    /**
     * Parse LAMMPS dump format
     * 
     * Format:
     * ITEM: TIMESTEP
     * <timestep>
     * ITEM: NUMBER OF ATOMS
     * <N>
     * ITEM: BOX BOUNDS ...
     * <xlo> <xhi>
     * <ylo> <yhi>
     * <zlo> <zhi>
     * ITEM: ATOMS <columns...>
     * <atom data...>
     */
    parseLAMMPS(content, filename, options = {}) {
        const lines = content.trim().split('\n');
        const frames = [];
        let i = 0;

        while (i < lines.length) {
            // Find ITEM: TIMESTEP
            while (i < lines.length && !lines[i].toUpperCase().startsWith('ITEM: TIMESTEP')) {
                i++;
            }
            if (i >= lines.length) break;
            i++; // Move past ITEM: TIMESTEP

            const timestep = parseInt(lines[i++]);

            // ITEM: NUMBER OF ATOMS
            while (i < lines.length && !lines[i].toUpperCase().startsWith('ITEM: NUMBER OF ATOMS')) {
                i++;
            }
            if (i >= lines.length) break;
            i++; // Move past ITEM: NUMBER OF ATOMS

            const atomCount = parseInt(lines[i++]);

            // ITEM: BOX BOUNDS
            while (i < lines.length && !lines[i].toUpperCase().startsWith('ITEM: BOX BOUNDS')) {
                i++;
            }
            if (i >= lines.length) break;
            
            const boundsLine = lines[i++].toUpperCase();
            const isPeriodic = boundsLine.includes('PP');
            const isTriclinic = boundsLine.includes('XY');

            let box;
            if (isTriclinic) {
                const xBounds = lines[i++].split(/\s+/).map(parseFloat);
                const yBounds = lines[i++].split(/\s+/).map(parseFloat);
                const zBounds = lines[i++].split(/\s+/).map(parseFloat);
                
                box = {
                    min: { x: xBounds[0], y: yBounds[0], z: zBounds[0] },
                    max: { x: xBounds[1], y: yBounds[1], z: zBounds[1] },
                    tilt: {
                        xy: xBounds[2] || 0,
                        xz: yBounds[2] || 0,
                        yz: zBounds[2] || 0
                    }
                };
            } else {
                const xBounds = lines[i++].split(/\s+/).map(parseFloat);
                const yBounds = lines[i++].split(/\s+/).map(parseFloat);
                const zBounds = lines[i++].split(/\s+/).map(parseFloat);
                
                box = {
                    min: { x: xBounds[0], y: yBounds[0], z: zBounds[0] },
                    max: { x: xBounds[1], y: yBounds[1], z: zBounds[1] }
                };
            }

            // ITEM: ATOMS
            while (i < lines.length && !lines[i].toUpperCase().startsWith('ITEM: ATOMS')) {
                i++;
            }
            if (i >= lines.length) break;

            const atomsHeader = lines[i++];
            const columns = atomsHeader.replace(/ITEM:\s*ATOMS\s*/i, '').trim().split(/\s+/);

            // Build column index map
            const colMap = {};
            columns.forEach((col, idx) => {
                colMap[col.toLowerCase()] = idx;
            });

            // Parse atoms
            const atoms = [];
            for (let j = 0; j < atomCount && i < lines.length; j++, i++) {
                const line = lines[i].trim();
                if (!line || line.toUpperCase().startsWith('ITEM:')) {
                    i--; // Don't consume the ITEM line
                    break;
                }

                const parts = line.split(/\s+/);
                if (parts.length < columns.length) continue;

                const atom = this.parseLAMMPSAtom(parts, colMap, box);
                if (atom) {
                    atoms.push(atom);
                }
            }

            if (atoms.length > 0) {
                // Sort atoms by ID if available
                if (atoms[0].id !== undefined) {
                    atoms.sort((a, b) => a.id - b.id);
                }

                frames.push({
                    atoms,
                    timestep,
                    time: timestep,
                    box,
                    atomCount: atoms.length,
                    isPeriodic
                });
            }
        }

        if (frames.length === 0) {
            throw new Error('No valid frames found in LAMMPS dump file');
        }

        return this.createTrajectoryObject('lammps', filename, frames);
    }

    /**
     * Parse a single LAMMPS atom line
     */
    parseLAMMPSAtom(parts, colMap, box) {
        const getValue = (key, defaultVal) => {
            const idx = colMap[key];
            return idx !== undefined ? parts[idx] : defaultVal;
        };

        const id = parseInt(getValue('id', parts[0]));
        const type = parseInt(getValue('type', '1'));

        // Get coordinates - handle scaled and unscaled
        let x, y, z;
        
        if (colMap['xu'] !== undefined) {
            // Unwrapped coordinates
            x = parseFloat(getValue('xu'));
            y = parseFloat(getValue('yu'));
            z = parseFloat(getValue('zu'));
        } else if (colMap['xs'] !== undefined) {
            // Scaled coordinates - convert to real
            const xs = parseFloat(getValue('xs'));
            const ys = parseFloat(getValue('ys'));
            const zs = parseFloat(getValue('zs'));
            
            const lx = box.max.x - box.min.x;
            const ly = box.max.y - box.min.y;
            const lz = box.max.z - box.min.z;
            
            x = box.min.x + xs * lx;
            y = box.min.y + ys * ly;
            z = box.min.z + zs * lz;
        } else {
            // Regular coordinates
            x = parseFloat(getValue('x', parts[2]));
            y = parseFloat(getValue('y', parts[3]));
            z = parseFloat(getValue('z', parts[4]));
        }

        if (isNaN(x) || isNaN(y) || isNaN(z)) {
            return null;
        }

        // Get element
        let symbol = getValue('element', null);
        if (!symbol) {
            symbol = this.lammpsTypeMap[type] || this.typeToElement(type);
        }
        symbol = this.normalizeElement(symbol);

        const atom = {
            id,
            type,
            symbol,
            x, y, z
        };

        // Optional properties
        if (colMap['vx'] !== undefined) {
            atom.vx = parseFloat(getValue('vx'));
            atom.vy = parseFloat(getValue('vy'));
            atom.vz = parseFloat(getValue('vz'));
        }

        if (colMap['fx'] !== undefined) {
            atom.fx = parseFloat(getValue('fx'));
            atom.fy = parseFloat(getValue('fy'));
            atom.fz = parseFloat(getValue('fz'));
        }

        if (colMap['q'] !== undefined) {
            atom.charge = parseFloat(getValue('q'));
        }

        if (colMap['mol'] !== undefined) {
            atom.molecule = parseInt(getValue('mol'));
        }

        return atom;
    }

    /**
     * Parse GSD format (HOOMD-blue)
     * This handles text-based exports of GSD files
     */
    parseGSD(content, filename, options = {}) {
        // Try to parse as JSON first (common export format)
        try {
            const data = JSON.parse(content);
            
            if (data.frames && Array.isArray(data.frames)) {
                const frames = data.frames.map((f, idx) => {
                    const particles = f.particles || f;
                    const N = particles.N || (particles.position ? particles.position.length / 3 : 0);
                    
                    const atoms = [];
                    for (let i = 0; i < N; i++) {
                        const typeId = particles.typeid?.[i] || 0;
                        atoms.push({
                            id: i + 1,
                            symbol: particles.types?.[typeId] || this.typeToElement(typeId + 1),
                            x: particles.position[i * 3],
                            y: particles.position[i * 3 + 1],
                            z: particles.position[i * 3 + 2],
                            type: typeId
                        });
                    }

                    const config = f.configuration || {};
                    let box = null;
                    if (config.box) {
                        const b = config.box;
                        box = {
                            min: { x: -b[0]/2, y: -b[1]/2, z: -b[2]/2 },
                            max: { x: b[0]/2, y: b[1]/2, z: b[2]/2 }
                        };
                    }

                    return {
                        atoms,
                        time: f.timestep || idx,
                        box,
                        atomCount: atoms.length
                    };
                });

                return this.createTrajectoryObject('gsd', filename, frames);
            }
        } catch (e) {
            // Not JSON format
        }

        // Try text-based format
        const lines = content.trim().split('\n');
        const frames = [];
        let currentFrame = null;
        let atomIndex = 0;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();
            
            if (line.startsWith('FRAME') || line.startsWith('frame')) {
                if (currentFrame && currentFrame.atoms.length > 0) {
                    frames.push(currentFrame);
                }
                currentFrame = {
                    atoms: [],
                    time: frames.length,
                    box: null,
                    atomCount: 0
                };
                atomIndex = 0;
            } else if (line.startsWith('BOX') || line.startsWith('box')) {
                const parts = line.split(/\s+/).slice(1).map(parseFloat);
                if (parts.length >= 3 && currentFrame) {
                    currentFrame.box = {
                        min: { x: -parts[0]/2, y: -parts[1]/2, z: -parts[2]/2 },
                        max: { x: parts[0]/2, y: parts[1]/2, z: parts[2]/2 }
                    };
                }
            } else if (currentFrame && line && !line.startsWith('#')) {
                const parts = line.split(/\s+/);
                if (parts.length >= 3) {
                    currentFrame.atoms.push({
                        id: ++atomIndex,
                        symbol: parts.length >= 4 ? this.normalizeElement(parts[0]) : 'C',
                        x: parseFloat(parts.length >= 4 ? parts[1] : parts[0]),
                        y: parseFloat(parts.length >= 4 ? parts[2] : parts[1]),
                        z: parseFloat(parts.length >= 4 ? parts[3] : parts[2])
                    });
                }
            }
        }

        if (currentFrame && currentFrame.atoms.length > 0) {
            frames.push(currentFrame);
        }

        if (frames.length === 0) {
            throw new Error('No valid frames found in GSD file. For binary GSD files, please convert using: gsd.hoomd.open("file.gsd")');
        }

        return this.createTrajectoryObject('gsd', filename, frames);
    }

    /**
     * Parse H5MD format (HDF5 for molecular data)
     * This handles text exports of H5MD files
     */
    parseH5MD(content, filename, options = {}) {
        // H5MD is typically HDF5 binary, but we can handle text exports
        
        // Try JSON format first
        try {
            const data = JSON.parse(content);
            
            if (data.particles) {
                const particles = data.particles.all || data.particles;
                const position = particles.position?.value || particles.position;
                const species = particles.species?.value || particles.species;
                
                if (position) {
                    const frames = [];
                    const nFrames = position.length;
                    
                    for (let f = 0; f < nFrames; f++) {
                        const framePos = position[f];
                        const atoms = [];
                        const N = framePos.length / 3;
                        
                        for (let i = 0; i < N; i++) {
                            atoms.push({
                                id: i + 1,
                                symbol: species ? this.typeToElement(species[i] + 1) : 'C',
                                x: framePos[i * 3],
                                y: framePos[i * 3 + 1],
                                z: framePos[i * 3 + 2]
                            });
                        }
                        
                        frames.push({
                            atoms,
                            time: f,
                            atomCount: atoms.length
                        });
                    }
                    
                    return this.createTrajectoryObject('h5md', filename, frames);
                }
            }
        } catch (e) {
            // Not JSON
        }

        throw new Error('H5MD format requires HDF5 support. Please convert to XYZ using: h5dump or MDAnalysis');
    }

    /**
     * Parse multi-model PDB format
     */
    parsePDB(content, filename, options = {}) {
        const lines = content.split('\n');
        const frames = [];
        let currentFrame = { atoms: [], time: 0, box: null, atomCount: 0 };
        let modelNumber = 0;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const record = line.substring(0, 6).trim().toUpperCase();

            switch (record) {
                case 'MODEL':
                    if (currentFrame.atoms.length > 0) {
                        frames.push(currentFrame);
                    }
                    modelNumber = parseInt(line.substring(10, 14).trim()) || frames.length + 1;
                    currentFrame = {
                        atoms: [],
                        time: modelNumber,
                        box: null,
                        atomCount: 0
                    };
                    break;

                case 'ATOM':
                case 'HETATM':
                    const atom = this.parsePDBAtom(line);
                    if (atom) {
                        currentFrame.atoms.push(atom);
                    }
                    break;

                case 'CRYST1':
                    currentFrame.box = this.parsePDBCryst(line);
                    break;

                case 'ENDMDL':
                    if (currentFrame.atoms.length > 0) {
                        currentFrame.atomCount = currentFrame.atoms.length;
                        frames.push(currentFrame);
                        currentFrame = {
                            atoms: [],
                            time: frames.length,
                            box: null,
                            atomCount: 0
                        };
                    }
                    break;
            }
        }

        // Add last frame if not ended with ENDMDL
        if (currentFrame.atoms.length > 0) {
            currentFrame.atomCount = currentFrame.atoms.length;
            frames.push(currentFrame);
        }

        if (frames.length === 0) {
            throw new Error('No valid models found in PDB file');
        }

        return this.createTrajectoryObject('pdb', filename, frames);
    }

    /**
     * Parse a single PDB ATOM/HETATM line
     */
    parsePDBAtom(line) {
        try {
            const serial = parseInt(line.substring(6, 11).trim());
            const name = line.substring(12, 16).trim();
            const resName = line.substring(17, 20).trim();
            const chainId = line.substring(21, 22).trim();
            const resSeq = parseInt(line.substring(22, 26).trim());
            const x = parseFloat(line.substring(30, 38).trim());
            const y = parseFloat(line.substring(38, 46).trim());
            const z = parseFloat(line.substring(46, 54).trim());
            
            // Element symbol is at positions 77-78, or infer from atom name
            let element = line.substring(76, 78).trim();
            if (!element) {
                element = name.replace(/[0-9]/g, '').charAt(0);
            }
            element = this.normalizeElement(element);

            const occupancy = parseFloat(line.substring(54, 60).trim()) || 1.0;
            const tempFactor = parseFloat(line.substring(60, 66).trim()) || 0.0;

            if (isNaN(x) || isNaN(y) || isNaN(z)) {
                return null;
            }

            return {
                id: serial,
                symbol: element,
                name,
                x, y, z,
                residue: resName,
                residueId: resSeq,
                chain: chainId,
                occupancy,
                tempFactor
            };
        } catch (e) {
            return null;
        }
    }

    /**
     * Parse PDB CRYST1 record for box dimensions
     */
    parsePDBCryst(line) {
        try {
            const a = parseFloat(line.substring(6, 15).trim());
            const b = parseFloat(line.substring(15, 24).trim());
            const c = parseFloat(line.substring(24, 33).trim());
            const alpha = parseFloat(line.substring(33, 40).trim()) || 90;
            const beta = parseFloat(line.substring(40, 47).trim()) || 90;
            const gamma = parseFloat(line.substring(47, 54).trim()) || 90;

            // For orthogonal boxes
            return {
                min: { x: 0, y: 0, z: 0 },
                max: { x: a, y: b, z: c },
                angles: { alpha, beta, gamma }
            };
        } catch (e) {
            return null;
        }
    }

    /**
     * Handle GROMACS binary formats
     */
    parseGromacsBinary(content, filename, format, options = {}) {
        // These are binary formats that cannot be parsed in pure JavaScript
        // Provide helpful conversion instructions
        
        const instructions = format === 'xtc' 
            ? `XTC format is a compressed binary trajectory format from GROMACS.
               
To convert to XYZ format, use GROMACS tools:
  gmx trjconv -f trajectory.xtc -s topology.tpr -o trajectory.xyz

Or use MDAnalysis in Python:
  import MDAnalysis as mda
  u = mda.Universe("topology.pdb", "trajectory.xtc")
  u.atoms.write("trajectory.xyz")`
            : `TRR format is a binary trajectory format from GROMACS.
               
To convert to XYZ format, use GROMACS tools:
  gmx trjconv -f trajectory.trr -s topology.tpr -o trajectory.xyz

Or use MDAnalysis in Python:
  import MDAnalysis as mda
  u = mda.Universe("topology.pdb", "trajectory.trr")
  u.atoms.write("trajectory.xyz")`;

        throw new Error(`Binary ${format.toUpperCase()} format detected.\n\n${instructions}`);
    }

    /**
     * Normalize element symbol to standard form
     */
    normalizeElement(symbol) {
        if (!symbol || typeof symbol !== 'string') {
            return 'C';
        }
        
        // Clean up and capitalize correctly
        symbol = symbol.trim();
        
        // Remove numbers and special characters
        symbol = symbol.replace(/[^a-zA-Z]/g, '');
        
        if (symbol.length === 0) {
            return 'C';
        }
        
        // First letter uppercase, rest lowercase
        symbol = symbol.charAt(0).toUpperCase() + symbol.slice(1).toLowerCase();
        
        // Validate against known elements
        if (this.elementData[symbol]) {
            return symbol;
        }
        
        // Try just first letter
        const firstLetter = symbol.charAt(0);
        if (this.elementData[firstLetter]) {
            return firstLetter;
        }
        
        return 'C'; // Default to carbon
    }

    /**
     * Convert numeric type to element symbol
     */
    typeToElement(type) {
        const elements = ['H', 'C', 'N', 'O', 'S', 'P', 'Fe', 'Cu', 'Zn', 'Na', 'Cl', 'Ca', 'Mg', 'K', 'Si', 'Al'];
        return elements[(type - 1) % elements.length] || 'C';
    }

    /**
     * Create standardized trajectory object
     */
    createTrajectoryObject(format, filename, frames) {
        // Calculate bounding box from first frame
        const box = frames[0].box || this.calculateBoundingBox(frames[0].atoms);
        
        // Apply box to all frames that don't have one
        frames.forEach(frame => {
            if (!frame.box) {
                frame.box = box;
            }
            frame.atomCount = frame.atoms.length;
        });

        return {
            format,
            filename,
            frameCount: frames.length,
            atomCount: frames[0].atomCount,
            frames,
            box,
            metadata: {
                parsedAt: new Date().toISOString(),
                parser: 'TrajectoryParser v1.0'
            }
        };
    }

    /**
     * Calculate bounding box from atom coordinates
     */
    calculateBoundingBox(atoms) {
        if (!atoms || atoms.length === 0) {
            return { min: { x: 0, y: 0, z: 0 }, max: { x: 10, y: 10, z: 10 } };
        }

        const min = { x: Infinity, y: Infinity, z: Infinity };
        const max = { x: -Infinity, y: -Infinity, z: -Infinity };

        atoms.forEach(atom => {
            if (atom.x < min.x) min.x = atom.x;
            if (atom.y < min.y) min.y = atom.y;
            if (atom.z < min.z) min.z = atom.z;
            if (atom.x > max.x) max.x = atom.x;
            if (atom.y > max.y) max.y = atom.y;
            if (atom.z > max.z) max.z = atom.z;
        });

        // Add small padding
        const padding = 1;
        min.x -= padding; min.y -= padding; min.z -= padding;
        max.x += padding; max.y += padding; max.z += padding;

        return { min, max };
    }

    /**
     * Validate trajectory data
     */
    validate(trajectory) {
        const issues = [];

        if (!trajectory.frames || trajectory.frames.length === 0) {
            issues.push('No frames in trajectory');
        }

        trajectory.frames.forEach((frame, idx) => {
            if (!frame.atoms || frame.atoms.length === 0) {
                issues.push(`Frame ${idx + 1} has no atoms`);
            }
            
            frame.atoms.forEach((atom, atomIdx) => {
                if (isNaN(atom.x) || isNaN(atom.y) || isNaN(atom.z)) {
                    issues.push(`Frame ${idx + 1}, atom ${atomIdx + 1}: invalid coordinates`);
                }
            });

            // Check atom count consistency
            if (idx > 0 && frame.atoms.length !== trajectory.frames[0].atoms.length) {
                issues.push(`Frame ${idx + 1}: atom count mismatch (${frame.atoms.length} vs ${trajectory.frames[0].atoms.length})`);
            }
        });

        return {
            valid: issues.length === 0,
            issues
        };
    }
}

// Export
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TrajectoryParser;
} else if (typeof window !== 'undefined') {
    window.TrajectoryParser = TrajectoryParser;
}
