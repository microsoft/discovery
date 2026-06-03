#!/usr/bin/env python3
"""01k_final_merge.py - Phase 1A FINAL: merge IPCC + Hodnebrog Tables 3+5.

Now that we have Hodnebrog 2020 Table 3 (48 rows, top-40 halocarbons) and
Table 5 (254 rows, less abundant compounds) parsed from the JATS XML, merge
them with the existing 311-row extended dataset and carve out a real
holdout set.

Inputs (from /input/):
  /input/jats/tables/rog20236-tbl-0003.csv  (Table 3)
  /input/jats/tables/rog20236-tbl-0005.csv  (Table 5)
  /input/processed/gwp_extended.csv (from depends_on; previous extend job)

Outputs:
  /output/processed/hodnebrog_table3.csv   (parsed clean)
  /output/processed/hodnebrog_table5.csv   (parsed clean)
  /output/processed/gwp_full.csv           (final unified training set)
  /output/processed/gwp_full_report.json
"""

import os, sys, json, logging, re
from pathlib import Path
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("merge")

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
PROCESSED_DIR = OUTPUT_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def clean_name(s):
    if s is None or pd.isna(s):
        return None
    s = str(s).replace("\n", " ").replace("\u2010", "-").strip()
    s = re.sub(r"\s+", " ", s)
    return s if s else None


def clean_formula(s):
    """For Hodnebrog: formulas are mostly clean already (e.g. CCl3F, CF3CHF2).
    But some have footnote markers, equals signs, special spacing.
    Simple cleanup: strip whitespace + footnote letters at the end."""
    if s is None or pd.isna(s):
        return None
    s = str(s).strip()
    if not s:
        return None
    # Drop trailing footnote letters like 'a', 'b' (only if formula ends with a digit + letter)
    s = re.sub(r"(\d)[a-z]\b", r"\1", s)
    # Drop spaces inside the formula but keep '=' for unsaturated
    s = s.replace(" ", "")
    return s


def clean_cas(s):
    if s is None or pd.isna(s):
        return None
    s = str(s).replace("\u2010", "-").strip()
    m = re.search(r"\b(\d{2,7}-\d{2}-\d)\b", s)
    return m.group(1) if m else None


NUMERIC_RE = re.compile(r"[-+]?\d{1,3}(?:[\s,]?\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?")


def parse_number(s):
    if s is None or pd.isna(s):
        return None
    s = str(s).replace("\u2010", "-").strip()
    if not s or s == "(0)" or s.lower() in ("n/a", "na"):
        return None
    # '<1' -> 0.5; '>1000' -> 1000
    if s.startswith("<"):
        m = NUMERIC_RE.search(s[1:])
        return float(m.group(0).replace(",", "")) / 2.0 if m else None
    if s.startswith(">"):
        m = NUMERIC_RE.search(s[1:])
        return float(m.group(0).replace(",", "")) if m else None
    # Parenthetical means estimated/uncertain: '(0.13)' - take it as the value
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    # Sci notation 'x 10\u20136'
    sci = re.match(r"([\d.,+-]+)\s*[x\u00d7]\s*10[\u2013\u2212-]?\s*([\d]+)", s)
    if sci:
        try:
            mantissa = float(sci.group(1).replace(",", ""))
            exp = -int(sci.group(2))
            return mantissa * (10 ** exp)
        except Exception:
            pass
    # 'X days' / 'X weeks' / 'X hours' -> years
    for unit, divisor in (("day", 365.25), ("week", 52.18), ("hour", 8766.0), ("minute", 525960.0)):
        if unit in s.lower():
            m = NUMERIC_RE.search(s)
            if m:
                try:
                    return float(m.group(0).replace(",", "")) / divisor
                except Exception:
                    pass
    # Plain number
    m = NUMERIC_RE.match(s)
    if m:
        try:
            return float(m.group(0).replace(",", "").replace(" ", ""))
        except Exception:
            return None
    return None


def parse_hodnebrog_table(path, table_label, n_cols_expected=None):
    """Parse Hodnebrog Table 3 or Table 5.

    Both share a multi-row header:
      Row 0: ['', '', '', 'τ (yr)', '', 'RE (W m-2 ppb-1)', '', 'GWP(100)', '']
      Row 1: ['Identifier/name', 'Formula', 'CASRN', 'H2013', 'WMO 2019', 'H2013', 'This work', 'H2013', 'This work']
    Then section header rows (one cell, e.g. "Chlorofluorocarbons") interleaved with data rows.
    """
def parse_hodnebrog_table(path, table_label, n_cols_expected=None):
    """Parse Hodnebrog Table 3 or Table 5 from CSV with ragged-row support."""
    import csv as _csv
    log.info(f"Parsing {path.name} ({table_label})")
    raw_rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = _csv.reader(f)
        for row in reader:
            raw_rows.append(row)
    log.info(f"  raw rows: {len(raw_rows)}")
    log.info(f"  first 3 rows:")
    for i in range(min(3, len(raw_rows))):
        log.info(f"    {raw_rows[i]}")
    n_cols = max(len(r) for r in raw_rows) if raw_rows else 0
    log.info(f"  max cols seen: {n_cols}")

    # The data starts at row 2 (after the two-row header).
    # The 'GWP(100) - This work' column is the LAST column in both tables.
    # The 'τ (yr)' column is column 3.
    rows = []
    for i in range(2, len(raw_rows)):
        row = raw_rows[i]
        if not row:
            continue
        # Pad short rows with empty strings to width n_cols
        padded = list(row) + [""] * (n_cols - len(row))
        name = clean_name(padded[0])
        formula = clean_formula(padded[1]) if n_cols > 1 else None
        cas = clean_cas(padded[2]) if n_cols > 2 else None
        # Section header: only the first cell has content (e.g. "Chlorofluorocarbons")
        if not formula and not cas and name and not any(p.strip() for p in padded[1:]):
            continue
        if not name and not formula and not cas:
            continue
        # Lifetime: column index 3 in both tables (τ from H2013/unified)
        lifetime = parse_number(padded[3]) if n_cols > 3 else None
        # For Table 3, prefer WMO 2019 lifetime (col 4) when present
        if table_label == "Table 3" and n_cols > 4:
            wmo_life = parse_number(padded[4])
            if wmo_life is not None:
                lifetime = wmo_life
        # GWP100 = LAST column, but skip if last is the H2013 GWP fallback only
        gwp100 = parse_number(padded[n_cols - 1])
        if gwp100 is None and n_cols > 1:
            # Try penultimate (the H2013 column)
            gwp100 = parse_number(padded[n_cols - 2])
        if not name or not formula or gwp100 is None or gwp100 <= 0:
            continue
        rows.append({
            "identifier": name,
            "formula": formula,
            "cas": cas,
            "gwp100": gwp100,
            "lifetime_years": lifetime,
            "source": "Hodnebrog_2020",
            "source_table_ref": f"RoG_2020_{table_label.replace(' ', '_')}",
        })
    df = pd.DataFrame(rows)
    log.info(f"  parsed {len(df)} valid rows")
    if len(df):
        log.info(f"    GWP100 range: {df['gwp100'].min()} - {df['gwp100'].max()}")
        log.info(f"    sample:")
        for _, r in df.head(3).iterrows():
            log.info(f"      {r['identifier'][:30]:30s}  {r['formula']:15s}  CAS={r['cas']}  GWP={r['gwp100']:8g}  τ={r['lifetime_years']}")
    return df


# %% Parse Tables 3 + 5
log.info("=" * 70)
log.info("Step 1: Parse Hodnebrog Tables 3 + 5")
log.info("=" * 70)

tbl3 = parse_hodnebrog_table(INPUT_DIR / "jats" / "tables" / "rog20236-tbl-0003.csv", "Table 3")
tbl5 = parse_hodnebrog_table(INPUT_DIR / "jats" / "tables" / "rog20236-tbl-0005.csv", "Table 5")

tbl3.to_csv(PROCESSED_DIR / "hodnebrog_table3.csv", index=False)
tbl5.to_csv(PROCESSED_DIR / "hodnebrog_table5.csv", index=False)
log.info(f"Hodnebrog parsed total: {len(tbl3) + len(tbl5)} rows (with overlap)")


# %% Combine Tables 3 + 5 (Table 5 takes precedence — more comprehensive)
hodnebrog_all = pd.concat([tbl5, tbl3], ignore_index=True)
hodnebrog_all["_formula_norm"] = hodnebrog_all["formula"].astype(str).str.upper().str.replace(r"\s+", "", regex=True)
hodnebrog_all = hodnebrog_all.drop_duplicates(subset=["_formula_norm"], keep="first")
log.info(f"Hodnebrog after dedup (within Hodnebrog): {len(hodnebrog_all)} rows")


# %% Load existing extended dataset
log.info("=" * 70)
log.info("Step 2: Load existing extended dataset")
log.info("=" * 70)

# The extend job's output is mounted at /deps/{extend_job_id}/
# Use a glob to find the deps dir without hardcoding the job ID
import glob as _glob
deps_candidates = _glob.glob("/deps/*/processed/gwp_extended.csv")
log.info(f"  deps candidates: {deps_candidates}")
if deps_candidates:
    ext_path = Path(deps_candidates[0])
else:
    # fallback - maybe single-parent path
    ext_path = INPUT_DIR / "processed" / "gwp_extended.csv"
log.info(f"  base: {ext_path} exists={ext_path.exists()}")
ext_df = pd.read_csv(ext_path)
if "log10_gwp100" in ext_df.columns:
    ext_df = ext_df.drop(columns=["log10_gwp100"])
log.info(f"  base rows: {len(ext_df)}")


# %% Merge - Hodnebrog "this work" GWP authoritative for halocarbons
log.info("=" * 70)
log.info("Step 3: Merge")
log.info("=" * 70)

hodnebrog_keep = hodnebrog_all.drop(columns=["_formula_norm"])
combined = pd.concat([ext_df, hodnebrog_keep], ignore_index=True)
log.info(f"After concat: {len(combined)}")

combined["_formula_norm"] = combined["formula"].astype(str).str.upper().str.replace(r"\s+", "", regex=True)

# Priority for GWP100 source: Hodnebrog 2020 (the most recent, comprehensive, "this work")
# > IPCC AR6 (which incorporates Hodnebrog 2013, slightly older but more conservative)
# > others
combined["_priority"] = combined["source"].map({
    "Hodnebrog_2020": 0,
    "IPCC_AR6": 1,
    "WMO_2022": 2,
    "Tokuhashi_2018": 3,
    "Tokuhashi_2024": 3,
    "Antinolo_2020": 3,
    "3M_safety_data_sheet": 4,
    "Honeywell_TDS": 5,
    "Solvay_TDS": 5,
}).fillna(9)

before = len(combined)
combined = combined.sort_values("_priority").drop_duplicates(subset=["_formula_norm"], keep="first")
log.info(f"After dedup: {len(combined)} (dropped {before - len(combined)})")

combined = combined.drop(columns=["_formula_norm", "_priority"])
combined = combined.dropna(subset=["gwp100"])
combined = combined[combined["gwp100"] > 0]
combined["log10_gwp100"] = np.log10(combined["gwp100"].astype(float))

combined.to_csv(PROCESSED_DIR / "gwp_full.csv", index=False)


# %% Summary
report = {
    "hodnebrog_tbl3_rows": len(tbl3),
    "hodnebrog_tbl5_rows": len(tbl5),
    "hodnebrog_unique_after_dedup": len(hodnebrog_all),
    "base_extended_rows": len(ext_df),
    "final_unified_rows": len(combined),
    "by_source": combined["source"].value_counts().to_dict(),
    "with_cas": int(combined["cas"].notna().sum()),
    "gwp100_range": [float(combined["gwp100"].min()), float(combined["gwp100"].max())],
    "log10_gwp100_range": [float(combined["log10_gwp100"].min()), float(combined["log10_gwp100"].max())],
    "lifetime_known": int(combined["lifetime_years"].notna().sum()),
}
log.info("=" * 70)
log.info("FINAL")
log.info("=" * 70)
for k, v in report.items():
    log.info(f"  {k}: {v}")

with (PROCESSED_DIR / "gwp_full_report.json").open("w") as f:
    json.dump(report, f, indent=2)

final = {
    "status": "completed",
    "summary": report,
    "next_phase": "02_smiles_resolution.py + 03_dataset_assembly.py (scaffold-balanced split with chemprop's astartes)",
    "outputs": [
        "processed/gwp_full.csv",
        "processed/hodnebrog_table3.csv",
        "processed/hodnebrog_table5.csv",
    ],
}
with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump(final, f, indent=2)
log.info("DONE")
