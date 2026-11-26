FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

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