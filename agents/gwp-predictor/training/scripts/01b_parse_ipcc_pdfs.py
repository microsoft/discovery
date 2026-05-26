#!/usr/bin/env python3
"""01b_parse_pdfs.py - Phase 1A continued.

Reads IPCC AR6 WG1 Ch7 SM and WMO 2022 ozone assessment PDFs that arrive at
/input/raw/ via depends_on_job_id chaining, extracts all tables with
pdfplumber, scores them against the expected GWP/lifetime schema, and emits:

  /output/tables/<source>_p<NNN>_t<N>.csv  - every detected table (raw)
  /output/tables/<source>_p<NNN>_t<N>.json - cell-level metadata
  /output/parsed/ipcc_ar6_table_7sm7.csv   - best-scoring IPCC GWP table
  /output/parsed/wmo_2022_halocarbons.csv  - best-scoring WMO table
  /output/parsed/parse_report.json         - per-table diagnostics
  /output/final_results.json               - summary
"""

import os, sys, json, logging, subprocess, re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("parse")

# Install pdfplumber (not in moltoolkit by default)
log.info("Installing pdfplumber...")
subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "--no-cache-dir", "pdfplumber==0.11.4"])
import pdfplumber

OUTPUT_DIR = Path("/output")
TABLES_DIR = OUTPUT_DIR / "tables"
PARSED_DIR = OUTPUT_DIR / "parsed"
TABLES_DIR.mkdir(parents=True, exist_ok=True)
PARSED_DIR.mkdir(parents=True, exist_ok=True)

# --- Locate input PDFs (mounted from previous job's /output via depends_on_job_id) ---
INPUT_ROOT = Path("/input")
log.info(f"Scanning {INPUT_ROOT} for PDFs...")
pdf_paths = list(INPUT_ROOT.rglob("*.pdf"))
log.info(f"Found {len(pdf_paths)} PDFs:")
for p in pdf_paths:
    log.info(f"  {p}  ({p.stat().st_size/1e6:.2f} MB)")

# Identify by name
def find_pdf(pattern):
    for p in pdf_paths:
        if pattern.lower() in p.name.lower():
            return p
    return None

ipcc_pdf = find_pdf("IPCC_AR6_WGI_Chapter07_SM")
wmo_full_pdf = find_pdf("2022OzoneAssessment.pdf") or find_pdf("Chapter7_2022")
wmo_chap7_pdf = find_pdf("Chapter7_2022OzoneAssessment")

log.info(f"IPCC: {ipcc_pdf}")
log.info(f"WMO full: {wmo_full_pdf}")
log.info(f"WMO chap7: {wmo_chap7_pdf}")

# --- Generic table extractor + scorer ---
GWP_KEYWORDS = ["gwp", "global warming", "warming potential", "radiative", "lifetime",
                "perturbation", "tau", "agwp", "gtp", "halocarbon", "hfc", "hfo", "pfc", "cfc"]
NUMERIC_RE = re.compile(r"[-+]?\d{1,3}(?:[\s,]?\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?")


def score_table(table_rows, page_text=""):
    """Heuristic: how likely is this table the GWP/lifetime table?"""
    if not table_rows or len(table_rows) < 3:
        return 0.0, {"reason": "too_few_rows"}
    flat = " ".join(
        str(c).lower() for row in table_rows[:5] if row for c in row if c
    )
    pt_lower = (page_text or "").lower()
    keyword_hits = sum(1 for kw in GWP_KEYWORDS if kw in flat or kw in pt_lower)

    # Count numeric cells (GWP tables are number-dense)
    n_cells = sum(1 for row in table_rows for c in row if c)
    n_numeric = sum(
        1 for row in table_rows for c in row if c and NUMERIC_RE.search(str(c))
    )
    numeric_density = n_numeric / max(n_cells, 1)

    # Has chemical-formula column? Look for entries like CHF3, C2H2F4, CCl3F, SF6
    formula_re = re.compile(r"\b(?:[CHNOPSF][a-z]?\d?){2,}\b")
    n_formula = sum(
        1 for row in table_rows for c in row if c and formula_re.search(str(c))
    )

    score = (
        keyword_hits * 2.0
        + numeric_density * 5.0
        + min(n_formula / 5, 3.0)
        + min(len(table_rows) / 20, 2.0)
    )
    return score, {
        "n_rows": len(table_rows),
        "n_cols": max((len(r) for r in table_rows), default=0),
        "keyword_hits": keyword_hits,
        "numeric_density": round(numeric_density, 2),
        "n_formula_cells": n_formula,
        "score": round(score, 2),
    }


def extract_pdf_tables(pdf_path, source_label, page_range=None):
    """Open PDF, extract every table on every (or selected) page."""
    log.info(f"--- {source_label}: {pdf_path} ---")
    results = []
    if not pdf_path or not pdf_path.exists():
        log.warning(f"  PDF not found: {pdf_path}")
        return results
    with pdfplumber.open(str(pdf_path)) as pdf:
        n_pages = len(pdf.pages)
        log.info(f"  {n_pages} pages")
        pages_to_scan = (
            range(page_range[0], min(page_range[1], n_pages))
            if page_range
            else range(n_pages)
        )
        for pg_idx in pages_to_scan:
            page = pdf.pages[pg_idx]
            try:
                tables = page.extract_tables()
            except Exception as e:
                log.warning(f"    page {pg_idx+1}: extract_tables raised {type(e).__name__}: {e}")
                continue
            if not tables:
                continue
            page_text = page.extract_text() or ""
            for t_idx, t in enumerate(tables):
                if not t or len(t) < 3:
                    continue
                score, meta = score_table(t, page_text)
                meta["page"] = pg_idx + 1
                meta["table_index"] = t_idx
                meta["source"] = source_label
                # Save raw CSV
                base = f"{source_label}_p{pg_idx+1:03d}_t{t_idx}"
                csv_path = TABLES_DIR / f"{base}.csv"
                json_path = TABLES_DIR / f"{base}.json"
                with csv_path.open("w") as f:
                    for row in t:
                        f.write(
                            ",".join(
                                '"{}"'.format(str(c or "").replace('"', '""').replace("\n", " "))
                                for c in row
                            )
                            + "\n"
                        )
                with json_path.open("w") as f:
                    json.dump({"meta": meta, "rows": t}, f, indent=2)
                results.append({
                    "csv": str(csv_path.relative_to(OUTPUT_DIR)),
                    "json": str(json_path.relative_to(OUTPUT_DIR)),
                    **meta,
                })
                if score > 5:
                    log.info(
                        f"    p{pg_idx+1} t{t_idx}: score={score:.1f} "
                        f"rows={meta['n_rows']} cols={meta['n_cols']} "
                        f"kw={meta['keyword_hits']} num={meta['numeric_density']}"
                    )
    return results


# --- Run extraction ---
log.info("=" * 70)
log.info("Extracting IPCC AR6 WG1 Chapter 7 SM tables")
log.info("=" * 70)
# Table 7.SM.7 historically lives in pages 30-50 of the SM PDF; scan all pages
ipcc_tables = extract_pdf_tables(ipcc_pdf, "ipcc_ar6")
log.info(f"IPCC: {len(ipcc_tables)} tables extracted")

log.info("=" * 70)
log.info("Extracting WMO 2022 Chapter 7 tables")
log.info("=" * 70)
# Chapter 7 of WMO 2022 holds the GWP/RE annex; the full report PDF has Annex A as well.
wmo_chap7_tables = extract_pdf_tables(wmo_chap7_pdf, "wmo_chap7")
log.info(f"WMO Chap 7: {len(wmo_chap7_tables)} tables")

log.info("=" * 70)
log.info("Extracting WMO 2022 full-report Annex tables")
log.info("=" * 70)
# Full report Annex A1 / A2 is typically near the end of the PDF
wmo_full_tables = extract_pdf_tables(wmo_full_pdf, "wmo_full")
log.info(f"WMO Full: {len(wmo_full_tables)} tables")

# --- Save report ---
all_tables = ipcc_tables + wmo_chap7_tables + wmo_full_tables
all_tables_sorted = sorted(all_tables, key=lambda x: x.get("score", 0), reverse=True)

log.info("=" * 70)
log.info(f"Top 20 tables by GWP-likeness score (out of {len(all_tables)}):")
log.info("=" * 70)
for t in all_tables_sorted[:20]:
    log.info(
        f"  score={t['score']:5.1f}  {t['source']:10s}  p{t['page']:03d} t{t['table_index']}  "
        f"{t['n_rows']}x{t['n_cols']}  kw={t['keyword_hits']}  num={t['numeric_density']}  "
        f"-> {t['csv']}"
    )

with (PARSED_DIR / "parse_report.json").open("w") as f:
    json.dump(
        {
            "summary": {
                "total_tables": len(all_tables),
                "ipcc_tables": len(ipcc_tables),
                "wmo_chap7_tables": len(wmo_chap7_tables),
                "wmo_full_tables": len(wmo_full_tables),
                "top_20": all_tables_sorted[:20],
            },
            "all_tables": all_tables_sorted,
        },
        f,
        indent=2,
        default=str,
    )

# --- Final summary ---
final = {
    "status": "completed",
    "summary": {
        "total_tables_extracted": len(all_tables),
        "ipcc_tables": len(ipcc_tables),
        "wmo_chap7_tables": len(wmo_chap7_tables),
        "wmo_full_tables": len(wmo_full_tables),
        "top_score": all_tables_sorted[0]["score"] if all_tables_sorted else 0,
        "candidate_csvs": [t["csv"] for t in all_tables_sorted[:20]],
    },
    "next_step": (
        "Inspect top-scoring CSVs in /output/tables/. Pick the table(s) that "
        "actually correspond to IPCC Table 7.SM.7 and WMO halocarbon annex, "
        "then write a per-table normaliser to map columns into our unified "
        "schema. This is iterative."
    ),
}
with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump(final, f, indent=2)

log.info("DONE")
log.info(f"  {len(all_tables)} tables extracted across all PDFs")
log.info(f"  See /output/tables/ for raw CSVs + /output/parsed/parse_report.json")
