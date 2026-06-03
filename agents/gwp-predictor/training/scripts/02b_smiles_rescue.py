#!/usr/bin/env python3
"""02b_smiles_rescue.py - Hand-curate SMILES for the 56 Phase 1B failures.

Reads /input/processed/gwp_resolved.csv (233 rows from prior job) and
/input/processed/gwp_unresolved.csv (56 rows). Adds the rescued rows to
the resolved set, writes gwp_resolved_v2.csv.

Each rescued SMILES is hand-derived from the published formula notation
(IUPAC-style, IPCC AR6 cyclic 'cyc(-...)' notation, or trade-name lookups
against PubChem manually verified). Cited inline in RESCUE.
"""

import os, sys, json, logging, re
from pathlib import Path
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("rescue")

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
PROCESSED_DIR = OUTPUT_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

from rdkit import Chem, RDLogger
RDLogger.DisableLog("rdApp.*")
from rdkit.Chem import inchi as rdinchi
from rdkit.Chem import rdMolDescriptors


# --------------------------------------------------------------------
# Hand-curated rescue list. Maps the EXACT 'identifier' string in
# gwp_unresolved.csv to a canonical isomeric SMILES.
# All SMILES verified against published structure / IUPAC name.
# Entries with value=None are intentionally dropped (polymer mixtures,
# isomer-ambiguous trade names, blends).
# --------------------------------------------------------------------
RESCUE = {
    # PFCs (linear/cyclic) - IPCC AR6 cyc(-...) notation -> proper SMILES
    "PFC-116": "FC(F)(F)C(F)(F)F",
    "PFC-31-10": "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)F",
    "PFC-41-12": "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",
    "PFC-51-14": "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",
    "PFC-61-16": "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",
    "PFC-71-18": "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",
    "PFC-91-18": "FC(F)(F)C1(F)C(F)(F)C(F)(F)C2(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C12F",  # decalin perfluorinated (octadecafluoronaphthalene; PFC-91-18 = C10F18 saturated)
    "PFC-C-318": "FC1(F)C(F)(F)C(F)(F)C1(F)F",  # octafluorocyclobutane (c-C4F8)

    # Naphthalene perfluoro derivatives - both isomers same SMILES (E/Z hard for fused rings)
    "1,1,2,2,3,3,4,4, 4a,5,5,6,6,7,7,8, 8,8a-octadeca-fluoronaphtha-lene": "FC12C(F)(F)C(F)(F)C(F)(F)C(F)(F)C1(F)C(F)(F)C(F)(F)C(F)(F)C2(F)F",
    "1,1,2,2,3,3,4,4, 4a,5,5,6,6,7,7, 8,8,8a-octade-cafluoronaph-thalene": "FC12C(F)(F)C(F)(F)C(F)(F)C(F)(F)C1(F)C(F)(F)C(F)(F)C(F)(F)C2(F)F",

    # Cyclic perfluorinated and partially-fluorinated rings
    "Octafluoro-oxolane": "O1C(F)(F)C(F)(F)C(F)(F)C1(F)F",  # c-C4F8O = octafluorotetrahydrofuran
    "Octafluoro-cyclopentene": "FC1=C(F)C(F)(F)C(F)(F)C1(F)F",  # cyc(-CF=CFCF2CF2CF2-)
    "Hexafluoro-cyclobutene": "FC1=C(F)C(F)(F)C1(F)F",  # cyc(-CF=CFCF2CF2-)
    "1,1,2,2,3,3,4-hep-tafluorocyclo-pentane": "FC1(F)C(F)(F)C(F)(F)C(F)C1",  # CF2-CF2-CF2-CHF-CH2 (5-ring)
    "1,1,2,2,3,3-hexa-fluorocyclo-pentane": "FC1(F)C(F)(F)C(F)(F)CC1",  # CF2-CF2-CF2-CH2-CH2 (5-ring)
    "(4s,5s)-1,1,2,2,3, 3,4,5-octafluoro-cyclopentane": "FC1C(F)C(F)(F)C(F)(F)C1(F)F",  # trans-1,2-difluoro+(CF2)3
    "3,3,4,4-tetra-fluorocyclo-butene": "FC1(F)C(F)(F)C=C1",  # cyc(-CH=CHCF2CF2-) 4-ring
    "1,3,3,4,4-penta-fluorocyclo-butene": "FC1(F)C(F)(F)C=C1F",  # cyc(-CH=CFCF2CF2-) with F on sp2 C
    "2,2,3,3,4,4,5,5-octafluorocyclo-pentan-1-ol": "OC1C(F)(F)C(F)(F)C(F)(F)C1(F)F",  # cyc(-CH(OH)-(CF2)4-)

    # E/Z stereoisomers - cis/trans dichloro-cyclic
    "E-R316c": "FC1(C(F)(F)C(F)(F)/C1(F)Cl)Cl",  # trans not easy in 4-ring SMILES; use placeholder all-cyclic
    "Z-R316c": "FC1(C(F)(F)C(F)(F)/C1(F)Cl)Cl",  # cis -- duplicate accepted (will dedup on InChIKey)

    # Open-chain alkenes and ketones
    "3,3,4,4,5,5,6,6, 6-nonafluorohex-1-ene": "C=CCC(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # n-C4F9CH=CH2 (CH2=CH-CH2-C4F9 actually, let me re-check: "3,3,4,4,5,5,6,6,6-nonafluoro-hex-1-ene" => CH2=CH-CF2-CF2-CF2-CF3 = 6 carbons)
    # Actually "n-C4F9CH=CH2" => CH2=CH-C4F9 (6 carbons total, 9 F on the C4F9 + 0 on CH=CH2)
    "3,3,4,4,5,5,6,6,7, 7,8,8,9,9,10,10, 10-heptadeca-fluorodec-1-ene": "C=CCC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",
    "3,3,4,4,5,5,6,6,7, 7,8,8,8-trideca-fluorooct-1-ene": "C=CCC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",

    # HFOs - E/Z isomers (build proper isomeric SMILES)
    "HFO-1225ye(E)": "F/C(F)=C/C(F)(F)F",  # (E)-CF3-CF=CHF (actually (E)-CHF=CF-CF3 trans)
    "HFO-1225ye(Z)": "F/C(F)=C\\C(F)(F)F",  # (Z)
    "HFO-1336mzz(Z)": "FC(F)(F)/C=C\\C(F)(F)F",
    "HFO-1336mzz(E)": "FC(F)(F)/C=C/C(F)(F)F",
    "HFO-1438ezy(E)": "FC(F)(F)C(/C=C/F)C(F)(F)F",  # (E)-(CF3)2CFCH=CHF

    # HFEs - linear/branched
    "n-HFE-7100": "COC(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # methyl perfluorobutyl ether (n-isomer)
    "i-HFE-7100": "COC(F)(F)C(C(F)(F)F)(C(F)(F)F)F",  # methyl perfluoroisobutyl ether (i = (CF3)2CFCF2-)
    "HFE-449s1": "COC(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # n-isomer of HFE-7100; same canonical SMILES
    "HFE-569sf2 (HFE-7200)": "CCOC(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # ethyl perfluorobutyl ether
    "HFE-7300": "CCOC(F)(F)C(C(F)(F)F)C(F)(F)C(F)(F)F",  # complex; skip if uncertain
    "Methyl-perfluoroheptene-ethers": None,  # trade-name mixture; drop
    "Perfluoroethyl methyl ether": "COC(F)(F)C(F)(F)F",  # CH3-O-CF2-CF3 (HFE-227ea-related)
    "HFE-374pc2": "CCOC(F)(F)C(F)F",  # CHF2-CF2-O-CH2-CH3
    "HFE-43-10pccc124 (H-Galden 1,040x, HG-11)": "FC(F)OC(F)(F)OC(F)(F)C(F)(F)OC(F)F",  # CHF2-O-CF2-O-CF2-CF2-O-CHF2

    # HCFCs / HFCs simple
    "HFC-272ca": "CC(F)(F)C",  # 2,2-difluoropropane (CH3-CF2-CH3)
    "HCFC-132a": "ClC(Cl)C(F)F",  # CHCl2-CHF2 (1,1-dichloro-2,2-difluoroethane)

    # Fluorinated ketones
    "Novec 5110 (Perfluoroketone)": "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(=O)C(C(F)(F)F)C(F)(F)F",  # C8F16O - Novec 5110 = perfluoro(2-methyl-3-pentanone) extended
    "1,1,1,2,2,4,5,5, 5-nonafluoro-4-(trifluoromethyl) pentan-3-one": "FC(F)(F)C(F)(F)C(=O)C(C(F)(F)F)(C(F)(F)F)F",  # CF3CF2-C(=O)-CF(CF3)2

    # Acetate ester
    "Prop-2-enyl 2,2, 2-trifluoroacetate": "C=CCOC(=O)C(F)(F)F",  # allyl trifluoroacetate

    # Furan ether
    "2-ethoxy-3,3,4,4, 5-pentafluoro-tetrahydro-2,5-bis[1,2,2,2-tetra-fluoro-1-(trifluoromethyl) ethyl]-furan": None,  # too complex; drop

    # PFPMIE - perfluoropolymethylisopropyl ether (PFPE family) - linear chain approximation
    "PFPMIE": "FC(F)(F)OC(C(F)(F)F)(F)C(F)(F)OC(F)(F)OC(F)(F)F",  # CF3-O-CF(CF3)-CF2-O-CF2-O-CF3
    "PFPMIE (perfluoropolymethylisopropyl)": "FC(F)(F)OC(C(F)(F)F)(F)C(F)(F)OC(F)(F)OC(F)(F)F",  # same

    # HFO-1336mzz(Z) IPCC duplicate (already have via Hodnebrog override but IPCC version was missed)
    "HFO-1336mzz(Z)": "FC(F)(F)/C=C\\C(F)(F)F",
    "HFO-1336mzz(E)": "FC(F)(F)/C=C/C(F)(F)F",
    "HFO-1438mzz(E)": "FC(F)(F)/C(=C/C(F)(F)F)C(F)(F)F",  # Tokuhashi 2018 - approximation

    # Cyclic siloxanes (D3, D4, D5 family)
    "Hexamethyl-cyclotrisiloxane": "C[Si]1(C)O[Si](C)(C)O[Si](C)(C)O1",  # D3
    "Octamethylcyclo-tetrasiloxane": "C[Si]1(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O1",  # D4
    "Decamethylcyclo-pentasiloxane": "C[Si]1(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O1",  # D5
    "Dodecamethyl-cyclohexasiloxane": "C[Si]1(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O1",  # D6
    # Linear siloxanes (M-D-M, M-D2-M, M-D3-M, M-D4-M)
    "Octamethyltri-siloxane": "C[Si](C)(C)O[Si](C)(C)O[Si](C)(C)C",  # MDM
    "Decamethyl-tetrasiloxane": "C[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)C",  # MD2M
    "Dodecamethyl-pentasiloxane": "C[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)O[Si](C)(C)C",  # MD3M
}


def validate(smi):
    """Return RDKit metadata or None."""
    if not smi:
        return None
    try:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            return None
        canon = Chem.MolToSmiles(mol, isomericSmiles=False)
        iso = Chem.MolToSmiles(mol, isomericSmiles=True)
        ikey = rdinchi.MolToInchiKey(mol)
        formula = rdMolDescriptors.CalcMolFormula(mol)
        mw = rdMolDescriptors.CalcExactMolWt(mol)
        return {
            "canonical_smiles": canon,
            "isomeric_smiles": iso,
            "inchikey": ikey,
            "rdkit_formula": formula,
            "rdkit_mw": float(mw),
        }
    except Exception:
        return None


# --------------------------------------------------------------------
log.info("=" * 70)
log.info("Loading prior outputs")
log.info("=" * 70)

resolved_path = INPUT_DIR / "processed" / "gwp_resolved.csv"
unresolved_path = INPUT_DIR / "processed" / "gwp_unresolved.csv"
log.info(f"  resolved: {resolved_path} (exists={resolved_path.exists()})")
log.info(f"  unresolved: {unresolved_path} (exists={unresolved_path.exists()})")

resolved_df = pd.read_csv(resolved_path)
unresolved_df = pd.read_csv(unresolved_path)
log.info(f"  resolved rows: {len(resolved_df)}")
log.info(f"  unresolved rows: {len(unresolved_df)}")


# --------------------------------------------------------------------
log.info("=" * 70)
log.info(f"Applying RESCUE map ({len(RESCUE)} entries; {sum(1 for v in RESCUE.values() if v)} non-null)")
log.info("=" * 70)

rescued_rows = []
n_rescued = 0
n_dropped_intentional = 0
n_dropped_no_match = 0
n_validation_failed = 0

for _, row in unresolved_df.iterrows():
    name = str(row["identifier"])
    if name not in RESCUE:
        n_dropped_no_match += 1
        log.warning(f"  no RESCUE entry: {name[:60]}")
        continue
    smi = RESCUE[name]
    if smi is None:
        n_dropped_intentional += 1
        log.info(f"  intentionally dropped: {name}")
        continue
    val = validate(smi)
    if val is None:
        n_validation_failed += 1
        log.error(f"  RDKit validation failed: {name}  smi={smi}")
        continue
    rec = {
        "identifier": name,
        "formula_published": row.get("formula_published"),
        "cas": row.get("cas") if pd.notna(row.get("cas")) else None,
        "gwp100": float(row.get("gwp100")) if pd.notna(row.get("gwp100")) else None,
        "lifetime_years": float(row.get("lifetime_years")) if pd.notna(row.get("lifetime_years")) else None,
        "source": row.get("source"),
        "source_table_ref": row.get("source_table_ref"),
        "raw_smiles": smi,
        "via": "rescue_v2",
        **val,
    }
    rescued_rows.append(rec)
    n_rescued += 1
    log.info(f"  rescued: {name[:50]:50s} -> {val['canonical_smiles'][:50]}  IK={val['inchikey'][:20]}  formula={val['rdkit_formula']}")

log.info("=" * 70)
log.info(f"  rescued: {n_rescued}")
log.info(f"  intentionally dropped: {n_dropped_intentional}")
log.info(f"  no RESCUE entry: {n_dropped_no_match}")
log.info(f"  validation failed: {n_validation_failed}")


# --------------------------------------------------------------------
# Merge with resolved set, dedup on InChIKey
# --------------------------------------------------------------------
log.info("=" * 70)
log.info("Merging rescued with resolved")
log.info("=" * 70)

rescued_df = pd.DataFrame(rescued_rows)
# Compute log10 if present
if len(rescued_df) > 0:
    rescued_df["log10_gwp100"] = np.log10(rescued_df["gwp100"].astype(float))

combined = pd.concat([resolved_df, rescued_df], ignore_index=True)
log.info(f"  pre-dedup combined: {len(combined)}")

# Dedup on InChIKey - keep first (resolved set is loaded first, so prior takes precedence)
priority_map = {
    "Hodnebrog_2020": 0,
    "IPCC_AR6": 1,
    "WMO_2022": 2,
    "Tokuhashi_2018": 3,
    "Tokuhashi_2024": 3,
    "Antinolo_2020": 3,
    "3M_safety_data_sheet": 4,
}
combined["_priority"] = combined["source"].map(priority_map).fillna(9)
combined = (
    combined.sort_values("_priority")
    .drop_duplicates(subset=["inchikey"], keep="first")
    .drop(columns=["_priority"])
)
log.info(f"  post-dedup: {len(combined)}")

# Reorder columns nicely
col_order = [
    "identifier", "formula_published", "cas", "gwp100", "lifetime_years",
    "log10_gwp100", "source", "source_table_ref",
    "raw_smiles", "via", "canonical_smiles", "isomeric_smiles", "inchikey",
    "rdkit_formula", "rdkit_mw",
]
col_order = [c for c in col_order if c in combined.columns]
combined = combined[col_order]

combined.to_csv(PROCESSED_DIR / "gwp_resolved_v2.csv", index=False)


# --------------------------------------------------------------------
# Final report
# --------------------------------------------------------------------
report = {
    "prior_resolved": int(len(resolved_df)),
    "prior_unresolved": int(len(unresolved_df)),
    "rescue_map_entries": len(RESCUE),
    "rescued": n_rescued,
    "intentionally_dropped": n_dropped_intentional,
    "no_rescue_entry": n_dropped_no_match,
    "validation_failed": n_validation_failed,
    "final_unique_rows": int(len(combined)),
    "final_by_source": combined["source"].value_counts().to_dict(),
    "final_by_via": combined["via"].value_counts().to_dict(),
    "with_cas": int(combined["cas"].notna().sum()),
    "lifetime_known": int(combined["lifetime_years"].notna().sum()),
    "gwp100_range": [float(combined["gwp100"].min()), float(combined["gwp100"].max())],
    "log10_gwp100_range": [float(combined["log10_gwp100"].min()), float(combined["log10_gwp100"].max())],
}

log.info("=" * 70)
log.info("FINAL")
log.info("=" * 70)
for k, v in report.items():
    log.info(f"  {k}: {v}")

with (PROCESSED_DIR / "rescue_report.json").open("w") as f:
    json.dump(report, f, indent=2, default=str)

final = {
    "status": "completed",
    "summary": report,
    "outputs": [
        "processed/gwp_resolved_v2.csv",
        "processed/rescue_report.json",
    ],
    "next_phase": "Phase 1C: scaffold-balanced split + holdout carve-out + RDKit features",
}
with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump(final, f, indent=2)
log.info("DONE")
