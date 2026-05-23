#!/usr/bin/env python3
"""
Create standardized Element.UPF symlinks for SSSP pseudopotentials.

SSSP 1.3.0 uses multiple naming conventions:
  PSLibrary:  Si.pbe-n-rrkjus_psl.1.0.0.UPF   (Element.xxx.UPF)
  GBRV:       li_pbe_v1.4.uspp.F.UPF           (lowercase element_xxx.UPF)
  ONCV:       Ag_ONCV_PBE-1.0.oncvpsp.upf      (Element_xxx.upf)
  PAW:        Cu.paw.z_11.ld1.psl.v1.0.0-low.upf

Without symlinks, referencing "Li.UPF" in pw.x input fails because the
actual file is "li_pbe_v1.4.uspp.F.UPF". This creates Element.UPF links
for ALL elements, enabling uniform access.

BUILD FAILS (exit 1) if any critical element is missing.
"""
import os, sys, json

PSEUDO_DIR = os.environ.get('PSEUDO_DIR', '/opt/apps/qe/7.3/pseudo')
os.chdir(PSEUDO_DIR)

ELEMENTS = {
    'H','He','Li','Be','B','C','N','O','F','Ne','Na','Mg','Al','Si','P','S','Cl','Ar',
    'K','Ca','Sc','Ti','V','Cr','Mn','Fe','Co','Ni','Cu','Zn','Ga','Ge','As','Se','Br','Kr',
    'Rb','Sr','Y','Zr','Nb','Mo','Tc','Ru','Rh','Pd','Ag','Cd','In','Sn','Sb','Te','I','Xe',
    'Cs','Ba','La','Ce','Pr','Nd','Pm','Sm','Eu','Gd','Tb','Dy','Ho','Er','Tm','Yb','Lu',
    'Hf','Ta','W','Re','Os','Ir','Pt','Au','Hg','Tl','Pb','Bi','Po','At','Rn','Fr','Ra',
    'Ac','Th','Pa','U','Np','Pu','Am','Cm','Bk','Cf','Es','Fm','Md','No','Lr'}
ELEM_LOWER = {e.lower(): e for e in ELEMENTS}

upf_files = sorted(f for f in os.listdir('.') if f.lower().endswith('.upf') and not os.path.islink(f))
print(f"Scanning {len(upf_files)} UPF files in {PSEUDO_DIR}")

# Map each element to its best PP file (prefer USPP over PAW for consistency)
elem_map = {}
for f in upf_files:
    elem = None
    for sep in ('.', '_', '-'):
        cand = f.split(sep)[0]
        if cand in ELEMENTS:
            elem = cand
            break
        if cand.lower() in ELEM_LOWER:
            elem = ELEM_LOWER[cand.lower()]
            break
    if elem is None:
        print(f"  SKIP: {f}")
        continue
    if elem not in elem_map:
        elem_map[elem] = f
    else:
        cur, new = elem_map[elem].lower(), f.lower()
        cur_uspp = 'uspp' in cur or 'rrkjus' in cur
        new_uspp = 'uspp' in new or 'rrkjus' in new
        if new_uspp and not cur_uspp:
            elem_map[elem] = f

# Write JSON map for programmatic lookups
with open('element_pp_map.json', 'w') as fh:
    json.dump(dict(sorted(elem_map.items())), fh, indent=2)
print(f"Mapped {len(elem_map)} elements to PP files")

# Create Element.UPF symlinks
created = 0
for elem, filename in sorted(elem_map.items()):
    link = f"{elem}.UPF"
    if os.path.exists(link):
        if os.path.islink(link):
            print(f"  EXISTS (link): {link} -> {os.readlink(link)}")
        else:
            print(f"  EXISTS (file): {link}")
    else:
        os.symlink(filename, link)
        print(f"  SYMLINK: {link} -> {filename}")
        created += 1
print(f"Created {created} new symlinks")

# Verify critical elements for materials science
CRITICAL = ['Li','Na','Be','Cu','Ti','Si','C','N','O','H','Fe','K','Mg','Ca','Al','Zn','P','S','F','Cl']
missing = [e for e in CRITICAL if e not in elem_map]
if missing:
    print(f"FATAL: Missing critical elements: {missing}", file=sys.stderr)
    sys.exit(1)
print(f"All {len(CRITICAL)} critical elements verified present.")
