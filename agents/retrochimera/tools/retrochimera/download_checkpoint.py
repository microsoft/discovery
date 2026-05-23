#!/usr/bin/env python3
"""Download RetroChimera Pistachio checkpoint from Figshare.

Used during Docker build. Handles Figshare's 302 redirect to signed S3 URL
and the large file size (~4.2 GB).
"""
import os
import shutil
import sys
import time
import urllib.request
import zipfile

# Default Figshare URL for the Pistachio checkpoint.
# IMPORTANT: Use ndownloader.figshare.com (not figshare.com/ndownloader) to get
# a direct 302→S3 redirect. The main-domain path triggers an AWS WAF JavaScript
# challenge that fails in non-browser clients.
# Override via CHECKPOINT_URL env var if the file ID changes or moves.
_DEFAULT_URL = "https://ndownloader.figshare.com/files/59468882"
URL = os.environ.get("CHECKPOINT_URL", _DEFAULT_URL)
DEST_DIR = "/app/models/pistachio"
ZIP_PATH = "/app/models/pistachio.zip"
TMP_DIR = "/app/models/pistachio_tmp"

# Add browser-like User-Agent to get proper 302 redirect from Figshare
opener = urllib.request.build_opener()
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
]
urllib.request.install_opener(opener)

os.makedirs(DEST_DIR, exist_ok=True)

# Download with retries
for attempt in range(5):
    try:
        print(f"Download attempt {attempt + 1}/5...")
        urllib.request.urlretrieve(URL, ZIP_PATH)
        size = os.path.getsize(ZIP_PATH)
        print(f"Downloaded {size / 1024 / 1024:.1f} MB")
        if size > 1_000_000:  # > 1 MB means real data
            break
        print("File too small, retrying in 15s...")
        os.remove(ZIP_PATH)
        time.sleep(15)
    except Exception as e:
        print(f"Attempt {attempt + 1} failed: {e}")
        if os.path.exists(ZIP_PATH):
            os.remove(ZIP_PATH)
        time.sleep(15)
else:
    print("ERROR: Failed to download checkpoint after 5 attempts")
    print(f"  URL used: {URL}")
    print("  The Figshare file may have been removed or moved.")
    print("  Check https://github.com/microsoft/retrochimera#checkpoints-for-retrochimera-1")
    print("  for updated URLs, then rebuild with:")
    print("    docker build --build-arg CHECKPOINT_URL=<new-url> ...")
    sys.exit(1)
def _safe_extract(zip_obj: zipfile.ZipFile, target_dir: str) -> None:
    """Extract a zip safely, rejecting absolute paths and parent traversal."""
    target_root = os.path.realpath(target_dir)
    for member in zip_obj.infolist():
        member_name = member.filename
        # Reject absolute paths and Windows drive letters.
        if member_name.startswith(("/", "\\")) or (
            len(member_name) > 1 and member_name[1] == ":"
        ):
            raise RuntimeError(f"Refusing to extract absolute path: {member_name}")
        dest_path = os.path.realpath(os.path.join(target_root, member_name))
        if not (
            dest_path == target_root
            or dest_path.startswith(target_root + os.sep)
        ):
            raise RuntimeError(
                f"Refusing to extract path outside target dir: {member_name}"
            )
        # Reject symlinks (mode bits in external_attr for unix entries).
        mode = (member.external_attr >> 16) & 0xFFFF
        if mode and (mode & 0o170000) == 0o120000:
            raise RuntimeError(f"Refusing to extract symlink entry: {member_name}")
    zip_obj.extractall(target_dir)


# Extract
print("Extracting zip file...")
with zipfile.ZipFile(ZIP_PATH) as z:
    names = z.namelist()
    print(f"Zip contains {len(names)} entries")
    _safe_extract(z, TMP_DIR)

print("Extraction complete")

# Move to final location, handling nested directory structures
top_items = os.listdir(TMP_DIR)
if len(top_items) == 1 and os.path.isdir(os.path.join(TMP_DIR, top_items[0])):
    # Single top-level directory in zip
    nested = os.path.join(TMP_DIR, top_items[0])
    for item in os.listdir(nested):
        shutil.move(os.path.join(nested, item), os.path.join(DEST_DIR, item))
else:
    for item in top_items:
        shutil.move(os.path.join(TMP_DIR, item), os.path.join(DEST_DIR, item))

os.remove(ZIP_PATH)
shutil.rmtree(TMP_DIR, ignore_errors=True)

# Verify
print("Checkpoint contents:")
for item in sorted(os.listdir(DEST_DIR)):
    p = os.path.join(DEST_DIR, item)
    if os.path.isdir(p):
        n = len(os.listdir(p))
        print(f"  DIR:  {item}/ ({n} files)")
    else:
        sz = os.path.getsize(p) / 1024 / 1024
        print(f"  FILE: {item} ({sz:.1f} MB)")

models_json = os.path.join(DEST_DIR, "models.json")
if os.path.exists(models_json):
    print("PASS: models.json found")
else:
    print("FAIL: models.json not found")
    sys.exit(1)
