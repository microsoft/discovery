"""
Molecular structure safety checker.
This module provides a simple function to check if molecules match any safety-related functional groups.
It can process multiple SMILES strings from input files and identify hazardous groups in each molecule.
"""

import os
import sys
import json
import glob
from pathlib import Path

FG_SAFETY_FILTERS = {
    "us_pfas_groups": {
        "us_1": "[#6](-[#6]-[F])(-[F])-[F]",
        "us_2": "[#6](-[F])(-[F])-[#8]-[#6](-[F])-[F]",
        "us_3": "[#6](-[#6]-[#6](-[F])(-[F])-[F])-[F]"
    },

    "cwc_groups": {
        "cwc_1A1": "O[P](F)=O",
        "cwc_1A2": "O[P](=O)(C#N)N",
        "cwc_1A3": "O[P](=O)SCCN",
        "cwc_1A4-1": "C(CCl)SCCl",
        "cwc_1A4-2": "ClCCSCCCl",
        "cwc_1A4-3": "ClCCSCSCCCl",
        "cwc_1A4-4": "ClCCSCCSCCCl",
        "cwc_1A4-5": "ClCCSCCCSCCCl",
        "cwc_1A4-6": "ClCCSCCCCSCCCl",
        "cwc_1A4-7": "ClCCSCCCCCSCCCl",
        "cwc_1A4-8": "ClCCSCOCSCCCl",
        "cwc_1A4-9": "ClCCSCCOCCSCCCl",
        "cwc_1A5-1": "C(=C[As](Cl)Cl)Cl",
        "cwc_1A5-2": "ClC=C[As](Cl)C=CCl",
        "cwc_1A5-3": "ClC=C[As](C=CCl)C=CCl",
        "cwc_1A6-1": "CCN(CCCl)CCCl",
        "cwc_1A6-2": "CN(CCCl)CCCl",
        "cwc_1A6-3": "C(CCl)N(CCCl)CCCl",
        "cwc_1A7": "NC(=O)OC[C@@H]1NC(=N)N2CCC(O)(O)[C@@]22N=C(N)N[C@@H]12",
        "cwc_1A13": "P(F)(=O)N=CN",
        "cwc_1A14": "P(F)(=O)(O)N=CN",
        "cwc_1A15": "CCN(CC)C(=N[P](C)(F)=O)N(CC)CC",
        "cwc_1B9": "P(F)(=O)F",
        "cwc_1B10": "OPOCCN",
        "cwc_1B11": "CC(C)O[P](C)(Cl)=O",
        "cwc_1B12": "CC(O[P](C)(Cl)=O)C(C)(C)C",
        "cwc_2A1": "CCO[P](=O)(OCC)SCCN(CC)CC",
        "cwc_2A2": "FC(F)=C(C(F)(F)F)C(F)(F)F",
        "cwc_2A3": "OC(C(=O)OC1CN2CCC1CC2)(c3ccccc3)c4ccccc4",
        "cwc_2B4": "P(C)",
        "cwc_2B5": "P(=O)N",
        "cwc_2B6": "[P](N)(=O)(O)O",
        "cwc_2B7": "Cl[As](Cl)Cl",
        "cwc_2B8": "OC(=O)C(O)(c1ccccc1)c2ccccc2",
        "cwc_2B9": "OC1CN2CCC1CC2",
        "cwc_2B10": "NCCCl",
        "cwc_2B11": "NCCO[H]",
        "cwc_2B12": "NCCS[H]",
        "cwc_2B13": "OCCSCCO",
        "cwc_2B14": "CC(O)C(C)(C)C",
        "cwc_3A1": "ClC(Cl)=O",
        "cwc_3A2": "ClC#N",
        "cwc_3A3": "C#N",
        "cwc_3A4": "[O-][N+](=O)C(Cl)(Cl)Cl",
        "cwc_3B5": "Cl[P](Cl)(Cl)=O",
        "cwc_3B6": "ClP(Cl)Cl",
        "cwc_3B7": "Cl[P](Cl)(Cl)(Cl)Cl",
        "cwc_3B8": "COP(OC)OC",
        "cwc_3B9": "CCOP(OCC)OCC",
        "cwc_3B10": "[H]P(=O)(OC)OC",
        "cwc_3B11": "[H]P(=O)(OCC)OCC",
        "cwc_3B12": "ClSSCl",
        "cwc_3B13": "ClSCl",
        "cwc_3B14": "Cl[S](Cl)=O",
        "cwc_3B15": "CCN(CCO)CCO",
        "cwc_3B16": "CN(CCO)CCO",
        "cwc_3B17": "OCCN(CCO)CCO"
    },

    "explosive_groups": {
        "acetylene": "C#C",
        "azetidine": "[#6]-1-[#6]-[#7]-[#6]-1",
        "azide_1": "[N;H0;$(N-[#6]);D2]=[N;D2]=[N;D1]",
        "azide_2": "[NX1]#[NX2+]-[NX1-2]",
        "azide_3": "[NX1-]=[NX2+]=[NX1-]",
        "azide_4": "[NX2]=[NX2+]=[NX1-]",
        "azide_5": "[NX2-]-[NX2+]#[NX1]",
        "azide_ali": "[N;H0;$(N-C);D2]=[N;D2]=[N;D1]",
        "azide_aro": "[N;H0;$(N-c);D2]=[N;D2]=[N;D1]",
        "cyano": "[#6]#[#7]",
        "diazo": "[#7]#[#7]-[#6]",
        "epoxides": "[#6]-1-[#6]-[#8]-1",
        "nitrate_1": "[NX3](=[OX1])(=[OX1])O",
        "nitrate_2": "[NX3+]([OX1-])(=[OX1])O",
        "nitro_1": "[N;H0;$(N-[#6]);D3](=[O;D1])~[O;D1]",
        "nitro_2": "[NX3](=O)=O",
        "nitro_3": "[NX3+](=O)[O-]",
        "nitro_ali": "[N;H0;$(N-C);D3](=[O;D1])~[O;D1]",
        "nitro_aro": "[N;H0;$(N-c);D3](=[O;D1])~[O;D1]",
        "peroxide_1": "[#8]-[#8]",
        "peroxide_2": "[#8-]-[#8]",
        "peroxyacids": "[#8](-[#8]-[#1])-[#6]=[#8]",
        "peroxyesters": "[#8](-[#8])-[#6]=[#8]",
        "anion": "[-]",
        "cation": "[+]",
        "small_rings": "[r3,r4]"
    },

    "self_reactive_groups": {
        "aminonitriles": "C(C#N)N",
        "phosphites": "[P](=O)(O)(O)C",
        "epoxides": "C1CO1",
        "aziridines": "C1CN1",
        "cyanates": "C(#N)O",
        "haloaniline_Cl_0": "c1c(Cl)cc(N)cc1",
        "haloaniline_Cl_1": "c1cc(Cl)c(N)cc1",
        "haloaniline_Cl_2": "c1(Cl)ccc(N)cc1",
        "haloaniline_F_0": "c1c(F)cc(N)cc1",
        "haloaniline_F_1": "c1cc(F)c(N)cc1",
        "haloaniline_F_2": "c1(F)ccc(N)cc1",
        "haloaniline_Br_0": "c1c(Br)cc(N)cc1",
        "haloaniline_Br_1": "c1cc(Br)c(N)cc1",
        "haloaniline_Br_2": "c1(Br)ccc(N)cc1",
        "haloaniline_I_0": "c1c(I)cc(N)cc1",
        "haloaniline_I_1": "c1cc(I)c(N)cc1",
        "haloaniline_I_2": "c1(I)ccc(N)cc1",
        "sulfonyl_Cl": "[S](=O)(=O)Cl",
        "sulfonyl_F": "[S](=O)(=O)F",
        "sulfonyl_Br": "[S](=O)(=O)Br",
        "sulfonyl_I": "[S](=O)(=O)I",
        "sulfonyl_CN": "[S](=O)(=O)C#N",
        "sulfonyl_NN": "[S](=O)(=O)NN"
    },

    "autorxn_reactive_groups": {
        "SiH3": "[SiH3]",
        "C2Si=O": "[C]-[Si](-[C])=[O]",
        "CB=O": "[C]-[B]=[O]",
        "RSF3": "[*]-[SX4](-[F])(-[F])-[F]",
        "Cl-Cl": "[Cl]-[Cl]",
        "F-F": "[F]-[F]",
        "F-Cl": "[F]-[Cl]",
        "(C)3SH": "[C]-[SX4H](-[C])-[C]",
        "C2C=PC": "[C]-[C](-[C])=[P]-[C]",
        "CB=SiC2": "[C]-[B]=[Si](-[C])-[C]",
        "CB=PC": "[C]-[B]=[PX2]-[C]",
        "CB=S": "[C]-[B]=[SX]",
        "CN=SiC2": "[C]-[N]=[Si](-[C])-[C]",
        "CN=S": "[C]-[N]=[SX]",
        "C2Si=SiC2": "[C]-[Si]([-C])=[Si](-[C])-[C]",
        "C2Si=PC": "[C]-[Si]([-C])=[P]-[C]",
        "C2Si=S": "[C]-[Si]([-C])=[SX]",
        "CP=PC": "[C]-[PX2]=[PX2]-[C]",
        "CP=S": "[C]-[PX2]=[SX]",
        "C2C=BC": "[C]-[C](-[C])=[B]-[C]",
        "C2C=SiC2": "[C]-[C](-[C])=[Si](-[C])-[C]",
        "CB=BC": "[C]-[B]=[B]-[C]",
        "CSF": "[#6]-[SX2]-[F]",
        "RC#PR2": "[*]-[C]#[PX3](-[*])-[*]",
        "C=S=C": "[C]=[SX2]=[C]"
    },
    
    "pnnl_hazardous_groups": {
        "PF4": "[P](-[F])(-[F])(-[F])-[F]",
        "SC2Cl": "[#16]-[#6]-[#6]-[Cl]",
        "N(C)2C2Cl": "[#6](-[#7](-[#6])-[#6])-[#6]-[Cl]",
        "PO2F": "[P](-[F])(=[#8])-[#8]",
        "PONF": "[P](-[F])(=[#8])-[#7]",
        "PO2S": "[P](=[#8])(-[#8])-[#16]",
        "B-H": "[B]-[H]",
        "BH1": "[BH1]",
        "BH2": "[BH2]",
        "BH3": "[BH3]",
        "P-H": "[P]-[H]",
        "O-F": "[O]-[F]",
        "O-Cl": "[O]-[Cl]",
        "O-O": "[O]-[Cl]",
        "N-N": "[N]-[N]",
        "N=N": "[N]=[N]",
        "S=S": "[S]=[S]",
        "C=Si": "[C]=[Si]"
    },

    "pnnl_air_water_sensitive_groups": {
        "B-B": "[B]-[B]",
        "B-Cl": "[B]-[Cl]",
        "C=B": "[C]=[B]",
        "B=B": "[B]=[B]",
        "B=N": "[B]=[N]",
        "B=Si": "[B]=[Si]",
        "B=P": "[B]=[P]",
        "RN=O": "[*]-[N]=[O]"
    },

    "pnnl_flourinated_reactive_groups": {
        "P-F": "[P]-[F]",
        "Si-F": "[Si]-[F]",
        "S-F": "[S]-[F]",
        "B-F": "[B]-[F]"
    },

    "pnnl_fg_dependent_reactive_groups": {
        "*=*=*": "[*]=[*]=[*]",
        "N=P": "[N]=[P]",
        "N=Si": "[N]=[Si]",
        "Si=P": "[Si]=[P]"
    },

    "richman_reactive_groups": {
        "N(F)(F)C=NF": "N(F)(F)C=NF",
        "NF": "NF",
        "C=N": "C=N"
    },
    
    "cf3_pfas_groups": {
        "CF3": "[C](F)(F)F",
        "aromatic CF3": "[c](F)(F)F"
    },

    "cf2_pfas_groups": {
        "CF2": "[C](F)F",
        "aromatic CF2": "[c](F)F"
    },

    "triple_bond_groups": {
        "triple_bond": "*#*"
    }
}


from rdkit import Chem

# Cache for compiled SMARTS patterns
_compiled_smarts_cache = {}

def _compile_smarts_patterns():
    """Compile all SMARTS patterns from FG_SAFETY_FILTERS."""
    compiled_smarts = {}
    
    # Process each category of functional groups
    for category, patterns in FG_SAFETY_FILTERS.items():
        for name, smarts in patterns.items():
            # Create a unique key for each pattern that includes both category and name
            key = f"{category}.{name}"
            try:
                # Compile the SMARTS pattern
                compiled_pattern = Chem.MolFromSmarts(smarts)
                if compiled_pattern:
                    compiled_smarts[key] = compiled_pattern
                else:
                    print(f"Warning: Could not compile SMARTS pattern for {key}: {smarts}")
            except Exception as e:
                print(f"Error compiling SMARTS pattern for {key}: {smarts}. Error: {e}")
    
    return compiled_smarts

def get_compiled_smarts():
    """Get or create the dictionary of compiled SMARTS patterns."""
    global _compiled_smarts_cache
    if not _compiled_smarts_cache:
        _compiled_smarts_cache = _compile_smarts_patterns()
    return _compiled_smarts_cache

def identify_hazardous_groups(smiles):
    """
    Check if a molecule matches any safety-related functional groups.
    
    Args:
        smiles (str): SMILES string of the molecule
    
    Returns:
        list: List of matched functional groups (empty if no matches)
    """
    mol = Chem.MolFromSmiles(smiles)
    if not mol:
        return []
    
    compiled_smarts = get_compiled_smarts()
    matches = []
    
    for key, pattern in compiled_smarts.items():
        if mol.HasSubstructMatch(pattern):
            matches.append(key)
    
    return matches

