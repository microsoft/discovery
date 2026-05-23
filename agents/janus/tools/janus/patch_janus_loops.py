#!/usr/bin/env python3
"""Patch janus/janus.py to add iteration caps on the exploration and exploitation while loops.

This script is run ONCE at Docker build time (in the Dockerfile) to fix the infinite-loop
bug in the upstream janus-ga 1.0.3 library.

Usage in Dockerfile:
    RUN python3 /app/patch_janus_loops.py
"""

import re
import site
import os

# Find the installed janus.py
janus_paths = [
    os.path.join(d, "janus", "janus.py")
    for d in site.getsitepackages() + [site.getusersitepackages()]
    if os.path.isfile(os.path.join(d, "janus", "janus.py"))
]
if not janus_paths:
    for root in ["/usr/lib", "/usr/local/lib"]:
        for dirpath, _, filenames in os.walk(root):
            if "janus.py" in filenames and "janus" in dirpath:
                candidate = os.path.join(dirpath, "janus.py")
                with open(candidate) as f:
                    if "class JANUS" in f.read():
                        janus_paths.append(candidate)

if not janus_paths:
    raise FileNotFoundError("Could not find janus/janus.py in site-packages")

janus_file = janus_paths[0]
print(f"Patching: {janus_file}")

with open(janus_file, "r") as f:
    lines = f.readlines()

source = "".join(lines)

# Verify we have the right file
assert "class JANUS" in source, "Not the right janus.py"
assert "while len(explr_smiles)" in source, "Exploration loop not found"
assert "while len(exploit_smiles)" in source, "Exploitation loop not found"

# ============================================================
# Strategy: work line-by-line, inserting code after specific marker lines.
# This is more robust than exact string matching against multiline blocks.
# ============================================================

patched_lines = []
patch_count = 0

# Add MAX_LOOP_ITERS constant after the last import
imports_done = False

i = 0
while i < len(lines):
    line = lines[i]
    patched_lines.append(line)

    # Insert constant after the last "from .xxx import" line
    if not imports_done and line.strip().startswith("from .") and "import" in line:
        # Check if next line is NOT an import (end of import block)
        if i + 1 < len(lines) and not lines[i + 1].strip().startswith(("from ", "import ")):
            patched_lines.append("\n")
            patched_lines.append("# --- Discovery platform patch: iteration cap for exploration/exploitation loops ---\n")
            patched_lines.append("MAX_LOOP_ITERS = 500\n")
            patched_lines.append("\n")
            imports_done = True
            patch_count += 1
            print("  Inserted MAX_LOOP_ITERS = 500 after imports")

    # Patch exploration timeout: find the line that prints "Exploration: ... iterations"
    # and add a break condition after the print block
    if "Exploration:" in line and "iterations of filtering" in line:
        # This might be a continuation line (backslash). Consume continuation lines.
        while line.rstrip().endswith("\\"):
            i += 1
            line = lines[i]
            patched_lines.append(line)
        # Now insert the iteration cap check
        # Determine indentation from the timeout_counter line (2 lines back typically)
        indent = "                "  # 16 spaces (4 levels of 4-space indent)
        patched_lines.append(f"{indent}if timeout_counter >= MAX_LOOP_ITERS:\n")
        patched_lines.append(f"{indent}    needed = self.generation_size - len(keep_smiles)\n")
        patched_lines.append(f"{indent}    print(f'Exploration: reached {{MAX_LOOP_ITERS}} iteration cap. '\n")
        patched_lines.append(f"{indent}          f'Got {{len(explr_smiles)}}/{{needed}} candidates. Breaking.')\n")
        patched_lines.append(f"{indent}    import random as _rnd\n")
        patched_lines.append(f"{indent}    while len(explr_smiles) < needed:\n")
        patched_lines.append(f"{indent}        explr_smiles.append(_rnd.choice(keep_smiles))\n")
        patched_lines.append(f"{indent}    break\n")
        patch_count += 1
        print("  Inserted exploration loop iteration cap")

    # Patch exploitation timeout: same approach
    if "Exploitation:" in line and "iterations of filtering" in line:
        while line.rstrip().endswith("\\"):
            i += 1
            line = lines[i]
            patched_lines.append(line)
        indent = "                "
        patched_lines.append(f"{indent}if timeout_counter >= MAX_LOOP_ITERS:\n")
        patched_lines.append(f"{indent}    print(f'Exploitation: reached {{MAX_LOOP_ITERS}} iteration cap. '\n")
        patched_lines.append(f"{indent}          f'Got {{len(exploit_smiles)}}/{{self.generation_size}} candidates. Breaking.')\n")
        patched_lines.append(f"{indent}    import random as _rnd\n")
        patched_lines.append(f"{indent}    pad_source = population_sort[0:max(self.top_mols, 5)].tolist()\n")
        patched_lines.append(f"{indent}    while len(exploit_smiles) < self.generation_size:\n")
        patched_lines.append(f"{indent}        exploit_smiles.append(_rnd.choice(pad_source))\n")
        patched_lines.append(f"{indent}    break\n")
        patch_count += 1
        print("  Inserted exploitation loop iteration cap")

    i += 1

assert patch_count >= 3, f"Expected at least 3 patches, only applied {patch_count}"

with open(janus_file, "w") as f:
    f.writelines(patched_lines)

print(f"\nSuccessfully applied {patch_count} patches to {janus_file}")
print(f"  - MAX_LOOP_ITERS = 500 constant")
print(f"  - Exploration while loop: break + pad after 500 iterations")
print(f"  - Exploitation while loop: break + pad after 500 iterations")