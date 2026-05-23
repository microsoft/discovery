"""
Molecule functional group definitions.
This module provides a list of common functional groups with their SMARTS patterns.
It can process multiple SMILES strings from input files and identify functional groups in each molecule.
"""

import os
import sys
import json
import glob
from pathlib import Path

FUNCTIONAL_GROUPS = [
    # Carboxylic derivatives & carbonyls
    {"name": "Carboxylic Acid",      "smarts": "[CX3](=O)[OX2H]",               "priority": 120, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Acid Anhydride",       "smarts": "[CX3](=O)O[CX3](=O)[#6]",       "priority": 119, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Ester",                "smarts": "[CX3](=O)[OX2][#6]",            "priority": 118, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Acid Halide",          "smarts": "[CX3](=O)[F,Cl,Br,I]",          "priority": 117, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Carboxylate (anion)",  "smarts": "[CX3](=O)[O-]",                 "priority": 116, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Imide",                "smarts": "[#6C](=O)N-C(=O)",              "priority": 115, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Thioester",            "smarts": "[CX3](=O)[SX2][#6]",            "priority": 114, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Amide",                "smarts": "[CX3](=O)[NX3]",                "priority": 113, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Urea / Carbamide",     "smarts": "[NX3][CX3](=O)[NX3]",           "priority": 112, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Carbamate",            "smarts": "[NX3][CX3](=O)[OX2]",           "priority": 111, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Thioamide",            "smarts": "[NX3][CX3]=[SX1]",              "priority": 110, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Aldehyde",             "smarts": "[CX3H1](=O)",                   "priority": 109, "category": "Carboxylic derivatives & carbonyls"},
    {"name": "Ketone",               "smarts": "[#6][CX3](=O)[#6]",             "priority": 108, "category": "Carboxylic derivatives & carbonyls"},

    # Oxygen-containing
    {"name": "Alcohol",              "smarts": "[#6][OX2H]",                    "priority": 107, "category": "Oxygen-containing"},
    {"name": "Phenol",               "smarts": "c[OX2H]",                       "priority": 106, "category": "Oxygen-containing"},
    {"name": "Enol",                 "smarts": "[#6X3][OX2H]",                  "priority": 105, "category": "Oxygen-containing"},
    {"name": "Ether",                "smarts": "[#6][OX2][#6]",                 "priority": 104, "category": "Oxygen-containing"},
    {"name": "Epoxide",              "smarts": "[OX2r3]1[#6r3][#6r3]1",         "priority": 103, "category": "Oxygen-containing"},
    {"name": "Peroxide",             "smarts": "[OX2,OX1-][OX2,OX1-]",          "priority": 102, "category": "Oxygen-containing"},
    {"name": "Hydroperoxide",        "smarts": "[OX2H][OX2]",                   "priority": 101, "category": "Oxygen-containing"},

    # Nitrogen-containing
    {"name": "Nitrile",              "smarts": "[CX2]#N",                       "priority": 100, "category": "Nitrogen-containing"},
    {"name": "Isonitrile",           "smarts": "[NX2+]#[CX1-]",                 "priority":  99, "category": "Nitrogen-containing"},
    {"name": "Imine",                "smarts": "[CX3]=[NX2]",                   "priority":  98, "category": "Nitrogen-containing"},
    {"name": "Enamine",              "smarts": "[NX3][CX3]=[CX3]",              "priority":  97, "category": "Nitrogen-containing"},
    {"name": "Oxime",                "smarts": "[CX3](=NO)[#6]",                "priority":  96, "category": "Nitrogen-containing"},
    {"name": "Hydrazone",            "smarts": "[CX3]=NN",                      "priority":  95, "category": "Nitrogen-containing"},
    {"name": "Nitro",                "smarts": "[$([NX3](=O)=O),$([NX3+](=O)[O-])]", "priority":  94, "category": "Nitrogen-containing"},
    {"name": "Nitroso",              "smarts": "[NX2]=[OX1]",                   "priority":  93, "category": "Nitrogen-containing"},
    {"name": "Azide",                "smarts": "[$(*-[NX2-]-[NX2+]#[NX1]),$(*-[NX2]=[NX2+]=[NX1-])]", "priority":  92, "category": "Nitrogen-containing"},
    {"name": "Azo Compound",         "smarts": "[NX2]=[NX2]",                   "priority":  91, "category": "Nitrogen-containing"},
    {"name": "Diazonium",            "smarts": "[NX2+]#[NX1-]",                 "priority":  90, "category": "Nitrogen-containing"},
    {"name": "Isocyanate",           "smarts": "[NX2]=[CX2]=[OX1]",             "priority":  89, "category": "Nitrogen-containing"},
    {"name": "Isothiocyanate",       "smarts": "[NX2]=[CX2]=[SX1]",             "priority":  88, "category": "Nitrogen-containing"},
    {"name": "Quaternary Ammonium",  "smarts": "[NX4+]",                        "priority":  87, "category": "Nitrogen-containing"},
    {"name": "Amine",                "smarts": "[NX3;!$(NC=O)]",                "priority":  86, "category": "Nitrogen-containing"},
    {"name": "Aniline",              "smarts": "c[NX3]",                        "priority":  85, "category": "Nitrogen-containing"},
    {"name": "Nitrosoamine",         "smarts": "[NX3][NX2]=O",                  "priority":  84, "category": "Nitrogen-containing"},
    {"name": "N-oxide",              "smarts": "[NX3+](=O)[O-]",                "priority":  83, "category": "Nitrogen-containing"},

    # Sulfur-containing
    {"name": "Sulfonic Acid",        "smarts": "[SX3](=O)(=O)[OX2H]",           "priority":  82, "category": "Sulfur-containing"},
    {"name": "Sulfonate Ester",      "smarts": "[$([#16X4](=O)(=O)[OX2][#6]),$([#16X4+2](=O)(=O)[OX2][#6])]", "priority":  81, "category": "Sulfur-containing"},
    {"name": "Sulfonamide",          "smarts": "[$([#16X4](=O)(=O)[NX3][#6]),$([#16X4+2](=O)(=O)[NX3][#6])]", "priority":  80, "category": "Sulfur-containing"},
    {"name": "Sulfonyl Halide",      "smarts": "[SX4](=O)(=O)Cl",               "priority":  79, "category": "Sulfur-containing"},
    {"name": "Thiol",                "smarts": "[#6][SX2H]",                    "priority":  78, "category": "Sulfur-containing"},
    {"name": "Thioether",            "smarts": "[#6][SX2][#6]",                 "priority":  77, "category": "Sulfur-containing"},
    {"name": "Disulfide",            "smarts": "[#16X2H0][#16X2H0]",            "priority":  76, "category": "Sulfur-containing"},
    {"name": "Sulfoxide",            "smarts": "[$([#16X3]=O),$([#16X3+][O-])]", "priority":  75, "category": "Sulfur-containing"},
    {"name": "Sulfone",              "smarts": "[$([#16X4](=O)=O),$([#16X4+2]([O-])[O-])]", "priority":  74, "category": "Sulfur-containing"},

    # Phosphorus-containing
    {"name": "Organophosphate",      "smarts": "P(=O)(O)(O)O",                 "priority":  73, "category": "Phosphorus-containing"},
    {"name": "Phosphate Anhydride",  "smarts": "P(=O)(O)OP(=O)",               "priority":  72, "category": "Phosphorus-containing"},
    {"name": "Phosphate",            "smarts": "[OX2][PX4](=O)(O)(O)",          "priority":  71, "category": "Phosphorus-containing"},
    {"name": "Phosphonate",          "smarts": "[#6][PX4](=O)([O])[O][O]",      "priority":  70, "category": "Phosphorus-containing"},
    {"name": "Phosphine Oxide",      "smarts": "[PX3](=O)([#6])[#6]",           "priority":  69, "category": "Phosphorus-containing"},
    {"name": "Phosphine",            "smarts": "[PX3;!$(P=O)]",                "priority":  68, "category": "Phosphorus-containing"},

    # Boron-containing
    {"name": "Boronic Acid",         "smarts": "[#6][BX3]([OX2H])([OX2H])",    "priority":  67, "category": "Boron-containing"},
    {"name": "Boric Acid",           "smarts": "[BX3]([OX2H])([OX2H])[OX2H]",   "priority":  66, "category": "Boron-containing"},
    {"name": "Organoborane",         "smarts": "[BX3]([#6])([#6])[#6]",        "priority":  65, "category": "Boron-containing"},
    {"name": "Borane",               "smarts": "[#6][B]",                      "priority":  64, "category": "Boron-containing"},
    {"name": "Borohydride",          "smarts": "[BH4]",                        "priority":  63, "category": "Boron-containing"},
    {"name": "Tetracoordinate Borate", "smarts": "[BX4]",                      "priority":  62, "category": "Boron-containing"},

    # Silicon-containing
    {"name": "Organosilane",         "smarts": "[SiX4]([#6])([#6])([#6])[#6]",  "priority":  61, "category": "Silicon-containing"},
    {"name": "Silane",               "smarts": "[#6][Si]",                     "priority":  60, "category": "Silicon-containing"},
    {"name": "Silyl Ether",          "smarts": "[#6][OX2][Si]",                "priority":  59, "category": "Silicon-containing"},
    {"name": "Silyl Halide",         "smarts": "[SiX4]([#6])([#6])[#6][F,Cl,Br,I]", "priority":  58, "category": "Silicon-containing"},
    {"name": "Silanol",              "smarts": "[SiX4](O)([#6])([#6])[#6]",    "priority":  57, "category": "Silicon-containing"},
    {"name": "Siloxane",             "smarts": "[Si]-O-[Si]",                  "priority":  56, "category": "Silicon-containing"},

    # Selenium-containing
    {"name": "Selenoxide",           "smarts": "[#6][Se;X3](=O)[#6]",          "priority":  55, "category": "Selenium-containing"},
    {"name": "Selenide",             "smarts": "[#6][Se][#6]",                 "priority":  54, "category": "Selenium-containing"},

    # Hydrocarbon
    {"name": "Arene (Aromatic)",     "smarts": "c",                           "priority":  53, "category": "Hydrocarbon"},
    {"name": "Alkene (Olefin)",      "smarts": "[CX3]=[CX3]",                 "priority":  52, "category": "Hydrocarbon"},
    {"name": "Allene",               "smarts": "[CX3]=[CX2]=[CX3]",            "priority":  51, "category": "Hydrocarbon"},
    {"name": "Alkyne",               "smarts": "[CX2]#[CX2]",                 "priority":  50, "category": "Hydrocarbon"},
    {"name": "Alkane (Alkyl)",       "smarts": "[CX4]",                       "priority":  49, "category": "Hydrocarbon"},

    # Halogen-containing
    {"name": "Alkyl Halide",         "smarts": "[#6][F,Cl,Br,I]",             "priority":  48, "category": "Halogen-containing"},
    {"name": "Aryl Halide",          "smarts": "c[F,Cl,Br,I]",                "priority":  47, "category": "Halogen-containing"},
    {"name": "Vinylic Halide",       "smarts": "[#6]=[#6][F,Cl,Br,I]",         "priority":  46, "category": "Halogen-containing"},
    {"name": "Fluoride",             "smarts": "[F]",                         "priority":  45, "category": "Halogen-containing"},
    {"name": "Chloride",             "smarts": "[Cl]",                        "priority":  44, "category": "Halogen-containing"},
    {"name": "Bromide",              "smarts": "[Br]",                        "priority":  43, "category": "Halogen-containing"},
    {"name": "Iodide",               "smarts": "[I]",                         "priority":  42, "category": "Halogen-containing"}
]

def get_functional_groups_by_category():
    """
    Group functional groups by their category.
    
    Returns:
        dict: A dictionary with categories as keys and lists of functional groups as values
    """
    categories = {}
    for fg in FUNCTIONAL_GROUPS:
        category = fg["category"]
        if category not in categories:
            categories[category] = []
        categories[category].append(fg)
    return categories

def get_smarts_patterns():
    """
    Get a dictionary of SMARTS patterns for all functional groups.
    
    Returns:
        dict: A dictionary with functional group names as keys and SMARTS patterns as values
    """
    return {fg["name"]: fg["smarts"] for fg in FUNCTIONAL_GROUPS}

def identify_functional_groups(smiles, sort_by_priority=True):
    """
    Identify all functional groups in a molecule given its SMILES string.
    
    Args:
        smiles (str): SMILES representation of the molecule
        sort_by_priority (bool): Whether to sort the results by functional group priority
        
    Returns:
        list: Names of functional groups found in the molecule, sorted by priority if requested
        
    Raises:
        ImportError: If RDKit is not installed
    """
    try:
        from rdkit import Chem
    except ImportError:
        raise ImportError("RDKit is required for this function. Install it with: pip install rdkit")
    
    # Parse the molecule
    mol = Chem.MolFromSmiles(smiles)
    if not mol:
        return []
    
    # Compile SMARTS patterns if not already done
    compiled_patterns = {}
    for fg in FUNCTIONAL_GROUPS:
        name = fg["name"]
        smarts = fg["smarts"]
        try:
            pattern = Chem.MolFromSmarts(smarts)
            if pattern:
                compiled_patterns[name] = pattern
        except Exception:
            pass  # Skip patterns that can't be compiled
    
    # Find matches
    matches = []
    for name, pattern in compiled_patterns.items():
        if mol.HasSubstructMatch(pattern):
            matches.append(name)
    
    # Sort by priority if requested
    if sort_by_priority and matches:
        priority_dict = {fg["name"]: fg["priority"] for fg in FUNCTIONAL_GROUPS}
        matches.sort(key=lambda x: priority_dict.get(x, 0), reverse=True)
    
    return matches

