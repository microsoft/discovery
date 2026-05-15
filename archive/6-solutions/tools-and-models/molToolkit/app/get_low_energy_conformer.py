import os
import sys
import json
import glob
from pathlib import Path
from rdkit.Chem import rdDistGeom
from rdkit.Chem import AllChem
from rdkit import Chem

def read_smiles_from_file(file_path):
    """Read SMILES strings from a file, supporting .smi, .txt, and .csv formats."""
    smiles_list = []
    try:
        with open(file_path, 'r') as f:
            if file_path.endswith('.csv'):
                import csv
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0].strip():
                        smiles_list.append(row[0].strip())
            else:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        smiles_list.append(line.split()[0])
    except Exception as e:
        print(f"Error reading SMILES file {file_path}: {e}")
    return smiles_list

def find_smiles_files(directory):
    """Find all SMILES files in a directory."""
    extensions = ['*.smi', '*.txt', '*.csv']
    smiles_files = []
    for ext in extensions:
        smiles_files.extend(glob.glob(os.path.join(directory, ext)))
    return smiles_files

def write_results_to_json(results, output_file):
    """Write results to a JSON file."""
    try:
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Results written to {output_file}")
    except Exception as e:
        print(f"Error writing results to {output_file}: {e}")

def validate_atom_distances(mol):
    """
    Returns a boolean for whether a molecule has valid chemical properties and a sensible geometry,
    primarily using RDKit's SanitizeMol.
    Parameters:
        mol (RDKit mol): the RDKit mol of the molecule, expected to have a conformer.
    Returns:
        status (bool): True if the molecule is considered valid, False otherwise.
    """
    try:
        # RDKit's SanitizeMol performs a range of checks for chemical sensibility
        # (e.g., valency, aromaticity) which implicitly depend on reasonable geometry.
        # Using catchErrors=True to get a status code instead of an exception on sanitization failure.
        sanitize_outcome = Chem.SanitizeMol(mol, catchErrors=True)
        
        if sanitize_outcome == Chem.SanitizeFlags.SANITIZE_NONE:
            # Molecule sanitized successfully, considered valid.
            return True
        else:
            # Sanitization failed, molecule is considered invalid.
            print(f"TRACE: RDKit SanitizeMol validation failed. Status code: {sanitize_outcome}")
            print(f"TRACE: Exiting validate_atom_distances with status=False")
            return False
            
    except Exception as e:
        # Catch any other unexpected errors during the process.
        print(f"TRACE: Exception in validate_atom_distances: {str(e)}")
        print(f"TRACE: Exiting validate_atom_distances with status=False")
        return False

def filter_conformers(mol, output_list):
    """
    Returns a list of filtered optimized 3D conformers with valid geometries
    Parameters:
        mol (RDKit mol): the RDKit mol of the molecule
        output_list (list): a list of tuples containing the convergence status of that conformer and its energy
    Returns:
        filtered_output_list (list): a list of tuples containing information of each valid conformer
    """
    print(f"TRACE: Entering filter_conformers with {len(output_list)} conformers")
    filtered_output_list = []
    for idx, current_tuple in enumerate(output_list):
        temp_mol = Chem.Mol(mol, confId=idx)
        if validate_atom_distances(temp_mol):
            filtered_output_list.append((idx, temp_mol, current_tuple[0], current_tuple[1]))
    print(f"TRACE: Exiting filter_conformers with {len(filtered_output_list)} valid conformers")
    return filtered_output_list

def get_conformers_from_mol(mol, maxIters=1, numConfs=10, UFF_status=False):
    """
    Generate multiple optimized 3D conformers and return them as Conformer objects.
    This function is designed to work seamlessly with mol.AddConformer().
    
    Parameters:
        mol (RDKit mol): the RDKit mol of the molecule (will be hydrogenated internally)
        maxIters (int): the number of iterations to run the force-field optimization for
        numConfs (int): the number of conformers to be generated (default: 10)
        UFF_status (bool): whether to run UFF forcefield optimization or not
    
    Returns:
        list: List of RDKit Conformer objects that can be added to a molecule
    
    Example:
        mol = Chem.MolFromSmiles('CCO')
        conformers = get_conformers_from_mol(mol, numConfs=5)
        for conf in conformers:
            mol.AddConformer(conf, assignId=True)
    """
    print(f"TRACE: Entering get_conformers_from_mol with maxIters={maxIters}, numConfs={numConfs}, UFF_status={UFF_status}")
    
    # Generate conformers using the existing function
    filtered_output_list = generate_multiple_conformers(mol, maxIters=maxIters, numConfs=numConfs, UFF_status=UFF_status)
    
    # Extract the conformer objects from the filtered list
    # filtered_output_list contains tuples: (idx, temp_mol, convergence_status, energy)
    conformers = []
    for conf_tuple in filtered_output_list:
        temp_mol = conf_tuple[1]  # Extract the molecule with conformer
        # Get the conformer from the molecule
        conf = temp_mol.GetConformer()
        conformers.append(conf)
    
    print(f"TRACE: Exiting get_conformers_from_mol with {len(conformers)} conformer objects")
    return conformers

def generate_multiple_conformers(mol, maxIters=1, numConfs=1000, UFF_status=False):
    """
    Returns a list of optimized 3D conformers
    Parameters:
        mol (RDKit mol): the RDKit mol of the molecule
        max_iters (int): the number of iterations to run the force-field optimization for
        numConfs (int): the number of conformers to be generated
        UFF_status (bool): whether to run UFF forcefield optimization or not
    Returns:
        filtered_output_list (list): a list of tuples containing information of each valid conformer
    """
    print(f"TRACE: Entering generate_multiple_conformers with maxIters={maxIters}, numConfs={numConfs}, UFF_status={UFF_status}")
    params = rdDistGeom.ETKDGv3()
    params.numThreads = 0
    params.useRandomCoords = True

    new_mol = Chem.AddHs(mol)
    print(f"TRACE: Starting to embed {numConfs} conformers")
    AllChem.EmbedMultipleConfs(new_mol, numConfs=numConfs, params=params)
    if UFF_status:
        print(f"TRACE: Using UFF optimization")
        try:
            output_list = AllChem.UFFOptimizeMoleculeConfs(new_mol, numThreads=0, maxIters=maxIters)
        except Exception as e:
            print(f"WARNING: UFF optimization failed: {str(e)}")
            print(f"TRACE: Falling back to MMFF optimization")
            try:
                output_list = AllChem.MMFFOptimizeMoleculeConfs(new_mol, numThreads=0, maxIters=maxIters)
            except Exception as mmff_e:
                print(f"WARNING: MMFF fallback optimization also failed: {str(mmff_e)}")
                print(f"TRACE: Proceeding with unoptimized conformers")
                output_list = [(0, 0.0)] * numConfs  # Default to no optimization status
    else:
        print(f"TRACE: Using MMFF optimization")
        try:
            output_list = AllChem.MMFFOptimizeMoleculeConfs(new_mol, numThreads=0, maxIters=maxIters)
        except Exception as e:
            print(f"WARNING: MMFF optimization failed: {str(e)}")
            print(f"TRACE: Falling back to UFF optimization")
            try:
                output_list = AllChem.UFFOptimizeMoleculeConfs(new_mol, numThreads=0, maxIters=maxIters)
            except Exception as uff_e:
                print(f"WARNING: UFF fallback optimization also failed: {str(uff_e)}")
                print(f"TRACE: Proceeding with unoptimized conformers")
                output_list = [(0, 0.0)] * numConfs  # Default to no optimization status
    filtered_output_list = filter_conformers(new_mol, output_list)
    
    print(f"TRACE: Exiting generate_multiple_conformers with {len(filtered_output_list)} filtered conformers")
    return filtered_output_list

def get_low_energy_conformer(smiles):
    """
    Returns an optimized 3D conformer, chosen by the lowest energy from a list of multiple possible optimized conformers
    Parameters:
        smiles (str): SMILES string of the molecule
    Returns:
        tuple: (RDKit mol object with optimized 3D conformer, XYZ string representation)
    """
    print(f"TRACE: Entering get_low_energy_conformer for thorough optimization")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES string: {smiles}")
        
    UFF_status = check_UFF_status(mol)
    
    print(f"TRACE: Performing standard optimization (10000 conformers, 1000 iterations)")
    filtered_output_list = generate_multiple_conformers(mol, maxIters=1000, numConfs=10000, UFF_status=UFF_status)
    
    # Only do additional conformers if we don't have enough good ones
    if len(filtered_output_list) < 700:
        print(f"TRACE: Not enough good conformers, generating additional (10000 conformers, 1 iteration)")
        additional_list = generate_multiple_conformers(mol, maxIters=1, numConfs=10000, UFF_status=UFF_status)
        filtered_output_list.extend(additional_list)
    
    # Print the top 10 conformers with the lowest energy
    print(f"TRACE: Top 10 conformers with the lowest energy:")
    sorted_conformers = sorted(filtered_output_list, key=lambda x: x[3])[:10]
    for i, conf in enumerate(sorted_conformers):
        print(f"Conformer {i}: Energy = {conf[3]} kcal/mol")

    print(f"TRACE: Finding minimum energy conformer from {len(filtered_output_list)} candidates")
    min_tuple = min(filtered_output_list, key=lambda x: x[3])
    new_mol = min_tuple[1]
    print(f"TRACE: Selected conformer with energy: {min_tuple[-1]}")

    # Generate the XYZ string for the optimized molecule
    xyz_string = mol_to_xyz_string(new_mol)
    
    return new_mol, xyz_string

def check_UFF_status(mol):
    """
    Returns a boolean for whether a molecule should use UFF optimization or not
    Parameters:
        mol (RDKit mol): the RDKit mol of the molecule
    Returns:
        status (bool): a boolean for whether a molecule should use UFF optimization
    """
    print(f"TRACE: Entering check_UFF_status")
    # Add hydrogens but don't embed - just check if MMFF is available for this molecule
    mol_with_h = Chem.AddHs(mol)
    mmff_props = AllChem.MMFFGetMoleculeProperties(mol_with_h)
    status = mmff_props is None
    print(f"TRACE: Exiting check_UFF_status with status={status} - {'Using UFF' if status else 'Using MMFF'}")
    return status

def mol_to_xyz_string(mol):
    """
    Converts an RDKit molecule to XYZ string format
    Parameters:
        mol (RDKit mol): the RDKit mol of the molecule
    Returns:
        xyz_string (str): the XYZ format string representation
    """
    print(f"TRACE: Entering mol_to_xyz_string")
    conf = mol.GetConformer()
    atoms = [atom.GetSymbol() for atom in mol.GetAtoms()]
    xyz_string = f"{mol.GetNumAtoms()}\n\n"
    
    for i, atom in enumerate(atoms):
        pos = conf.GetAtomPosition(i)
        xyz_string += f"{atom} {pos.x:.6f} {pos.y:.6f} {pos.z:.6f}\n"
    
    print(f"TRACE: Exiting mol_to_xyz_string")
    return xyz_string
