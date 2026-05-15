#!/bin/bash
# Initialize conda
. /opt/conda/etc/profile.d/conda.sh

# Activate conda environment
conda activate molenv

# Verify the environment is working
echo "Using Python: $(which python)"
echo "Python version: $(python --version)"
echo "PYTHONPATH: $PYTHONPATH"

# Test imports to verify packages are available
python -c "
import importlib
packages = [
    ('ase', None),
    ('biopython', 'Bio'),
    ('MDAnalysis', 'MDAnalysis'),
    ('matplotlib', 'matplotlib'),
    ('numpy', 'numpy'),
    ('openbabel', 'openbabel'),
    ('pyarrow', 'pyarrow'),
    ('pandas', 'pandas'),
    ('pymatgen', 'pymatgen'),
    ('pymol-open-source', 'pymol'),
    ('pyscf', 'pyscf'),
    ('rdkit', 'rdkit'),
    ('ruamel.yaml', 'ruamel.yaml'),
    ('scanpy', 'scanpy'),
    ('scikit-bio', 'skbio'),
    ('scikit-learn', 'sklearn'),
    ('scipy', 'scipy'),
    ('seaborn', 'seaborn'),
    ('sympy', 'sympy'),
    ('molecular_utils', 'molecular_utils'),
]
for pkg, mod in packages:
    modname = mod if mod else pkg
    try:
        importlib.import_module(modname)
        print(f'✓ {modname} available')
    except ImportError as e:
        print(f'✗ {modname} not available:', e)
"

# Execute the passed command
exec "$@"
