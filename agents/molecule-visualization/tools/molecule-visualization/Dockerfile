FROM python:3.15-slim-bookworm@sha256:4e03260adeeebafccd084f3584e6b84823aba5651cfb53ef8a078ed441ddf9cd

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/visualizer \
    TMPDIR=/workdir \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --only-binary=:all: -r /app/requirements.txt \
    && python -m pip check

COPY app/visualizations.py /app/visualizations.py

RUN python -c "import rdkit, plotly, PIL; from PIL import Image; import visualizations; print('RDKit', rdkit.__version__, 'Plotly', plotly.__version__, 'Pillow', PIL.__version__)"

RUN groupadd --gid 10001 visualizer \
    && useradd --uid 10001 --gid visualizer --create-home --shell /usr/sbin/nologin visualizer \
    && mkdir -p /input /output /workdir \
    && chown visualizer:visualizer /input /output /workdir

WORKDIR /workdir
USER 10001:10001

ENTRYPOINT ["python", "/app/visualizations.py"]