FROM r-base:4.6.2@sha256:7bb56b8b7c849d1cea9a5cff981789622340326abdce817ed44c00ac45947a37

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
