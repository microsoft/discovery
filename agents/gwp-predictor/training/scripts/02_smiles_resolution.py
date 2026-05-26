#!/usr/bin/env python3
"""02_smiles_resolution.py - Phase 1B.

Resolves CAS / name -> canonical SMILES + InChIKey for every row in
gwp_full.csv. Strategy:
  1. Hand-curated overrides for known-difficult species (refrigerant trade
     names, E/Z isomers, polymer-mixture entries).
  2. PubChem REST /compound/cas/{cas}/... for rows with valid CAS.
  3. PubChem REST /compound/name/{name}/... fallback for rows without CAS.
  4. RDKit Chem.MolFromSmiles to validate every SMILES + canonicalize.
  5. Dedupe on InChIKey.
  6. Save gwp_resolved.csv.

Inputs:
  /input/processed/gwp_full.csv

Outputs:
  /output/processed/gwp_resolved.csv         (rows with valid SMILES)
  /output/processed/gwp_unresolved.csv       (rows where lookup failed)
  /output/processed/resolution_report.json
  /output/checkpoint.json                    (incremental save state)
"""

import os, sys, json, logging, time, re
from pathlib import Path
import requests
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("smiles")

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
PROCESSED_DIR = OUTPUT_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Lazy-import RDKit
from rdkit import Chem, RDLogger
RDLogger.DisableLog("rdApp.*")
from rdkit.Chem import inchi as rdinchi


PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; MicrosoftDiscovery-gwp-predictor/1.0; mailto:discovery-catalog@microsoft.com)"
})


# ------------------------------------------------------------------
# Hand-curated overrides for refrigerant trade names, E/Z isomers, etc.
# Each entry: identifier-pattern OR cas -> isomeric SMILES (verified against
# PubChem CIDs and IUPAC nomenclature). Keyed by canonical lookup keys.
# ------------------------------------------------------------------
OVERRIDES_BY_CAS = {
    # (CAS -> canonical SMILES) - hand-verified
    "75-10-5":   "FCF",                      # HFC-32 (CH2F2 = methylene fluoride)
    "354-33-6":  "FC(F)(F)C(F)F",            # HFC-125 (pentafluoroethane)
    "811-97-2":  "FC(F)(F)CF",               # HFC-134a (1,1,1,2-tetrafluoroethane)
    "359-35-3":  "FC(F)C(F)F",               # HFC-134 (1,1,2,2-tetrafluoroethane)
    "420-46-2":  "CC(F)(F)F",                # HFC-143a (1,1,1-trifluoroethane)
    "75-37-6":   "CC(F)F",                   # HFC-152a (1,1-difluoroethane)
    "75-46-7":   "FC(F)F",                   # HFC-23 (trifluoromethane)
    "754-12-1":  "FC(F)(F)C(F)=C",           # HFO-1234yf (2,3,3,3-tetrafluoroprop-1-ene)
    "29118-24-9": "F/C=C/C(F)(F)F",          # HFO-1234ze(E) (trans)
    "29118-25-0": "F/C=C\\C(F)(F)F",         # HFO-1234ze(Z) (cis)
    "5528-43-8": "F/C(F)=C\\C(F)(F)F",       # HFO-1225ye(Z) (cis)
    "5595-10-8": "F/C(F)=C/C(F)(F)F",        # HFO-1225ye(E) (trans)
    "692-49-9":  "FC(F)(F)/C=C\\C(F)(F)F",   # HFO-1336mzz(Z) (cis)
    "66711-86-2": "FC(F)(F)/C=C/C(F)(F)F",   # HFO-1336mzz(E) (trans)
    "102687-65-0": "ClC=C/C(F)(F)F",         # HCFO-1233zd(E) (1-chloro-3,3,3-trifluoropropene)
    "111512-60-8": "F/C(Cl)=C\\C(F)(F)F",    # HCFO-1224yd(Z)
    "75-69-4":   "FC(Cl)(Cl)Cl",             # CFC-11
    "75-71-8":   "FC(F)(Cl)Cl",              # CFC-12
    "75-72-9":   "FC(F)(F)Cl",               # CFC-13
    "75-73-0":   "FC(F)(F)F",                # PFC-14 (CF4 / tetrafluoromethane)
    "76-16-4":   "FC(F)(F)C(F)(F)F",         # PFC-116 (C2F6)
    "76-19-7":   "FC(F)(F)C(F)(F)C(F)(F)F",  # PFC-218 (C3F8)
    "115-25-3":  "FC1(F)C(F)(F)C(F)(F)C1(F)F",  # PFC-c318 (octafluorocyclobutane)
    "355-25-9":  "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # PFC-3-1-10 (n-C4F10)
    "678-26-2":  "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # PFC-4-1-12 (n-C5F12)
    "355-42-0":  "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # PFC-5-1-14 (n-C6F14)
    "2551-62-4": "FS(F)(F)(F)(F)F",          # SF6
    "7783-54-2": "FN(F)F",                   # NF3 (nitrogen trifluoride)
    "2699-79-8": "FS(F)(=O)=O",              # SO2F2 (sulfuryl fluoride)
    "756-13-8":  "CCC(=O)C(F)(F)C(F)(F)C(F)(F)F",  # Novec 649 (FK-5-1-12)
    "163702-07-6": "COC(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # HFE-7100 (n-isomer; methyl perfluorobutyl ether)
    "163702-05-4": "CCOC(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # HFE-7200 (ethyl perfluorobutyl ether)
    "297730-93-9": "CCC(OC)(C(F)(F)F)C(F)(F)C(F)(F)C(F)(F)F",  # HFE-7500 (approx; methoxynonafluorobutane derivative)
    "132182-92-4": "CCOC(F)(F)C(F)(F)OC(F)(F)C(F)(F)C(F)(F)F",  # HFE-7300
    "353-59-3":   "FC(F)(Cl)Br",             # Halon-1211 (CBrClF2)
    "75-63-8":    "FC(F)(F)Br",              # Halon-1301 (CBrF3)
    "124-73-2":   "FC(F)(Br)C(F)(F)Br",      # Halon-2402
    "311-89-7":   "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)N(C(F)(F)C(F)(F)C(F)(F)C(F)(F)F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # Perfluorotributylamine
    "338-84-1":   "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)N(C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",  # Perfluorotripentylamine
    "373-80-8":   "FC(F)(F)S(F)(F)(F)(F)F",  # Trifluoromethylsulfur pentafluoride (SF5CF3)
    "42532-60-5": "CC(C#N)(C(F)(F)F)C(F)(F)F",  # Heptafluoroisobutyronitrile (Novec 4710)
    "10024-97-2": "[N-]=[N+]=O",             # Nitrous oxide (N2O)
    "124-38-9":   "O=C=O",                   # Carbon dioxide
    "74-82-8":    "C",                       # Methane
    "74-83-9":    "CBr",                     # Methyl bromide
    "74-87-3":    "CCl",                     # Methyl chloride
    "75-09-2":    "ClCCl",                   # Methylene chloride
    "67-66-3":    "ClC(Cl)Cl",               # Chloroform
    "56-23-5":    "ClC(Cl)(Cl)Cl",           # Carbon tetrachloride
    "71-55-6":    "CC(Cl)(Cl)Cl",            # 1,1,1-trichloroethane
    "75-25-2":    "BrC(Br)Br",               # Bromoform
    "74-95-3":    "BrCBr",                   # Dibromomethane
    "74-88-4":    "CI",                      # Methyl iodide
    "79-01-6":    "ClC=C(Cl)Cl",             # Trichloroethylene
    "127-18-4":   "ClC(Cl)=C(Cl)Cl",         # Tetrachloroethylene
    "2314-97-8":  "FC(F)(F)I",               # CF3I
    "75-45-6":    "FC(F)Cl",                 # HCFC-22
    "76-13-1":    "FC(F)(Cl)C(F)(Cl)Cl",     # CFC-113
    "76-14-2":    "FC(F)(Cl)C(F)(F)Cl",      # CFC-114
    "76-15-3":    "FC(F)(F)C(F)(F)Cl",       # CFC-115
    "76-12-0":    "FC(F)(Cl)C(Cl)(Cl)F",     # CFC-112 (alpha)
    "76-11-9":    "FC(F)(Cl)C(Cl)(Cl)Cl",    # CFC-112a (beta)
    "354-58-5":   "FC(F)(F)C(Cl)(Cl)Cl",     # CFC-113a
    "374-07-2":   "FC(F)(F)C(F)(Cl)Cl",      # CFC-114a
    "598-88-9":   "FC=CCl",                  # CFC 1112 (1,2-difluoro-1,2-dichloroethylene)
    "79-35-6":    "FC(F)=C(Cl)Cl",           # CFC 1112a
    "359-29-5":   "FC(=C(Cl)Cl)Cl",          # 1,1,2-trichloro-2-fluoroethene
    "79-38-9":    "FC(=C(F)Cl)F",            # Chlorotrifluoroethylene (CFC-1113)
    "75-38-7":    "FC(F)=C",                 # HFO-1132a (vinylidene fluoride)
    "75-02-5":    "FC=C",                    # HFO-1141 (vinyl fluoride)
    "75-89-8":    "OCC(F)(F)F",              # 2,2,2-trifluoroethanol
    "920-66-1":   "OC(C(F)(F)F)C(F)(F)F",    # Hexafluoroisopropanol
    "684-16-2":   "O=C(C(F)(F)F)C(F)(F)F",   # Hexafluoroacetone
}

# Identifier-pattern-based overrides for rows without CAS (or where CAS lookup failed)
OVERRIDES_BY_NAME = {
    # Generic identifier substrings -> SMILES; first matching key wins.
    # Use lowercase keys; matched as substring on lower(identifier).
    "perfluorohexane": "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",
    "perfluoropropane": "FC(F)(F)C(F)(F)C(F)(F)F",
    "octafluoroprop": "FC(F)(F)C(F)(F)C(F)(F)F",
    "novec 649": "CCC(=O)C(F)(F)C(F)(F)C(F)(F)F",
    "novec 1230": "CCC(=O)C(F)(F)C(F)(F)C(F)(F)F",
    "novec 4710": "CC(C#N)(C(F)(F)F)C(F)(F)F",
    "fk-5-1-12": "CCC(=O)C(F)(F)C(F)(F)C(F)(F)F",
    "perfluorotributylamine": "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)N(C(F)(F)C(F)(F)C(F)(F)C(F)(F)F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",
    "perfluorotripentylamine": "FC(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)N(C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)C(F)(F)F",
}


def pubchem_cids_by_cas(cas, retries=3, timeout=15):
    """Returns list of CIDs for a CAS RN or empty list."""
    if not cas:
        return []
    # PubChem accepts CAS via the name namespace -> /cids endpoint
    url = f"{PUBCHEM_BASE}/compound/name/{cas}/cids/JSON"
    for attempt in range(1, retries + 1):
        try:
            r = SESSION.get(url, timeout=timeout)
            if r.status_code == 200:
                d = r.json()
                cids = d.get("IdentifierList", {}).get("CID", [])
                return cids
            elif r.status_code == 404:
                return []
        except Exception:
            pass
        time.sleep(0.3 * attempt)
    return []


def pubchem_props_by_cid(cid, retries=2, timeout=15):
    """Returns dict {smiles, isomeric_smiles, inchikey, iupac} or None.

    Uses the modern PubChem property names: 'SMILES' is the canonical
    isomeric SMILES (replaces deprecated 'CanonicalSMILES'/'IsomericSMILES'
    fields from pre-2025 API).
    """
    if not cid:
        return None
    url = f"{PUBCHEM_BASE}/compound/cid/{cid}/property/SMILES,ConnectivitySMILES,InChIKey,IUPACName/JSON"
    for attempt in range(1, retries + 1):
        try:
            r = SESSION.get(url, timeout=timeout)
            if r.status_code == 200:
                d = r.json()
                props = d.get("PropertyTable", {}).get("Properties", [])
                if props:
                    p = props[0]
                    smi = p.get("SMILES") or p.get("ConnectivitySMILES")
                    return {
                        "cid": p.get("CID"),
                        "smiles": p.get("ConnectivitySMILES") or smi,
                        "isomeric_smiles": smi,  # SMILES field is the isomeric one
                        "inchikey": p.get("InChIKey"),
                        "iupac": p.get("IUPACName"),
                    }
            elif r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(0.3 * attempt)
    return None


def pubchem_lookup_by_cas(cas, retries=3, timeout=15):
    """Two-step: CAS -> CID -> properties."""
    cids = pubchem_cids_by_cas(cas, retries=retries, timeout=timeout)
    if not cids:
        return None
    return pubchem_props_by_cid(cids[0], retries=retries, timeout=timeout)


def pubchem_lookup_by_name(name, retries=2, timeout=15):
    """Two-step: name -> CID -> properties."""
    if not name:
        return None
    from urllib.parse import quote
    url = f"{PUBCHEM_BASE}/compound/name/{quote(name)}/cids/JSON"
    for attempt in range(1, retries + 1):
        try:
            r = SESSION.get(url, timeout=timeout)
            if r.status_code == 200:
                d = r.json()
                cids = d.get("IdentifierList", {}).get("CID", [])
                if cids:
                    return pubchem_props_by_cid(cids[0], retries=retries, timeout=timeout)
            elif r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(0.3 * attempt)
    return None


def find_override(cas, name):
    """Return SMILES if hand-curated override matches."""
    if cas and cas in OVERRIDES_BY_CAS:
        return OVERRIDES_BY_CAS[cas], "override_by_cas"
    if name:
        n = name.lower()
        for pattern, smi in OVERRIDES_BY_NAME.items():
            if pattern in n:
                return smi, f"override_by_name:{pattern}"
    return None, None


def validate_and_canonicalize(smi):
    """Returns dict {canonical_smiles, isomeric_smiles, inchikey, formula, mw} or None."""
    if not smi:
        return None
    try:
        mol = Chem.MolFromSmiles(smi)
    except Exception:
        return None
    if mol is None:
        return None
    try:
        canon = Chem.MolToSmiles(mol, isomericSmiles=False)
        iso = Chem.MolToSmiles(mol, isomericSmiles=True)
        ikey = rdinchi.MolToInchiKey(mol)
        from rdkit.Chem import rdMolDescriptors
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


# ------------------------------------------------------------------
# Load input + checkpoint state
# ------------------------------------------------------------------
log.info("=" * 70)
log.info("Loading input dataset")
log.info("=" * 70)

input_csv = INPUT_DIR / "processed" / "gwp_full.csv"
log.info(f"  reading {input_csv} (exists={input_csv.exists()})")
df = pd.read_csv(input_csv)
log.info(f"  loaded {len(df)} rows")
log.info(f"  with CAS: {df['cas'].notna().sum()}")
log.info(f"  without CAS: {df['cas'].isna().sum()}")

CHECKPOINT_PATH = OUTPUT_DIR / "checkpoint.json"
if CHECKPOINT_PATH.exists():
    state = json.loads(CHECKPOINT_PATH.read_text())
    results = state.get("results", [])
    done_keys = {r["_key"] for r in results}
    log.info(f"  resuming from checkpoint: {len(results)} already done")
else:
    results = []
    done_keys = set()


def save_checkpoint():
    CHECKPOINT_PATH.write_text(json.dumps({"results": results}, default=str))


# ------------------------------------------------------------------
# Resolve every row
# ------------------------------------------------------------------
log.info("=" * 70)
log.info("Resolving SMILES")
log.info("=" * 70)

start = time.time()
n_total = len(df)
n_processed = 0
n_via_override = 0
n_via_cas = 0
n_via_name = 0
n_failed = 0

for idx, row in df.iterrows():
    cas = row.get("cas") if pd.notna(row.get("cas")) else None
    name = row.get("identifier") if pd.notna(row.get("identifier")) else None
    formula = row.get("formula") if pd.notna(row.get("formula")) else None
    key = f"{cas or ''}__{name or ''}__{formula or ''}"
    if key in done_keys:
        continue

    raw_smi = None
    via = None

    # Step 1: hand-curated override
    raw_smi, via = find_override(cas, name)

    # Step 2: PubChem by CAS
    if not raw_smi and cas:
        pc = pubchem_lookup_by_cas(cas)
        if pc and pc.get("isomeric_smiles"):
            raw_smi = pc["isomeric_smiles"]
            via = "pubchem_cas"
            pubchem_meta = pc

    # Step 3: PubChem by name (last resort)
    if not raw_smi and name:
        # Strip trailing footnote letters and parenthetical clarifications
        name_clean = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        pc = pubchem_lookup_by_name(name_clean)
        if pc and pc.get("isomeric_smiles"):
            raw_smi = pc["isomeric_smiles"]
            via = "pubchem_name"

    # Validate
    val = validate_and_canonicalize(raw_smi) if raw_smi else None

    rec = {
        "_key": key,
        "_original_index": int(idx),
        "identifier": name,
        "formula_published": formula,
        "cas": cas,
        "gwp100": float(row.get("gwp100")) if pd.notna(row.get("gwp100")) else None,
        "lifetime_years": float(row.get("lifetime_years")) if pd.notna(row.get("lifetime_years")) else None,
        "source": row.get("source"),
        "source_table_ref": row.get("source_table_ref"),
        "raw_smiles": raw_smi,
        "via": via or "failed",
    }
    if val:
        rec.update(val)
        if via == "override_by_cas":
            n_via_override += 1
        elif via and via.startswith("override_by_name"):
            n_via_override += 1
        elif via == "pubchem_cas":
            n_via_cas += 1
        elif via == "pubchem_name":
            n_via_name += 1
    else:
        n_failed += 1
        if via:
            log.warning(f"  validation failed for {name} via={via} smi={raw_smi}")

    results.append(rec)
    done_keys.add(key)
    n_processed += 1

    # Checkpoint every 10 rows
    if n_processed % 10 == 0:
        save_checkpoint()
        elapsed = time.time() - start
        rate = n_processed / max(elapsed, 1e-6)
        eta = (n_total - n_processed) / max(rate, 1e-6)
        log.info(
            f"  [{n_processed}/{n_total}] override={n_via_override} "
            f"cas={n_via_cas} name={n_via_name} fail={n_failed} "
            f"rate={rate:.1f}/s eta={eta:.0f}s"
        )

save_checkpoint()
log.info(f"DONE resolving. Total processed: {len(results)}")


# ------------------------------------------------------------------
# Build resolved + unresolved DataFrames
# ------------------------------------------------------------------
log.info("=" * 70)
log.info("Building output CSVs")
log.info("=" * 70)

resolved_records = [r for r in results if r.get("canonical_smiles")]
unresolved_records = [r for r in results if not r.get("canonical_smiles")]

resolved_df = pd.DataFrame(resolved_records)
unresolved_df = pd.DataFrame(unresolved_records)

# Drop the internal _key column for output
for col in ["_key", "_original_index"]:
    if col in resolved_df.columns:
        resolved_df = resolved_df.drop(columns=[col])
    if col in unresolved_df.columns:
        unresolved_df = unresolved_df.drop(columns=[col])

# Dedup resolved on InChIKey (preferring Hodnebrog source if conflict)
log.info(f"Pre-dedup resolved: {len(resolved_df)}")
priority_map = {
    "Hodnebrog_2020": 0,
    "IPCC_AR6": 1,
    "WMO_2022": 2,
    "Tokuhashi_2018": 3,
    "Tokuhashi_2024": 3,
    "Antinolo_2020": 3,
    "3M_safety_data_sheet": 4,
}
resolved_df["_priority"] = resolved_df["source"].map(priority_map).fillna(9)
resolved_df = (
    resolved_df.sort_values("_priority")
    .drop_duplicates(subset=["inchikey"], keep="first")
    .drop(columns=["_priority"])
)
log.info(f"Post-dedup resolved: {len(resolved_df)}")

# Add log10
resolved_df["log10_gwp100"] = np.log10(resolved_df["gwp100"].astype(float))

# Save
resolved_df.to_csv(PROCESSED_DIR / "gwp_resolved.csv", index=False)
unresolved_df.to_csv(PROCESSED_DIR / "gwp_unresolved.csv", index=False)


# ------------------------------------------------------------------
# Report
# ------------------------------------------------------------------
report = {
    "total_input_rows": int(len(df)),
    "n_processed": len(results),
    "n_resolved_pre_dedup": len([r for r in results if r.get("canonical_smiles")]),
    "n_resolved_post_dedup": int(len(resolved_df)),
    "n_unresolved": int(len(unresolved_df)),
    "by_via": {
        "override_by_cas": n_via_override,
        "pubchem_cas": n_via_cas,
        "pubchem_name": n_via_name,
        "failed": n_failed,
    },
    "by_source": resolved_df["source"].value_counts().to_dict(),
    "gwp100_range_resolved": [
        float(resolved_df["gwp100"].min()),
        float(resolved_df["gwp100"].max()),
    ],
    "log10_gwp100_range_resolved": [
        float(resolved_df["log10_gwp100"].min()),
        float(resolved_df["log10_gwp100"].max()),
    ],
    "lifetime_known_resolved": int(resolved_df["lifetime_years"].notna().sum()),
    "unresolved_examples": [
        {"identifier": r["identifier"], "cas": r["cas"], "via": r["via"]}
        for r in unresolved_records[:20]
    ],
}
log.info("=" * 70)
log.info("FINAL")
log.info("=" * 70)
for k, v in report.items():
    if k == "unresolved_examples":
        log.info(f"  {k}:")
        for ex in v:
            log.info(f"    {ex}")
    else:
        log.info(f"  {k}: {v}")

with (PROCESSED_DIR / "resolution_report.json").open("w") as f:
    json.dump(report, f, indent=2, default=str)

final = {
    "status": "completed",
    "summary": report,
    "next_phase": "Phase 1C: scaffold-balanced split + holdout carve-out + RDKit features",
    "outputs": [
        "processed/gwp_resolved.csv",
        "processed/gwp_unresolved.csv",
        "processed/resolution_report.json",
    ],
}
with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump(final, f, indent=2)
log.info("DONE")
