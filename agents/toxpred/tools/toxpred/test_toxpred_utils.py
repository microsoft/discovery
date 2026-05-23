import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import toxpred_utils as tp


def has_pandas():
    return tp._optional_import('pandas') is not None


def has_rdkit():
    return tp._optional_import('rdkit.Chem') is not None


class TestCommandBuilders(unittest.TestCase):
    def test_build_chemprop_train_command(self):
        cmd = tp.build_chemprop_train_command('data.csv', ['ames', 'herg'], 'out', epochs=3)
        joined = ' '.join(cmd)
        self.assertIn('chemprop train', joined)
        self.assertIn('--target-columns ames herg', joined)
        self.assertIn('--epochs 3', joined)

    def test_build_chemprop_predict_command(self):
        cmd = tp.build_chemprop_predict_command('test.csv', ['model_a.pt', 'model_b.pt'], 'preds.csv')
        joined = ' '.join(cmd)
        self.assertIn('chemprop predict', joined)
        self.assertIn('model_a.pt', joined)
        self.assertIn('preds.csv', joined)


@unittest.skipUnless(has_rdkit(), 'rdkit required')
class TestChemistry(unittest.TestCase):
    def test_canonicalize_smiles(self):
        self.assertEqual(tp.canonicalize_smiles('C1=CC=CC=C1'), 'c1ccccc1')
        self.assertTrue(tp.validate_smiles('CCO'))
        self.assertFalse(tp.validate_smiles('not_a_smiles'))


@unittest.skipUnless(has_pandas(), 'pandas required')
class TestTableWorkflows(unittest.TestCase):
    def test_merge_panel(self):
        pd = tp._require('pandas')
        spine = pd.DataFrame([
            {'dsstox_substance_id': 'DTXSIDDEMO0001', 'preferred_name': 'demo1', 'smiles': 'CCO', 'qc_level': 1},
            {'dsstox_substance_id': 'DTXSIDDEMO0002', 'preferred_name': 'demo2', 'smiles': 'CCN', 'qc_level': 1},
        ])
        toxcast = pd.DataFrame([
            {'dsstox_substance_id': 'DTXSIDDEMO0001', 'assay_component_name': 'NR_AR', 'hitc': 1, 'modl_acc': 3.1},
            {'dsstox_substance_id': 'DTXSIDDEMO0001', 'assay_component_name': 'NR_PPARg', 'hitc': 0, 'modl_acc': 10.0},
            {'dsstox_substance_id': 'DTXSIDDEMO0002', 'assay_component_name': 'SR_MMP', 'hitc': 1, 'modl_acc': 1.2},
        ])
        ames = pd.DataFrame([
            {'smiles': 'CCO', 'label': 0, 'split': 'train'},
            {'smiles': 'CCN', 'label': 1, 'split': 'test'},
        ])
        spine_norm = tp.build_dsstox_spine(spine)
        tox_summary = tp.summarize_toxcast_assays(toxcast)
        ames_norm = tp.normalize_endpoint_table(ames, 'ames')
        panel = tp.merge_toxicity_panel(spine_norm, tox_summary, [ames_norm])
        self.assertIn('ames', panel.columns)
        self.assertIn('toxcast_assay_count', panel.columns)
        self.assertEqual(panel.shape[0], 2)

    def test_export_panel(self):
        pd = tp._require('pandas')
        frame = pd.DataFrame([{'canonical_smiles': 'CCO', 'ames': 0, 'split': 'train'}])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'panel.csv')
            returned = tp.export_panel(frame, path)
            self.assertEqual(returned, path)
            self.assertTrue(os.path.exists(path))


if __name__ == '__main__':
    unittest.main()
