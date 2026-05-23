#!/usr/bin/env python3
"""Unit tests for boltztwo_utils.py -- run with pytest.

These tests exercise input generation, output parsing, FASTA reading, and
entity construction WITHOUT requiring the boltz binary or GPU.  They use
temp directories and synthetic data.
"""

import json
import os
import sys
import tempfile

import pytest
import yaml

# Allow import from same directory
sys.path.insert(0, os.path.dirname(__file__))
from boltztwo_utils import (
    build_input_yaml,
    copy_structures_to_output,
    dna_entity,
    extract_plddt_per_residue,
    fasta_to_boltz_yaml,
    find_output_structures,
    ligand_entity_ccd,
    ligand_entity_smiles,
    parse_affinity_output,
    parse_confidence_json,
    protein_entity,
    read_fasta,
    rna_entity,
    save_final_results,
    summarize_prediction,
)
import boltztwo_utils as utils


# ---------- Fixtures ----------


@pytest.fixture(autouse=True)
def setup_dirs(tmp_path):
    """Set module-level dirs to temp directories for each test."""
    utils.INPUT_DIR = str(tmp_path / "input")
    utils.OUTPUT_DIR = str(tmp_path / "output")
    utils.WORK_DIR = str(tmp_path / "workdir")
    os.makedirs(utils.INPUT_DIR, exist_ok=True)
    os.makedirs(utils.OUTPUT_DIR, exist_ok=True)
    os.makedirs(utils.WORK_DIR, exist_ok=True)
    os.chdir(utils.WORK_DIR)
    yield


# ---------- Entity Construction ----------


class TestEntityBuilders:
    def test_protein_entity(self):
        e = protein_entity("A", "MKTAYIA")
        assert e == {"protein": {"id": "A", "sequence": "MKTAYIA"}}

    def test_protein_entity_with_msa(self):
        e = protein_entity("A", "MKTAYIA", msa="/path/to/msa.a3m")
        assert e["protein"]["msa"] == "/path/to/msa.a3m"

    def test_ligand_smiles(self):
        e = ligand_entity_smiles("B", "CCO")
        assert e == {"smiles": {"id": "B", "smi": "CCO"}}

    def test_ligand_ccd(self):
        e = ligand_entity_ccd("C", "ATP")
        assert e == {"ccd": {"id": "C", "code": "ATP"}}

    def test_rna_entity(self):
        e = rna_entity("D", "AUGCAUGC")
        assert e == {"rna": {"id": "D", "sequence": "AUGCAUGC"}}

    def test_dna_entity(self):
        e = dna_entity("E", "ATGCATGC")
        assert e == {"dna": {"id": "E", "sequence": "ATGCATGC"}}


# ---------- Input YAML Generation ----------


class TestBuildInputYaml:
    def test_single_protein(self):
        seqs = [protein_entity("A", "MKTAYIA")]
        path = build_input_yaml(seqs, "test.yaml")
        assert os.path.isfile(path)
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["version"] == 2
        assert len(data["sequences"]) == 1
        assert "protein" in data["sequences"][0]

    def test_protein_ligand_complex(self):
        seqs = [
            protein_entity("A", "MKTAYIA"),
            ligand_entity_smiles("B", "c1ccccc1"),
        ]
        path = build_input_yaml(seqs, "complex.yaml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert len(data["sequences"]) == 2

    def test_multi_chain(self):
        seqs = [
            protein_entity("A", "MKTAYIA"),
            protein_entity("B", "GGGGGGG"),
            rna_entity("C", "AUGCAU"),
        ]
        path = build_input_yaml(seqs, "multi.yaml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert len(data["sequences"]) == 3


# ---------- FASTA Reading ----------


class TestReadFasta:
    def test_single_entry(self):
        fasta = ">protein_A\nMKTAYIA\nGGGGGGG\n"
        path = os.path.join(utils.WORK_DIR, "test.fasta")
        with open(path, "w") as f:
            f.write(fasta)
        entries = read_fasta(path)
        assert len(entries) == 1
        assert entries[0]["id"] == "protein_A"
        assert entries[0]["sequence"] == "MKTAYIAGGGGGGG"

    def test_multi_entry(self):
        fasta = ">A\nMKTAYIA\n>B\nGGGGGGG\n"
        path = os.path.join(utils.WORK_DIR, "multi.fasta")
        with open(path, "w") as f:
            f.write(fasta)
        entries = read_fasta(path)
        assert len(entries) == 2
        assert entries[0]["sequence"] == "MKTAYIA"
        assert entries[1]["sequence"] == "GGGGGGG"

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            read_fasta("/nonexistent/file.fasta")


class TestFastaToBoltzYaml:
    def test_basic(self):
        fasta = ">chain_A\nMKTAYIA\n"
        path = os.path.join(utils.WORK_DIR, "test.fasta")
        with open(path, "w") as f:
            f.write(fasta)
        yaml_path = fasta_to_boltz_yaml(path, "output.yaml")
        assert os.path.isfile(yaml_path)
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert len(data["sequences"]) == 1

    def test_with_ligand(self):
        fasta = ">chain_A\nMKTAYIA\n"
        path = os.path.join(utils.WORK_DIR, "test.fasta")
        with open(path, "w") as f:
            f.write(fasta)
        yaml_path = fasta_to_boltz_yaml(path, "lig.yaml", ligand_smiles="CCO")
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert len(data["sequences"]) == 2


# ---------- Output Parsing ----------


class TestOutputParsing:
    def _make_out_dir(self):
        d = os.path.join(utils.WORK_DIR, "out")
        os.makedirs(d, exist_ok=True)
        return d

    def test_find_structures_empty(self):
        d = self._make_out_dir()
        assert find_output_structures(d) == []

    def test_find_structures(self):
        d = self._make_out_dir()
        for name in ["model_0.cif", "model_1.cif"]:
            with open(os.path.join(d, name), "w") as f:
                f.write("data_test\n")
        result = find_output_structures(d)
        assert len(result) == 2

    def test_parse_confidence_json(self):
        d = self._make_out_dir()
        conf = {"ptm": 0.85, "iptm": 0.72, "plddt": [80.0, 90.0, 70.0]}
        with open(os.path.join(d, "confidence_model_0.json"), "w") as f:
            json.dump(conf, f)
        results = parse_confidence_json(d)
        assert len(results) == 1
        assert results[0]["ptm"] == 0.85

    def test_parse_affinity(self):
        d = self._make_out_dir()
        aff = {"binder_probability": 0.92, "pic50": 7.3}
        with open(os.path.join(d, "affinity_model_0.json"), "w") as f:
            json.dump(aff, f)
        results = parse_affinity_output(d)
        assert len(results) == 1
        assert results[0]["pic50"] == 7.3

    def test_parse_affinity_from_confidence(self):
        d = self._make_out_dir()
        conf = {"ptm": 0.8, "binder_probability": 0.5, "pic50": 5.0}
        with open(os.path.join(d, "confidence_model_0.json"), "w") as f:
            json.dump(conf, f)
        results = parse_affinity_output(d)
        assert len(results) >= 1
        assert results[0]["pic50"] == 5.0

    def test_extract_plddt(self):
        d = self._make_out_dir()
        conf = {"plddt": [80.0, 90.0, 70.0]}
        with open(os.path.join(d, "confidence_model_0.json"), "w") as f:
            json.dump(conf, f)
        plddt = extract_plddt_per_residue(d)
        assert len(plddt) == 1
        key = list(plddt.keys())[0]
        assert plddt[key] == [80.0, 90.0, 70.0]

    def test_summarize_prediction(self):
        d = self._make_out_dir()
        with open(os.path.join(d, "model_0.cif"), "w") as f:
            f.write("data_test\n")
        conf = {"ptm": 0.85, "iptm": 0.72, "plddt": [80.0, 90.0]}
        with open(os.path.join(d, "confidence_model_0.json"), "w") as f:
            json.dump(conf, f)
        summary = summarize_prediction(d)
        assert summary["num_structures"] == 1
        assert summary["ptm"] == 0.85


# ---------- save_final_results ----------


class TestSaveFinalResults:
    def test_basic_save(self):
        save_final_results({"key": "value"})
        path = os.path.join(utils.OUTPUT_DIR, "final_results.json")
        assert os.path.isfile(path)
        with open(path) as f:
            data = json.load(f)
        assert data["status"] == "completed"
        assert data["summary"]["key"] == "value"

    def test_with_files(self):
        save_final_results(
            {"k": 1},
            output_files={"plot": "/output/p.png"},
            file_descriptions={"plot": "A plot"},
        )
        path = os.path.join(utils.OUTPUT_DIR, "final_results.json")
        with open(path) as f:
            data = json.load(f)
        assert "output_files" in data


# ---------- copy_structures_to_output ----------


class TestCopyStructures:
    def test_copy(self):
        d = os.path.join(utils.WORK_DIR, "out")
        os.makedirs(d)
        with open(os.path.join(d, "model.cif"), "w") as f:
            f.write("data_test\n")
        copied = copy_structures_to_output(d)
        assert len(copied) == 1
        assert os.path.isfile(os.path.join(utils.OUTPUT_DIR, "model.cif"))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
