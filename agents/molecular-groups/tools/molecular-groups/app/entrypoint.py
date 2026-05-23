#!/usr/bin/env python3
"""
Entrypoint script for molecular-groups-tool.
Handles action-based execution for functional group and hazardous group identification.
"""

import os
import sys
import json
import glob
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional

# Add app directory to path for imports
sys.path.insert(0, '/app')

from rdkit import Chem, RDLogger

# Suppress RDKit C++ warnings (e.g. "Can't kekulize mol") — we do our own
# validation and report the specific SMILES that caused the issue.
RDLogger.DisableLog('rdApp.*')

# Import utility modules
import io_utils
from mol_hazardous_groups import identify_hazardous_groups, FG_SAFETY_FILTERS
from mol_functional_groups import identify_functional_groups as identify_fg, FUNCTIONAL_GROUPS

# Available actions that this tool can perform
AVAILABLE_ACTIONS = {
    'identify_functional_groups': {
        'description': 'Identify common functional groups in molecules (carbonyls, amines, alcohols, etc.)'
    },
    'identify_hazardous_groups': {
        'description': 'Identify hazardous functional groups in molecules (explosives, PFAS, CWC, etc.)'
    }
}


def process_molecule_for_functional_groups(smiles: str) -> Dict[str, Any]:
    """
    Process a single molecule for functional groups.

    Args:
        smiles: SMILES string of the molecule

    Returns:
        dict: Functional group analysis results
    """
    # Get all functional groups for the molecule
    groups = identify_fg(smiles, sort_by_priority=True)

    # Organize groups by category
    groups_by_category = {}
    for group_name in groups:
        # Find the category for this group
        for fg in FUNCTIONAL_GROUPS:
            if fg['name'] == group_name:
                category = fg['category']
                if category not in groups_by_category:
                    groups_by_category[category] = []
                groups_by_category[category].append(group_name)
                break

    return {
        'smiles': smiles,
        'group_count': len(groups),
        'functional_groups': groups,
        'groups_by_category': groups_by_category
    }


def run_identify_functional_groups(input_path: str, output_path: str, params: Dict[str, Any]) -> bool:
    """
    Run comprehensive functional groups identification.

    Args:
        input_path: Path to input directory or file
        output_path: Path to output directory
        params: Additional parameters

    Returns:
        bool: True if successful
    """
    io_utils.setup_session_logger('identify_functional_groups', output_path)
    io_utils.log_step('Identifying functional groups', 'Comprehensive molecular analysis')

    try:
        # Get input files
        input_files = []
        if os.path.isfile(input_path):
            input_files = [input_path]
        else:
            file_pattern = params.get('file_pattern', '*.*')
            input_files = glob.glob(os.path.join(input_path, file_pattern))

            if not input_files:
                # Try common extensions
                for ext in ['.smi', '.csv', '.txt', '.dat']:
                    input_files.extend(glob.glob(os.path.join(input_path, f"*{ext}")))

        if not input_files:
            io_utils.log_error(f"No files found in {input_path}")
            return False

        input_files.sort()
        io_utils.log_message(f"Found {len(input_files)} files to process")

        # Ensure output directory exists
        os.makedirs(output_path, exist_ok=True)

        # Process all files
        all_results = []
        skipped_molecules = []
        summary_stats = {
            'total_molecules': 0,
            'total_groups_found': 0,
            'group_distribution': {},
            'category_distribution': {}
        }

        for file_path in input_files:
            file_basename = os.path.basename(file_path)
            io_utils.log_step('Processing file', file_basename)

            # Load SMILES
            smiles_list = io_utils.read_smiles_from_file(file_path, column_name=params.get('column_name'))

            if not smiles_list:
                io_utils.log_error(f"No SMILES loaded from {file_path}")
                continue

            # Process each molecule
            for idx, smiles in enumerate(smiles_list):
                try:
                    # Pre-validate SMILES so we can report which molecule is problematic
                    mol = Chem.MolFromSmiles(smiles)
                    if mol is None:
                        io_utils.log_message(
                            f"Skipping invalid SMILES at index {idx + 1} in {file_basename}: '{smiles}'",
                            level="WARNING"
                        )
                        skipped_molecules.append({'file': file_basename, 'index': idx + 1, 'smiles': smiles})
                        continue

                    result = process_molecule_for_functional_groups(smiles)
                    all_results.append(result)

                    # Update statistics
                    summary_stats['total_molecules'] += 1
                    summary_stats['total_groups_found'] += result['group_count']

                    # Update group distribution
                    for group in result['functional_groups']:
                        if group not in summary_stats['group_distribution']:
                            summary_stats['group_distribution'][group] = 0
                        summary_stats['group_distribution'][group] += 1

                    # Update category distribution
                    for category in result['groups_by_category'].keys():
                        if category not in summary_stats['category_distribution']:
                            summary_stats['category_distribution'][category] = 0
                        summary_stats['category_distribution'][category] += len(result['groups_by_category'][category])

                except Exception as e:
                    io_utils.log_error(f"Error processing molecule at index {idx + 1} in {file_basename}: '{smiles}'", e)

            io_utils.log_step('File complete', f"{file_basename} - {len(smiles_list)} molecules")

        if skipped_molecules:
            io_utils.log_message(
                f"Skipped {len(skipped_molecules)} invalid molecules (e.g. kekulization failures)",
                level="WARNING"
            )

        # Save detailed results as CSV
        import pandas as pd
        df = pd.DataFrame(all_results)
        csv_path = os.path.join(output_path, 'functional_groups_detailed.csv')
        df.to_csv(csv_path, index=False)

        # Create final results
        summary_stats['skipped_molecules'] = len(skipped_molecules)
        final_results = {
            'action': 'identify_functional_groups',
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'parameters': {
                'files_processed': len(input_files)
            },
            'summary': summary_stats,
            'skipped': skipped_molecules if skipped_molecules else None,
            'output_files': {
                'detailed_analysis': csv_path
            },
            'status': 'completed'
        }

        # Save final results
        results_file = os.path.join(output_path, 'results.json')
        with open(results_file, 'w') as f:
            json.dump(final_results, f, indent=2)

        io_utils.log_step('Analysis complete',
                         f"Analyzed {summary_stats['total_molecules']} molecules, "
                         f"found {summary_stats['total_groups_found']} total functional groups")
        io_utils.finalize_session_log('identify_functional_groups')

        return True

    except Exception as e:
        io_utils.log_error(f"Error in identify_functional_groups", e)
        io_utils.finalize_session_log('identify_functional_groups')
        return False


def process_molecule_for_hazards(smiles: str, categories: List[str] = None) -> Dict[str, Any]:
    """
    Process a single molecule for hazardous groups.

    Args:
        smiles: SMILES string of the molecule
        categories: List of specific categories to check, or None for all

    Returns:
        dict: Hazard analysis results
    """
    # Get all hazards for the molecule
    all_hazards = identify_hazardous_groups(smiles)

    # Filter by categories if specified
    if categories and 'all' not in categories:
        filtered_hazards = []
        for hazard in all_hazards:
            category = hazard.split('.')[0]  # Extract category from "category.pattern" format
            if category in categories:
                filtered_hazards.append(hazard)
        hazards = filtered_hazards
    else:
        hazards = all_hazards

    # Organize hazards by category
    hazards_by_category = {}
    for hazard in hazards:
        parts = hazard.split('.', 1)
        if len(parts) == 2:
            category, pattern = parts
            if category not in hazards_by_category:
                hazards_by_category[category] = []
            hazards_by_category[category].append(pattern)

    # Determine risk level
    hazard_count = len(hazards)
    if hazard_count == 0:
        risk_level = 'safe'
    elif hazard_count <= 2:
        risk_level = 'low'
    elif hazard_count <= 5:
        risk_level = 'medium'
    else:
        risk_level = 'high'

    return {
        'smiles': smiles,
        'hazard_count': hazard_count,
        'risk_level': risk_level,
        'hazards_found': hazards,
        'hazards_by_category': hazards_by_category
    }


def run_identify_hazardous_groups(input_path: str, output_path: str, params: Dict[str, Any]) -> bool:
    """
    Run comprehensive hazardous groups identification.

    Args:
        input_path: Path to input directory or file
        output_path: Path to output directory
        params: Additional parameters

    Returns:
        bool: True if successful
    """
    io_utils.setup_session_logger('identify_hazardous_groups', output_path)
    io_utils.log_step('Identifying hazardous groups', 'Comprehensive safety screening')

    try:
        # Parse categories parameter
        categories_param = params.get('categories', 'all')
        if categories_param == 'all':
            categories = ['all']
        else:
            categories = [c.strip() for c in categories_param.split(',')]

        io_utils.log_message(f"Screening for categories: {', '.join(categories)}")

        # Get input files
        input_files = []
        if os.path.isfile(input_path):
            input_files = [input_path]
        else:
            file_pattern = params.get('file_pattern', '*.*')
            input_files = glob.glob(os.path.join(input_path, file_pattern))

            if not input_files:
                # Try common extensions
                for ext in ['.smi', '.csv', '.txt', '.dat']:
                    input_files.extend(glob.glob(os.path.join(input_path, f"*{ext}")))

        if not input_files:
            io_utils.log_error(f"No files found in {input_path}")
            return False

        input_files.sort()
        io_utils.log_message(f"Found {len(input_files)} files to process")

        # Ensure output directory exists
        os.makedirs(output_path, exist_ok=True)

        # Process all files
        all_results = []
        skipped_molecules = []
        summary_stats = {
            'total_molecules': 0,
            'molecules_with_hazards': 0,
            'hazard_distribution': {},
            'risk_distribution': {'safe': 0, 'low': 0, 'medium': 0, 'high': 0}
        }

        for file_path in input_files:
            file_basename = os.path.basename(file_path)
            io_utils.log_step('Processing file', file_basename)

            # Load SMILES
            smiles_list = io_utils.read_smiles_from_file(file_path, column_name=params.get('column_name'))

            if not smiles_list:
                io_utils.log_error(f"No SMILES loaded from {file_path}")
                continue

            # Process each molecule
            for idx, smiles in enumerate(smiles_list):
                try:
                    # Pre-validate SMILES so we can report which molecule is problematic
                    mol = Chem.MolFromSmiles(smiles)
                    if mol is None:
                        io_utils.log_message(
                            f"Skipping invalid SMILES at index {idx + 1} in {file_basename}: '{smiles}'",
                            level="WARNING"
                        )
                        skipped_molecules.append({'file': file_basename, 'index': idx + 1, 'smiles': smiles})
                        continue

                    result = process_molecule_for_hazards(smiles, categories)
                    all_results.append(result)

                    # Update statistics
                    summary_stats['total_molecules'] += 1
                    if result['hazard_count'] > 0:
                        summary_stats['molecules_with_hazards'] += 1

                    summary_stats['risk_distribution'][result['risk_level']] += 1

                    # Update hazard distribution
                    for category in result['hazards_by_category'].keys():
                        if category not in summary_stats['hazard_distribution']:
                            summary_stats['hazard_distribution'][category] = 0
                        summary_stats['hazard_distribution'][category] += len(result['hazards_by_category'][category])

                except Exception as e:
                    io_utils.log_error(f"Error processing molecule at index {idx + 1} in {file_basename}: '{smiles}'", e)

            io_utils.log_step('File complete', f"{file_basename} - {len(smiles_list)} molecules")

        if skipped_molecules:
            io_utils.log_message(
                f"Skipped {len(skipped_molecules)} invalid molecules (e.g. kekulization failures)",
                level="WARNING"
            )

        # Save detailed results as CSV
        import pandas as pd
        df = pd.DataFrame(all_results)
        csv_path = os.path.join(output_path, 'hazard_assessment_detailed.csv')
        df.to_csv(csv_path, index=False)

        # Save high-risk molecules separately
        high_risk = [r for r in all_results if r['risk_level'] == 'high']
        if high_risk:
            high_risk_path = os.path.join(output_path, 'high_risk_molecules.csv')
            pd.DataFrame(high_risk).to_csv(high_risk_path, index=False)

        # Create final results
        summary_stats['skipped_molecules'] = len(skipped_molecules)
        final_results = {
            'action': 'identify_hazardous_groups',
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'parameters': {
                'categories': categories,
                'files_processed': len(input_files)
            },
            'summary': summary_stats,
            'skipped': skipped_molecules if skipped_molecules else None,
            'output_files': {
                'detailed_assessment': csv_path,
                'high_risk_molecules': os.path.join(output_path, 'high_risk_molecules.csv') if high_risk else None
            },
            'status': 'completed'
        }

        # Save final results
        results_file = os.path.join(output_path, 'results.json')
        with open(results_file, 'w') as f:
            json.dump(final_results, f, indent=2)

        io_utils.log_step('Analysis complete',
                         f"Screened {summary_stats['total_molecules']} molecules, "
                         f"found {summary_stats['molecules_with_hazards']} with hazards")
        io_utils.finalize_session_log('identify_hazardous_groups')

        return True

    except Exception as e:
        io_utils.log_error(f"Error in identify_hazardous_groups", e)
        io_utils.finalize_session_log('identify_hazardous_groups')
        return False


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Molecular Groups Tool Entrypoint")

    parser.add_argument('--action', choices=AVAILABLE_ACTIONS.keys(),
                       help='Action to perform')
    parser.add_argument('--input',
                       help='Path to input directory or file')
    parser.add_argument('--output',
                       help='Path to output directory')
    parser.add_argument('--column-name',
                       help='Column name containing SMILES (for CSV files)')
    parser.add_argument('--batch-size', type=int, default=100,
                       help='Batch size for processing')
    parser.add_argument('--file-pattern', default='*.*',
                       help='File pattern to match')
    parser.add_argument('--categories',
                       help='Comma-separated list of categories (for identify_hazardous_groups)')

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_arguments()

    if not args.action:
        print("Error: --action is required")
        print(f"Available actions: {list(AVAILABLE_ACTIONS.keys())}")
        return 1

    if not args.input or not args.output:
        print("Error: --input and --output are required")
        return 1

    # Build parameters dictionary
    params = {}
    if args.column_name:
        params['column_name'] = args.column_name
    if args.batch_size:
        params['batch_size'] = args.batch_size
    if args.file_pattern:
        params['file_pattern'] = args.file_pattern
    if args.categories:
        params['categories'] = args.categories

    # Execute action
    if args.action == 'identify_functional_groups':
        success = run_identify_functional_groups(args.input, args.output, params)
    elif args.action == 'identify_hazardous_groups':
        success = run_identify_hazardous_groups(args.input, args.output, params)
    else:
        print(f"Unknown action: {args.action}")
        return 1

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
