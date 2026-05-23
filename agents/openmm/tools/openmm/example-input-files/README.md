# Example Input Files for OpenMM

This directory contains example molecular structures for testing OpenMM simulations on the Discovery platform.

## Files

| File | System | Atoms | Use Case |
|------|--------|-------|----------|
| `alanine_dipeptide.pdb` | ACE-ALA-NME | 22 | Quick minimization, short MD, implicit solvent testing |

## Recommended Tests

### Quick Test (< 1 minute)
```python
from openmm_utils import quick_setup, fix_pdb, create_system, setup_simulation, run_minimization
quick_setup()
fixed = fix_pdb('alanine_dipeptide.pdb')
sys_data = create_system(fixed, box_padding_nm=0.8)
sim = setup_simulation(sys_data['system'], sys_data['topology'], sys_data['positions'])
result = run_minimization(sim)
print(f"Energy: {result['final_energy_kcal']:.1f} kcal/mol")
```

### Implicit Solvent (< 1 minute)
```python
from openmm_utils import quick_setup, fix_pdb, create_system, setup_simulation, run_minimization, run_production
quick_setup()
fixed = fix_pdb('alanine_dipeptide.pdb')
sys_data = create_system(fixed, water_model='implicit/gbn2.xml',
                         nonbonded_method='NoCutoff', solvate=False)
sim = setup_simulation(sys_data['system'], sys_data['topology'], sys_data['positions'])
run_minimization(sim)
prod = run_production(sim, nsteps=50000)
print(f"Performance: {prod['ns_per_day']:.1f} ns/day")
```

### Full MD Pipeline (5-10 minutes on GPU)
```python
from openmm_utils import (
    quick_setup, quick_finish, save_final_results,
    fix_pdb, create_system, setup_simulation,
    run_minimization, run_nvt, run_npt, run_production,
    parse_log, compute_rmsd, plot_energy, plot_rmsd,
)
quick_setup()
fixed = fix_pdb('alanine_dipeptide.pdb')
sys_data = create_system(fixed)
sim = setup_simulation(sys_data['system'], sys_data['topology'], sys_data['positions'])
run_minimization(sim)
run_nvt(sim, nsteps=10000)
run_npt(sim, nsteps=10000)
prod = run_production(sim, nsteps=100000, report_interval=1000)
log_data = parse_log('production.log')
rmsd = compute_rmsd('production.dcd', 'minimized.pdb')
plot_energy(log_data, 'energy.png')
plot_rmsd(rmsd, 'rmsd.png')
save_final_results({'rmsd_mean_nm': rmsd['mean_nm'], 'ns_per_day': prod['ns_per_day']},
                   {'energy': 'energy.png', 'rmsd': 'rmsd.png'})
quick_finish()
```
