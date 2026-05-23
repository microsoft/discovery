import sys
import logging
from rdkit import Chem
# RDKit standardization
from rdkit.Chem import MolStandardize

# Guard Open Babel import
try:
    from openbabel import openbabel as ob
except ImportError:
    ob = None

# Utility funcions for molecular analysis and descriptor calculations

def prepare_molecule(smiles: str, add_hs: bool = True, embed: bool = False):
    """Prepare an RDKit molecule from a SMILES string using ETKDGv3 for embedding.

    Args:
        smiles (str): SMILES representation of the molecule.
        add_hs (bool): If True, add explicit hydrogens (default: True).
        embed (bool): If True, embed 3D coordinates using ETKDGv3 (default: False).

    Returns:
        mol: The prepared RDKit molecule.

    Raises:
        ValueError: If the SMILES string is invalid.
        RuntimeError: If embedding fails.
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError("Invalid SMILES string")
    if add_hs:
        mol = Chem.AddHs(mol)
    if embed:
        if AllChem.EmbedMolecule(mol, AllChem.ETKDGv3()) != 0:
            raise RuntimeError("Embedding failed")
    return mol


def count_aromatic_rings(smiles: str) -> int:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        ri = mol.GetRingInfo()
        ring_count = 0
        for ring_atoms in ri.AtomRings():
            if all(mol.GetAtomWithIdx(idx).GetIsAromatic() for idx in ring_atoms):
                ring_count += 1
        return ring_count
    except Exception as e:
        logging.error(f"Error counting aromatic rings for {smiles}: {e}")
        return -1

def calculate_drug_likeness(smiles: str, method="QED") -> dict:
    """
    Calculates drug-likeness using different available methods.

    :param smiles: SMILES representation of the molecule.
    :param method: Drug-likeness method. Options: "QED", "Lipinski", "Ghose", "Veber", "Egan", "ALL".
    :return: Dictionary of drug-likeness scores.
             - QED returns: {'score': float} where float is 0-1
             - Lipinski returns: {'compliant': bool, 'violations': list[str], 'num_violations': int}
             - ALL returns: {'QED': {'score': float}, 'Lipinski': {...}, ...}
             - Other methods return: {'method_name': str} with violation info
    """
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        results = {}

        # QED Score (0 to 1) - ALWAYS return dict with 'score' key
        if method == "QED" or method == "ALL":
            qed_score = QED.qed(mol)
            if method == "QED":
                results["score"] = float(qed_score)
            else:
                results["QED"] = {"score": float(qed_score)}

        # Lipinski's Rule of Five - return dict with boolean 'compliant' and list of violations
        if method == "Lipinski" or method == "ALL":
            mw = Descriptors.MolWt(mol)  # Molecular Weight
            logp = Crippen.MolLogP(mol)  # LogP
            h_donors = Descriptors.NumHDonors(mol)  # Hydrogen Bond Donors
            h_acceptors = Descriptors.NumHAcceptors(mol)  # Hydrogen Bond Acceptors

            violations_list = []
            if mw > 500:
                violations_list.append("MW > 500")
            if logp > 5:
                violations_list.append("LogP > 5")
            if h_donors > 5:
                violations_list.append("HBD > 5")
            if h_acceptors > 10:
                violations_list.append("HBA > 10")
            
            lipinski_result = {
                "compliant": len(violations_list) == 0,
                "violations": violations_list,
                "num_violations": len(violations_list)
            }
            if method == "Lipinski":
                results = lipinski_result
            else:
                results["Lipinski"] = lipinski_result

        # Ghose Filter
        if method == "Ghose" or method == "ALL":
            mw = Descriptors.MolWt(mol)
            logp = Crippen.MolLogP(mol)
            atom_count = mol.GetNumAtoms()
            mr = Descriptors.MolMR(mol)
            
            ghose_violations = sum([
                not (160 <= mw <= 480),
                not (-0.4 <= logp <= 5.6),
                not (20 <= atom_count <= 70),
                not (40 <= mr <= 130)  # Add check for molar refractivity range
            ])
            ghose_violation_list = []
            if not (160 <= mw <= 480):
                ghose_violation_list.append(f"MW={mw:.2f} not in [160,480]")
            if not (-0.4 <= logp <= 5.6):
                ghose_violation_list.append(f"LogP={logp:.2f} not in [-0.4,5.6]")
            if not (20 <= atom_count <= 70):
                ghose_violation_list.append(f"AtomCount={atom_count} not in [20,70]")
            if not (40 <= mr <= 130):
                ghose_violation_list.append(f"MR={mr:.2f} not in [40,130]")
            ghose_result = {
                "compliant": len(ghose_violation_list) == 0,
                "violations": ghose_violation_list,
                "num_violations": len(ghose_violation_list)
            }
            if method == "Ghose":
                results = ghose_result
            else:
                results["Ghose"] = ghose_result

        # Veber's Rule
        if method == "Veber" or method == "ALL":
            rot_bonds = Descriptors.NumRotatableBonds(mol)
            psa = Descriptors.TPSA(mol)

            veber_violations = sum([
                rot_bonds > 10,
                psa > 140
            ])
            veber_violation_list = []
            if rot_bonds > 10:
                veber_violation_list.append(f"RotBonds={rot_bonds} > 10")
            if psa > 140:
                veber_violation_list.append(f"TPSA={psa:.2f} > 140")
            veber_result = {
                "compliant": len(veber_violation_list) == 0,
                "violations": veber_violation_list,
                "num_violations": len(veber_violation_list)
            }
            if method == "Veber":
                results = veber_result
            else:
                results["Veber"] = veber_result

        # Egan's Rule
        if method == "Egan" or method == "ALL":
            logp = Crippen.MolLogP(mol)
            psa = Descriptors.TPSA(mol)

            egan_violations = sum([
                psa > 131,
                logp > 5.88
            ])
            egan_violation_list = []
            if psa > 131:
                egan_violation_list.append(f"TPSA={psa:.2f} > 131")
            if logp > 5.88:
                egan_violation_list.append(f"LogP={logp:.2f} > 5.88")
            egan_result = {
                "compliant": len(egan_violation_list) == 0,
                "violations": egan_violation_list,
                "num_violations": len(egan_violation_list)
            }
            if method == "Egan":
                results = egan_result
            else:
                results["Egan"] = egan_result

        return results

    except Exception as e:
        logging.error(f"Error calculating drug-likeness for {smiles}: {e}")
        return {"Error": str(e)}

def calculate_exact_mass(smiles: str) -> float:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        return Descriptors.ExactMolWt(mol)
    except Exception as e:
        logging.error(f"Error calculating exact mass for SMILES {smiles}: {e}")
        return 0.0

def generate_conformers(smiles: str, max_conformers: int = 10, prune_rms_threshold: float = 0.5) -> list:
    """
    Generate molecular conformers from a SMILES string.
    
    Args:
        smiles: SMILES representation of the molecule
        max_conformers: Maximum number of conformers to generate
        prune_rms_threshold: RMS threshold for pruning similar conformers
        
    Returns:
        List of XYZ format strings for each conformer
        
    Raises:
        ValueError: If SMILES string is invalid or parameters are out of range
        RuntimeError: If conformer generation fails
        TypeError: If input parameters are of incorrect type
    """
    if not isinstance(smiles, str) or not smiles:
        logging.error("Invalid SMILES input: empty or not a string")
        raise ValueError("SMILES must be a non-empty string")
        
    if not isinstance(max_conformers, int) or max_conformers <= 0:
        logging.error(f"Invalid max_conformers value: {max_conformers}")
        raise ValueError("max_conformers must be a positive integer")
        
    if not isinstance(prune_rms_threshold, (int, float)) or prune_rms_threshold < 0:
        logging.error(f"Invalid prune_rms_threshold value: {prune_rms_threshold}")
        raise ValueError("prune_rms_threshold must be a non-negative number")
    
    try:
        molecule = prepare_molecule(smiles, add_hs=True, embed=False)

        # Check if molecule is too large or complex for reasonable conformer generation
        if molecule.GetNumAtoms() > 200:
            logging.warning(f"Very large molecule ({molecule.GetNumAtoms()} atoms) may cause performance issues")
            
        molecule = Chem.AddHs(molecule)
        params = AllChem.ETKDGv3()
        params.numThreads = 0
        params.pruneRmsThresh = prune_rms_threshold

        try:
            conformer_ids = AllChem.EmbedMultipleConfs(molecule, numConfs=max_conformers, params=params)
        except RuntimeError as e:
            logging.error(f"RDKit conformer generation error: {e}")
            raise RuntimeError(f"Failed to generate conformers: {e}")
            
        if not conformer_ids:
            logging.error("No conformers could be generated for the molecule")
            raise RuntimeError("No conformers could be generated. The molecule might be too complex or have structural issues.")

        xyz_strings = []
        for conf_id in conformer_ids:
            try:
                atom_count = molecule.GetNumAtoms()
                xyz_string = f"{atom_count}\nConformer {conf_id}\n"
                for atom_idx in range(atom_count):
                    atom = molecule.GetAtomWithIdx(atom_idx)
                    pos = molecule.GetConformer(conf_id).GetAtomPosition(atom_idx)
                    xyz_string += f"{atom.GetSymbol()} {pos.x:.4f} {pos.y:.4f} {pos.z:.4f}\n"
                xyz_strings.append(xyz_string)
            except Exception as e:
                logging.error(f"Error processing conformer {conf_id}: {e}")
                # Continue with other conformers instead of failing completely
                
        if not xyz_strings:
            logging.error("Failed to extract valid XYZ strings from any conformers")
            raise RuntimeError("Generated conformers could not be converted to XYZ format")
            
        return xyz_strings
        
    except ValueError as e:
        # Let ValueError pass through with its message
        raise
    except RuntimeError as e:
        # Let RuntimeError pass through with its message
        raise
    except Exception as e:
        # Catch any other unexpected errors
        logging.error(f"Unexpected error in conformer generation: {e}")
        raise RuntimeError(f"Unexpected error during conformer generation: {e}")

from rdkit.Chem.MolStandardize import rdMolStandardize
def generate_tautomers(smiles: str, max_tautomers: int = 10) -> list[str]:
    """
    Generate tautomers using RDKit's TautomerEnumerator.
    
    Args:
        smiles: SMILES string representation of the molecule
        max_tautomers: Maximum number of tautomers to generate
    
    Returns:
        list: List of tautomer SMILES strings
    """
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)

        enumerator = rdMolStandardize.TautomerEnumerator()
        tautomers = enumerator.Enumerate(mol)
        # Convert to SMILES
        tautomer_smiles = set()
        for taut in tautomers:
            tautomer_smiles.add(Chem.MolToSmiles(taut, isomericSmiles=True))

        # Limit to max_tautomers
        return list(tautomer_smiles)[:max_tautomers]
    except Exception as e:
        logging.error(f"Error generating tautomers for {smiles}: {e}")
        return []

from rdkit.Chem import Lipinski
def calculate_hbond_acceptors(smiles: str) -> int:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        return Lipinski.NumHAcceptors(mol)
    except Exception as e:
        logging.error(f"Error calculating H-bond acceptors for {smiles}: {e}")
        return -1

def calculate_hbond_donors(smiles: str) -> int:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        return Lipinski.NumHDonors(mol)
    except Exception as e:
        logging.error(f"Error calculating H-bond donors for {smiles}: {e}")
        return -1

def count_atoms(smiles: str) -> tuple[int, int]:
    """Count heavy atoms and heteroatoms in a molecule.
    
    Args:
        smiles: SMILES string representation of the molecule
    
    Returns:
        tuple: (heavy_atom_count, heteroatom_count)
            - heavy_atom_count: Number of non-hydrogen atoms
            - heteroatom_count: Number of atoms that are not C or H
    
    Example:
        heavy, hetero = count_atoms('CCO')  # Returns (3, 1)
    """
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        heavy_atom_count = sum(1 for atom in mol.GetAtoms() if atom.GetAtomicNum() > 1)
        heteroatom_count = sum(1 for atom in mol.GetAtoms() if atom.GetSymbol() not in ["C", "H"])
        return heavy_atom_count, heteroatom_count
    except Exception as e:
        logging.error(f"Error counting atoms for SMILES {smiles}: {e}")
        return 0, 0

def get_isomeric_smiles(smiles: str) -> str:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        return Chem.MolToSmiles(mol, isomericSmiles=True)
    except Exception as e:
        logging.error(f"Error getting isomeric SMILES for {smiles}: {e}")
        return ""

def check_lipinski(smiles: str) -> dict:
    """
    Check compliance with Lipinski's Rule of Five.
    
    Lipinski's Rule of Five:
      1) MW <= 500
      2) LogP <= 5
      3) HBD <= 5
      4) HBA <= 10
    
    Args:
        smiles: SMILES string representation of the molecule
    
    Returns:
        dict: {'compliant': bool, 'violations': list[str], 'num_violations': int}
            - compliant: True if all rules are satisfied
            - violations: List of rule violations as strings
            - num_violations: Count of violations
    """
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)

        mw = Descriptors.MolWt(mol)
        logp = Descriptors.MolLogP(mol)
        hbd = Lipinski.NumHDonors(mol)
        hba = Lipinski.NumHAcceptors(mol)

        violations = []
        if mw > 500:
            violations.append("MW > 500")
        if logp > 5:
            violations.append("LogP > 5")
        if hbd > 5:
            violations.append("HBD > 5")
        if hba > 10:
            violations.append("HBA > 10")

        compliance = (len(violations) == 0)
        return {"compliant": compliance, "violations": violations}

    except Exception as e:
        logging.error(f"Error in Lipinski check for {smiles}: {e}")
        return {"compliant": False, "violations": ["error"]}

from rdkit.Chem import Crippen, QED
def calculate_logp(smiles: str) -> float:
    """
    Calculate the LogP of a molecule given its SMILES.
    """
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        logp_val = Crippen.MolLogP(mol)
        return logp_val
    except Exception as e:
        logging.error(f"Error calculating LogP for SMILES {smiles}: {e}")
        return float('nan')

def calculate_descriptors(smiles: str):
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        # Approximate solubility as negative logP and use MolMR as refractivity proxy.
        solubility = -Crippen.MolLogP(mol)
        refractivity = Crippen.MolMR(mol)
        qed_val = QED.qed(mol)
        return solubility, refractivity, qed_val
    except Exception as e:
        logging.error(f"Error calculating descriptors for SMILES {smiles}: {e}")
        return 0.0, 0.0, 0.0

from rdkit.Chem.rdMolDescriptors import CalcMolFormula
def calculate_molecular_formula(smiles: str) -> str:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        formula = CalcMolFormula(mol)
        return formula
    except Exception as e:
        logging.error(f"Error calculating molecular formula for SMILES {smiles}: {e}")
        return ""

from rdkit.Chem import Descriptors
def calculate_molecular_weight(smiles: str) -> float:
    """
    Calculate the molecular weight of a molecule given its SMILES.
    """
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        return Descriptors.MolWt(mol)
    except Exception as e:
        logging.error(f"Error calculating molecular weight for SMILES {smiles}: {e}")
        return -1.0  # Return negative to indicate an error

from rdkit.Chem import AllChem
def optimize_structure(smiles: str, max_iterations: int = 200, convergence_threshold: float = 1e-4,
                       force_field: str = "MMFF94") -> dict:
    try:
        mol = prepare_molecule(smiles, add_hs=True, embed=True)

        energy = None
        status = "optimized"
        ff_used = force_field.upper()

        if ff_used == "MMFF94":
            try:
                properties = AllChem.MMFFGetMoleculeProperties(mol)
                if properties is None:
                    raise RuntimeError("MMFF94 properties could not be obtained")
                ff = AllChem.MMFFGetMoleculeForceField(mol, properties)
                if ff is None:
                    raise RuntimeError("MMFF94 force field could not be created")
                ff.Minimize(maxIts=max_iterations, energyTol=convergence_threshold)
                energy = ff.CalcEnergy()
            except Exception as e:
                logging.warning(f"MMFF94 optimization failed for SMILES {smiles}: {str(e)}")
                logging.warning("Trying UFF optimization as fallback...")
                try:
                    ff = AllChem.UFFGetMoleculeForceField(mol)
                    if ff is None:
                        raise RuntimeError("UFF force field could not be created")
                    ff.Minimize(maxIts=max_iterations, energyTol=convergence_threshold)
                    energy = ff.CalcEnergy()
                    ff_used = "UFF"
                    status = "optimized_with_fallback"
                except Exception as uff_e:
                    logging.warning(f"UFF fallback optimization also failed: {str(uff_e)}")
                    status = "unoptimized"
        elif ff_used == "UFF":
            try:
                ff = AllChem.UFFGetMoleculeForceField(mol)
                if ff is None:
                    raise RuntimeError("UFF force field could not be created")
                ff.Minimize(maxIts=max_iterations, energyTol=convergence_threshold)
                energy = ff.CalcEnergy()
            except Exception as e:
                logging.warning(f"UFF optimization failed for SMILES {smiles}: {str(e)}")
                logging.warning("Trying MMFF94 optimization as fallback...")
                try:
                    properties = AllChem.MMFFGetMoleculeProperties(mol)
                    if properties is not None:
                        ff = AllChem.MMFFGetMoleculeForceField(mol, properties)
                        if ff is not None:
                            ff.Minimize(maxIts=max_iterations, energyTol=convergence_threshold)
                            energy = ff.CalcEnergy()
                            ff_used = "MMFF94"
                            status = "optimized_with_fallback"
                        else:
                            status = "unoptimized"
                    else:
                        logging.warning("MMFF94 parameters not available for this molecule")
                        status = "unoptimized"
                except Exception as mmff_e:
                    logging.warning(f"MMFF94 fallback optimization also failed: {str(mmff_e)}")
                    status = "unoptimized"
        elif ff_used == "NONE":
            status = "unoptimized"
        else:
            try:
                ff = AllChem.UFFGetMoleculeForceField(mol)
                if ff is None:
                    raise RuntimeError("UFF force field could not be created")
                ff.Minimize(maxIts=max_iterations, energyTol=convergence_threshold)
                energy = ff.CalcEnergy()
                ff_used = "UFF"
            except Exception as e:
                logging.warning(f"UFF optimization failed for SMILES {smiles}: {str(e)}")
                status = "unoptimized"

        sdf_block = Chem.MolToMolBlock(mol)
        return {
            "energy": energy,
            "status": status,
            "force_field": ff_used,
            "sdf_block": sdf_block
        }
    except Exception as e:
        logging.error(f"Error optimizing 3D structure for SMILES {smiles}: {e}")
        return {"energy": None, "status": f"error: {str(e)}", "force_field": force_field, "sdf_block": ""}

from rdkit.Chem import FilterCatalog
def check_pains_alerts(smiles: str, catalog: FilterCatalog) -> list:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        if catalog.HasMatch(mol):
            alerts = [entry.GetDescription() for entry in catalog.GetMatches(mol)]
            return alerts
    except Exception as e:
        logging.error(f"Error checking PAINS for {smiles}: {e}")
        return []

def calculate_partial_charges(smiles: str, method: str = "Gasteiger", iterations: int = 10, output_format: str = "detailed"):
    """
    Calculate partial charges for a molecule.
    
    Args:
        smiles: SMILES string representation of the molecule
        method: Charge calculation method (currently only "Gasteiger" supported)
        iterations: Maximum number of iterations for the calculation
        output_format: Format of the output - "list" (original format), "detailed" (dictionary with atom info),
                      or "smiles_map" (dictionary with SMILES as key)
    
    Returns:
        Based on output_format:
        - "list": List of partial charges (original format)
        - "detailed": Dictionary where keys are "{atom_symbol}_{atom_idx}" and values are charges
        - "smiles_map": Dictionary with SMILES as key and list of charges as value
    """
    try:
        mol = prepare_molecule(smiles, add_hs=True, embed=False)
        if not mol:
            raise ValueError(f"Invalid SMILES: {smiles}")
        
        if method.lower() == "gasteiger":
            Chem.rdPartialCharges.ComputeGasteigerCharges(mol, nIter=iterations)
        else:
            supported_methods = ["gasteiger"]
            raise ValueError(f"Unsupported charge calculation method: {method}. Supported methods: {supported_methods}")
        
        # Collect charges
        charges_list = []
        charges_detailed = {}
        
        for atom in mol.GetAtoms():
            charge = atom.GetProp("_GasteigerCharge") if atom.HasProp("_GasteigerCharge") else "0.0"
            try:
                charge = float(charge)
            except ValueError:
                logging.warning(f"Non-numeric charge value '{charge}' for atom {atom.GetIdx()} in {smiles}. Using 0.0.")
                charge = 0.0
            
            charges_list.append(charge)
            atom_key = f"{atom.GetSymbol()}_{atom.GetIdx()}"
            charges_detailed[atom_key] = charge
        
        # Return in the requested format
        if output_format.lower() == "list":
            return charges_list
        elif output_format.lower() == "detailed":
            return charges_detailed
        elif output_format.lower() == "smiles_map":
            return {smiles: charges_list}
        else:
            logging.warning(f"Unknown output format: {output_format}. Using 'detailed'.")
            return charges_detailed
            
    except Exception as e:
        logging.error(f"Error calculating partial charges for SMILES {smiles}: {str(e)}")
        if output_format.lower() == "list":
            return []
        elif output_format.lower() == "detailed":
            return {}
        elif output_format.lower() == "smiles_map":
            return {smiles: []}
        else:
            return {}


from rdkit.Chem import rdMolDescriptors
def calculate_rotatable_bonds(smiles: str) -> int:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        return rdMolDescriptors.CalcNumRotatableBonds(mol)
    except Exception as e:
        logging.error(f"Error calculating rotatable bonds for {smiles}: {e}")
        return -1

from rdkit.Chem.Scaffolds import MurckoScaffold
def extract_scaffold(smiles: str) -> str:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        scaffold = MurckoScaffold.GetScaffoldForMol(mol)
        scaffold_smiles = Chem.MolToSmiles(scaffold)
        return scaffold_smiles
    except Exception as e:
        logging.error(f"Error extracting scaffold for SMILES {smiles}: {e}")
        return ""

def standardize_molecule(smiles: str) -> str:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        try:
            # Attempt to import and use the Uncharger from MolStandardize
            from rdkit.Chem.MolStandardize import Uncharger
            uncharger = Uncharger()
            mol = uncharger.uncharge(mol)
        except ImportError:
            logging.warning("Uncharger not available in this RDKit version; skipping uncharge step")
        Chem.SanitizeMol(mol)
        return Chem.MolToSmiles(mol, canonical=True)
    except Exception as e:
        logging.error(f"Error standardizing SMILES {smiles}: {e}")
        return ""

def identify_stereocenters(smiles: str):
    """
    Returns a list of stereocenters in the molecule.
    Each stereocenter is represented by the atom index and configuration.
    """
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        chiral_centers = Chem.FindMolChiralCenters(mol, includeUnassigned=True)
        return chiral_centers
    except Exception as e:
        logging.error(f"Error identifying stereocenters for {smiles}: {e}")
        return []

from rdkit.Chem.EnumerateStereoisomers import EnumerateStereoisomers, StereoEnumerationOptions
def enumerate_stereoisomers(smiles: str, max_isomers: int = 10):
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None: # Add check for valid molecule
            # Log an error or raise a more specific exception if preferred
            logging.error(f"Failed to create molecule from SMILES: {smiles}")
            return [] # Return empty list or handle error as appropriate
        opts = StereoEnumerationOptions(maxIsomers=max_isomers, unique=True)
        isomers = list(EnumerateStereoisomers(mol, options=opts))
        isomer_smiles = [Chem.MolToSmiles(isomer, isomericSmiles=True) for isomer in isomers]
        return isomer_smiles
    except Exception as e:
        logging.error(f"Error enumerating stereoisomers for SMILES {smiles}: {e}")
        return []

def search_substructure(smiles: str, substructure_pattern: str) -> bool:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        substructure = Chem.MolFromSmarts(substructure_pattern)
        if not substructure:
            raise ValueError("Invalid substructure pattern")
        return mol.HasSubstructMatch(substructure)
    except Exception as e:
        logging.error(f"Error in substructure search for SMILES {smiles} with pattern {substructure_pattern}: {e}")
        return False

def calculate_tpsa(smiles: str) -> float:
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        tpsa_value = Descriptors.TPSA(mol)
        return tpsa_value
    except Exception as e:
        logging.error(f"Error calculating TPSA for SMILES {smiles}: {e}")
        return -1.0

def validate_smiles(smiles: str) -> tuple[bool, str]:
    """Validate a SMILES string.
    
    Args:
        smiles: SMILES string to validate
    
    Returns:
        tuple: (is_valid, error_message)
            - is_valid: True if SMILES is valid
            - error_message: Empty string if valid, error description if invalid
    
    Example:
        is_valid, error = validate_smiles('CCO')
        if is_valid:
            # proceed with valid SMILES
    """
    try:
        mol = Chem.MolFromSmiles(smiles, sanitize=False)
        # Attempt sanitization
        Chem.SanitizeMol(mol)
        return True, ""
    except Exception as e:
        return False, str(e)

## Format conversions (CIF via Open Babel)
def cif_to_mol2(cif_path):
    if ob is None:
        raise ImportError("Open Babel not installed: install openbabel to enable CIF conversions.")
    try:
        obConversion = ob.OBConversion()
        obConversion.SetInFormat("cif")
        mol = ob.OBMol()
        if not obConversion.ReadFile(mol, cif_path):
            raise RuntimeError("Failed to read CIF file")
        obConversion.SetOutFormat("mol2")
        mol2_str = obConversion.WriteString(mol)
        return mol2_str
    except Exception as e:
        raise RuntimeError(f"Conversion CIF to MOL2 failed: {e}")

def cif_to_pdb(cif_path):
    if ob is None:
        raise ImportError("Open Babel not installed: install openbabel to enable CIF conversions.")
    try:
        obConversion = ob.OBConversion()
        obConversion.SetInFormat("cif")
        mol = ob.OBMol()
        if not obConversion.ReadFile(mol, cif_path):
            raise RuntimeError("Failed to read CIF file")
        obConversion.SetOutFormat("pdb")
        pdb_str = obConversion.WriteString(mol)
        return pdb_str
    except Exception as e:
        raise RuntimeError(f"Conversion CIF to PDB failed: {e}")

def cif_to_smiles(cif_path):
    if ob is None:
        raise ImportError("Open Babel not installed: install openbabel to enable CIF conversions.")
    try:
        obConversion = ob.OBConversion()
        obConversion.SetInFormat("cif")
        mol = ob.OBMol()
        if not obConversion.ReadFile(mol, cif_path):
            raise RuntimeError("Failed to read CIF file")
        conv_out = ob.OBConversion()
        conv_out.SetOutFormat("smi")
        smiles_str = conv_out.WriteString(mol).strip()
        return smiles_str
    except Exception as e:
        raise RuntimeError(f"Conversion CIF to SMILES failed: {e}")

def cif_to_xyz(cif_file_path):
    if not os.path.isfile(cif_file_path):
        raise FileNotFoundError(f"File not found: {cif_file_path}")

    if ob is None:
        raise ImportError("Open Babel not installed: install openbabel to enable CIF conversions.")
    try:
        # Set up Open Babel conversion
        ob_conversion = ob.OBConversion()
        ob_conversion.SetInAndOutFormats("cif", "xyz")

        # Read CIF into Open Babel molecule
        ob_mol = ob.OBMol()
        if not ob_conversion.ReadFile(ob_mol, cif_file_path):
            raise RuntimeError("Failed to read CIF file with Open Babel.")

        # Convert to XYZ format
        xyz_str = ob_conversion.WriteString(ob_mol)
        return xyz_str.strip()  # Remove trailing newlines

    except Exception as e:
        raise RuntimeError(f"Conversion CIF to XYZ failed: {e}")

def cml_to_pdb(cml_path):
    """
    Convert a CML file to PDB format using Open Babel.
    Parameters:
        cml_path (str): Path to the CML input file
    Returns:
        str: PDB-format string
    Raises:
        ImportError: If Open Babel is not available
        RuntimeError: If conversion fails
    """
    if ob is None:
        raise ImportError("Open Babel not installed: install openbabel to enable CML conversions.")
    try:
        obConversion = ob.OBConversion()
        obConversion.SetInFormat("cml")
        mol = ob.OBMol()
        if not obConversion.ReadFile(mol, cml_path):
            raise RuntimeError("Failed to read CML file")
        obConversion.SetOutFormat("pdb")
        pdb_str = obConversion.WriteString(mol)
        return pdb_str
    except Exception as e:
        raise RuntimeError(f"Conversion CML to PDB failed: {e}")

def inchi_to_smiles(inchi_str):
    """
    Convert an InChI string to a SMILES string using RDKit.
    Added detailed logging to help with debugging.
    """
    try:
        inchi_str = inchi_str.strip()
        logging.info(f"Received InChI string: '{inchi_str}'")
        if not inchi_str:
            raise ValueError("Empty InChI string provided")
        
        logging.info("Attempting conversion with removeHs=False and sanitize=True")
        mol = Chem.MolFromInchi(inchi_str, sanitize=True, removeHs=True)
        if mol is None:
            logging.error("Chem.MolFromInchi returned None. InChI may be invalid or improperly formatted.")
            raise ValueError("Invalid InChI string; conversion returned None")
        
        num_atoms = mol.GetNumAtoms()
        logging.info(f"Molecule conversion successful. Molecule has {num_atoms} atoms.")
        
        smiles_str = Chem.MolToSmiles(mol, isomericSmiles=True)
        logging.info(f"Generated SMILES: {smiles_str}")
        return smiles_str
    except Exception as e:
        logging.exception("Conversion InChI to SMILES failed.")
        raise RuntimeError(f"Conversion InChI to SMILES failed: {e}")

def mol2_to_pdb(mol2_path):
    if ob is None:
        raise RuntimeError("OpenBabel is not installed")
    try:
        obConversion = ob.OBConversion()
        obConversion.SetInFormat("mol2")
        mol = ob.OBMol()
        if not obConversion.ReadFile(mol, mol2_path):
            raise RuntimeError("Failed to read MOL2 file")
        obConversion.SetOutFormat("pdb")
        pdb_str = obConversion.WriteString(mol)
        return pdb_str
    except Exception as e:
        raise RuntimeError(f"Conversion MOL2 to PDB failed: {e}")

def mol2_to_sdf(mol2_path):
    try:
        if not os.path.exists(mol2_path):
            logging.error(f"File not found: {mol2_path}")
            raise FileNotFoundError(f"File not found: {mol2_path}")
        logging.info(f"Opening file: {mol2_path}")
        with open(mol2_path, 'r') as f:
            mol2_content = f.read()
        logging.info(f"File read successfully: {mol2_path}")
        
        # Directly use the MOL2 content
        mol = Chem.MolFromMol2Block(mol2_content, removeHs=False, sanitize=False)
        if mol is None:
            logging.error("RDKit failed to convert MOL2 block to molecule.")
            raise ValueError("Invalid MOL2 file")
        logging.info("Molecule created from MOL2 content")
        
        mol = Chem.AddHs(mol)
        
        # Bypass kekulization by removing the kekulize flag (assumed value 8)
        kekulize_flag = 8
        sanitize_ops = Chem.SanitizeFlags.SANITIZE_ALL & ~kekulize_flag
        try:
            Chem.SanitizeMol(mol, sanitizeOps=sanitize_ops)
        except Exception as e:
            logging.error(f"Sanitization (without kekulization) failed: {e}")
            raise RuntimeError(f"Sanitization failed: {e}")
        
        sdf_block = Chem.MolToMolBlock(mol, kekulize=False)
        logging.info("SDF block generated successfully")
        return sdf_block
    except Exception as e:
        logging.error(f"Conversion MOL2 to SDF failed: {e}")
        raise RuntimeError(f"Conversion MOL2 to SDF failed: {e}")

def mol2_to_smiles(mol2_path):
    try:
        if not os.path.exists(mol2_path):
            logging.error(f"File not found: {mol2_path}")
            raise FileNotFoundError(f"File not found: {mol2_path}")
        logging.info(f"Opening file: {mol2_path}")
        with open(mol2_path, 'r') as f:
            mol2_content = f.read()
        logging.info(f"File read successfully: {mol2_path}")

        # Optional: fix MOL2 content if needed
        # mol2_content = fix_mol2_content(mol2_content)

        mol = Chem.MolFromMol2Block(mol2_content, removeHs=False, sanitize=False)
        if mol is None:
            logging.error("RDKit failed to convert MOL2 block to molecule.")
            raise ValueError("Invalid MOL2 file")
        logging.info("Molecule created from MOL2 content")
        
        mol = Chem.AddHs(mol)

        # Bypass kekulization by removing the kekulize flag (assumed value 8)
        kekulize_flag = 8
        sanitize_ops = Chem.SanitizeFlags.SANITIZE_ALL & ~kekulize_flag
        try:
            Chem.SanitizeMol(mol, sanitizeOps=sanitize_ops)
        except Exception as e:
            logging.error(f"Sanitization (without kekulization) failed: {e}")
            raise RuntimeError(f"Sanitization failed: {e}")

        # Generate SMILES string
        smiles_str = Chem.MolToSmiles(mol, kekuleSmiles=False)
        logging.info("SMILES string generated successfully")
        return smiles_str
    except Exception as e:
        logging.error(f"Conversion MOL2 to SMILES failed: {e}")
        raise RuntimeError(f"Conversion MOL2 to SMILES failed: {e}")

def mol2_to_xyz(mol2_path):
    if ob is None:
        raise ImportError("Open Babel not installed; install openbabel to enable MOL2 to XYZ conversion.")
    try:
        obConversion = ob.OBConversion()
        obConversion.SetInFormat("mol2")
        mol = ob.OBMol()
        if not obConversion.ReadFile(mol, mol2_path):
            raise RuntimeError("Failed to read MOL2 file")
        obConversion.SetOutFormat("xyz")
        xyz_str = obConversion.WriteString(mol)
        return xyz_str
    except Exception as e:
        raise RuntimeError(f"Conversion MOL2 to XYZ failed: {e}")

def pdb_to_mol2(pdb_path):
    if ob is None:
        raise ImportError("Open Babel not installed; install openbabel to enable PDB to MOL2 conversion.")
    try:
        obConversion = ob.OBConversion()
        obConversion.SetInFormat("pdb")
        mol = ob.OBMol()
        if not obConversion.ReadFile(mol, pdb_path):
            raise RuntimeError("Failed to read PDB file")
        obConversion.SetOutFormat("mol2")
        mol2_str = obConversion.WriteString(mol)
        return mol2_str
    except Exception as e:
        raise RuntimeError(f"Conversion PDB to MOL2 failed: {e}")

def pdb_to_sdf(pdb_path):
    try:
        mol = Chem.MolFromPDBFile(pdb_path, removeHs=False)
        sdf_block = Chem.MolToMolBlock(mol)
        return sdf_block
    except Exception as e:
        raise RuntimeError(f"Conversion PDB to SDF failed: {e}")

def pdb_to_xyz(pdb_path):
    if ob is None:
        raise ImportError("Open Babel not installed; install openbabel to enable PDB to XYZ conversion.")
    try:
        obConversion = ob.OBConversion()
        obConversion.SetInFormat("pdb")
        mol = ob.OBMol()
        if not obConversion.ReadFile(mol, pdb_path):
            raise RuntimeError("Failed to read PDB file")
        obConversion.SetOutFormat("xyz")
        xyz_str = obConversion.WriteString(mol)
        return xyz_str
    except Exception as e:
        raise RuntimeError(f"Conversion PDB to XYZ failed: {e}")

def sdf_to_mol2(sdf_path):
    """
    Convert an SDF file to a MOL2 block string using OpenBabel's OBConversion.
    
    Steps:
      1. Check that the SDF file exists.
      2. Set up OBConversion with input format "sdf" and output format "mol2".
      3. Read the SDF file into an OBMol.
      4. Write the OBMol out as a MOL2 string.
    """
    if ob is None:
        raise ImportError("Open Babel not installed; install openbabel to enable SDF to MOL2 conversion.")
    try:
        if not os.path.exists(sdf_path):
            logging.error(f"File not found: {sdf_path}")
            raise FileNotFoundError(f"File not found: {sdf_path}")
        logging.info(f"Opening SDF file: {sdf_path}")

        obConversion = ob.OBConversion()
        if not obConversion.SetInFormat("sdf"):
            raise ValueError("Could not set OBConversion input format to SDF")
        if not obConversion.SetOutFormat("mol2"):
            raise ValueError("Could not set OBConversion output format to MOL2")

        mol = ob.OBMol()
        # Use OBConversion's ReadFile method (which reads from a file path)
        if obConversion.ReadFile(mol, sdf_path) == 0:
            logging.error("OpenBabel failed to read the SDF file.")
            raise ValueError("Conversion failed: Could not read SDF file")
        logging.info("Molecule read from SDF successfully")

        mol2_str = obConversion.WriteString(mol).strip()
        logging.info("MOL2 block generated successfully")
        return mol2_str
    except Exception as e:
        logging.exception("Conversion SDF to MOL2 failed.")
        raise RuntimeError(f"Conversion SDF to MOL2 failed: {e}")

def sdf_to_pdb(sdf_path):
    if ob is None:
        raise ImportError("Open Babel not installed; install openbabel to enable SDF to PDB conversion.")
    try:
        obConversion = ob.OBConversion()
        obConversion.SetInFormat("sdf")
        mol = ob.OBMol()
        if not obConversion.ReadFile(mol, sdf_path):
            raise RuntimeError("Failed to read SDF file")
        obConversion.SetOutFormat("pdb")
        pdb_str = obConversion.WriteString(mol)
        return pdb_str
    except Exception as e:
        raise RuntimeError(f"Conversion SDF to PDB failed: {e}")

def sdf_to_smiles(sdf_path):
    try:
        suppl = Chem.SDMolSupplier(sdf_path, removeHs=False)
        smiles_list = []
        for mol in suppl:
            if mol:
                smiles = Chem.MolToSmiles(mol)
                smiles_list.append(smiles)
        return ";".join(smiles_list)  # Concatenate SMILES with semicolon
    except Exception as e:
        raise RuntimeError(f"Conversion SDF to SMILES failed: {e}")

import os
def mol_to_xyz(mol):
    """
    Convert a single RDKit molecule to an XYZ block string.
    If no conformer exists, generate one.
    """
    if mol.GetNumConformers() == 0:
        try:
            AllChem.EmbedMolecule(mol)
        except Exception as e:
            logging.error(f"Embedding molecule failed: {e}")
            raise RuntimeError(f"Embedding molecule failed: {e}")
    conf = mol.GetConformer()
    num_atoms = mol.GetNumAtoms()
    # Use molecule name if available; otherwise, leave comment blank.
    comment = mol.GetProp('_Name') if mol.HasProp('_Name') else ""
    lines = [str(num_atoms), comment]
    for atom in mol.GetAtoms():
        pos = conf.GetAtomPosition(atom.GetIdx())
        lines.append(f"{atom.GetSymbol()} {pos.x:.4f} {pos.y:.4f} {pos.z:.4f}")
    return "\n".join(lines)

def sdf_to_xyz(sdf_path):
    try:
        if not os.path.exists(sdf_path):
            logging.error(f"File not found: {sdf_path}")
            raise FileNotFoundError(f"File not found: {sdf_path}")
        logging.info(f"Opening file: {sdf_path}")
        suppl = Chem.SDMolSupplier(sdf_path, removeHs=False, sanitize=True)
        xyz_blocks = []
        for mol in suppl:
            if mol is None:
                continue
            xyz = mol_to_xyz(mol)
            xyz_blocks.append(xyz)
        if not xyz_blocks:
            logging.error("No valid molecules found in SDF file.")
            raise ValueError("No valid molecules found in SDF file.")
        # Separate multiple molecules with a delimiter.
        return "\n$$$$\n".join(xyz_blocks)
    except Exception as e:
        logging.error(f"Conversion SDF to XYZ failed: {e}")
        raise RuntimeError(f"Conversion SDF to XYZ failed: {e}")

from rdkit.Chem import inchi
def smiles_to_inchi(smiles):
    print(hasattr(inchi, 'MolToInchi'))
    try:
        mol = prepare_molecule(smiles, add_hs=False, embed=False)
        inchi_str = inchi.MolToInchi(mol)
        return inchi_str
    except Exception as e:
        raise RuntimeError(f"Conversion SMILES to InChI failed: {e}")

def smiles_to_mol2(smiles_str):
    """
    Convert a SMILES string to a MOL2 block string using RDKit and OpenBabel.
    
    Steps:
      1. Validate and strip the input SMILES string.
      2. Convert the SMILES to an RDKit molecule.
      3. Add explicit hydrogens and embed 3D coordinates if needed.
      4. Convert the RDKit molecule to a MOL block (using MolToMolBlock).
      5. Use OpenBabel to convert the MOL block to a MOL2 block.
    """
    try:
        smiles_str = smiles_str.strip()
        logging.info(f"Received SMILES string: '{smiles_str}'")
        if not smiles_str:
            raise ValueError("Empty SMILES string provided")
        
        # Convert SMILES to an RDKit molecule.
        mol = prepare_molecule(smiles_str, add_hs=True, embed=True)
        if mol is None:
            logging.error("RDKit failed to convert SMILES to molecule.")
            raise ValueError("Invalid SMILES string")
        logging.info("Molecule created successfully from SMILES")
        
        # Generate a MOL block from the RDKit molecule.
        mol_block = Chem.MolToMolBlock(mol)
        
        # Use OpenBabel to convert the MOL block to MOL2.
        if ob is None:
            raise RuntimeError("OpenBabel is not installed")
        obConversion = ob.OBConversion()
        if not obConversion.SetInFormat("mol"):
            raise ValueError("Could not set OBConversion input format to MOL")
        if not obConversion.SetOutFormat("mol2"):
            raise ValueError("Could not set OBConversion output format to MOL2")

        obMol = ob.OBMol()
        # Read the MOL block from the RDKit molecule into an OBMol.
        if not obConversion.ReadString(obMol, mol_block):
            logging.error("OpenBabel failed to read the MOL block.")
            raise ValueError("Conversion failed: Could not parse MOL block")
        
        # Write the OBMol as a MOL2 block.
        mol2_str = obConversion.WriteString(obMol).strip()
        logging.info("MOL2 block generated successfully")
        return mol2_str
    except Exception as e:
        logging.error(f"Conversion SMILES to MOL2 failed: {e}")
        raise RuntimeError(f"Conversion SMILES to MOL2 failed: {e}")

def smiles_to_pdb(smiles):
    try:
        mol = prepare_molecule(smiles, add_hs=True, embed=True)
        mol = Chem.AddHs(mol)
        AllChem.EmbedMolecule(mol)
        pdb_block = Chem.MolToPDBBlock(mol)
        return pdb_block
    except Exception as e:
        raise RuntimeError(f"Conversion SMILES to PDB failed: {e}")

def smiles_to_sdf(smiles):
    try:
        mol = prepare_molecule(smiles, add_hs=True, embed=True)
        sdf_block = Chem.MolToMolBlock(mol)
        return sdf_block
    except Exception as e:
        raise RuntimeError(f"Conversion SMILES to SDF failed: {e}")

from rdkit.Chem.rdmolfiles import MolToXYZBlock
def smiles_to_xyz(smiles, optimize=False):
    """
    Convert a SMILES string to XYZ format using RDKit.

    Parameters:
        smiles (str): SMILES representation of the molecule.
        optimize (bool): Whether to optimize the geometry using MMFF94.

    Returns:
        str: XYZ formatted string.
    """
    try:
        # Convert SMILES to RDKit molecule
        mol = prepare_molecule(smiles, add_hs=True, embed=True)

        # If optimization is requested, optimize using MMFF94
        if optimize:
            AllChem.MMFFOptimizeMolecule(mol)

        # Convert to XYZ format
        xyz_str = MolToXYZBlock(mol)
        return xyz_str

    except Exception as e:
        logging.error(f"Error converting SMILES to XYZ: {e}")
        return ""

from ase.io import read, write
import numpy as np
def xyz_to_cif(xyz_path, cif_path):
    logging.info(f"Starting conversion for: {xyz_path}")
    try:
        logging.debug("Reading XYZ file...")
        with open(xyz_path, 'r') as f:
            xyz_block = f.read()
        atoms = read(xyz_path, format='xyz')
        logging.debug("Successfully read atoms: %s", atoms)

        cell = atoms.get_cell()
        logging.debug("Initial cell: %s", cell)

        if not np.any(cell) or not np.any(atoms.pbc):
            logging.info("No valid cell info found. Computing default cell...")
            mol = Chem.MolFromXYZBlock(xyz_block)
            if mol is None:
                logging.error(f"RDKit failed to parse XYZ content for {xyz_path}. Check the format.")
                return None

            # Ensure molecule has 3D coordinates.
            if mol.GetNumConformers() == 0:
                AllChem.EmbedMolecule(mol, AllChem.ETKDGv3())
            elif mol.GetNumConformers() == 1 and not mol.GetConformer().Is3D():
                AllChem.EmbedMolecule(mol, AllChem.ETKDGv3())

            conf = mol.GetConformer(0)

            # After computing cell_lengths, add centering of the molecule
            positions = conf.GetPositions()
            min_pos = np.min(positions, axis=0)
            max_pos = np.max(positions, axis=0)
            margin = 5.0
            cell_lengths = max_pos - min_pos + margin
            min_cell_length = 1.0
            cell_lengths = np.maximum(cell_lengths, min_cell_length)

            # Center the molecule in the cell
            center = (min_pos + max_pos) / 2.0
            cell_center = cell_lengths / 2.0
            centered_positions = positions - center + cell_center
            conf.SetPositions(centered_positions)
            atoms.positions = centered_positions

            atoms.cell = np.diag(cell_lengths)
            atoms.pbc = True

            logging.info(f"Computed cell: {atoms.cell}")
            logging.info(f"pbc set to: {atoms.pbc}")
        else:
            logging.info(f"Cell from XYZ: {atoms.cell}")
            logging.info(f"pbc from XYZ: {atoms.pbc}")

        import io
        write(cif_path, [atoms], format='cif')
        logging.info(f"Successfully wrote CIF file: {cif_path}")
    except Exception as e:
        logging.error("Conversion XYZ to CIF failed: %s", e, exc_info=True)
        return None

def xyz_to_mol2(xyz_path):
    if ob is None:
        raise RuntimeError("OpenBabel is not installed")
    try:
        obConversion = ob.OBConversion()
        obConversion.SetInFormat("xyz")
        mol = ob.OBMol()
        if not obConversion.ReadFile(mol, xyz_path):
            raise RuntimeError("Failed to read XYZ file")
        obConversion.SetOutFormat("mol2")
        mol2_str = obConversion.WriteString(mol)
        return mol2_str
    except Exception as e:
        raise RuntimeError(f"Conversion XYZ to MOL2 failed: {e}")
    
def xyz_to_pdb(xyz_path, add_hydrogens=True):
    try:
        ob_conversion = ob.OBConversion()
        ob_conversion.SetInAndOutFormats("xyz", "pdb")

        ob_mol = ob.OBMol()
        if not ob_conversion.ReadFile(ob_mol, xyz_path):
            raise ValueError("Failed to read XYZ file")

        if add_hydrogens:
            ob_mol.AddHydrogens()

        pdb_str = ob_conversion.WriteString(ob_mol)
        return pdb_str
    except Exception as e:
        logging.error(f"Error converting XYZ to PDB: {e}")
        return ""

def xyz_to_sdf(xyz_path, sdf_path, precision=6):
    """Converts an XYZ file to an SDF file using RDKit.

    Args:
        xyz_path: Path to the input XYZ file.
        sdf_path: Path to the output SDF file.
    """
    logging.info(f"Starting conversion from {xyz_path} to {sdf_path}")
    try:
        with open(xyz_path, 'r') as f:
            xyz_block = f.read()

        mol = Chem.MolFromXYZBlock(xyz_block)
        if mol is None:
            logging.error(f"RDKit failed to parse XYZ content from {xyz_path}. Check the format.")
            return False  # Indicate failure

        # If the molecule doesn't have 3D coordinates, generate them
        if mol.GetNumConformers() == 0:
            print("No 3D coordinates found, generating them...")
            AllChem.EmbedMolecule(mol, AllChem.ETKDGv3()) # Generate 3D coordinates
        elif mol.GetNumConformers() == 1 and mol.GetConformer().Is3D() == False:  # Generate 3D coordinates if there is only 1 2D conformer
            print("Converting 2D coordinates to 3D...")
            AllChem.EmbedMolecule(mol, AllChem.ETKDGv3())  # Generate 3D coordinates

        with Chem.SDWriter(sdf_path) as writer:  # Use SDWriter for SDF output
            writer.SetKekulize(True) # Set Kekule flag to write proper valences.
            writer.write(mol)

        logging.info(f"Conversion from {xyz_path} to {sdf_path} successful.")
        return True  # Indicate success

    except Exception as e:
        logging.error(f"Conversion from {xyz_path} to {sdf_path} failed: {e}", exc_info=True)
        return False  # Indicate failure

def xyz_to_smiles(xyz_path):
    try:
        logging.info(f"Converting XYZ file: {xyz_path}")  # Log the file being processed

        with open(xyz_path, 'r') as f:
            xyz_block = f.read()

        mol = Chem.MolFromXYZBlock(xyz_block)

        if mol is None:
            logging.error(f"Failed to read/parse XYZ file: {xyz_path}. Check the format.")  # Log the error with the filename
            raise RuntimeError(f"Failed to read/parse XYZ file: {xyz_path}")

        smiles_str = Chem.MolToSmiles(mol)
        logging.info(f"SMILES generated: {smiles_str}")  # Log the generated SMILES

        return smiles_str

    except FileNotFoundError:
        logging.error(f"File not found: {xyz_path}") # Log the file not found error
        raise RuntimeError(f"File not found: {xyz_path}")
    except Exception as e:
        logging.exception(f"Conversion XYZ to SMILES failed: {e}")  # Use logging.exception for full traceback
        raise RuntimeError(f"Conversion XYZ to SMILES failed: {e}")