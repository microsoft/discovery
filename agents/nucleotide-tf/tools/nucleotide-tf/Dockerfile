# Nucleotide Transformer v2 Container for Microsoft Discovery Platform
# Azure Linux 3.0 (Python 3.12) - hardened, minimal, fast CVE patching
# Model: InstaDeepAI/nucleotide-transformer-v2-500m-multi-species (500M params)

FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV HF_HOME=/app/model_cache
ENV TRANSFORMERS_CACHE=/app/model_cache

# Thread control defaults (let scripts override at runtime)
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1

# System dependencies -- identical across agents for layer sharing
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# Common scientific Python packages (shared layer)
RUN pip3 install --no-cache-dir \
    matplotlib numpy pandas requests scipy seaborn

# PyTorch CPU-only (smaller image; GPU support can be added in v2)
RUN pip3 install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Transformers and ML stack
# Pin transformers<=4.44.2 for compatibility with NT v2's custom modeling code
# (find_pruneable_heads_and_indices was renamed in 4.45+)
RUN pip3 install --no-cache-dir \
    "transformers<=4.44.2" safetensors tokenizers \
    scikit-learn biopython tqdm PyYAML

# Create directories
RUN mkdir -p /app /workdir /input /output /tmp/nt_scratch /tmp/matplotlib /app/model_cache

# Download model weights at build time (container is self-contained, no runtime internet needed)
# NT v2 500M multi-species: ~2 GB weights, 6-mer tokenizer, custom modeling code
RUN python3 -c "from transformers import AutoTokenizer, AutoModelForMaskedLM; \
print('Downloading tokenizer...'); \
AutoTokenizer.from_pretrained('InstaDeepAI/nucleotide-transformer-v2-500m-multi-species', trust_remote_code=True, cache_dir='/app/model_cache'); \
print('Downloading model weights...'); \
AutoModelForMaskedLM.from_pretrained('InstaDeepAI/nucleotide-transformer-v2-500m-multi-species', trust_remote_code=True, cache_dir='/app/model_cache'); \
print('Model downloaded successfully')"

# Copy utilities
WORKDIR /app
COPY nucleotide_tf_utils.py /app/nucleotide_tf_utils.py
COPY test_nucleotide_tf_utils.py /app/test_nucleotide_tf_utils.py
ENV PYTHONPATH="/app"

WORKDIR /app/workdir
CMD ["/bin/bash"]
