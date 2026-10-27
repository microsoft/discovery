FROM r-base:4.5.3@sha256:881cf9bc036d399aafe32954e16de5bf5663d9a7aae4a68a3d87222a573a28c9

COPY packages.csv install-packages.R /tmp/
RUN Rscript --vanilla /tmp/install-packages.R \
 && rm /tmp/packages.csv /tmp/install-packages.R

ENV HOME=/home/rworker \
    TMPDIR=/workdir \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

RUN groupadd --gid 10001 rworker \
 && useradd --uid 10001 --gid rworker --create-home --shell /usr/sbin/nologin rworker \
 && mkdir -p /input /output /workdir \
 && chown rworker:rworker /input /output /workdir

WORKDIR /workdir
USER 10001:10001

CMD ["sleep", "infinity"]
