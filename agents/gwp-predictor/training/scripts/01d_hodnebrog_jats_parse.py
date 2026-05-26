#!/usr/bin/env python3
"""01j_jats_parse.py - Parse JATS XML directly from the OAI service.

The OAI XML at PMC7518032_oai.xml from job bdb8881e is 548 KB - that's the
full article body in JATS format including every inline table. This is
likely sufficient on its own; we don't need the supplementary CSV.

Strategy:
  1. Re-fetch the OAI XML (cleaner than chaining inputs).
  2. Try three tarball URL patterns just to also have the SI files.
  3. Parse JATS XML for every <table-wrap> and emit per-table CSVs.
"""

import os, sys, json, logging, re, html, tarfile
from pathlib import Path
import xml.etree.ElementTree as ET
import requests
import ftplib, io

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("jats")

OUTPUT_DIR = Path("/output")
JATS_DIR = OUTPUT_DIR / "jats"
TABLES_DIR = JATS_DIR / "tables"
TAR_DIR = OUTPUT_DIR / "tar"
JATS_DIR.mkdir(parents=True, exist_ok=True)
TABLES_DIR.mkdir(parents=True, exist_ok=True)
TAR_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; MicrosoftDiscovery-gwp-predictor/1.0; mailto:discovery-catalog@microsoft.com)"
})


# %% Fetch the OAI XML
log.info("=" * 70)
log.info("Step 1: Fetch OAI JATS XML")
log.info("=" * 70)

oai_url = "https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:7518032&metadataPrefix=pmc"
log.info(f"  GET {oai_url}")
r = session.get(oai_url, timeout=180)
log.info(f"    status={r.status_code} bytes={len(r.content):,}")
if r.status_code != 200:
    log.error("    OAI fetch failed")
    sys.exit(1)
oai_path = JATS_DIR / "PMC7518032_oai.xml"
oai_path.write_bytes(r.content)


# %% Parse JATS tables from OAI XML
log.info("=" * 70)
log.info("Step 2: Parse JATS tables")
log.info("=" * 70)

xml_text = oai_path.read_text(encoding="utf-8", errors="replace")
# Strip namespaces (XPath becomes simple)
xml_text_ns = re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", xml_text)
xml_text_ns = re.sub(r'(?<![\w-])(?:xlink|mml|xsi|ali):', "", xml_text_ns)


def cell_text(el):
    out = []
    if el.text:
        out.append(el.text)
    for child in el:
        out.append(cell_text(child))
        if child.tail:
            out.append(child.tail)
    s = "".join(out)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


try:
    root = ET.fromstring(xml_text_ns)
except ET.ParseError as e:
    log.error(f"  XML parse error: {e}")
    sys.exit(1)

table_wraps = root.findall(".//table-wrap")
log.info(f"  Found {len(table_wraps)} <table-wrap> elements in JATS")

tables_meta = []
for tw in table_wraps:
    tw_id = tw.get("id", f"untitled_{len(tables_meta)}")
    label_el = tw.find("./label")
    caption_el = tw.find("./caption")
    label = cell_text(label_el) if label_el is not None else ""
    caption = cell_text(caption_el) if caption_el is not None else ""
    table_el = tw.find(".//table")
    if table_el is None:
        log.warning(f"    {tw_id}: no <table> child")
        continue
    rows = []
    for tr in table_el.findall(".//tr"):
        cells = [cell_text(c) for c in tr]
        if cells:
            rows.append(cells)
    if not rows:
        continue
    out_csv = TABLES_DIR / f"{tw_id}.csv"
    with out_csv.open("w") as f:
        for row in rows:
            f.write(",".join('"{}"'.format(c.replace('"', '""')) for c in row) + "\n")
    n_rows = len(rows)
    n_cols = max((len(r) for r in rows), default=0)
    tables_meta.append({
        "id": tw_id, "label": label, "caption": caption[:300],
        "n_rows": n_rows, "n_cols": n_cols, "csv": str(out_csv.relative_to(OUTPUT_DIR)),
    })
    log.info(f"    {tw_id}: {label[:30]} ({n_rows}x{n_cols})")
    log.info(f"      caption: {caption[:200]}")

with (JATS_DIR / "tables_meta.json").open("w") as f:
    json.dump(tables_meta, f, indent=2)


# %% Also try fetching the tarball
log.info("=" * 70)
log.info("Step 3: Try tarball URLs")
log.info("=" * 70)

# Try via real ftp protocol (ftplib)
try:
    log.info("  ftplib connection to ftp.ncbi.nlm.nih.gov...")
    ftp = ftplib.FTP("ftp.ncbi.nlm.nih.gov", timeout=120)
    ftp.login()  # anonymous
    log.info(f"  banner: {ftp.getwelcome()[:200]}")
    # Try the /pub/pmc/oa_package/4f/f0/PMC7518032.tar.gz path
    bio = io.BytesIO()
    ftp.cwd("/pub/pmc/oa_package/4f/f0")
    files = ftp.nlst()
    log.info(f"  /pub/pmc/oa_package/4f/f0 contents (first 20): {files[:20]}")
    target = None
    for f in files:
        if "7518032" in f:
            target = f
            break
    if target:
        log.info(f"  RETR {target}")
        ftp.retrbinary(f"RETR {target}", bio.write)
        ftp.quit()
        if bio.tell() > 1000 and bio.getvalue()[:2] == b"\x1f\x8b":
            tar_path = TAR_DIR / target
            tar_path.write_bytes(bio.getvalue())
            log.info(f"    OK saved {tar_path.relative_to(OUTPUT_DIR)} ({tar_path.stat().st_size:,} bytes)")
            # Extract
            with tarfile.open(tar_path, "r:gz") as tf:
                members = tf.getnames()
                log.info(f"    Tarball contents ({len(members)} members):")
                for m in members:
                    log.info(f"      {m}")
                extract_dir = TAR_DIR / "extracted"
                extract_dir.mkdir(exist_ok=True)
                tf.extractall(extract_dir, filter="data")
        else:
            log.warning(f"    bad/empty (head={bio.getvalue()[:8]})")
    else:
        log.warning(f"  PMC7518032.tar.gz not found in /pub/pmc/oa_package/4f/f0")
        # Walk a few neighbouring shards
        for shard in [files[i] for i in range(min(5, len(files)))]:
            log.info(f"    sample neighbour: {shard}")
        try:
            ftp.quit()
        except Exception:
            pass
except Exception as e:
    log.warning(f"  ftplib EXC: {type(e).__name__}: {e}")

# %% Final
final = {
    "status": "completed",
    "summary": {
        "n_tables_found": len(tables_meta),
        "tables": [(t["id"], t["label"][:30], t["n_rows"], t["n_cols"]) for t in tables_meta],
        "tarball_extracted": (TAR_DIR / "extracted").exists() and any((TAR_DIR / "extracted").rglob("*")),
    },
}
log.info("=" * 70)
log.info("DONE")
log.info(f"  Parsed {len(tables_meta)} tables to /output/jats/tables/")
with (OUTPUT_DIR / "final_results.json").open("w") as f:
    json.dump(final, f, indent=2)
