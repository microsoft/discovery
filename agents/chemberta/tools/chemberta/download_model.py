#!/usr/bin/env python3
"""Download and cache ChemBERTa-2 model weights during Docker build."""
from transformers import AutoModel, AutoTokenizer
print('Downloading ChemBERTa-77M-MTR...')
t = AutoTokenizer.from_pretrained('DeepChem/ChemBERTa-77M-MTR')
m = AutoModel.from_pretrained('DeepChem/ChemBERTa-77M-MTR')
t.save_pretrained('/app/model_cache')
m.save_pretrained('/app/model_cache')
print('Model cached successfully')
