FROM continuumio/miniconda3:latest

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential curl ca-certificates wget git \
    && rm -rf /var/lib/apt/lists/*

RUN conda create -n tool python=3.11 -y && \
    conda install -n tool -c conda-forge \
    openjdk=17 \
    -y && conda clean -afy

ENV PATH="/opt/conda/envs/tool/bin:$PATH"
ENV CONDA_DEFAULT_ENV=tool
ENV LD_LIBRARY_PATH="/opt/conda/envs/tool/lib:$LD_LIBRARY_PATH"

# P2Rank is a standalone Java tarball (not on conda); fetch a pinned release.
# Do NOT symlink prank into /usr/local/bin — its launcher resolves its own
# directory to build the classpath, so add the install dir to PATH instead.
RUN wget -q https://github.com/rdk/p2rank/releases/download/2.4.2/p2rank_2.4.2.tar.gz -O /tmp/p2rank.tar.gz \
    && tar -xzf /tmp/p2rank.tar.gz -C /opt \
    && ln -s /opt/conda/envs/tool/bin/java /usr/local/bin/java \
    && rm /tmp/p2rank.tar.gz
ENV JAVA_HOME=/opt/conda/envs/tool
ENV PATH="/opt/p2rank_2.4.2:$PATH"

COPY app/ /app/
RUN chmod +x /app/entrypoint.py
RUN mkdir -p /input /output

ENV TOOL_INPUT_DIR=/input
ENV TOOL_OUTPUT_DIR=/output
ENV PYTHONPATH=/app:$PYTHONPATH

CMD ["/bin/bash"]
