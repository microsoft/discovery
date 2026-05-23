#!/usr/bin/env python3
"""ChemBERTa utilities library for Microsoft Discovery platform.

Provides molecular property prediction, embedding extraction, SMILES augmentation,
fine-tuning, similarity/clustering, and visualization using the ChemBERTa-2
transformer model (DeepChem/ChemBERTa-77M-MTR).

Reference: Ahmad et al. "ChemBERTa-2: Towards Chemical Foundation Models" (2022)
"""
import os
import sys
import glob
import json
import logging
import shutil
import traceback
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/chemberta_scratch"
MODEL_CACHE = "/app/model_cache"
DEFAULT_MODEL = "DeepChem/ChemBERTa-77M-MTR"
MAX_SMILES_LENGTH = 512


# ============= SETUP FUNCTIONS =============
def quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir'):
    """Initialize directories, logging, and copy input files to workdir."""
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    for d in [WORK_DIR, OUTPUT_DIR, SCRATCH_DIR]:
        os.makedirs(d, exist_ok=True)
    os.chdir(WORK_DIR)
    _copy_input_files()
    logging.info(f"ChemBERTa agent initialized. Working dir: {WORK_DIR}")
    logging.info(f"Input files: {os.listdir(INPUT_DIR) if os.path.exists(INPUT_DIR) else []}")


def _copy_input_files():
    """Copy input files to working directory."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def quick_finish():
    """Copy key output files from workdir to output directory."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ['*.json', '*.csv', '*.png', '*.html', '*.npy', '*.pt', '*.log']
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None, status: str = "completed"):
    """Save structured results to final_results.json (MANDATORY for every script)."""
    def _convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [_convert(v) for v in obj]
        return obj

    final = {"status": status, "summary": _convert(results)}
    if output_files:
        final["output_files"] = _convert(output_files)
    if file_descriptions:
        final["file_descriptions"] = _convert(file_descriptions)

    path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(path, 'w') as f:
        json.dump(final, f, indent=2, default=str)
    logging.info(f"Saved final_results.json to {path}")


# ============= SMILES UTILITIES =============
def validate_smiles(smiles: str) -> bool:
    """Check if a SMILES string is valid using RDKit."""
    from rdkit import Chem
    if not smiles or not isinstance(smiles, str):
        return False
    mol = Chem.MolFromSmiles(smiles)
    return mol is not None


def canonicalize_smiles(smiles: str) -> Optional[str]:
    """Return canonical SMILES, or None if invalid."""
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return Chem.MolToSmiles(mol)


def augment_smiles(smiles: str, n_augmentations: int = 10) -> List[str]:
    """Generate multiple random SMILES representations of the same molecule.

    Used for data augmentation and confidence scoring (FART paper methodology).
    Returns a list of unique SMILES strings (may be fewer than n_augmentations).
    """
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return [smiles]

    augmented = set()
    augmented.add(Chem.MolToSmiles(mol))  # Always include canonical
    max_attempts = n_augmentations * 3
    attempts = 0
    while len(augmented) < n_augmentations and attempts < max_attempts:
        random_smi = Chem.MolToSmiles(mol, doRandom=True)
        augmented.add(random_smi)
        attempts += 1
    return list(augmented)


def batch_validate_smiles(smiles_list: List[str]) -> Dict:
    """Validate a list of SMILES and return statistics."""
    valid = []
    invalid = []
    for i, smi in enumerate(smiles_list):
        if validate_smiles(smi):
            valid.append(smi)
        else:
            invalid.append({"index": i, "smiles": smi})
    return {
        "total": len(smiles_list),
        "valid": len(valid),
        "invalid": len(invalid),
        "valid_smiles": valid,
        "invalid_entries": invalid,
        "validity_rate": len(valid) / max(len(smiles_list), 1)
    }


def smiles_stats(smiles_list: List[str]) -> Dict:
    """Compute statistics about a collection of SMILES."""
    from rdkit import Chem
    from rdkit.Chem import Descriptors

    valid_mols = []
    for smi in smiles_list:
        mol = Chem.MolFromSmiles(smi)
        if mol:
            valid_mols.append(mol)

    if not valid_mols:
        return {"error": "No valid molecules found"}

    mws = [Descriptors.MolWt(m) for m in valid_mols]
    n_atoms = [m.GetNumAtoms() for m in valid_mols]
    n_heavy = [m.GetNumHeavyAtoms() for m in valid_mols]

    return {
        "n_molecules": len(valid_mols),
        "n_invalid": len(smiles_list) - len(valid_mols),
        "molecular_weight": {"mean": float(np.mean(mws)), "std": float(np.std(mws)),
                             "min": float(np.min(mws)), "max": float(np.max(mws))},
        "n_atoms": {"mean": float(np.mean(n_atoms)), "std": float(np.std(n_atoms))},
        "n_heavy_atoms": {"mean": float(np.mean(n_heavy)), "std": float(np.std(n_heavy))},
        "smiles_lengths": {"mean": float(np.mean([len(s) for s in smiles_list])),
                           "max": int(max(len(s) for s in smiles_list))}
    }


# ============= MODEL LOADING =============
def load_model(model_path: str = None, device: str = 'auto'):
    """Load pre-trained ChemBERTa model and tokenizer for embedding extraction.

    Args:
        model_path: Path to model or HuggingFace model ID.
                    Defaults to pre-cached ChemBERTa-77M-MTR at /app/model_cache.
        device: 'auto' (GPU if available, else CPU), 'cpu', or 'cuda'

    Returns:
        (model, tokenizer) tuple
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    if model_path is None:
        model_path = MODEL_CACHE if os.path.exists(MODEL_CACHE) else DEFAULT_MODEL

    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

    logging.info(f"Loading ChemBERTa model from {model_path} on {device}")
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModel.from_pretrained(model_path)
    model = model.to(device)
    model.eval()
    logging.info(f"Model loaded: {model.config.hidden_size}d embeddings, "
                 f"{sum(p.numel() for p in model.parameters()) / 1e6:.1f}M params")
    return model, tokenizer


def load_classification_model(model_path: str, num_labels: int, device: str = 'auto'):
    """Load a fine-tuned ChemBERTa classification model.

    Args:
        model_path: Path to fine-tuned model directory
        num_labels: Number of output classes
        device: Device to load onto

    Returns:
        (model, tokenizer) tuple
    """
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path, num_labels=num_labels
    )
    model = model.to(device)
    model.eval()
    logging.info(f"Classification model loaded: {num_labels} labels")
    return model, tokenizer


def load_regression_model(model_path: str, num_targets: int = 1, device: str = 'auto'):
    """Load a fine-tuned ChemBERTa regression model.

    Args:
        model_path: Path to fine-tuned model directory
        num_targets: Number of regression targets
        device: Device to load onto

    Returns:
        (model, tokenizer) tuple
    """
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path, num_labels=num_targets, problem_type="regression"
    )
    model = model.to(device)
    model.eval()
    logging.info(f"Regression model loaded: {num_targets} targets")
    return model, tokenizer


# ============= EMBEDDING EXTRACTION =============
def extract_embeddings(smiles_list: List[str], model, tokenizer,
                       pooling: str = 'mean', batch_size: int = 32,
                       max_length: int = MAX_SMILES_LENGTH) -> np.ndarray:
    """Extract molecular embeddings from SMILES using ChemBERTa.

    Args:
        smiles_list: List of SMILES strings
        model: ChemBERTa model (AutoModel)
        tokenizer: ChemBERTa tokenizer
        pooling: 'mean' (all tokens), 'cls' (CLS token only), 'max'
        batch_size: Batch size for inference
        max_length: Maximum tokenization length

    Returns:
        numpy array of shape (n_molecules, hidden_size)
    """
    import torch

    device = next(model.parameters()).device
    all_embeddings = []

    for i in range(0, len(smiles_list), batch_size):
        batch = smiles_list[i:i + batch_size]
        inputs = tokenizer(batch, padding=True, truncation=True,
                           max_length=max_length, return_tensors='pt')
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)

        hidden = outputs.last_hidden_state  # (batch, seq_len, hidden)
        mask = inputs['attention_mask'].unsqueeze(-1)  # (batch, seq_len, 1)

        if pooling == 'cls':
            emb = hidden[:, 0, :]
        elif pooling == 'max':
            hidden_clone = hidden.clone()
            hidden_clone[mask.expand_as(hidden_clone) == 0] = -1e9
            emb = hidden_clone.max(dim=1).values
        else:  # mean pooling (default)
            emb = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)

        all_embeddings.append(emb.cpu().numpy())

    result = np.concatenate(all_embeddings, axis=0)
    logging.info(f"Extracted embeddings: {result.shape}")
    return result


# ============= PROPERTY PREDICTION =============
def predict_classification(smiles_list: List[str], model, tokenizer,
                           class_names: List[str] = None,
                           batch_size: int = 32) -> Dict:
    """Predict class probabilities using a fine-tuned classification model.

    Args:
        smiles_list: Input SMILES
        model: Fine-tuned AutoModelForSequenceClassification
        tokenizer: ChemBERTa tokenizer
        class_names: Optional label names
        batch_size: Batch size

    Returns:
        Dict with predictions, probabilities, and class distribution
    """
    import torch

    device = next(model.parameters()).device
    all_probs = []

    for i in range(0, len(smiles_list), batch_size):
        batch = smiles_list[i:i + batch_size]
        inputs = tokenizer(batch, padding=True, truncation=True,
                           max_length=MAX_SMILES_LENGTH, return_tensors='pt')
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)

        probs = torch.softmax(outputs.logits, dim=-1).cpu().numpy()
        all_probs.append(probs)

    all_probs = np.concatenate(all_probs, axis=0)
    predictions = np.argmax(all_probs, axis=1)

    num_classes = all_probs.shape[1]
    if class_names is None:
        class_names = [f"class_{i}" for i in range(num_classes)]

    results = []
    for i, smi in enumerate(smiles_list):
        results.append({
            "smiles": smi,
            "predicted_class": class_names[predictions[i]],
            "predicted_index": int(predictions[i]),
            "confidence": float(all_probs[i, predictions[i]]),
            "probabilities": {name: float(all_probs[i, j])
                              for j, name in enumerate(class_names)}
        })

    return {
        "n_molecules": len(smiles_list),
        "class_names": class_names,
        "predictions": results,
        "class_distribution": {name: int((predictions == j).sum())
                               for j, name in enumerate(class_names)}
    }


def predict_regression(smiles_list: List[str], model, tokenizer,
                       target_names: List[str] = None,
                       batch_size: int = 32) -> Dict:
    """Predict continuous values using a fine-tuned regression model.

    Args:
        smiles_list: Input SMILES
        model: Fine-tuned regression model
        tokenizer: ChemBERTa tokenizer
        target_names: Optional target property names
        batch_size: Batch size

    Returns:
        Dict with predictions and statistics per target
    """
    import torch

    device = next(model.parameters()).device
    all_preds = []

    for i in range(0, len(smiles_list), batch_size):
        batch = smiles_list[i:i + batch_size]
        inputs = tokenizer(batch, padding=True, truncation=True,
                           max_length=MAX_SMILES_LENGTH, return_tensors='pt')
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)

        all_preds.append(outputs.logits.cpu().numpy())

    all_preds = np.concatenate(all_preds, axis=0)
    n_targets = all_preds.shape[1] if all_preds.ndim > 1 else 1

    if target_names is None:
        target_names = [f"target_{i}" for i in range(n_targets)]

    if all_preds.ndim == 1:
        all_preds = all_preds.reshape(-1, 1)

    results = []
    for i, smi in enumerate(smiles_list):
        results.append({
            "smiles": smi,
            "predictions": {name: float(all_preds[i, j])
                            for j, name in enumerate(target_names)}
        })

    return {
        "n_molecules": len(smiles_list),
        "target_names": target_names,
        "predictions": results,
        "statistics": {
            name: {"mean": float(np.mean(all_preds[:, j])),
                   "std": float(np.std(all_preds[:, j])),
                   "min": float(np.min(all_preds[:, j])),
                   "max": float(np.max(all_preds[:, j]))}
            for j, name in enumerate(target_names)
        }
    }


def predict_with_confidence(smiles_list: List[str], model, tokenizer,
                            class_names: List[str] = None,
                            n_augmentations: int = 10,
                            batch_size: int = 32) -> Dict:
    """Predict with confidence scoring via SMILES augmentation consensus.

    For each molecule, generates multiple random SMILES representations and
    checks prediction agreement. Confidence = fraction of augmented SMILES
    that agree with the majority prediction. Implements the FART paper method.

    Args:
        smiles_list: Input SMILES
        model: Fine-tuned classification model
        tokenizer: ChemBERTa tokenizer
        class_names: Label names
        n_augmentations: Number of SMILES augmentations per molecule
        batch_size: Batch size for inference

    Returns:
        Dict with predictions, confidence scores, and consensus info
    """
    import torch
    from collections import Counter

    device = next(model.parameters()).device

    if class_names is None:
        num_labels = model.config.num_labels
        class_names = [f"class_{i}" for i in range(num_labels)]

    results = []
    for idx, smi in enumerate(smiles_list):
        aug_smiles = augment_smiles(smi, n_augmentations)

        # Predict for all augmented SMILES
        inputs = tokenizer(aug_smiles, padding=True, truncation=True,
                           max_length=MAX_SMILES_LENGTH, return_tensors='pt')
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)

        probs = torch.softmax(outputs.logits, dim=-1).cpu().numpy()
        preds = np.argmax(probs, axis=1)

        # Majority vote
        vote_counts = Counter(preds.tolist())
        majority_class = vote_counts.most_common(1)[0][0]
        consensus = vote_counts[majority_class] / len(preds)

        # Average probabilities across augmentations
        mean_probs = probs.mean(axis=0)

        results.append({
            "smiles": smi,
            "predicted_class": class_names[majority_class],
            "predicted_index": int(majority_class),
            "confidence": float(consensus),
            "n_augmentations": len(aug_smiles),
            "mean_probabilities": {name: float(mean_probs[j])
                                   for j, name in enumerate(class_names)},
            "consensus_votes": {class_names[k]: v for k, v in vote_counts.items()}
        })

        if (idx + 1) % 100 == 0:
            logging.info(f"Predicted {idx + 1}/{len(smiles_list)} molecules")

    confidences = [r["confidence"] for r in results]
    return {
        "n_molecules": len(smiles_list),
        "class_names": class_names,
        "predictions": results,
        "confidence_stats": {
            "mean": float(np.mean(confidences)),
            "min": float(np.min(confidences)),
            "high_confidence_count": sum(1 for c in confidences if c >= 0.8),
        }
    }


# ============= FINE-TUNING =============
def prepare_dataset(smiles_list: List[str], labels: List, tokenizer,
                    max_length: int = MAX_SMILES_LENGTH):
    """Prepare a PyTorch Dataset from SMILES and labels.

    Args:
        smiles_list: List of SMILES strings
        labels: List of labels (int for classification, float for regression)
        tokenizer: ChemBERTa tokenizer
        max_length: Maximum token length

    Returns:
        torch Dataset with input_ids, attention_mask, and labels
    """
    import torch
    from torch.utils.data import Dataset

    encodings = tokenizer(smiles_list, padding=True, truncation=True,
                          max_length=max_length, return_tensors='pt')

    # Determine dtype from first label
    if isinstance(labels[0], (int, np.integer)):
        label_tensor = torch.tensor(labels, dtype=torch.long)
    else:
        label_tensor = torch.tensor(labels, dtype=torch.float)

    class MolDataset(Dataset):
        def __init__(self, enc, lab):
            self.encodings = enc
            self.labels = lab

        def __len__(self):
            return len(self.labels)

        def __getitem__(self, idx):
            item = {k: v[idx] for k, v in self.encodings.items()}
            item['labels'] = self.labels[idx]
            return item

    return MolDataset(encodings, label_tensor)


def prepare_augmented_dataset(smiles_list: List[str], labels: List, tokenizer,
                              n_augmentations: int = 5,
                              max_length: int = MAX_SMILES_LENGTH):
    """Prepare dataset with SMILES augmentation for improved training.

    Each molecule is represented by multiple random SMILES strings, all sharing
    the same label. This follows the FART paper's augmentation strategy.
    """
    aug_smiles = []
    aug_labels = []
    for smi, label in zip(smiles_list, labels):
        augmented = augment_smiles(smi, n_augmentations)
        aug_smiles.extend(augmented)
        aug_labels.extend([label] * len(augmented))

    logging.info(f"Augmented {len(smiles_list)} molecules to {len(aug_smiles)} samples")
    return prepare_dataset(aug_smiles, aug_labels, tokenizer, max_length)


def finetune_classification(base_model_path: str, train_smiles: List[str],
                            train_labels: List[int], val_smiles: List[str] = None,
                            val_labels: List[int] = None, num_labels: int = None,
                            class_names: List[str] = None,
                            augment: bool = True, n_augmentations: int = 5,
                            num_epochs: int = 10, batch_size: int = 32,
                            learning_rate: float = 2e-5,
                            output_dir: str = '/output/finetuned_model',
                            device: str = 'auto') -> Dict:
    """Fine-tune ChemBERTa for classification tasks.

    Args:
        base_model_path: Path to base model (None = pre-cached ChemBERTa-77M-MTR)
        train_smiles: Training SMILES
        train_labels: Training labels (integers)
        val_smiles: Validation SMILES (optional, auto-split 15% if None)
        val_labels: Validation labels
        num_labels: Number of classes (auto-detected if None)
        class_names: Human-readable class names
        augment: Whether to use SMILES augmentation
        n_augmentations: Augmentations per molecule
        num_epochs: Training epochs
        batch_size: Batch size
        learning_rate: Learning rate
        output_dir: Where to save the fine-tuned model
        device: Device to train on

    Returns:
        Dict with training history, evaluation metrics, and model path
    """
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    from sklearn.metrics import accuracy_score, f1_score, classification_report

    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

    if num_labels is None:
        num_labels = len(set(train_labels))

    if class_names is None:
        class_names = [f"class_{i}" for i in range(num_labels)]

    # Split validation set if not provided
    if val_smiles is None:
        from sklearn.model_selection import train_test_split
        train_smiles, val_smiles, train_labels, val_labels = train_test_split(
            train_smiles, train_labels, test_size=0.15, stratify=train_labels,
            random_state=42
        )

    logging.info(f"Training: {len(train_smiles)} molecules, Validation: {len(val_smiles)}")
    logging.info(f"Classes: {num_labels} ({class_names}), Augment: {augment}")

    # Load model and tokenizer
    if base_model_path is None:
        base_model_path = MODEL_CACHE if os.path.exists(MODEL_CACHE) else DEFAULT_MODEL

    tokenizer = AutoTokenizer.from_pretrained(base_model_path)
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model_path, num_labels=num_labels
    )
    model = model.to(device)

    # Prepare datasets
    if augment:
        train_dataset = prepare_augmented_dataset(
            train_smiles, train_labels, tokenizer, n_augmentations
        )
    else:
        train_dataset = prepare_dataset(train_smiles, train_labels, tokenizer)

    val_dataset = prepare_dataset(val_smiles, val_labels, tokenizer)

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size)

    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=num_epochs)

    history = {"train_loss": [], "val_loss": [], "val_accuracy": [], "val_f1": []}
    best_f1 = 0

    for epoch in range(num_epochs):
        # Training
        model.train()
        total_loss = 0
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            outputs = model(**batch)
            loss = outputs.loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad()
            total_loss += loss.item()

        avg_train_loss = total_loss / len(train_loader)

        # Validation
        model.eval()
        val_loss = 0
        all_preds = []
        all_true = []
        with torch.no_grad():
            for batch in val_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                outputs = model(**batch)
                val_loss += outputs.loss.item()
                preds = torch.argmax(outputs.logits, dim=-1)
                all_preds.extend(preds.cpu().numpy())
                all_true.extend(batch['labels'].cpu().numpy())

        avg_val_loss = val_loss / len(val_loader)
        val_acc = accuracy_score(all_true, all_preds)
        val_f1 = f1_score(all_true, all_preds, average='macro', zero_division=0)

        history["train_loss"].append(avg_train_loss)
        history["val_loss"].append(avg_val_loss)
        history["val_accuracy"].append(val_acc)
        history["val_f1"].append(val_f1)

        logging.info(f"Epoch {epoch + 1}/{num_epochs}: train_loss={avg_train_loss:.4f}, "
                     f"val_loss={avg_val_loss:.4f}, val_acc={val_acc:.4f}, val_f1={val_f1:.4f}")

        # Save best model
        if val_f1 > best_f1:
            best_f1 = val_f1
            os.makedirs(output_dir, exist_ok=True)
            model.save_pretrained(output_dir)
            tokenizer.save_pretrained(output_dir)
            with open(os.path.join(output_dir, 'class_names.json'), 'w') as f:
                json.dump(class_names, f)
            logging.info(f"  New best model saved (F1={best_f1:.4f})")

        scheduler.step()

    # Final classification report
    report = classification_report(all_true, all_preds, target_names=class_names,
                                   output_dict=True, zero_division=0)

    return {
        "training_complete": True,
        "best_val_f1": float(best_f1),
        "final_val_accuracy": float(history["val_accuracy"][-1]),
        "num_epochs": num_epochs,
        "train_size": len(train_smiles),
        "val_size": len(val_smiles),
        "augmented": augment,
        "history": history,
        "classification_report": report,
        "model_saved_to": output_dir
    }


def finetune_regression(base_model_path: str, train_smiles: List[str],
                        train_values: List[float], val_smiles: List[str] = None,
                        val_values: List[float] = None, num_targets: int = 1,
                        target_names: List[str] = None,
                        num_epochs: int = 10, batch_size: int = 32,
                        learning_rate: float = 2e-5,
                        output_dir: str = '/output/finetuned_model',
                        device: str = 'auto') -> Dict:
    """Fine-tune ChemBERTa for regression (e.g., pKi, logP, solubility).

    Args:
        base_model_path: Path to base model (None = pre-cached)
        train_smiles: Training SMILES
        train_values: Training target values (floats)
        val_smiles: Validation SMILES
        val_values: Validation values
        num_targets: Number of regression targets
        target_names: Names of targets
        num_epochs, batch_size, learning_rate: Training hyperparameters
        output_dir: Model save directory
        device: Compute device

    Returns:
        Dict with training history and evaluation metrics
    """
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    from sklearn.metrics import mean_squared_error, r2_score

    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

    if target_names is None:
        target_names = [f"target_{i}" for i in range(num_targets)]

    if val_smiles is None:
        from sklearn.model_selection import train_test_split
        train_smiles, val_smiles, train_values, val_values = train_test_split(
            train_smiles, train_values, test_size=0.15, random_state=42
        )

    if base_model_path is None:
        base_model_path = MODEL_CACHE if os.path.exists(MODEL_CACHE) else DEFAULT_MODEL

    tokenizer = AutoTokenizer.from_pretrained(base_model_path)
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model_path, num_labels=num_targets, problem_type="regression"
    )
    model = model.to(device)

    train_dataset = prepare_dataset(train_smiles, train_values, tokenizer)
    val_dataset = prepare_dataset(val_smiles, val_values, tokenizer)

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size)

    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.01)

    history = {"train_loss": [], "val_loss": [], "val_r2": [], "val_rmse": []}
    best_r2 = -float('inf')

    for epoch in range(num_epochs):
        model.train()
        total_loss = 0
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            outputs = model(**batch)
            loss = outputs.loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad()
            total_loss += loss.item()

        avg_train_loss = total_loss / len(train_loader)

        model.eval()
        all_preds = []
        all_true = []
        val_loss = 0
        with torch.no_grad():
            for batch in val_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                outputs = model(**batch)
                val_loss += outputs.loss.item()
                all_preds.extend(outputs.logits.squeeze(-1).cpu().numpy())
                all_true.extend(batch['labels'].cpu().numpy())

        avg_val_loss = val_loss / len(val_loader)
        val_r2 = r2_score(all_true, all_preds)
        val_rmse = float(mean_squared_error(all_true, all_preds, squared=False))

        history["train_loss"].append(avg_train_loss)
        history["val_loss"].append(avg_val_loss)
        history["val_r2"].append(float(val_r2))
        history["val_rmse"].append(val_rmse)

        logging.info(f"Epoch {epoch + 1}/{num_epochs}: train_loss={avg_train_loss:.4f}, "
                     f"val_r2={val_r2:.4f}, val_rmse={val_rmse:.4f}")

        if val_r2 > best_r2:
            best_r2 = val_r2
            os.makedirs(output_dir, exist_ok=True)
            model.save_pretrained(output_dir)
            tokenizer.save_pretrained(output_dir)
            with open(os.path.join(output_dir, 'target_names.json'), 'w') as f:
                json.dump(target_names, f)

    return {
        "training_complete": True,
        "best_val_r2": float(best_r2),
        "final_val_rmse": history["val_rmse"][-1],
        "num_epochs": num_epochs,
        "train_size": len(train_smiles),
        "val_size": len(val_smiles),
        "history": history,
        "model_saved_to": output_dir
    }


# ============= SIMILARITY & CLUSTERING =============
def compute_similarity_matrix(embeddings: np.ndarray, metric: str = 'cosine') -> np.ndarray:
    """Compute pairwise similarity matrix from molecular embeddings.

    Args:
        embeddings: (n, d) array of embeddings
        metric: 'cosine', 'euclidean', or 'manhattan'

    Returns:
        (n, n) similarity matrix with values in [0, 1]
    """
    from sklearn.metrics.pairwise import cosine_similarity, euclidean_distances

    if metric == 'cosine':
        return cosine_similarity(embeddings)
    elif metric == 'euclidean':
        dist = euclidean_distances(embeddings)
        return 1 / (1 + dist)
    elif metric == 'manhattan':
        from sklearn.metrics.pairwise import manhattan_distances
        dist = manhattan_distances(embeddings)
        return 1 / (1 + dist)
    else:
        raise ValueError(f"Unknown metric: {metric}")


def find_similar_molecules(query_embedding: np.ndarray, database_embeddings: np.ndarray,
                           labels: List[str], top_k: int = 5,
                           metric: str = 'cosine') -> List[Dict]:
    """Find the most similar molecules to a query in an embedding database.

    Args:
        query_embedding: (d,) or (1, d) query embedding
        database_embeddings: (n, d) database embeddings
        labels: Labels/names for database molecules
        top_k: Number of results
        metric: Similarity metric

    Returns:
        List of dicts with label, similarity, index
    """
    if query_embedding.ndim == 1:
        query_embedding = query_embedding.reshape(1, -1)

    sim = compute_similarity_matrix(
        np.vstack([query_embedding, database_embeddings]), metric=metric
    )[0, 1:]

    top_idx = np.argsort(sim)[::-1][:top_k]
    return [{"label": labels[i], "similarity": float(sim[i]), "index": int(i)}
            for i in top_idx]


def cluster_molecules(embeddings: np.ndarray, n_clusters: int = None,
                      method: str = 'kmeans', min_clusters: int = 2,
                      max_clusters: int = 10) -> Dict:
    """Cluster molecules based on their ChemBERTa embeddings.

    Args:
        embeddings: (n, d) embedding array
        n_clusters: Number of clusters (auto-selected via silhouette if None)
        method: 'kmeans' or 'agglomerative'
        min_clusters, max_clusters: Range for auto-selection

    Returns:
        Dict with labels, n_clusters, silhouette_score, cluster_sizes
    """
    from sklearn.cluster import KMeans, AgglomerativeClustering
    from sklearn.metrics import silhouette_score
    from collections import Counter

    if n_clusters is None and len(embeddings) > max_clusters:
        best_score = -1
        best_k = min_clusters
        for k in range(min_clusters, min(max_clusters + 1, len(embeddings))):
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            lab = km.fit_predict(embeddings)
            score = silhouette_score(embeddings, lab)
            if score > best_score:
                best_score = score
                best_k = k
        n_clusters = best_k
        logging.info(f"Auto-selected {n_clusters} clusters (silhouette={best_score:.3f})")
    elif n_clusters is None:
        n_clusters = min(min_clusters, len(embeddings))

    if method == 'kmeans':
        clusterer = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    elif method == 'agglomerative':
        clusterer = AgglomerativeClustering(n_clusters=n_clusters)
    else:
        raise ValueError(f"Unknown method: {method}")

    labels = clusterer.fit_predict(embeddings)
    score = silhouette_score(embeddings, labels) if len(set(labels)) > 1 else 0.0
    sizes = dict(Counter(labels.tolist()))

    return {
        "labels": labels.tolist(),
        "n_clusters": n_clusters,
        "silhouette_score": float(score),
        "cluster_sizes": sizes,
        "method": method
    }


def reduce_dimensions(embeddings: np.ndarray, n_components: int = 2,
                      method: str = 'pca') -> Tuple[np.ndarray, Dict]:
    """Reduce embedding dimensions for visualization.

    Args:
        embeddings: (n, d) array
        n_components: Target dimensions (2 or 3)
        method: 'pca' or 'tsne'

    Returns:
        (reduced_embeddings, metadata_dict)
    """
    if method == 'pca':
        from sklearn.decomposition import PCA
        reducer = PCA(n_components=n_components, random_state=42)
        reduced = reducer.fit_transform(embeddings)
        meta = {"method": "PCA",
                "explained_variance_ratio": reducer.explained_variance_ratio_.tolist()}
    elif method == 'tsne':
        from sklearn.manifold import TSNE
        perplexity = min(30, max(5, len(embeddings) - 1))
        reducer = TSNE(n_components=n_components, random_state=42, perplexity=perplexity)
        reduced = reducer.fit_transform(embeddings)
        meta = {"method": "t-SNE", "perplexity": perplexity}
    else:
        raise ValueError(f"Unknown method: {method}")

    return reduced, meta


# ============= VISUALIZATION =============
def plot_embedding_scatter(embeddings_2d: np.ndarray, labels: List[str] = None,
                           title: str = "Molecular Embedding Space",
                           output_path: str = '/output/embedding_scatter.png',
                           color_by: List = None, cmap: str = 'tab10'):
    """Plot 2D scatter of molecular embeddings."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 8))

    if color_by is not None:
        unique_classes = sorted(set(color_by))
        colors = plt.cm.get_cmap(cmap)(np.linspace(0, 1, max(len(unique_classes), 1)))
        for i, cls in enumerate(unique_classes):
            mask = np.array([c == cls for c in color_by])
            ax.scatter(embeddings_2d[mask, 0], embeddings_2d[mask, 1],
                       c=[colors[i]], label=str(cls), alpha=0.7, s=30)
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    else:
        ax.scatter(embeddings_2d[:, 0], embeddings_2d[:, 1], alpha=0.7, s=30)

    ax.set_title(title)
    ax.set_xlabel('Component 1')
    ax.set_ylabel('Component 2')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved scatter plot: {output_path}")


def plot_similarity_matrix(sim_matrix: np.ndarray, labels: List[str] = None,
                           title: str = "Molecular Similarity Matrix",
                           output_path: str = '/output/similarity_matrix.png'):
    """Plot heatmap of pairwise molecular similarities."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(sim_matrix, cmap='viridis', aspect='auto')
    plt.colorbar(im, ax=ax, label='Similarity')

    if labels and len(labels) <= 30:
        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
        ax.set_yticklabels(labels, fontsize=8)

    ax.set_title(title)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved similarity matrix: {output_path}")


def plot_training_history(history: Dict, output_path: str = '/output/training_history.png'):
    """Plot training loss and validation metrics over epochs."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    epochs = range(1, len(history["train_loss"]) + 1)

    axes[0].plot(epochs, history["train_loss"], 'b-', label='Train Loss')
    axes[0].plot(epochs, history["val_loss"], 'r-', label='Val Loss')
    axes[0].set_xlabel('Epoch')
    axes[0].set_ylabel('Loss')
    axes[0].set_title('Training & Validation Loss')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    if "val_accuracy" in history:
        axes[1].plot(epochs, history["val_accuracy"], 'g-', label='Val Accuracy')
        axes[1].plot(epochs, history["val_f1"], 'm-', label='Val F1 (macro)')
        axes[1].set_ylabel('Score')
    elif "val_r2" in history:
        axes[1].plot(epochs, history["val_r2"], 'g-', label='Val R²')
        ax2 = axes[1].twinx()
        ax2.plot(epochs, history["val_rmse"], 'r--', label='Val RMSE')
        ax2.set_ylabel('RMSE')
        ax2.legend(loc='center right')

    axes[1].set_xlabel('Epoch')
    axes[1].set_title('Validation Metrics')
    axes[1].legend(loc='best')
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved training history: {output_path}")


def plot_confusion_matrix(y_true: List[int], y_pred: List[int],
                          class_names: List[str],
                          output_path: str = '/output/confusion_matrix.png'):
    """Plot confusion matrix for classification results."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from sklearn.metrics import confusion_matrix

    cm = confusion_matrix(y_true, y_pred)
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(cm, interpolation='nearest', cmap='Blues')
    plt.colorbar(im, ax=ax)

    ax.set(xticks=np.arange(cm.shape[1]),
           yticks=np.arange(cm.shape[0]),
           xticklabels=class_names, yticklabels=class_names,
           ylabel='True label', xlabel='Predicted label',
           title='Confusion Matrix')
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    thresh = cm.max() / 2.
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, format(cm[i, j], 'd'),
                    ha="center", va="center",
                    color="white" if cm[i, j] > thresh else "black")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved confusion matrix: {output_path}")


def plot_property_distribution(predictions: List[Dict], property_key: str = 'predicted_class',
                               title: str = 'Prediction Distribution',
                               output_path: str = '/output/distribution.png'):
    """Plot distribution of predicted properties."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from collections import Counter

    values = [p[property_key] for p in predictions]
    fig, ax = plt.subplots(figsize=(10, 6))

    if all(isinstance(v, (int, float)) for v in values):
        ax.hist(values, bins=30, edgecolor='black', alpha=0.7)
        ax.set_ylabel('Count')
    else:
        counts = Counter(values)
        ax.bar(range(len(counts)), counts.values(), tick_label=list(counts.keys()))
        ax.set_ylabel('Count')
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    ax.set_title(title)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved distribution plot: {output_path}")


# ============= CLEANUP =============
def chemberta_cleanup(deep: bool = False):
    """Clean up scratch files and temporary data.

    Args:
        deep: If True, also remove scratch directory files
    """
    try:
        if deep:
            cleared = 0
            try:
                for entry in os.scandir(SCRATCH_DIR):
                    if entry.is_file():
                        try:
                            os.remove(entry.path)
                            cleared += 1
                        except OSError:
                            pass
            except FileNotFoundError:
                pass
            if cleared:
                logging.info(f"Cleared {cleared} scratch files")
            logging.info("Deep cleanup completed")
    except Exception as e:
        logging.warning(f"Cleanup warning: {e}")
