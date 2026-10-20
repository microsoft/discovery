# Both bases are pinned to their linux/amd64 manifests; build with --platform linux/amd64.
FROM node:22.22.0-bookworm-slim@sha256:7cc56ef285a8568121537d17b05e72128f01b89c54607b51acf084a50ef483f3 AS node-runtime

FROM python:3.12.14-slim@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79

LABEL org.opencontainers.image.title="FlowBlind prepare study v2"
LABEL org.opencontainers.image.version="2.0.0"

ENV NODE_ENV=production \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    OPENBLAS_CORETYPE=NEHALEM \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    BLIS_NUM_THREADS=1 \
    FLOWBLIND_INPUT_ROOT=/mnt/input \
    FLOWBLIND_OUTPUT_ROOT=/output \
    FLOWBLIND_TOOL_ROLE=prepare-study

WORKDIR /app

RUN addgroup --system --gid 10001 flowblind \
 && adduser --system --uid 10001 --ingroup flowblind --no-create-home flowblind \
 && mkdir -p /app/runtime /mnt/input /output \
 && printf '{"type":"module"}\n' > /app/package.json \
 && chown flowblind:flowblind /output

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --chown=root:root runtime/ /app/runtime/

ARG PIP_INDEX_URL=https://pypi.org/simple
RUN python -m pip install \
      --no-cache-dir \
      --index-url "${PIP_INDEX_URL}" \
      --require-hashes \
      --only-binary=:all: \
      --requirement /app/runtime/generated/retained/hidden-flow-v1/runtime/generated/data/python/requirements.lock.txt \
 && chmod -R a-w /app/runtime \
 && chmod -R a+rX /app/runtime

USER 10001:10001

ENTRYPOINT []
CMD ["node", "/app/runtime/flowblind-prepare-study-v2.js"]
