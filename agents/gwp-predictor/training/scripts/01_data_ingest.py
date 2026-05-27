#!/usr/bin/env python3
"""01_data_ingest.py - Phase 1A of gwp-predictor build.

Downloads IPCC AR6 WG1 Ch7 SM, Hodnebrog 2020 ACP SI, and WMO 2022 ozone
assessment data. Always emits a 60-row hand-curated anchor CSV regardless
of download success so downstream phases can always proceed.
"""

# %% Imports + setup
import os, sys, json, logging, time, hashlib
from pathlib import Path
from urllib.parse import urlparse

import requests
import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("ingest")

OUTPUT_DIR = Path("/output")
RAW_DIR = OUTPUT_DIR / "raw"
INTERIM_DIR = OUTPUT_DIR / "interim"
RAW_DIR.mkdir(parents=True, exist_ok=True)
INTERIM_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (compatible; MicrosoftDiscovery-gwp-predictor/1.0)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

report = {"sources": {}, "totals": {}, "errors": []}


def fetch(url: str, dest: Path, timeout: int = 120, retries: int = 3) -> dict:
    """Download a URL to dest, return status dict."""
    info = {"url": url, "dest": str(dest), "status": "pending"}
    for attempt in range(1, retries + 1):
        try:
            log.info(f"  GET (attempt {attempt}/{retries}) {url}")
            r = SESSION.get(url, timeout=timeout, allow_redirects=True)
            info["http_status"] = r.status_code
            info["content_type"] = r.headers.get("content-type", "")
            info["bytes"] = len(r.content)
            if r.status_code == 200 and len(r.content) > 1000:
                dest.write_bytes(r.content)
                info["status"] = "ok"
                info["sha256"] = hashlib.sha256(r.content).hexdigest()[:16]
                log.info(f"    OK {info['bytes']:,} bytes  sha256={info['sha256']}")
                return info
            else:
                info["status"] = f"http_{r.status_code}_or_short"
                log.warning(f"    {r.status_code}  {len(r.content)} bytes")
        except Exception as e:
            info["status"] = f"error: {type(e).__name__}: {e}"
            log.warning(f"    EXCEPTION {type(e).__name__}: {e}")
            time.sleep(2 ** attempt)
    return info


# %% Source 1: IPCC AR6 WG1 Chapter 7 Supplementary
log.info("=" * 70 + "\nSource 1: IPCC AR6 WG1 Chapter 7 Supplementary\n" + "=" * 70)
ipcc_attempts = []
for url in [
    "https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_Chapter07_SM.pdf",
    "https://www.ipcc.ch/report/ar6/wg1/downloads/factsheets/IPCC_AR6_WGI_FactSheet_GHG.pdf",
]:
    fname = Path(urlparse(url).path).name
    ipcc_attempts.append(fetch(url, RAW_DIR / fname))
report["sources"]["ipcc_ar6"] = {"attempts": ipcc_attempts}

# %% Source 2: Hodnebrog 2020 (ACP)
log.info("=" * 70 + "\nSource 2: Hodnebrog 2020 (ACP)\n" + "=" * 70)
hodnebrog_attempts = []
for url in [
    "https://acp.copernicus.org/articles/20/14681/2020/acp-20-14681-2020-supplement.pdf",
    "https://acp.copernicus.org/articles/20/14681/2020/acp-20-14681-2020.pdf",
]:
    fname = Path(urlparse(url).path).name
    hodnebrog_attempts.append(fetch(url, RAW_DIR / fname))
report["sources"]["hodnebrog_2020"] = {"attempts": hodnebrog_attempts}

# %% Source 3: WMO 2022 Ozone Assessment
log.info("=" * 70 + "\nSource 3: WMO 2022\n" + "=" * 70)
wmo_attempts = []
for url in [
    "https://csl.noaa.gov/assessments/ozone/2022/downloads/Annex.pdf",
    "https://csl.noaa.gov/assessments/ozone/2022/downloads/Chapter7_2022OzoneAssessment.pdf",
    "https://csl.noaa.gov/assessments/ozone/2022/downloads/2022OzoneAssessment.pdf",
]:
    fname = Path(urlparse(url).path).name
    wmo_attempts.append(fetch(url, RAW_DIR / fname))
report["sources"]["wmo_2022"] = {"attempts": wmo_attempts}

# %% Source 4: NOAA JPL19 backup tables (machine-readable text)
log.info("=" * 70 + "\nSource 4: NOAA JPL19 backup\n" + "=" * 70)
backup_attempts = []
for url in [
    "https://csl.noaa.gov/groups/csl5/jpldata/JPL19_Table-1A.txt",
    "https://csl.noaa.gov/groups/csl5/jpldata/JPL19_Table-1B.txt",
    "https://csl.noaa.gov/groups/csl5/jpldata/JPL19_Table-1C.txt",
]:
    fname = Path(urlparse(url).path).name
    backup_attempts.append(fetch(url, RAW_DIR / fname))
report["sources"]["noaa_jpl19"] = {"attempts": backup_attempts}

# %% Hand-curated anchor set (60 species spanning 5 orders of magnitude in GWP)
# Curated from IPCC AR6 Table 7.SM.7 + Hodnebrog 2020 Table 2.
log.info("=" * 70 + "\nEmbedding hand-curated anchor set (60 species)\n" + "=" * 70)

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

anchor_df = pd.DataFrame(
    ANCHOR,
    columns=["identifier", "cas", "formula", "gwp100", "lifetime_years", "source"],
)
anchor_df["gwp100_unc"] = pd.NA
anchor_df["lifetime_unc"] = pd.NA
anchor_df["source_table_ref"] = "anchor_curated_v1"
anchor_df["identifier_in_source"] = anchor_df["identifier"]
anchor_df.to_csv(INTERIM_DIR / "anchor_curated.csv", index=False)
log.info(f"Anchor set: {len(anchor_df)} species")
log.info(f"  GWP range: {anchor_df['gwp100'].min()} - {anchor_df['gwp100'].max()}")
log10_gwp = np.log10(anchor_df["gwp100"].astype(float))
log.info(f"  log10(GWP) range: {log10_gwp.min():.2f} - {log10_gwp.max():.2f}")

report["sources"]["anchor_curated"] = {
    "n_rows": len(anchor_df),
    "min_gwp": float(anchor_df["gwp100"].min()),
    "max_gwp": float(anchor_df["gwp100"].max()),
    "log10_gwp_min": float(log10_gwp.min()),
    "log10_gwp_max": float(log10_gwp.max()),
    "by_source": anchor_df["source"].value_counts().to_dict(),
}

# %% Inspect downloads
log.info("=" * 70 + "\nInspecting downloaded artefacts\n" + "=" * 70)
parsed_summary = []
for raw_file in sorted(RAW_DIR.glob("*")):
    size_mb = raw_file.stat().st_size / 1e6
    head = raw_file.read_bytes()[:8]
    is_pdf = head.startswith(b"%PDF")
    parsed_summary.append({
        "file": raw_file.name,
        "size_mb": round(size_mb, 2),
        "type": "pdf" if is_pdf else "text/other",
    })
    log.info(f"  {raw_file.name}: {size_mb:.2f} MB type={'pdf' if is_pdf else 'text/other'}")
    if "JPL19" in raw_file.name and not is_pdf:
        try:
            txt = raw_file.read_text(encoding="utf-8", errors="replace")
            log.info(f"    First 25 lines of {raw_file.name}:")
            for line in txt.splitlines()[:25]:
                log.info(f"      {line[:120]}")
        except Exception as e:
            log.warning(f"    parse failed: {e}")

report["parsed_summary"] = parsed_summary

# %% Assemble unified interim
log.info("=" * 70 + "\nAssembling unified interim CSV\n" + "=" * 70)
unified = anchor_df.copy()
out_csv = INTERIM_DIR / "gwp_unified.csv"
unified.to_csv(out_csv, index=False)
log.info(f"Wrote unified interim: {out_csv} ({len(unified)} rows)")

report["totals"]["unified_n_rows"] = len(unified)
report["totals"]["unified_sources"] = unified["source"].value_counts().to_dict()

# %% Save reports
with (INTERIM_DIR / "ingest_report.json").open("w") as f:
    json.dump(report, f, indent=2, default=str)

final = {
    "status": "completed",
    "summary": {
        "anchor_rows": len(anchor_df),
        "unified_rows": len(unified),
        "live_download_success_count": sum(
            1 for src in report["sources"].values()
            for a in src.get("attempts", [])
            if a.get("status") == "ok"
        ),
        "live_download_attempts": sum(
            len(src.get("attempts", []))
            for src in report["sources"].values()
        ),
        "raw_files": [p.name for p in sorted(RAW_DIR.glob("*"))],
        "interim_files": [p.name for p in sorted(INTERIM_DIR.glob("*"))],
    },
    "next_phase": "02_smiles_resolution.py",
    "notes": (
        "Phase 1A produced a 60-row anchor set covering all major chemistry "
        "classes (HFC, HFO, HFE, PFC, CFC, HCFC, halon, S/N halides). PDF "
        "parsing of IPCC SM tables to expand to ~400 rows happens in a "
        "follow-up if downloads succeeded."
    ),
}
with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump(final, f, indent=2)

log.info("DONE")
log.info(f"  Live downloads: {final['summary']['live_download_success_count']}/{final['summary']['live_download_attempts']} succeeded")
log.info(f"  Unified CSV: {len(unified)} rows in {out_csv}")
