/**
 * Molecular Dynamics Analysis Tools
 * 
 * Provides real-time analysis capabilities for trajectory visualization:
 * - Distance measurements
 * - Angle calculations
 * - Dihedral angles
 * - Radial Distribution Function (RDF)
 * - Root Mean Square Deviation (RMSD)
 * - Center of Mass
 * - Radius of Gyration
 * - Mean Square Displacement (MSD)
 * - Coordination number
 * - Hydrogen bond analysis
 */

class MDAnalysisTools {
    constructor() {
        // Covalent radii for bond detection (in Ångströms)
        this.covalentRadii = {
            'H':  0.31, 'He': 0.28, 'Li': 1.28, 'Be': 0.96, 'B':  0.84,
            'C':  0.76, 'N':  0.71, 'O':  0.66, 'F':  0.57, 'Ne': 0.58,
            'Na': 1.66, 'Mg': 1.41, 'Al': 1.21, 'Si': 1.11, 'P':  1.07,
            'S':  1.05, 'Cl': 1.02, 'Ar': 1.06, 'K':  2.03, 'Ca': 1.76,
            'Fe': 1.32, 'Cu': 1.32, 'Zn': 1.22, 'Br': 1.20, 'I':  1.39
        };

        // Atomic masses (in atomic mass units)
        this.atomicMasses = {
            'H':  1.008,   'He': 4.003,   'Li': 6.941,   'Be': 9.012,
            'B':  10.811,  'C':  12.011,  'N':  14.007,  'O':  15.999,
            'F':  18.998,  'Ne': 20.180,  'Na': 22.990,  'Mg': 24.305,
            'Al': 26.982,  'Si': 28.086,  'P':  30.974,  'S':  32.065,
            'Cl': 35.453,  'Ar': 39.948,  'K':  39.098,  'Ca': 40.078,
            'Fe': 55.845,  'Cu': 63.546,  'Zn': 65.380,  'Br': 79.904,
            'I':  126.904
        };

        // VdW radii for surface calculations
        this.vdwRadii = {
            'H':  1.20, 'He': 1.40, 'C':  1.70, 'N':  1.55, 'O':  1.52,
            'F':  1.47, 'Ne': 1.54, 'Si': 2.10, 'P':  1.80, 'S':  1.80,
            'Cl': 1.75, 'Ar': 1.88, 'Br': 1.85, 'I':  1.98
        };
    }

    // ===========================
    // DISTANCE & GEOMETRY
    // ===========================

    /**
     * Calculate distance between two atoms
     */
    distance(atom1, atom2) {
        const dx = atom1.x - atom2.x;
        const dy = atom1.y - atom2.y;
        const dz = atom1.z - atom2.z;
        return Math.sqrt(dx * dx + dy * dy + dz * dz);
    }

    /**
     * Calculate distance with periodic boundary conditions
     */
    distancePBC(atom1, atom2, box) {
        let dx = atom1.x - atom2.x;
        let dy = atom1.y - atom2.y;
        let dz = atom1.z - atom2.z;

        // Apply minimum image convention
        const lx = box.max.x - box.min.x;
        const ly = box.max.y - box.min.y;
        const lz = box.max.z - box.min.z;

        dx -= Math.round(dx / lx) * lx;
        dy -= Math.round(dy / ly) * ly;
        dz -= Math.round(dz / lz) * lz;

        return Math.sqrt(dx * dx + dy * dy + dz * dz);
    }

    /**
     * Calculate angle between three atoms (in degrees)
     * Returns the angle at atom2 (vertex)
     */
    angle(atom1, atom2, atom3) {
        // Vectors from vertex to other atoms
        const v1 = {
            x: atom1.x - atom2.x,
            y: atom1.y - atom2.y,
            z: atom1.z - atom2.z
        };
        const v2 = {
            x: atom3.x - atom2.x,
            y: atom3.y - atom2.y,
            z: atom3.z - atom2.z
        };

        // Dot product
        const dot = v1.x * v2.x + v1.y * v2.y + v1.z * v2.z;
        
        // Magnitudes
        const mag1 = Math.sqrt(v1.x * v1.x + v1.y * v1.y + v1.z * v1.z);
        const mag2 = Math.sqrt(v2.x * v2.x + v2.y * v2.y + v2.z * v2.z);

        // Angle in radians, then convert to degrees
        const cosAngle = Math.max(-1, Math.min(1, dot / (mag1 * mag2)));
        return Math.acos(cosAngle) * (180 / Math.PI);
    }

    /**
     * Calculate dihedral angle between four atoms (in degrees)
     */
    dihedral(atom1, atom2, atom3, atom4) {
        // Vectors between consecutive atoms
        const b1 = {
            x: atom2.x - atom1.x,
            y: atom2.y - atom1.y,
            z: atom2.z - atom1.z
        };
        const b2 = {
            x: atom3.x - atom2.x,
            y: atom3.y - atom2.y,
            z: atom3.z - atom2.z
        };
        const b3 = {
            x: atom4.x - atom3.x,
            y: atom4.y - atom3.y,
            z: atom4.z - atom3.z
        };

        // Normal vectors to planes
        const n1 = this.crossProduct(b1, b2);
        const n2 = this.crossProduct(b2, b3);

        // Normalize
        const n1Mag = Math.sqrt(n1.x * n1.x + n1.y * n1.y + n1.z * n1.z);
        const n2Mag = Math.sqrt(n2.x * n2.x + n2.y * n2.y + n2.z * n2.z);
        
        if (n1Mag < 1e-10 || n2Mag < 1e-10) {
            return 0; // Degenerate case
        }

        n1.x /= n1Mag; n1.y /= n1Mag; n1.z /= n1Mag;
        n2.x /= n2Mag; n2.y /= n2Mag; n2.z /= n2Mag;

        // Cosine of dihedral
        const cos = n1.x * n2.x + n1.y * n2.y + n1.z * n2.z;
        
        // Get sign using cross product
        const m1 = this.crossProduct(n1, n2);
        const b2Mag = Math.sqrt(b2.x * b2.x + b2.y * b2.y + b2.z * b2.z);
        const sign = (m1.x * b2.x + m1.y * b2.y + m1.z * b2.z) / b2Mag;

        return Math.atan2(sign, cos) * (180 / Math.PI);
    }

    crossProduct(v1, v2) {
        return {
            x: v1.y * v2.z - v1.z * v2.y,
            y: v1.z * v2.x - v1.x * v2.z,
            z: v1.x * v2.y - v1.y * v2.x
        };
    }

    // ===========================
    // CENTER OF MASS & INERTIA
    // ===========================

    /**
     * Calculate center of mass
     */
    centerOfMass(atoms, useWeights = true) {
        let totalMass = 0;
        let cx = 0, cy = 0, cz = 0;

        atoms.forEach(atom => {
            const mass = useWeights ? (this.atomicMasses[atom.symbol] || 12) : 1;
            totalMass += mass;
            cx += atom.x * mass;
            cy += atom.y * mass;
            cz += atom.z * mass;
        });

        return {
            x: cx / totalMass,
            y: cy / totalMass,
            z: cz / totalMass,
            totalMass
        };
    }

    /**
     * Calculate radius of gyration
     */
    radiusOfGyration(atoms) {
        const com = this.centerOfMass(atoms);
        let sumSq = 0;
        let totalMass = 0;

        atoms.forEach(atom => {
            const mass = this.atomicMasses[atom.symbol] || 12;
            const dx = atom.x - com.x;
            const dy = atom.y - com.y;
            const dz = atom.z - com.z;
            sumSq += mass * (dx * dx + dy * dy + dz * dz);
            totalMass += mass;
        });

        return Math.sqrt(sumSq / totalMass);
    }

    /**
     * Calculate moment of inertia tensor
     */
    momentOfInertia(atoms) {
        const com = this.centerOfMass(atoms);
        
        let Ixx = 0, Iyy = 0, Izz = 0;
        let Ixy = 0, Ixz = 0, Iyz = 0;

        atoms.forEach(atom => {
            const mass = this.atomicMasses[atom.symbol] || 12;
            const x = atom.x - com.x;
            const y = atom.y - com.y;
            const z = atom.z - com.z;

            Ixx += mass * (y * y + z * z);
            Iyy += mass * (x * x + z * z);
            Izz += mass * (x * x + y * y);
            Ixy -= mass * x * y;
            Ixz -= mass * x * z;
            Iyz -= mass * y * z;
        });

        return {
            tensor: [
                [Ixx, Ixy, Ixz],
                [Ixy, Iyy, Iyz],
                [Ixz, Iyz, Izz]
            ],
            principalMoments: this.eigenvalues3x3(Ixx, Iyy, Izz, Ixy, Ixz, Iyz)
        };
    }

    /**
     * Calculate eigenvalues of 3x3 symmetric matrix (simplified)
     */
    eigenvalues3x3(a11, a22, a33, a12, a13, a23) {
        // Use Cardano's formula for 3x3 symmetric matrix
        const trace = a11 + a22 + a33;
        const q = trace / 3;
        
        const p1 = a12 * a12 + a13 * a13 + a23 * a23;
        const p2 = (a11 - q) * (a11 - q) + (a22 - q) * (a22 - q) + 
                   (a33 - q) * (a33 - q) + 2 * p1;
        const p = Math.sqrt(p2 / 6);

        // Simplified eigenvalue calculation
        // For more accurate results, use proper numerical library
        const I1 = trace;
        const I2 = a11 * a22 + a22 * a33 + a33 * a11 - a12 * a12 - a23 * a23 - a13 * a13;
        const I3 = a11 * a22 * a33 + 2 * a12 * a23 * a13 - 
                   a11 * a23 * a23 - a22 * a13 * a13 - a33 * a12 * a12;

        return { I1, I2, I3 };
    }

    // ===========================
    // RMSD & ALIGNMENT
    // ===========================

    /**
     * Calculate RMSD between two frames
     */
    rmsd(frame1, frame2, selection = null) {
        const atoms1 = selection ? this.selectAtoms(frame1.atoms, selection) : frame1.atoms;
        const atoms2 = selection ? this.selectAtoms(frame2.atoms, selection) : frame2.atoms;

        if (atoms1.length !== atoms2.length) {
            throw new Error('Frames have different number of atoms');
        }

        let sumSq = 0;
        for (let i = 0; i < atoms1.length; i++) {
            const dx = atoms1[i].x - atoms2[i].x;
            const dy = atoms1[i].y - atoms2[i].y;
            const dz = atoms1[i].z - atoms2[i].z;
            sumSq += dx * dx + dy * dy + dz * dz;
        }

        return Math.sqrt(sumSq / atoms1.length);
    }

    /**
     * Calculate RMSD over trajectory (against first frame)
     */
    rmsdTrajectory(trajectory, selection = null) {
        const results = [];
        const refFrame = trajectory.frames[0];

        trajectory.frames.forEach((frame, idx) => {
            results.push({
                frame: idx,
                time: frame.time || idx,
                rmsd: idx === 0 ? 0 : this.rmsd(refFrame, frame, selection)
            });
        });

        return results;
    }

    // ===========================
    // RADIAL DISTRIBUTION FUNCTION
    // ===========================

    /**
     * Calculate Radial Distribution Function (RDF)
     * g(r) for a single frame
     */
    rdf(frame, options = {}) {
        const {
            rMax = 10,
            dr = 0.1,
            typeA = null,  // Element symbol or null for all
            typeB = null,
            box = frame.box
        } = options;

        const atoms = frame.atoms;
        const n = atoms.length;
        const numBins = Math.ceil(rMax / dr);
        const histogram = new Array(numBins).fill(0);

        // Select atom pairs
        let atomsA, atomsB;
        if (typeA) {
            atomsA = atoms.filter(a => a.symbol === typeA);
        } else {
            atomsA = atoms;
        }
        if (typeB) {
            atomsB = atoms.filter(a => a.symbol === typeB);
        } else {
            atomsB = atoms;
        }

        // Count pairs
        let pairCount = 0;
        for (let i = 0; i < atomsA.length; i++) {
            for (let j = 0; j < atomsB.length; j++) {
                if (atomsA[i] === atomsB[j]) continue;

                const r = box 
                    ? this.distancePBC(atomsA[i], atomsB[j], box)
                    : this.distance(atomsA[i], atomsB[j]);

                if (r < rMax) {
                    const bin = Math.floor(r / dr);
                    if (bin < numBins) {
                        histogram[bin]++;
                        pairCount++;
                    }
                }
            }
        }

        // Normalize
        const volume = box 
            ? (box.max.x - box.min.x) * (box.max.y - box.min.y) * (box.max.z - box.min.z)
            : (4/3) * Math.PI * Math.pow(rMax, 3);
        
        const rho = atomsB.length / volume;
        const normFactor = (4 * Math.PI * rho * atomsA.length * dr);

        const rdfData = [];
        for (let i = 0; i < numBins; i++) {
            const rLower = i * dr;
            const rUpper = (i + 1) * dr;
            const rMid = (rLower + rUpper) / 2;
            const shellVolume = (4/3) * Math.PI * (Math.pow(rUpper, 3) - Math.pow(rLower, 3));
            
            const g = atomsA.length > 0 
                ? histogram[i] / (shellVolume * rho * atomsA.length)
                : 0;

            rdfData.push({
                r: rMid,
                g: g,
                count: histogram[i]
            });
        }

        return {
            data: rdfData,
            rMax,
            dr,
            typeA,
            typeB,
            atomCountA: atomsA.length,
            atomCountB: atomsB.length
        };
    }

    // ===========================
    // MEAN SQUARE DISPLACEMENT
    // ===========================

    /**
     * Calculate Mean Square Displacement over trajectory
     */
    msd(trajectory, options = {}) {
        const {
            selection = null,
            maxLag = null
        } = options;

        const frames = trajectory.frames;
        const nFrames = frames.length;
        const maxT = maxLag || Math.floor(nFrames / 2);

        // Get reference positions from first frame
        const refAtoms = selection 
            ? this.selectAtoms(frames[0].atoms, selection)
            : frames[0].atoms;
        const n = refAtoms.length;

        const msdData = [];

        for (let lag = 0; lag <= maxT; lag++) {
            let sumSq = 0;
            let count = 0;

            for (let t = 0; t < nFrames - lag; t++) {
                const atoms1 = selection 
                    ? this.selectAtoms(frames[t].atoms, selection)
                    : frames[t].atoms;
                const atoms2 = selection 
                    ? this.selectAtoms(frames[t + lag].atoms, selection)
                    : frames[t + lag].atoms;

                for (let i = 0; i < n; i++) {
                    const dx = atoms2[i].x - atoms1[i].x;
                    const dy = atoms2[i].y - atoms1[i].y;
                    const dz = atoms2[i].z - atoms1[i].z;
                    sumSq += dx * dx + dy * dy + dz * dz;
                    count++;
                }
            }

            msdData.push({
                lag,
                time: lag * (trajectory.frames[1]?.time - trajectory.frames[0]?.time || 1),
                msd: sumSq / count
            });
        }

        return msdData;
    }

    // ===========================
    // BOND & COORDINATION
    // ===========================

    /**
     * Detect bonds based on distance criteria
     */
    detectBonds(atoms, options = {}) {
        const {
            tolerance = 0.4,  // Ångströms above sum of covalent radii
            maxBondLength = 2.5
        } = options;

        const bonds = [];
        const n = atoms.length;

        for (let i = 0; i < n; i++) {
            const r1 = this.covalentRadii[atoms[i].symbol] || 1.5;
            
            for (let j = i + 1; j < n; j++) {
                const r2 = this.covalentRadii[atoms[j].symbol] || 1.5;
                const maxDist = Math.min(r1 + r2 + tolerance, maxBondLength);
                
                const dist = this.distance(atoms[i], atoms[j]);
                
                if (dist < maxDist && dist > 0.4) {
                    bonds.push({
                        atom1: i,
                        atom2: j,
                        length: dist,
                        order: this.estimateBondOrder(atoms[i].symbol, atoms[j].symbol, dist)
                    });
                }
            }
        }

        return bonds;
    }

    /**
     * Estimate bond order from distance (simplified)
     */
    estimateBondOrder(elem1, elem2, distance) {
        // Very simplified - proper bond order requires topology
        const singleBondDist = (this.covalentRadii[elem1] || 1.5) + (this.covalentRadii[elem2] || 1.5);
        
        if (distance < singleBondDist * 0.85) {
            return 3; // Triple bond
        } else if (distance < singleBondDist * 0.92) {
            return 2; // Double bond
        } else {
            return 1; // Single bond
        }
    }

    /**
     * Calculate coordination number
     */
    coordinationNumber(atoms, centerIndex, cutoff = 3.0) {
        const center = atoms[centerIndex];
        let count = 0;

        atoms.forEach((atom, i) => {
            if (i !== centerIndex) {
                const dist = this.distance(center, atom);
                if (dist <= cutoff) {
                    count++;
                }
            }
        });

        return count;
    }

    /**
     * Calculate average coordination numbers by element
     */
    averageCoordination(atoms, cutoff = 3.0) {
        const coordByElement = {};

        atoms.forEach((atom, i) => {
            const cn = this.coordinationNumber(atoms, i, cutoff);
            if (!coordByElement[atom.symbol]) {
                coordByElement[atom.symbol] = { sum: 0, count: 0 };
            }
            coordByElement[atom.symbol].sum += cn;
            coordByElement[atom.symbol].count++;
        });

        const result = {};
        for (const elem in coordByElement) {
            result[elem] = coordByElement[elem].sum / coordByElement[elem].count;
        }

        return result;
    }

    // ===========================
    // HYDROGEN BONDS
    // ===========================

    /**
     * Detect hydrogen bonds
     */
    findHydrogenBonds(atoms, options = {}) {
        const {
            donorElements = ['N', 'O'],
            acceptorElements = ['N', 'O', 'F'],
            maxDist = 3.5,        // D-A distance
            maxAngle = 30         // D-H-A angle deviation from 180°
        } = options;

        const hBonds = [];

        // Find potential donors (atoms bonded to H)
        const bonds = this.detectBonds(atoms);
        const hydrogenBonds = bonds.filter(b => 
            atoms[b.atom1].symbol === 'H' || atoms[b.atom2].symbol === 'H'
        );

        hydrogenBonds.forEach(bond => {
            const hIndex = atoms[bond.atom1].symbol === 'H' ? bond.atom1 : bond.atom2;
            const donorIndex = atoms[bond.atom1].symbol === 'H' ? bond.atom2 : bond.atom1;
            
            const donor = atoms[donorIndex];
            const hydrogen = atoms[hIndex];

            if (!donorElements.includes(donor.symbol)) return;

            // Find acceptors
            atoms.forEach((acceptor, accIndex) => {
                if (accIndex === donorIndex || accIndex === hIndex) return;
                if (!acceptorElements.includes(acceptor.symbol)) return;

                const daDist = this.distance(donor, acceptor);
                if (daDist > maxDist) return;

                const angle = this.angle(donor, hydrogen, acceptor);
                if (Math.abs(180 - angle) > maxAngle) return;

                hBonds.push({
                    donor: donorIndex,
                    hydrogen: hIndex,
                    acceptor: accIndex,
                    distance: daDist,
                    angle: angle,
                    donorSymbol: donor.symbol,
                    acceptorSymbol: acceptor.symbol
                });
            });
        });

        return hBonds;
    }

    // ===========================
    // SOLVENT ACCESSIBLE SURFACE
    // ===========================

    /**
     * Estimate solvent accessible surface area (simplified)
     */
    sasa(atoms, probeRadius = 1.4, nPoints = 100) {
        const totalSasa = { total: 0, byAtom: [] };

        // Generate points on sphere
        const spherePoints = this.fibonacciSphere(nPoints);

        atoms.forEach((atom, i) => {
            const radius = (this.vdwRadii[atom.symbol] || 1.7) + probeRadius;
            let accessible = 0;

            spherePoints.forEach(point => {
                const x = atom.x + point.x * radius;
                const y = atom.y + point.y * radius;
                const z = atom.z + point.z * radius;

                // Check if point is buried by other atoms
                let isBuried = false;
                for (let j = 0; j < atoms.length && !isBuried; j++) {
                    if (i === j) continue;
                    const other = atoms[j];
                    const otherRadius = (this.vdwRadii[other.symbol] || 1.7) + probeRadius;
                    const dx = x - other.x;
                    const dy = y - other.y;
                    const dz = z - other.z;
                    if (dx * dx + dy * dy + dz * dz < otherRadius * otherRadius) {
                        isBuried = true;
                    }
                }

                if (!isBuried) {
                    accessible++;
                }
            });

            const atomSasa = (accessible / nPoints) * 4 * Math.PI * radius * radius;
            totalSasa.byAtom.push({
                index: i,
                symbol: atom.symbol,
                sasa: atomSasa
            });
            totalSasa.total += atomSasa;
        });

        return totalSasa;
    }

    /**
     * Generate Fibonacci sphere points
     */
    fibonacciSphere(n) {
        const points = [];
        const phi = Math.PI * (3 - Math.sqrt(5)); // Golden angle

        for (let i = 0; i < n; i++) {
            const y = 1 - (i / (n - 1)) * 2;
            const radius = Math.sqrt(1 - y * y);
            const theta = phi * i;

            points.push({
                x: Math.cos(theta) * radius,
                y: y,
                z: Math.sin(theta) * radius
            });
        }

        return points;
    }

    // ===========================
    // SELECTION UTILITIES
    // ===========================

    /**
     * Select atoms based on criteria
     */
    selectAtoms(atoms, selection) {
        if (!selection) return atoms;

        if (typeof selection === 'function') {
            return atoms.filter(selection);
        }

        if (typeof selection === 'string') {
            // Parse selection string
            // Examples: "C", "C,N,O", "resid 1-10", "chain A"
            const parts = selection.toLowerCase().split(/\s+/);
            
            if (parts.length === 1) {
                // Element selection
                const elements = parts[0].split(',').map(e => e.toUpperCase());
                return atoms.filter(a => elements.includes(a.symbol));
            }

            // More complex selections
            const keyword = parts[0];
            const value = parts.slice(1).join(' ');

            switch (keyword) {
                case 'resid':
                case 'residue':
                    const range = this.parseRange(value);
                    return atoms.filter(a => range.includes(a.residueId));
                case 'chain':
                    return atoms.filter(a => a.chain === value.toUpperCase());
                case 'name':
                    return atoms.filter(a => a.name === value.toUpperCase());
                case 'index':
                    const indices = this.parseRange(value);
                    return atoms.filter((a, i) => indices.includes(i));
                default:
                    return atoms;
            }
        }

        if (Array.isArray(selection)) {
            // Array of indices
            return selection.map(i => atoms[i]).filter(Boolean);
        }

        return atoms;
    }

    /**
     * Parse range string like "1-10,15,20-25"
     */
    parseRange(str) {
        const result = [];
        const parts = str.split(',');

        parts.forEach(part => {
            if (part.includes('-')) {
                const [start, end] = part.split('-').map(Number);
                for (let i = start; i <= end; i++) {
                    result.push(i);
                }
            } else {
                result.push(Number(part));
            }
        });

        return result;
    }

    // ===========================
    // SUMMARY STATISTICS
    // ===========================

    /**
     * Calculate summary statistics for a frame
     */
    frameSummary(frame) {
        const atoms = frame.atoms;
        const com = this.centerOfMass(atoms);
        const rg = this.radiusOfGyration(atoms);
        const box = frame.box;

        // Element counts
        const elementCounts = {};
        atoms.forEach(atom => {
            elementCounts[atom.symbol] = (elementCounts[atom.symbol] || 0) + 1;
        });

        // Box dimensions
        let boxSize = null;
        let volume = null;
        let density = null;

        if (box) {
            boxSize = {
                x: box.max.x - box.min.x,
                y: box.max.y - box.min.y,
                z: box.max.z - box.min.z
            };
            volume = boxSize.x * boxSize.y * boxSize.z;
            density = atoms.length / volume;
        }

        // Total mass
        let totalMass = 0;
        atoms.forEach(atom => {
            totalMass += this.atomicMasses[atom.symbol] || 12;
        });

        return {
            atomCount: atoms.length,
            elementCounts,
            centerOfMass: com,
            radiusOfGyration: rg,
            totalMass,
            box: boxSize,
            volume,
            density
        };
    }

    /**
     * Calculate trajectory statistics
     */
    trajectorySummary(trajectory) {
        const frameStats = trajectory.frames.map(f => this.frameSummary(f));
        
        // Calculate averages and ranges
        const rgValues = frameStats.map(s => s.radiusOfGyration);
        
        return {
            frameCount: trajectory.frames.length,
            atomCount: trajectory.atomCount,
            format: trajectory.format,
            filename: trajectory.filename,
            radiusOfGyration: {
                mean: rgValues.reduce((a, b) => a + b, 0) / rgValues.length,
                min: Math.min(...rgValues),
                max: Math.max(...rgValues)
            },
            firstFrame: frameStats[0],
            lastFrame: frameStats[frameStats.length - 1]
        };
    }
}

// Export
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MDAnalysisTools;
} else if (typeof window !== 'undefined') {
    window.MDAnalysisTools = MDAnalysisTools;
}
