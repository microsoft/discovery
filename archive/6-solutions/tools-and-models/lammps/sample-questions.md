## 1. Algorithmic correctness and comparison (HEX vs eHEX)

- **Question:**
  **"For both LJ and SPC/E, quantify how HEX and eHEX differ in: (a) energy drift, (b) steady‑state temperature profile, and (c) computed thermal conductivity."**
  **Required files:**
  - `example-input-files/in.lj.hex`
  - `example-input-files/in.lj.ehex`
  - `example-input-files/in.spce.hex`
  - `example-input-files/in.spce.ehex`
  - `example-input-files/data.lj`
  - `example-input-files/data.spce`

  **Computation:**
  - Run `in.lj.hex`, `in.lj.ehex`, `in.spce.hex`, `in.spce.ehex`.
  - Extract `out.T*` and `out.E*`; fit linear T(z); compute κ from imposed heat flux vs gradient.
  - Compare drift in total energy over time.

- **Question:**
  **"Over a range of timesteps, at what timestep does each algorithm (HEX vs eHEX) become unstable or unacceptably inaccurate?"**
  **Required files:**
  - `example-input-files/in.lj.hex` (modify timestep parameter)
  - `example-input-files/in.lj.ehex` (modify timestep parameter)
  - `example-input-files/data.lj`

  **Computation:**
  - Sweep timestep (e.g., factor of 2 increments).
  - Monitor: energy conservation, gradient linearity, and any crashes or NaNs.
  - Identify stability and accuracy limits.

- **Question:**
  **"Does eHEX converge faster to the non‑equilibrium steady state than HEX for the same system and parameters?"**
  **Required files:**
  - `example-input-files/in.lj.hex`
  - `example-input-files/in.lj.ehex`
  - `example-input-files/data.lj`

  **Computation:**
  - Track time evolution of temperature profile to steady state.
  - Define a metric (e.g., L2 distance from final T(z)); estimate relaxation times.

---

## 2. Transport properties and system size effects

- **Question:**
  **"How does the computed thermal conductivity change with system length in the gradient direction?"**
  **Required files:**
  - `example-input-files/in.lj.ehex` (modify box dimensions)
  - `example-input-files/data.lj` (modify for different system sizes)

  **Computation:**
  - Create scaled versions of the LJ or SPC/E box (longer in z).
  - Keep density and thermostat parameters consistent.
  - Compute κ for each length and analyze finite‑size effects.

- **Question:**
  **"For a fixed geometry, how does thermal conductivity depend on the imposed heat flux (i.e., linear vs nonlinear response)?"**
  **Required files:**
  - `example-input-files/in.lj.ehex` (modify heat flux parameter)
  - `example-input-files/data.lj`

  **Computation:**
  - Vary the energy exchange rate in `fix ehex`.
  - Compute κ from flux vs ∇T; check linear-response regime vs nonlinear deviations.

- **Question:**
  **"Do the temperature profiles remain strictly linear, or is there curvature near hot/cold regions?"**
  **Required files:**
  - `example-input-files/in.lj.ehex`
  - `example-input-files/data.lj`

  **Computation:**
  - Fit both a linear and quadratic function to T(z).
  - Compare residuals; quantify any boundary layer effects.

---

## 3. Uncertainty, robustness, and reproducibility

- **Question:**
  **"What is the statistical uncertainty in the measured thermal conductivity, and how does it scale with simulation time?"**
  **Required files:**
  - `example-input-files/in.lj.ehex` (run with different random seeds)
  - `example-input-files/data.lj`

  **Computation:**
  - Run multiple independent replicas with different velocity seeds.
  - Block‑average κ as a function of simulation length.
  - Estimate error bars and convergence behavior.

- **Question:**
  **"How sensitive are the results to the choice of bin width in the temperature profile?"**
  **Required files:**
  - `example-input-files/in.lj.ehex` (modify chunk/bin settings)
  - `example-input-files/data.lj`

  **Computation:**
  - Rerun or post‑process with different spatial binning.
  - Compare gradients and inferred κ.

- **Question:**
  **"If we restart the simulation from different points, do we recover consistent temperature profiles and κ?"**
  **Required files:**
  - `example-input-files/in.lj.ehex`
  - `example-input-files/data.lj`
  - Generated restart files from previous runs

  **Computation:**
  - Use LAMMPS restart files, branch expansions from several snapshots.
  - Compare steady‑state properties across branches.

---

## 4. Method development and diagnostics

- **Question:**
  **"Can we implement an alternative non‑equilibrium thermostat (e.g., velocity swapping or local Langevin) and compare it to HEX/eHEX using the same data files?"**
  **Required files:**
  - `example-input-files/in.lj.ehex` (modify to use alternative thermostat)
  - `example-input-files/data.lj`

  **Computation:**
  - Clone the input scripts; replace `fix ehex` with alternative fixes.
  - Compare energy conservation, T(z), κ, and stability.

- **Question:**
  **"Where exactly is the entropy production localized in the system?"**
  **Required files:**
  - `example-input-files/in.lj.ehex`
  - `example-input-files/data.lj`

  **Computation:**
  - Combine local fluxes with local gradients (from chunks).
  - Map spatial distribution of entropy production.

- **Question:**
  **"How do different long‑range electrostatics settings (for SPC/E) affect the thermal conductivity and profile shape?"**
  **Required files:**
  - `example-input-files/in.spce.ehex` (modify PPPM settings)
  - `example-input-files/data.spce`

  **Computation:**
  - Compare `pppm`, different accuracy tolerances, cutoffs.
  - Measure κ and check whether artifacts appear near boundaries.

---

## 5. Performance and scaling questions

- **Question:**
  **"How does parallel performance (strong scaling) differ between HEX and eHEX for LJ and SPC/E?"**
  **Required files:**
  - `example-input-files/in.lj.hex`
  - `example-input-files/in.lj.ehex`
  - `example-input-files/in.spce.hex`
  - `example-input-files/in.spce.ehex`
  - `example-input-files/data.lj`
  - `example-input-files/data.spce`

  **Computation:**
  - Run each input on varying MPI task counts.
  - Extract wall time, ns/day (or steps/sec), and load balance from logs.

- **Question:**
  **"Does using GPUs (if available) change the timing balance between force calculation and HEX/eHEX operations?"**
  **Required files:**
  - `example-input-files/in.lj.hex`
  - `example-input-files/in.lj.ehex`
  - `example-input-files/data.lj`

  **Computation:**
  - Run CPU‑only vs GPU‑accelerated builds.
  - Profile time spent per fix vs pair compute.

---

## 6. Cross‑comparison with equilibrium methods

- **Question:**
  **"Do HEX/eHEX non‑equilibrium estimates of thermal conductivity agree with equilibrium Green–Kubo results for the same system?"**
  **Required files:**
  - `example-input-files/in.lj.ehex` (for NEMD)
  - `example-input-files/data.lj`
  - Additional equilibrium input file (to be created for Green-Kubo calculation)

  **Computation:**
  - Use the same data file for an equilibrium run (no gradient).
  - Compute heat flux autocorrelation and κ via Green–Kubo.
  - Compare with NEMD κ from HEAT runs.

---

---

## 7. Biomolecular simulations

- **Question:**
  **"Equilibrate a protein in explicit water using the CHARMM force field and compute the RMSD over a 1 ns trajectory."**
  **Required files:**
  - Protein structure file (PDB or LAMMPS data format)
  - CHARMM force field parameters
  - Water box setup

  **Computation:**
  - Solvate protein in TIP3P water box with appropriate padding
  - Energy minimize to remove bad contacts
  - NVT equilibration followed by NPT production
  - Compute backbone RMSD relative to initial structure

- **Question:**
  **"Calculate the radial distribution function g(r) between protein and water oxygen atoms."**
  **Required files:**
  - Equilibrated protein-water system

  **Computation:**
  - Use compute rdf to calculate g(r) between protein heavy atoms and water oxygens
  - Identify hydration shell distances (first peak location)
  - Compare hydration around different residue types

- **Question:**
  **"What is the diffusion coefficient of water molecules in the bulk vs. near the protein surface?"**
  **Required files:**
  - Equilibrated protein-water system

  **Computation:**
  - Use compute msd for different water populations (bulk vs. surface)
  - Fit MSD to extract diffusion coefficient D = MSD / (6t)
  - Quantify slowdown factor for surface water

---

## 8. Materials science - metals and alloys

- **Question:**
  **"Compute the elastic constants (C11, C12, C44) of copper using the EAM potential."**
  **Required files:**
  - Cu.eam.alloy potential file (available in LAMMPS potentials directory)

  **Computation:**
  - Create perfect FCC copper crystal at equilibrium lattice constant
  - Apply small strain deformations in different directions
  - Measure stress response to compute elastic tensor components
  - Compare with experimental values

- **Question:**
  **"Simulate the melting point of aluminum using two-phase coexistence."**
  **Required files:**
  - Al EAM potential

  **Computation:**
  - Create solid-liquid interface at various temperatures
  - Run NPT simulation and track interface motion
  - Identify temperature where interface is stationary (melting point)

- **Question:**
  **"How do grain boundaries affect thermal conductivity in polycrystalline copper?"**
  **Required files:**
  - Cu EAM potential

  **Computation:**
  - Create bicrystal with symmetric tilt grain boundary
  - Use NEMD (eHEX) to compute thermal conductivity across grain boundary
  - Compare with single crystal thermal conductivity
  - Quantify Kapitza resistance at grain boundary

---

## 9. Polymer simulations

- **Question:**
  **"Compute the radius of gyration and end-to-end distance of a polymer melt as a function of chain length."**
  **Required files:**
  - Polymer chain data files of varying lengths

  **Computation:**
  - Equilibrate polymer melts with different chain lengths
  - Compute Rg and R_ee using compute gyration
  - Verify scaling laws (Rg ~ N^0.5 for ideal chains)

- **Question:**
  **"What is the glass transition temperature (Tg) of polystyrene?"**
  **Required files:**
  - Polystyrene model (united atom or all-atom)

  **Computation:**
  - Cool system from high temperature at constant rate (NPT)
  - Track density vs. temperature
  - Identify Tg from change in slope of density-temperature curve

- **Question:**
  **"Simulate the uniaxial tensile deformation of a polymer network and compute the stress-strain curve."**
  **Required files:**
  - Crosslinked polymer network data file

  **Computation:**
  - Apply constant strain rate deformation using fix deform
  - Measure stress tensor components during deformation
  - Identify Young's modulus from linear region
  - Characterize yield point and strain hardening

---

## 10. Reactive chemistry - ReaxFF

- **Question:**
  **"Simulate the oxidation of a silicon surface using ReaxFF and identify the oxide layer thickness."**
  **Required files:**
  - Si/O ReaxFF parameter file

  **Computation:**
  - Create clean silicon surface
  - Introduce O2 molecules above the surface
  - Run high-temperature reactive MD
  - Analyze oxide formation kinetics and layer composition

- **Question:**
  **"What is the activation energy for hydrogen dissociation on a platinum catalyst surface?"**
  **Required files:**
  - Pt/H ReaxFF parameters

  **Computation:**
  - Place H2 molecule at various distances from Pt(111) surface
  - Use NEB (nudged elastic band) to find minimum energy path
  - Extract activation barrier for dissociative adsorption

- **Question:**
  **"Simulate combustion of methane in air and identify intermediate species."**
  **Required files:**
  - C/H/O/N ReaxFF combustion parameters

  **Computation:**
  - Mix methane and oxygen molecules in a box
  - Heat system to ignition temperature
  - Track species populations (CH3, OH, H2O, CO, CO2) over time
  - Compute heat release rate

---

## 11. Mechanical properties and fracture

- **Question:**
  **"Compute the fracture toughness of graphene with a pre-existing crack."**
  **Required files:**
  - Graphene structure with center crack
  - AIREBO or Tersoff potential for carbon

  **Computation:**
  - Apply tensile strain perpendicular to crack
  - Monitor stress and crack propagation
  - Compute critical stress intensity factor K_IC

- **Question:**
  **"Perform a nanoindentation simulation on a copper thin film and extract hardness."**
  **Required files:**
  - Cu EAM potential
  - Indenter geometry (spherical or Berkovich)

  **Computation:**
  - Use fix indent to simulate indenter
  - Record force-displacement curve during loading/unloading
  - Extract hardness H and reduced modulus E_r using Oliver-Pharr method

- **Question:**
  **"How does temperature affect the yield strength of an iron nanowire?"**
  **Required files:**
  - Fe EAM potential

  **Computation:**
  - Create cylindrical Fe nanowire
  - Apply tensile deformation at different temperatures (10K to 600K)
  - Extract yield stress from stress-strain curves
  - Fit temperature dependence to thermal activation model

---

## 12. Surface and interface phenomena

- **Question:**
  **"Calculate the contact angle of a water droplet on a hydrophobic surface."**
  **Required files:**
  - Water model (SPC/E or TIP4P)
  - Surface model with tunable hydrophobicity

  **Computation:**
  - Place water droplet on flat surface
  - Equilibrate and measure droplet shape
  - Fit to circular cap to extract contact angle
  - Vary surface-water interaction strength to tune hydrophobicity

- **Question:**
  **"What is the surface tension of liquid argon from molecular simulation?"**
  **Required files:**
  - LJ parameters for argon

  **Computation:**
  - Create liquid slab with two vacuum interfaces
  - Equilibrate system at appropriate temperature
  - Compute surface tension from pressure tensor anisotropy
  - Compare with experimental value (13 mN/m at 87K)

---

## 13. Enhanced sampling and free energy

- **Question:**
  **"Compute the potential of mean force for ion pair dissociation in water."**
  **Required files:**
  - Ion parameters (e.g., Na+, Cl-)
  - Water model

  **Computation:**
  - Use umbrella sampling with fix spring
  - Sample at different ion-ion distances
  - Apply WHAM to reconstruct free energy profile
  - Identify contact ion pair and solvent-separated ion pair states

- **Question:**
  **"Use replica exchange MD (REMD) to sample the folding landscape of a small peptide."**
  **Required files:**
  - Peptide structure and force field parameters

  **Computation:**
  - Set up temperature ladder spanning folded to unfolded states
  - Run REMD using fix temper
  - Compute folding free energy from temperature-dependent populations

