FROM continuumio/miniconda3:latest

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential curl ca-certificates wget git \
    && rm -rf /var/lib/apt/lists/*

RUN conda create -n tool python=3.11 -y && \
    conda install -n tool -c conda-forge -c bioconda \
    dftbplus \
    -y && conda clean -afy

ENV PATH="/opt/conda/envs/tool/bin:$PATH"
ENV CONDA_DEFAULT_ENV=tool
ENV LD_LIBRARY_PATH="/opt/conda/envs/tool/lib:$LD_LIBRARY_PATH"

COPY app/ /app/
RUN chmod +x /app/entrypoint.py
RUN mkdir -p /input /output

ENV TOOL_INPUT_DIR=/input
ENV TOOL_OUTPUT_DIR=/output
ENV PYTHONPATH=/app:$PYTHONPATH

CMD ["/bin/bash"]
