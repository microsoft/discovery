import csv
import glob
import importlib
import json
import logging
import os
import pickle
import shutil
import subprocess
import sys
import traceback
from pathlib import Path


LOGGER = logging.getLogger("toxpred")
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"


def _optional_import(module_name):
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def _require(module_name):
    module = _optional_import(module_name)
    if module is None:
        raise ImportError(f"Required dependency '{module_name}' is not available")
    return module


def _json_safe(value):
    try:
        import numpy as np
        if isinstance(value, (np.integer, np.floating)):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
    except Exception:
        pass
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir'):
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir
    for folder in [input_dir, output_dir, work_dir]:
        os.makedirs(folder, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    LOGGER.info('Initialized toxpred environment')
    LOGGER.info('Input: %s | Output: %s | Work: %s', input_dir, output_dir, work_dir)


def quick_finish():
    LOGGER.info('toxpred workflow finished')


def save_final_results(results, output_files=None, file_descriptions=None, status='completed'):
    payload = {
        'status': status,
        'results': results or {},
        'output_files': output_files or {},
        'file_descriptions': file_descriptions or {},
    }
    out_path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(out_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, default=_json_safe)
    LOGGER.info('Saved final results to %s', out_path)
    return out_path


def validate_smiles(smiles):
    if smiles is None or str(smiles).strip() == '':
        return False
    chem = _optional_import('rdkit.Chem')
    if chem is None:
        return True
    return chem.MolFromSmiles(str(smiles)) is not None


def canonicalize_smiles(smiles):
    if smiles is None or str(smiles).strip() == '':
        return None
    chem = _optional_import('rdkit.Chem')
    if chem is None:
        return str(smiles).strip()
    mol = chem.MolFromSmiles(str(smiles))
    if mol is None:
        return None
    return chem.MolToSmiles(mol, canonical=True)


def _ensure_dataframe(obj):
    pd = _require('pandas')
    if isinstance(obj, pd.DataFrame):
        return obj.copy()
    if isinstance(obj, str):
        return pd.read_csv(obj)
    raise TypeError('Expected pandas DataFrame or CSV path')


def build_dsstox_spine(df, id_col='dsstox_substance_id', smiles_col='smiles', name_col='preferred_name', qc_col='qc_level'):
    pd = _require('pandas')
    table = _ensure_dataframe(df)
    keep = [c for c in [id_col, name_col, smiles_col, qc_col] if c in table.columns]
    table = table[keep].copy()
    if id_col not in table.columns:
        raise KeyError(f"Missing required column: {id_col}")
    if smiles_col not in table.columns:
        raise KeyError(f"Missing required column: {smiles_col}")
    table['input_smiles'] = table[smiles_col].astype(str)
    table['canonical_smiles'] = table[smiles_col].apply(canonicalize_smiles)
    table['valid_smiles'] = table['canonical_smiles'].notna()
    table = table.drop_duplicates(subset=[id_col], keep='first').reset_index(drop=True)
    if name_col not in table.columns:
        table[name_col] = table[id_col]
    if qc_col not in table.columns:
        table[qc_col] = None
    ordered = [id_col, name_col, qc_col, 'input_smiles', 'canonical_smiles', 'valid_smiles']
    return table[ordered]


def summarize_toxcast_assays(df, id_col='dsstox_substance_id', assay_col='assay_component_name', hit_col='hitc', potency_col='modl_acc'):
    pd = _require('pandas')
    table = _ensure_dataframe(df)
    required = [id_col, assay_col]
    for column in required:
        if column not in table.columns:
            raise KeyError(f"Missing required column: {column}")
    if hit_col not in table.columns:
        table[hit_col] = 0
    table[hit_col] = pd.to_numeric(table[hit_col], errors='coerce').fillna(0)
    if potency_col not in table.columns:
        table[potency_col] = None
    table[potency_col] = pd.to_numeric(table[potency_col], errors='coerce')

    def _active_assays(group):
        assays = sorted({str(x) for x in group.loc[group[hit_col] > 0, assay_col].dropna().tolist()})
        return ';'.join(assays)

    summary = table.groupby(id_col).agg(
        toxcast_assay_count=(assay_col, 'count'),
        toxcast_active_count=(hit_col, lambda x: int((x > 0).sum())),
        toxcast_min_potency=(potency_col, 'min'),
        toxcast_median_potency=(potency_col, 'median'),
    ).reset_index()
    summary['toxcast_active_fraction'] = summary['toxcast_active_count'] / summary['toxcast_assay_count'].clip(lower=1)
    summary['toxcast_active_assays'] = table.groupby(id_col).apply(_active_assays).reset_index(drop=True)
    return summary


def normalize_endpoint_table(df, endpoint_name, smiles_col='smiles', label_col='label', split_col='split'):
    pd = _require('pandas')
    table = _ensure_dataframe(df)
    if smiles_col not in table.columns:
        raise KeyError(f"Missing required column: {smiles_col}")
    if label_col not in table.columns:
        if 'Y' in table.columns:
            label_col = 'Y'
        else:
            raise KeyError(f"Missing required column: {label_col}")
    if split_col not in table.columns:
        table[split_col] = 'train'
    table = table[[smiles_col, label_col, split_col]].copy()
    table['canonical_smiles'] = table[smiles_col].apply(canonicalize_smiles)
    table = table.rename(columns={label_col: endpoint_name, split_col: 'split'})
    table['endpoint_name'] = endpoint_name
    return table[['canonical_smiles', endpoint_name, 'split', 'endpoint_name']]


def load_tdc_endpoint_dataset(name, split='scaffold', cache_dir='/workdir/tdc_cache'):
    pd = _require('pandas')
    os.makedirs(cache_dir, exist_ok=True)
    tdc_mod = _require('tdc.single_pred')
    tox_cls = getattr(tdc_mod, 'Tox')
    dataset = tox_cls(name=name, path=cache_dir)
    split_map = dataset.get_split(method=split)
    frames = []
    for split_name, frame in split_map.items():
        tmp = frame.copy()
        tmp['split'] = split_name
        frames.append(tmp)
    merged = pd.concat(frames, ignore_index=True)
    return merged


def merge_toxicity_panel(spine_df, toxcast_summary_df=None, endpoint_tables=None):
    pd = _require('pandas')
    panel = _ensure_dataframe(spine_df)
    if 'canonical_smiles' not in panel.columns:
        raise KeyError('spine_df must contain canonical_smiles')
    if toxcast_summary_df is not None:
        tox = _ensure_dataframe(toxcast_summary_df)
        panel = panel.merge(tox, on='dsstox_substance_id', how='left')
    endpoint_tables = endpoint_tables or []
    split_columns = []
    for endpoint_df in endpoint_tables:
        endpoint = _ensure_dataframe(endpoint_df)
        endpoint_cols = [c for c in endpoint.columns if c not in {'canonical_smiles', 'endpoint_name', 'split'}]
        panel = panel.merge(endpoint[['canonical_smiles'] + endpoint_cols], on='canonical_smiles', how='left')
        split_name = endpoint['endpoint_name'].iloc[0] if 'endpoint_name' in endpoint.columns else endpoint_cols[0]
        split_col = endpoint[['canonical_smiles', 'split']].rename(columns={'split': f'split_{split_name}'})
        panel = panel.merge(split_col, on='canonical_smiles', how='left')
        split_columns.append(f'split_{split_name}')
    if split_columns:
        panel['split'] = panel[split_columns].bfill(axis=1).iloc[:, 0].fillna('train')
    else:
        panel['split'] = 'train'
    return panel


def export_panel(df, path='/output/harmonized_panel.csv'):
    table = _ensure_dataframe(df)
    table.to_csv(path, index=False)
    LOGGER.info('Saved harmonized panel to %s', path)
    return path


def _ecfp_matrix(smiles_list, radius=2, nbits=2048):
    np = _require('numpy')
    chem = _require('rdkit.Chem')
    allchem = _require('rdkit.Chem.AllChem')
    rows = []
    for smi in smiles_list:
        mol = chem.MolFromSmiles(str(smi))
        if mol is None:
            rows.append(np.zeros(nbits, dtype=float))
            continue
        fp = allchem.GetMorganFingerprintAsBitVect(mol, radius, nBits=nbits)
        arr = np.zeros((nbits,), dtype=float)
        for idx in fp.GetOnBits():
            arr[idx] = 1.0
        rows.append(arr)
    return np.vstack(rows)


def train_random_forest_panel(df, endpoint_cols, split_col='split', out_dir='/output/rf_model'):
    pd = _require('pandas')
    np = _require('numpy')
    sklearn_ensemble = _require('sklearn.ensemble')
    sklearn_metrics = _require('sklearn.metrics')
    os.makedirs(out_dir, exist_ok=True)
    table = _ensure_dataframe(df)
    if 'canonical_smiles' not in table.columns:
        raise KeyError('Data frame must contain canonical_smiles')
    results = {'backend': 'random_forest', 'endpoints': {}, 'artifacts': {}}
    for endpoint in endpoint_cols:
        subset = table[['canonical_smiles', split_col, endpoint]].dropna().copy()
        if subset.empty:
            results['endpoints'][endpoint] = {'status': 'skipped', 'reason': 'no labeled rows'}
            continue
        x = _ecfp_matrix(subset['canonical_smiles'].tolist())
        y = subset[endpoint].astype(int).to_numpy()
        train_mask = subset[split_col].isin(['train', 'val'])
        test_mask = subset[split_col].eq('test')
        if int(test_mask.sum()) == 0:
            test_mask = subset[split_col].eq('val')
        if int(test_mask.sum()) == 0 or int(train_mask.sum()) == 0:
            results['endpoints'][endpoint] = {'status': 'skipped', 'reason': 'insufficient split coverage'}
            continue
        model = sklearn_ensemble.RandomForestClassifier(n_estimators=200, random_state=0, class_weight='balanced')
        model.fit(x[train_mask.to_numpy()], y[train_mask.to_numpy()])
        probs = model.predict_proba(x[test_mask.to_numpy()])[:, 1]
        preds = (probs >= 0.5).astype(int)
        y_true = y[test_mask.to_numpy()]
        metrics = {
            'n_train': int(train_mask.sum()),
            'n_test': int(test_mask.sum()),
            'accuracy': float(sklearn_metrics.accuracy_score(y_true, preds)),
            'f1': float(sklearn_metrics.f1_score(y_true, preds, zero_division=0)),
        }
        if len(set(y_true.tolist())) > 1:
            metrics['roc_auc'] = float(sklearn_metrics.roc_auc_score(y_true, probs))
        model_path = os.path.join(out_dir, f'{endpoint}_rf.pkl')
        with open(model_path, 'wb') as handle:
            pickle.dump(model, handle)
        pred_path = os.path.join(out_dir, f'{endpoint}_test_predictions.csv')
        pd.DataFrame({'y_true': y_true, 'y_pred': preds, 'y_prob': probs}).to_csv(pred_path, index=False)
        results['endpoints'][endpoint] = metrics
        results['artifacts'][endpoint] = {'model': model_path, 'predictions': pred_path}
    return results


def build_chemprop_train_command(data_path, target_columns, output_dir, smiles_column='canonical_smiles', split_column='split', epochs=10, metric='roc'):
    command = [
        'chemprop', 'train',
        '--data-path', data_path,
        '--task-type', 'classification',
        '--smiles-columns', smiles_column,
        '--target-columns', *list(target_columns),
        '--output-dir', output_dir,
        '--epochs', str(epochs),
        '--metrics', metric, 'f1', 'accuracy',
        '--tracking-metric', metric,
    ]
    if split_column:
        command.extend(['--splits-column', split_column])
    else:
        command.extend(['--split', 'RANDOM'])
    return command


def run_chemprop_train(data_path, target_columns, output_dir, smiles_column='canonical_smiles', split_column='split', epochs=10, metric='roc'):
    os.makedirs(output_dir, exist_ok=True)
    command = build_chemprop_train_command(data_path, target_columns, output_dir, smiles_column, split_column, epochs, metric)
    LOGGER.info('Running Chemprop train: %s', ' '.join(command))
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    stdout_path = os.path.join(output_dir, 'chemprop_train_stdout.txt')
    stderr_path = os.path.join(output_dir, 'chemprop_train_stderr.txt')
    Path(stdout_path).write_text(result.stdout, encoding='utf-8')
    Path(stderr_path).write_text(result.stderr, encoding='utf-8')
    files = sorted([str(p) for p in Path(output_dir).rglob('*') if p.is_file()])
    return {
        'returncode': result.returncode,
        'command': command,
        'stdout_path': stdout_path,
        'stderr_path': stderr_path,
        'output_dir': output_dir,
        'files': files,
        'success': result.returncode == 0,
    }


def build_chemprop_predict_command(test_path, model_paths, preds_path, smiles_column='canonical_smiles'):
    if isinstance(model_paths, str):
        model_paths = [model_paths]
    return [
        'chemprop', 'predict',
        '--test-path', test_path,
        '--model-paths', *list(model_paths),
        '--smiles-columns', smiles_column,
        '--preds-path', preds_path,
    ]


def run_chemprop_predict(test_path, model_paths, preds_path, smiles_column='canonical_smiles'):
    os.makedirs(os.path.dirname(preds_path) or '.', exist_ok=True)
    command = build_chemprop_predict_command(test_path, model_paths, preds_path, smiles_column)
    LOGGER.info('Running Chemprop predict: %s', ' '.join(command))
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    sidecar = preds_path + '.stderr.txt'
    Path(sidecar).write_text(result.stderr, encoding='utf-8')
    return {
        'returncode': result.returncode,
        'command': command,
        'preds_path': preds_path,
        'stderr_path': sidecar,
        'success': result.returncode == 0,
    }


def list_output_files(root='/output'):
    return sorted(str(p) for p in Path(root).rglob('*') if p.is_file())
