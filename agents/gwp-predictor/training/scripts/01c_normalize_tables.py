#!/usr/bin/env python3
"""01c_normalize_tables.py - Phase 1A continued.

Reads raw extracted tables from previous job's /input/tables/ directory
(IPCC AR6 SM pages 16-27, WMO 2022 Annex pages 455-493) and produces a
unified clean CSV ready for SMILES resolution.

Outputs:
  /output/processed/ipcc_ar6_clean.csv
  /output/processed/wmo_2022_clean.csv
  /output/processed/gwp_unified.csv      (merged + anchor backfill)
  /output/processed/normalize_report.json
  /output/final_results.json
"""

import os, sys, json, logging, re
from pathlib import Path
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("normalize")

INPUT_TABLES = Path("/input/tables")
OUTPUT_DIR = Path("/output")
PROCESSED_DIR = OUTPUT_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# --- Anchor set (same as 01_data_ingest, embedded for offline backfill) ---
ANCHOR = [
    ("Carbon dioxide", "124-38-9", "CO2", 1.0, 1000.0, "IPCC_AR6"),
    ("Methane (fossil)", "74-82-8", "CH4", 29.8, 11.8, "IPCC_AR6"),
    ("Nitrous oxide", "10024-97-2", "N2O", 273.0, 109.0, "IPCC_AR6"),
    ("HFC-23", "75-46-7", "CHF3", 14600.0, 228.0, "IPCC_AR6"),
    ("HFC-32", "75-10-5", "CH2F2", 771.0, 5.4, "IPCC_AR6"),
    ("HFC-41", "593-53-3", "CH3F", 135.0, 2.8, "IPCC_AR6"),
    ("HFC-125", "354-33-6", "C2HF5", 3740.0, 30.0, "IPCC_AR6"),
    ("HFC-134", "359-35-3", "C2H2F4", 1260.0, 9.7, "IPCC_AR6"),
    ("HFC-134a", "811-97-2", "C2H2F4", 1530.0, 14.0, "IPCC_AR6"),
    ("HFC-143", "430-66-0", "C2H3F3", 364.0, 3.6, "IPCC_AR6"),
    ("HFC-143a", "420-46-2", "C2H3F3", 5810.0, 51.0, "IPCC_AR6"),
    ("HFC-152", "624-72-6", "C2H4F2", 21.5, 0.4, "IPCC_AR6"),
    ("HFC-152a", "75-37-6", "C2H4F2", 164.0, 1.6, "IPCC_AR6"),
    ("HFC-161", "353-36-6", "C2H5F", 4.8, 0.18, "IPCC_AR6"),
    ("HFC-227ea", "431-89-0", "C3HF7", 3600.0, 36.0, "IPCC_AR6"),
    ("HFC-236cb", "677-56-5", "C3H2F6", 1350.0, 13.4, "IPCC_AR6"),
    ("HFC-236ea", "431-63-0", "C3H2F6", 1500.0, 11.4, "IPCC_AR6"),
    ("HFC-236fa", "690-39-1", "C3H2F6", 8690.0, 213.0, "IPCC_AR6"),
    ("HFC-245ca", "679-86-7", "C3H3F5", 716.0, 6.6, "IPCC_AR6"),
    ("HFC-245fa", "460-73-1", "C3H3F5", 962.0, 7.9, "IPCC_AR6"),
    ("HFC-365mfc", "406-58-6", "C4H5F5", 914.0, 8.9, "IPCC_AR6"),
    ("HFC-43-10mee", "138495-42-8", "C5H2F10", 1600.0, 17.0, "IPCC_AR6"),
    ("HFO-1234yf", "754-12-1", "C3H2F4", 0.501, 0.029, "Hodnebrog_2020"),
    ("HFO-1234ze(E)", "29118-24-9", "C3H2F4", 1.37, 0.045, "Hodnebrog_2020"),
    ("HFO-1336mzz(Z)", "692-49-9", "C4H2F6", 2.0, 0.06, "Hodnebrog_2020"),
    ("HCFO-1233zd(E)", "102687-65-0", "C3H2ClF3", 3.88, 0.071, "Hodnebrog_2020"),
    ("HFE-7100", "163702-07-6", "C5H3F9O", 460.0, 4.7, "Hodnebrog_2020"),
    ("HFE-7200", "163702-05-4", "C6H5F9O", 60.0, 0.77, "Hodnebrog_2020"),
    ("HFE-7300", "132182-92-4", "C7H3F13O2", 405.0, 4.4, "Hodnebrog_2020"),
    ("HFE-7500", "297730-93-9", "C9H5F15O", 13.0, 0.22, "Hodnebrog_2020"),
    ("Novec 649 (FK-5-1-12)", "756-13-8", "C6F12O", 1.0, 0.014, "3M_safety_data_sheet"),
    ("PFC-14 (CF4)", "75-73-0", "CF4", 7380.0, 50000.0, "IPCC_AR6"),
    ("PFC-116 (C2F6)", "76-16-4", "C2F6", 12400.0, 10000.0, "IPCC_AR6"),
    ("PFC-218 (C3F8)", "76-19-7", "C3F8", 9290.0, 2600.0, "IPCC_AR6"),
    ("PFC-c318 (c-C4F8)", "115-25-3", "C4F8", 10200.0, 3200.0, "IPCC_AR6"),
    ("PFC-3-1-10 (n-C4F10)", "355-25-9", "C4F10", 10000.0, 2600.0, "IPCC_AR6"),
    ("PFC-4-1-12 (n-C5F12)", "678-26-2", "C5F12", 9220.0, 4100.0, "IPCC_AR6"),
    ("PFC-5-1-14 (n-C6F14)", "355-42-0", "C6F14", 7910.0, 3100.0, "IPCC_AR6"),
    ("Sulfur hexafluoride", "2551-62-4", "SF6", 24300.0, 3200.0, "IPCC_AR6"),
    ("Nitrogen trifluoride", "7783-54-2", "NF3", 17400.0, 569.0, "IPCC_AR6"),
    ("Sulfuryl fluoride", "2699-79-8", "SO2F2", 4090.0, 36.0, "Hodnebrog_2020"),
    ("CFC-11", "75-69-4", "CCl3F", 6230.0, 52.0, "IPCC_AR6"),
    ("CFC-12", "75-71-8", "CCl2F2", 10200.0, 102.0, "IPCC_AR6"),
    ("CFC-13", "75-72-9", "CClF3", 13900.0, 640.0, "IPCC_AR6"),
    ("CFC-113", "76-13-1", "C2Cl3F3", 6520.0, 93.0, "IPCC_AR6"),
    ("CFC-114", "76-14-2", "C2Cl2F4", 8590.0, 189.0, "IPCC_AR6"),
    ("CFC-115", "76-15-3", "C2ClF5", 7670.0, 540.0, "IPCC_AR6"),
    ("HCFC-22", "75-45-6", "CHClF2", 1960.0, 11.9, "IPCC_AR6"),
    ("HCFC-123", "306-83-2", "C2HCl2F3", 90.0, 1.3, "IPCC_AR6"),
    ("HCFC-124", "2837-89-0", "C2HClF4", 597.0, 5.9, "IPCC_AR6"),
    ("HCFC-141b", "1717-00-6", "C2H3Cl2F", 853.0, 9.4, "IPCC_AR6"),
    ("HCFC-142b", "75-68-3", "C2H3ClF2", 2300.0, 18.0, "IPCC_AR6"),
    ("HCFC-225ca", "422-56-0", "C3HCl2F5", 137.0, 1.9, "IPCC_AR6"),
    ("HCFC-225cb", "507-55-1", "C3HCl2F5", 568.0, 5.9, "IPCC_AR6"),
    ("Halon-1211", "353-59-3", "CBrClF2", 1930.0, 16.0, "IPCC_AR6"),
    ("Halon-1301", "75-63-8", "CBrF3", 7200.0, 72.0, "IPCC_AR6"),
    ("Halon-2402", "124-73-2", "C2Br2F4", 2170.0, 28.0, "IPCC_AR6"),
    ("Methyl bromide", "74-83-9", "CH3Br", 2.43, 0.8, "IPCC_AR6"),
    ("Methyl chloride", "74-87-3", "CH3Cl", 5.54, 0.9, "IPCC_AR6"),
    ("Methylene chloride", "75-09-2", "CH2Cl2", 11.2, 0.4, "IPCC_AR6"),
    ("Chloroform", "67-66-3", "CHCl3", 20.0, 0.5, "IPCC_AR6"),
    ("Carbon tetrachloride", "56-23-5", "CCl4", 2200.0, 32.0, "IPCC_AR6"),
    ("Trichloroethane", "71-55-6", "C2H3Cl3", 161.0, 5.0, "IPCC_AR6"),
]


def clean_name(s):
    """Collapse multi-line names + strip whitespace."""
    if s is None or pd.isna(s):
        return None
    s = str(s).replace("\n", " ").replace("- ", "-").strip()
    # collapse multiple spaces
    s = re.sub(r"\s+", " ", s)
    return s if s else None


def clean_formula(s):
    """Remove subscript spaces from PDF-extracted formulas.
    'CF 4' -> 'CF4'; 'CHCH 3 3' -> 'CH3CH3'; 'CCl 2 F 2' -> 'CCl2F2'.
    Strategy: split by space, the digits between letter-tokens are
    subscripts that follow the immediately preceding letter token.
    """
    if s is None or pd.isna(s):
        return None
    s = str(s).replace("\n", "").strip()
    if not s:
        return None
    # If already clean (no spaces), return as-is
    if " " not in s:
        return s
    # Tokenise: split on whitespace
    tokens = s.split()
    if not tokens:
        return None
    # Detect WMO's pattern: "<element-stem> <digit> <digit> ..."
    # vs IPCC's pattern: "CF2=CF2" (already clean, no spaces inside formula).
    # WMO uses subscript-style spaces where digits trail letters; we need
    # to inline them character-by-character.
    digit_only_tokens = [t for t in tokens if t.isdigit()]
    if len(digit_only_tokens) > 0 and len(digit_only_tokens) == len(tokens) - 1:
        # Pattern like "CF 4" or "CHCH 3 3" - assume the leading non-digit
        # token contains all letters and digits trail it positionally.
        letters_token = [t for t in tokens if not t.isdigit()][0]
        # Split letters_token into letter groups (capital + lowercase + 0-9)
        letter_groups = re.findall(r"[A-Z][a-z]?", letters_token)
        if len(letter_groups) == len(digit_only_tokens):
            # Interleave: each letter group gets the corresponding subscript
            result = "".join(g + d for g, d in zip(letter_groups, digit_only_tokens))
            return result
        # Fallback: just concatenate everything
        return letters_token + "".join(digit_only_tokens)
    # Otherwise (mixed with operators like '=', 'c-' prefix etc.), just remove spaces
    return s.replace(" ", "")


def clean_cas(s):
    if s is None or pd.isna(s):
        return None
    s = str(s).strip()
    # Standard CAS pattern: NNN-NN-N
    m = re.search(r"\b(\d{2,7}-\d{2}-\d)\b", s)
    return m.group(1) if m else None


NUMERIC_RE = re.compile(r"[-+]?\d{1,3}(?:[\s,]?\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?")


def parse_number(s):
    """Extract a single float from a possibly-messy cell string.
    Handles 'x 10\u201311', '×10\u20136', commas as thousands separators, '<', '>', '~'."""
    if s is None or pd.isna(s):
        return None
    s = str(s).strip()
    if not s:
        return None
    # Strip leading qualifiers
    s = re.sub(r"^[<>~\u2248]\s*", "", s)
    # Handle 'A x 10^B' or 'A × 10^B' notation (PDF often uses unicode ×)
    sci = re.match(
        r"([\d.,+-]+)\s*[x\u00d7\u00d7]\s*10[\u2013\u2212\-\u2014\u207b]?\s*([\d]+)",
        s,
    )
    if sci:
        try:
            mantissa = float(sci.group(1).replace(",", ""))
            exp = -int(sci.group(2))  # the dash means negative exponent
            return mantissa * (10 ** exp)
        except Exception:
            pass
    # Range: 'A-B' or 'A\u2013B' -> take midpoint
    rng = re.match(r"([\d.,]+)\s*[-\u2013]\s*([\d.,]+)$", s)
    if rng:
        try:
            a = float(rng.group(1).replace(",", ""))
            b = float(rng.group(2).replace(",", ""))
            return (a + b) / 2
        except Exception:
            pass
    # 'X days' -> convert to years
    if "day" in s.lower():
        m = re.match(r"([\d.,]+)", s)
        if m:
            try:
                return float(m.group(1).replace(",", "")) / 365.25
            except Exception:
                pass
    # 'X weeks' -> years
    if "week" in s.lower():
        m = re.match(r"([\d.,]+)", s)
        if m:
            try:
                return float(m.group(1).replace(",", "")) / 52.18
            except Exception:
                pass
    # Plain number (with commas as thousands separators)
    m = NUMERIC_RE.match(s)
    if m:
        try:
            return float(m.group(0).replace(",", "").replace(" ", ""))
        except Exception:
            return None
    return None


# --- Parse IPCC AR6 SM Table 7.SM.7 (pages 16-27) ---
log.info("=" * 70)
log.info("Parsing IPCC AR6 SM Table 7.SM.7 (pages 16-27)")
log.info("=" * 70)

# Verify input dir
log.info(f"INPUT_TABLES contents (first 5 IPCC files):")
ipcc_csvs = sorted(INPUT_TABLES.glob("ipcc_ar6_p0*.csv"))
for p in ipcc_csvs[:5]:
    log.info(f"  {p.name} ({p.stat().st_size} bytes)")
log.info(f"Total IPCC CSVs: {len(ipcc_csvs)}")

ipcc_pages = list(range(16, 28))  # pages 16-27 inclusive
ipcc_rows = []
for pg in ipcc_pages:
    csv_path = INPUT_TABLES / f"ipcc_ar6_p{pg:03d}_t0.csv"
    if not csv_path.exists():
        log.warning(f"  page {pg}: CSV missing")
        continue
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""])
    if len(df.columns) < 8:
        log.warning(f"  page {pg}: too few cols ({len(df.columns)}), skipping")
        continue
    # Expected columns by index based on the header confirmed in p022:
    #   0=Name, 1=Formula, 2=Lifetime(yr), 3=RE, 4=AGWP-20, 5=GWP-20,
    #   6=AGWP-100, 7=GWP-100, 8=AGWP-500, 9=GWP-500, ...
    log.info(f"  page {pg}: {len(df)} rows, cols={list(df.columns)[:5]}")
    for _, row in df.iterrows():
        name = clean_name(row.iloc[0])
        formula = clean_formula(row.iloc[1])
        # Drop section header rows (formula empty AND no number in lifetime col)
        if not formula and (not row.iloc[2] or not str(row.iloc[2]).strip()):
            continue
        # Drop the column-header row (sometimes repeats per page)
        if name and name.lower() in ("name", "industrial designation"):
            continue
        lifetime = parse_number(row.iloc[2])
        gwp_100 = parse_number(row.iloc[7]) if len(row) > 7 else None
        if name and formula and gwp_100 is not None and gwp_100 > 0:
            ipcc_rows.append({
                "identifier": name,
                "formula": formula,
                "cas": None,
                "gwp100": gwp_100,
                "lifetime_years": lifetime,
                "source": "IPCC_AR6",
                "source_table_ref": f"Table_7.SM.7_p{pg}",
            })

ipcc_df = pd.DataFrame(ipcc_rows)
log.info(f"IPCC parsed: {len(ipcc_df)} rows")
if len(ipcc_df):
    log.info(f"  GWP100 range: {ipcc_df['gwp100'].min()} - {ipcc_df['gwp100'].max()}")
    log.info(f"  log10(GWP100) range: {np.log10(ipcc_df['gwp100']).min():.2f} - {np.log10(ipcc_df['gwp100']).max():.2f}")
    log.info(f"  Sample rows:")
    for _, r in ipcc_df.head(5).iterrows():
        log.info(f"    {r['identifier'][:40]:40s}  {r['formula']:15s}  GWP100={r['gwp100']:8g}  lifetime={r['lifetime_years']}")
ipcc_df.to_csv(PROCESSED_DIR / "ipcc_ar6_clean.csv", index=False)


# --- Parse WMO 2022 Annex A1 (lifetime + CAS pages) ---
log.info("=" * 70)
log.info("Parsing WMO 2022 Annex A1 (lifetime+CAS pages)")
log.info("=" * 70)

# WMO Annex pages alternate: 455 lifetime, 456 GWP, 458 lifetime, 459 GWP, ...
# Lifetime+CAS pages contain columns: Name, Formula, CAS RN, Abundance, Lifetime
# Detect by checking if the table has a 'CAS' column
wmo_lifetime_pages = [455, 458, 460, 462, 464, 466, 468, 470, 472, 474, 476, 478, 480, 482, 484, 486, 488, 490, 492]

wmo_rows = []
for pg in wmo_lifetime_pages:
    csv_path = INPUT_TABLES / f"wmo_full_p{pg:03d}_t0.csv"
    if not csv_path.exists():
        log.warning(f"  page {pg}: CSV missing")
        continue
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""])
    if len(df.columns) < 5:
        log.warning(f"  page {pg}: too few cols, skipping")
        continue
    cols_lower = [str(c).lower() for c in df.columns]
    has_cas = any("cas" in c for c in cols_lower)
    if not has_cas:
        log.info(f"  page {pg}: no CAS column, skipping (likely the GWP companion page)")
        continue
    # Find column indices
    name_idx = 0
    formula_idx = 1
    cas_idx = 2
    # Lifetime col: prefer "WMO (2022) Total Lifetime"
    lifetime_idx = None
    for i, c in enumerate(cols_lower):
        if "2022" in c and "lifetime" in c:
            lifetime_idx = i
            break
    if lifetime_idx is None:
        for i, c in enumerate(cols_lower):
            if "lifetime" in c:
                lifetime_idx = i
                break
    log.info(f"  page {pg}: {len(df)} rows, lifetime_col_idx={lifetime_idx}")
    for _, row in df.iterrows():
        name = clean_name(row.iloc[name_idx])
        formula = clean_formula(row.iloc[formula_idx])
        cas = clean_cas(row.iloc[cas_idx])
        if not name or name.lower() in ("industrial designation or chemical name", ""):
            continue
        # Section header rows have empty formula
        if not formula:
            continue
        lifetime = parse_number(row.iloc[lifetime_idx]) if lifetime_idx else None
        wmo_rows.append({
            "identifier": name,
            "formula": formula,
            "cas": cas,
            "gwp100": None,  # GWP comes from companion page; we trust IPCC for GWP
            "lifetime_years": lifetime,
            "source": "WMO_2022",
            "source_table_ref": f"Annex_A1_p{pg}",
        })

wmo_df = pd.DataFrame(wmo_rows)
log.info(f"WMO parsed: {len(wmo_df)} rows")
if len(wmo_df):
    log.info(f"  Sample rows:")
    for _, r in wmo_df.head(5).iterrows():
        log.info(f"    {str(r['identifier'])[:40]:40s}  {r['formula']:15s}  CAS={r['cas']}  lifetime={r['lifetime_years']}")
wmo_df.to_csv(PROCESSED_DIR / "wmo_2022_clean.csv", index=False)


# --- Anchor backfill: ensure key compounds always present ---
anchor_df = pd.DataFrame(
    ANCHOR,
    columns=["identifier", "cas", "formula", "gwp100", "lifetime_years", "source"],
)
anchor_df["source_table_ref"] = "anchor_curated_v1"
anchor_df = anchor_df[["identifier", "formula", "cas", "gwp100", "lifetime_years", "source", "source_table_ref"]]


# --- Merge: precedence IPCC > anchor (for missing) > WMO (for CAS-only enrichment) ---
log.info("=" * 70)
log.info("Merging sources")
log.info("=" * 70)

# Step 1: union of IPCC + anchor (anchor adds Hodnebrog HFOs/HFEs/Novec missing from IPCC)
combined = pd.concat([ipcc_df, anchor_df], ignore_index=True)
log.info(f"After IPCC+anchor concat: {len(combined)} rows")

# Step 2: dedupe by formula (case-insensitive). Prefer IPCC over anchor.
combined["_formula_norm"] = combined["formula"].str.upper().str.replace(" ", "")
combined["_priority"] = combined["source"].map({"IPCC_AR6": 0, "Hodnebrog_2020": 1, "WMO_2022": 2, "3M_safety_data_sheet": 3}).fillna(9)
combined = combined.sort_values("_priority").drop_duplicates(subset=["_formula_norm"], keep="first")
log.info(f"After dedup by formula: {len(combined)} rows")

# Step 3: backfill CAS from WMO using formula match
wmo_lookup = wmo_df.dropna(subset=["cas"]).copy()
wmo_lookup["_formula_norm"] = wmo_lookup["formula"].str.upper().str.replace(" ", "")
wmo_cas_by_formula = dict(zip(wmo_lookup["_formula_norm"], wmo_lookup["cas"]))
mask_no_cas = combined["cas"].isna()
backfilled = 0
for idx in combined[mask_no_cas].index:
    fnorm = combined.at[idx, "_formula_norm"]
    if fnorm in wmo_cas_by_formula:
        combined.at[idx, "cas"] = wmo_cas_by_formula[fnorm]
        backfilled += 1
log.info(f"CAS backfill from WMO: {backfilled} rows enriched")

# Step 4: keep only rows with valid GWP100
combined = combined.dropna(subset=["gwp100"]).copy()
combined = combined[combined["gwp100"] > 0].copy()
log.info(f"After GWP100 validity filter: {len(combined)} rows")

combined = combined.drop(columns=["_formula_norm", "_priority"])
combined["log10_gwp100"] = np.log10(combined["gwp100"].astype(float))
combined.to_csv(PROCESSED_DIR / "gwp_unified.csv", index=False)


# --- Summary ---
report = {
    "ipcc_n": len(ipcc_df),
    "wmo_n": len(wmo_df),
    "anchor_n": len(anchor_df),
    "unified_n": len(combined),
    "unified_by_source": combined["source"].value_counts().to_dict(),
    "unified_with_cas": int(combined["cas"].notna().sum()),
    "gwp100_min": float(combined["gwp100"].min()),
    "gwp100_max": float(combined["gwp100"].max()),
    "log10_gwp100_min": float(combined["log10_gwp100"].min()),
    "log10_gwp100_max": float(combined["log10_gwp100"].max()),
    "lifetime_known": int(combined["lifetime_years"].notna().sum()),
}
log.info("=" * 70)
log.info("FINAL")
log.info("=" * 70)
for k, v in report.items():
    log.info(f"  {k}: {v}")

with (PROCESSED_DIR / "normalize_report.json").open("w") as f:
    json.dump(report, f, indent=2)

final = {
    "status": "completed",
    "summary": report,
    "next_phase": "02_smiles_resolution.py",
    "outputs": [
        "processed/ipcc_ar6_clean.csv",
        "processed/wmo_2022_clean.csv",
        "processed/gwp_unified.csv",
        "processed/normalize_report.json",
    ],
}
with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump(final, f, indent=2)
log.info("DONE")
