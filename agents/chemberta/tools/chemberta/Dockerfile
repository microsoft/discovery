FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV TRANSFORMERS_CACHE=/app/model_cache
ENV HF_HOME=/app/model_cache
ENV PYTHONPATH=/app
ENV OMP_NUM_THREADS=4
ENV MKL_NUM_THREADS=4
ENV TOKENIZERS_PARALLELISM=false

# Layer 1: System updates and CA certificates
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# Layer 2: Create directories
RUN mkdir -p /app /workdir /input /output /tmp/chemberta_scratch /app/model_cache && \
    chmod 755 /workdir /input /output

# Layer 3: Common scientific Python packages
RUN pip3 install --no-cache-dir \
    numpy==1.26.4 \
    pandas==2.2.1 \
    scipy==1.12.0 \
    matplotlib==3.8.3 \
    seaborn==0.13.2 \
    scikit-learn==1.4.1.post1

# Layer 4: PyTorch CPU-only
RUN pip3 install --no-cache-dir \
    torch==2.2.1 \
    --index-url https://download.pytorch.org/whl/cpu

# Layer 5: HuggingFace transformers and RDKit (Python 3.12 compatible)
RUN pip3 install --no-cache-dir \
    transformers==4.38.2 \
    tokenizers==0.15.2 \
    safetensors==0.4.2 \
    rdkit==2025.9.5 \
    tqdm==4.66.2 \
    pytest==8.0.2

# Layer 6: Pre-download ChemBERTa-2 model weights via script
COPY download_model.py /tmp/download_model.py
RUN python3 /tmp/download_model.py && rm /tmp/download_model.py

# Layer 7: Copy application code
COPY chemberta_utils.py /app/
COPY test_chemberta_utils.py /app/

# Verify installation
RUN python3 -c "import torch; import transformers; from rdkit import Chem; print('All imports OK')"
RUN python3 -c "from chemberta_utils import validate_smiles; print('Utils import OK')"

CMD ["/bin/bash"]
