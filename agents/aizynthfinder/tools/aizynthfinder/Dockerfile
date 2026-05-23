# ─────────────────────────────────────────────────────────────────────────────
#  AiZynthFinder Agent — Retrosynthetic Route Planning
#  Base: Azure Linux 3.0 + Python 3.12 (minimal CVE surface)
#  Models: USPTO expansion/filter policies + ZINC stock (pre-baked)
# ─────────────────────────────────────────────────────────────────────────────
FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app:${PYTHONPATH}
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV KMP_AFFINITY=disabled
ENV GOMP_CPU_AFFINITY=""
# Suppress TensorFlow / ONNX Runtime logging
ENV TF_CPP_MIN_LOG_LEVEL=2

# ── Layer 1: System update + TLS (shared across agents) ─────────────────────
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# ── Layer 2: Common scientific Python packages (shared across agents) ───────
RUN pip3 install --no-cache-dir \
    matplotlib numpy pandas requests scipy seaborn

# ── Layer 3: Build tools + X11 rendering libs (RDKit rdMolDraw2D needs them) ─
RUN tdnf -y install gcc gcc-c++ make pkg-config \
    libXrender libXext libX11 cairo && \
    tdnf clean all

# ── Layer 4: AiZynthFinder + extras ─────────────────────────────────────────
#    Pins numpy<2.0.0 as required by aizynthfinder.
#    The [all] extra adds: pymongo, route-distances, scipy, timeout-decorator, molbloom.
RUN pip3 install --no-cache-dir \
    "numpy<2.0.0" \
    "aizynthfinder[all]" \
    pyyaml

# ── Layer 5: Remove build tools only (keep X11 libs) ────────────────────────
RUN tdnf -y remove gcc gcc-c++ make pkg-config && \
    tdnf clean all || true

# ── Layer 6: Download public models (~600 MB total) ─────────────────────────
RUN mkdir -p /app/models && \
    echo "Downloading USPTO expansion model..." && \
    curl -fSL --retry 3 -o /app/models/uspto_model.onnx \
        "https://zenodo.org/record/7797465/files/uspto_model.onnx" && \
    echo "Downloading USPTO templates..." && \
    curl -fSL --retry 3 -o /app/models/uspto_templates.csv.gz \
        "https://zenodo.org/record/7341155/files/uspto_unique_templates.csv.gz" && \
    echo "Downloading RingBreaker model..." && \
    curl -fSL --retry 3 -o /app/models/uspto_ringbreaker_model.onnx \
        "https://zenodo.org/record/7797465/files/uspto_ringbreaker_model.onnx" && \
    echo "Downloading RingBreaker templates..." && \
    curl -fSL --retry 3 -o /app/models/uspto_ringbreaker_templates.csv.gz \
        "https://zenodo.org/record/7341155/files/uspto_ringbreaker_unique_templates.csv.gz" && \
    echo "Downloading ZINC stock..." && \
    curl -fSL --retry 3 -o /app/models/zinc_stock.hdf5 \
        "https://ndownloader.figshare.com/files/23086469" && \
    echo "Downloading USPTO filter model..." && \
    curl -fSL --retry 3 -o /app/models/uspto_filter_model.onnx \
        "https://zenodo.org/record/7797465/files/uspto_filter_model.onnx" && \
    echo "All models downloaded."

# ── Layer 7: Generate default config ────────────────────────────────────────
RUN python3 -c "\
import yaml, os; \
d = '/app/models'; \
cfg = { \
  'expansion': { \
    'uspto': [os.path.join(d,'uspto_model.onnx'), os.path.join(d,'uspto_templates.csv.gz')], \
    'ringbreaker': [os.path.join(d,'uspto_ringbreaker_model.onnx'), os.path.join(d,'uspto_ringbreaker_templates.csv.gz')], \
  }, \
  'filter': {'uspto': os.path.join(d,'uspto_filter_model.onnx')}, \
  'stock': {'zinc': os.path.join(d,'zinc_stock.hdf5')}, \
}; \
yaml.dump(cfg, open(os.path.join(d,'config.yml'),'w'), default_flow_style=False); \
print('Default config.yml generated')"

# ── Layer 8: Copy application code ──────────────────────────────────────────
COPY aizynthfinder_utils.py /app/
COPY test_aizynthfinder_utils.py /app/

# ── Layer 9: Directory structure ────────────────────────────────────────────
RUN mkdir -p /workdir /input /output /tmp/aizynthfinder_scratch /tmp/matplotlib && \
    chmod 755 /workdir /input /output

WORKDIR /workdir
CMD ["/bin/bash"]
