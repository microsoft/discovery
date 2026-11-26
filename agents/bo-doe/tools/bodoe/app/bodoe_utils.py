"""bodoe_utils -- single import surface for the BO/DoE agent.

Usage inside a job script::

    from bodoe_utils import *

    quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir')
    space = make_mixture_space(['A', 'B', 'C', 'D'], total=10.0)
    objs = [Objective('viscosity', 'minimize'), Objective('modulus', 'maximize')]
    out = suggest_next(X, Y, space, objs, q=4)
    save_final_results(out, {'suggestions': 'suggestions.csv'})
    quick_finish()
"""

import numpy as np
import pandas as pd

from acquisition import (acquisition, chebyshev_scalarization,
                         expected_hypervolume_improvement, expected_improvement,
                         hypervolume, hypervolume_improvement,
                         log_expected_improvement, lower_confidence_bound,
                         pareto_front, pareto_mask, probability_below_threshold,
                         probability_of_improvement)
from doe import (design_diagnostics, doe_box_behnken, doe_central_composite,
                 doe_extreme_vertices, doe_fractional_factorial,
                 doe_full_factorial, doe_latin_hypercube,
                 doe_mixture_space_filling, doe_plackett_burman, doe_simplex_centroid,
                 doe_simplex_lattice, doe_sobol, generate_design)
from io_utils import (load_table, quick_finish, quick_setup, save_final_results,
                      save_table)
from models import GPSurrogate, available_backends, fit_gp, resolve_backend
from optimize import (BayesianOptimizer, Objective, run_bo_campaign,
                      run_de_baseline, run_random_search, scalarize,
                      select_diverse_subset, select_from_library, suggest_next)
from plots import (plot_benchmark, plot_convergence, plot_design, plot_parity,
                   plot_pareto, plot_ternary_mixture)
from space import (Parameter, ParameterSpace, make_mixture_space, make_space)

__version__ = "1.0.0"

__all__ = [
    # re-exported so `from bodoe_utils import *` scripts can use np/pd directly
    "np", "pd",
    # space
    "Parameter", "ParameterSpace", "make_space", "make_mixture_space",
    # doe
    "generate_design", "design_diagnostics", "doe_full_factorial",
    "doe_fractional_factorial", "doe_plackett_burman", "doe_central_composite",
    "doe_box_behnken", "doe_latin_hypercube", "doe_sobol", "doe_simplex_lattice",
    "doe_simplex_centroid", "doe_extreme_vertices", "doe_mixture_space_filling",
    # models
    "GPSurrogate", "fit_gp", "available_backends", "resolve_backend",
    # acquisition
    "acquisition", "expected_improvement", "log_expected_improvement",
    "probability_of_improvement", "lower_confidence_bound",
    "probability_below_threshold", "pareto_mask", "pareto_front", "hypervolume",
    "hypervolume_improvement", "expected_hypervolume_improvement",
    "chebyshev_scalarization",
    # optimize
    "Objective", "BayesianOptimizer", "suggest_next", "scalarize",
    "select_from_library", "select_diverse_subset",
    "run_bo_campaign", "run_random_search", "run_de_baseline",
    # plots
    "plot_convergence", "plot_pareto", "plot_design", "plot_parity",
    "plot_ternary_mixture", "plot_benchmark",
    # io
    "quick_setup", "quick_finish", "save_final_results", "load_table", "save_table",
]
