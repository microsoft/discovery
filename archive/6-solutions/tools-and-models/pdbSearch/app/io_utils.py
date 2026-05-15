"""
IO utilities for file handling and data export.
"""
import os
import json
import csv
import pandas as pd
from typing import List, Dict, Optional, Union
import matplotlib.pyplot as plt
import seaborn as sns


def find_protein_files(directory: str) -> List[str]:
    """
    Find all protein structure files (PDB or CIF) in a directory.
    
    Args:
        directory: Directory to search
    
    Returns:
        List of file paths for protein structures
    """
    pdb_files = []
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(('.pdb', '.cif')):
                pdb_files.append(os.path.join(root, file))
    
    return pdb_files


def find_id_files(directory: str) -> List[str]:
    """
    Find files containing PDB IDs (text files with PDB ID lists).
    
    Args:
        directory: Directory to search
    
    Returns:
        List of ID file paths
    """
    id_files = []
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(('.txt', '.csv', '.tsv', '.ids')):
                id_files.append(os.path.join(root, file))
    
    return id_files


def read_pdb_ids_from_file(filepath: str) -> List[str]:
    """
    Read PDB IDs from a text file.
    
    Args:
        filepath: Path to file containing PDB IDs
    
    Returns:
        List of PDB IDs (empty list if file cannot be read)
    """
    pdb_ids = []
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            if filepath.lower().endswith('.csv'):
                # Try to read as CSV
                try:
                    df = pd.read_csv(filepath)
                    # Look for columns that might contain PDB IDs
                    for col in df.columns:
                        if 'pdb' in col.lower() or 'id' in col.lower():
                            pdb_ids.extend(df[col].dropna().astype(str).tolist())
                            break
                    else:
                        # If no obvious PDB column, take first column
                        if len(df.columns) > 0:
                            pdb_ids.extend(df.iloc[:, 0].dropna().astype(str).tolist())
                except pd.errors.EmptyDataError:
                    print(f"⚠️ CSV file is empty: {filepath}")
                    return []
                except pd.errors.ParserError as e:
                    print(f"⚠️ Error parsing CSV file {filepath}: {e}")
                    # Fall back to reading as text
                    f.seek(0)
                    for line in f:
                        line = line.strip()
                        if line and len(line) == 4:
                            pdb_ids.append(line.upper())
                except Exception as e:
                    print(f"⚠️ Unexpected error reading CSV {filepath}: {e}")
                    return []
            else:
                # Read as plain text
                for line in f:
                    line = line.strip()
                    if line and len(line) == 4:
                        pdb_ids.append(line.upper())
    except FileNotFoundError:
        print(f"⚠️ File not found: {filepath}")
        return []
    except PermissionError:
        print(f"⚠️ Permission denied reading file: {filepath}")
        return []
    except UnicodeDecodeError as e:
        print(f"⚠️ Encoding error reading file {filepath}: {e}")
        print(f"   Try re-saving the file as UTF-8")
        return []
    except Exception as e:
        print(f"⚠️ Unexpected error reading file {filepath}: {e}")
        return []
    
    # Remove duplicates while preserving order
    seen = set()
    unique_ids = []
    for pdb_id in pdb_ids:
        if pdb_id not in seen:
            seen.add(pdb_id)
            unique_ids.append(pdb_id)
    
    return unique_ids


def save_results_to_json(data: Dict, filepath: str) -> str:
    """
    Save results to JSON file.
    
    Args:
        data: Data to save
        filepath: Output file path
    
    Returns:
        Path to saved file (empty string if save fails)
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        
        return filepath
    except PermissionError:
        print(f"⚠️ Permission denied writing to: {filepath}")
        return ""
    except OSError as e:
        print(f"⚠️ OS error saving JSON to {filepath}: {e}")
        return ""
    except TypeError as e:
        print(f"⚠️ Data serialization error: {e}")
        return ""
    except Exception as e:
        print(f"⚠️ Unexpected error saving JSON: {e}")
        return ""


def save_results_to_csv(data: Union[List[Dict], pd.DataFrame], filepath: str) -> str:
    """
    Save results to CSV file.
    
    Args:
        data: Data to save (list of dictionaries or DataFrame)
        filepath: Output file path
    
    Returns:
        Path to saved file
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    if isinstance(data, list):
        # Convert list of dictionaries to DataFrame
        df = pd.DataFrame(data)
    else:
        df = data
    
    df.to_csv(filepath, index=False)
    
    return filepath


def export_structure_summary(structures_info: List[Dict], output_dir: str) -> str:
    """
    Export a summary of multiple structures to CSV.
    
    Args:
        structures_info: List of structure information dictionaries
        output_dir: Output directory
    
    Returns:
        Path to summary CSV file
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Flatten structure information for CSV export
    flattened_data = []
    
    for info in structures_info:
        row = {
            "pdb_id": info.get("pdb_id", "N/A"),
            "title": info.get("title", "N/A"),
            "experimental_method": info.get("experimental_method", "N/A"),
            "resolution": info.get("resolution", "N/A"),
            "deposition_date": info.get("deposition_date", "N/A"),
            "classification": info.get("classification", "N/A")
        }
        
        # Add basic properties if available
        if "basic_properties" in info:
            basic_props = info["basic_properties"]
            row.update({
                "num_chains": basic_props.get("num_chains", 0),
                "num_residues": basic_props.get("num_residues", 0),
                "num_atoms": basic_props.get("num_atoms", 0)
            })
        
        # Add secondary structure if available
        if "secondary_structure" in info:
            ss = info["secondary_structure"]
            row.update({
                "alpha_helix_percent": ss.get("alpha_helix", 0),
                "beta_sheet_percent": ss.get("beta_sheet", 0),
                "other_ss_percent": ss.get("other", 0)
            })
        
        flattened_data.append(row)
    
    # Save to CSV
    filepath = os.path.join(output_dir, "structures_summary.csv")
    return save_results_to_csv(flattened_data, filepath)


def create_visualization(data: Dict, plot_type: str, output_dir: str) -> str:
    """
    Create visualizations from analysis data.
    
    Args:
        data: Analysis data
        plot_type: Type of plot to create
        output_dir: Output directory
    
    Returns:
        Path to saved plot file
    """
    os.makedirs(output_dir, exist_ok=True)
    
    plt.figure(figsize=(10, 6))
    
    if plot_type == "resolution_distribution":
        # Plot resolution distribution with robust handling
        resolutions = []
        for item in data:
            res = item.get("resolution")
            if res and res != "N/A":
                try:
                    res_float = float(res)
                    if res_float > 0:
                        resolutions.append(res_float)
                except (ValueError, TypeError):
                    # Skip invalid resolution values
                    continue
        
        if resolutions:
            plt.hist(resolutions, bins=20, alpha=0.7, edgecolor='black')
            plt.xlabel("Resolution (Å)")
            plt.ylabel("Number of Structures")
            plt.title("Distribution of Structure Resolutions")
        else:
            plt.text(0.5, 0.5, "No resolution data available", 
                    transform=plt.gca().transAxes, ha='center', va='center')
    
    elif plot_type == "experimental_methods":
        # Plot experimental methods distribution
        methods = [item.get("experimental_method", "Unknown") for item in data]
        method_counts = pd.Series(methods).value_counts()
        
        method_counts.plot(kind='bar')
        plt.xlabel("Experimental Method")
        plt.ylabel("Number of Structures")
        plt.title("Distribution of Experimental Methods")
        plt.xticks(rotation=45, ha='right')
    
    elif plot_type == "secondary_structure":
        # Plot secondary structure composition
        if isinstance(data, dict) and "secondary_structure" in data:
            ss_data = data["secondary_structure"]
            labels = list(ss_data.keys())
            values = list(ss_data.values())
            
            plt.pie(values, labels=labels, autopct='%1.1f%%')
            plt.title("Secondary Structure Composition")
        else:
            plt.text(0.5, 0.5, "No secondary structure data available", 
                    transform=plt.gca().transAxes, ha='center', va='center')
    
    elif plot_type == "chain_length_distribution":
        # Plot chain length distribution
        lengths = []
        for item in data:
            if "basic_properties" in item and "chain_info" in item["basic_properties"]:
                for chain_id, chain_info in item["basic_properties"]["chain_info"].items():
                    lengths.append(chain_info.get("num_residues", 0))
        
        if lengths:
            plt.hist(lengths, bins=20, alpha=0.7, edgecolor='black')
            plt.xlabel("Chain Length (Number of Residues)")
            plt.ylabel("Number of Chains")
            plt.title("Distribution of Chain Lengths")
        else:
            plt.text(0.5, 0.5, "No chain length data available", 
                    transform=plt.gca().transAxes, ha='center', va='center')
    
    else:
        plt.text(0.5, 0.5, f"Plot type '{plot_type}' not recognized", 
                transform=plt.gca().transAxes, ha='center', va='center')
    
    plt.tight_layout()
    
    # Save plot
    filename = f"{plot_type}_plot.png"
    filepath = os.path.join(output_dir, filename)
    plt.savefig(filepath, dpi=300, bbox_inches='tight')
    plt.close()
    
    return filepath


def generate_report(analysis_results: Dict, output_dir: str) -> str:
    """
    Generate a comprehensive HTML report from analysis results.
    
    Args:
        analysis_results: Results from structure analysis
        output_dir: Output directory
    
    Returns:
        Path to generated HTML report
    """
    os.makedirs(output_dir, exist_ok=True)
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>PDB Structure Analysis Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
            .section {{ margin: 20px 0; }}
            .property {{ margin: 10px 0; }}
            .value {{ font-weight: bold; color: #0066cc; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>PDB Structure Analysis Report</h1>
            <p>Generated on: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="section">
            <h2>Summary</h2>
    """
    
    if isinstance(analysis_results, dict):
        if "pdb_id" in analysis_results:
            html_content += f'<div class="property">PDB ID: <span class="value">{analysis_results["pdb_id"]}</span></div>'
        
        if "basic_properties" in analysis_results:
            basic_props = analysis_results["basic_properties"]
            html_content += f"""
            <div class="property">Number of Chains: <span class="value">{basic_props.get("num_chains", "N/A")}</span></div>
            <div class="property">Number of Residues: <span class="value">{basic_props.get("num_residues", "N/A")}</span></div>
            <div class="property">Number of Atoms: <span class="value">{basic_props.get("num_atoms", "N/A")}</span></div>
            """
        
        if "secondary_structure" in analysis_results:
            ss = analysis_results["secondary_structure"]
            html_content += f"""
            <h3>Secondary Structure Composition</h3>
            <div class="property">Alpha Helix: <span class="value">{ss.get("alpha_helix", 0):.1f}%</span></div>
            <div class="property">Beta Sheet: <span class="value">{ss.get("beta_sheet", 0):.1f}%</span></div>
            <div class="property">Other: <span class="value">{ss.get("other", 0):.1f}%</span></div>
            """
        
        if "binding_sites" in analysis_results and analysis_results["binding_sites"]:
            html_content += "<h3>Binding Sites</h3><table><tr><th>Ligand</th><th>Chain</th><th>Contacts</th></tr>"
            for site in analysis_results["binding_sites"]:
                html_content += f"""
                <tr>
                    <td>{site.get("ligand_name", "N/A")}</td>
                    <td>{site.get("ligand_chain", "N/A")}</td>
                    <td>{site.get("num_contacts", 0)}</td>
                </tr>
                """
            html_content += "</table>"
    
    html_content += """
        </div>
        
        <div class="section">
            <h2>Raw Data</h2>
            <pre style="background-color: #f5f5f5; padding: 10px; border-radius: 3px; overflow-x: auto;">
    """
    
    html_content += json.dumps(analysis_results, indent=2)
    
    html_content += """
            </pre>
        </div>
    </body>
    </html>
    """
    
    # Save HTML report
    filepath = os.path.join(output_dir, "analysis_report.html")
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        return filepath
    except PermissionError:
        print(f"⚠️ Permission denied writing HTML report to: {filepath}")
        return ""
    except OSError as e:
        print(f"⚠️ OS error saving HTML report: {e}")
        return ""
    except Exception as e:
        print(f"⚠️ Unexpected error saving HTML report: {e}")
        return ""


def save_final_results(results: Dict, output_dir: str) -> str:
    """
    Save final results in the required format.
    
    Args:
        results: Final analysis results
        output_dir: Output directory
    
    Returns:
        Path to final results file
    """
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "final_results.json")
    
    # Ensure results have required metadata
    final_output = {
        "analysis_type": "RCSB PDB Analysis",
        "timestamp": pd.Timestamp.now().isoformat(),
        "results": results,
        "summary": {
            "total_structures_analyzed": len(results) if isinstance(results, list) else 1,
            "analysis_complete": True
        }
    }
    
    return save_results_to_json(final_output, filepath)


def organize_search_results(pdb_ids: List[str], search_type: str, structures_info: Optional[List[Dict]] = None) -> Dict:
    """
    Organize search results into a structured format.
    
    Args:
        pdb_ids: List of PDB IDs found in search
        search_type: Description of the search performed
        structures_info: Optional detailed information for each structure
    
    Returns:
        Dictionary with organized search results
    """
    organized_results = {
        "search_type": search_type,
        "search_timestamp": pd.Timestamp.now().isoformat(),
        "total_structures_found": len(pdb_ids),
        "pdb_ids": pdb_ids,
        "structures": structures_info if structures_info else []
    }
    
    if structures_info:
        # Helper function to safely convert resolution to float
        def safe_float_resolution(info):
            res = info.get("resolution")
            if res is None or res == "" or res == "N/A":
                return None
            try:
                return float(res)
            except (ValueError, TypeError):
                return None
        
        # Get all valid resolution values
        valid_resolutions = [r for r in (safe_float_resolution(info) for info in structures_info) if r is not None]
        
        organized_results["summary_stats"] = {
            "structures_with_details": len(structures_info),
            "unique_organisms": len(set(info.get("organism", "Unknown") for info in structures_info)),
            "resolution_range": {
                "min": min(valid_resolutions) if valid_resolutions else None,
                "max": max(valid_resolutions) if valid_resolutions else None
            }
        }
    
    return organized_results
