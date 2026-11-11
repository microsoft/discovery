# Both bases are pinned to their linux/amd64 manifests; build with --platform linux/amd64.
FROM node:26.13.0-bookworm-slim@sha256:add5c17c14752c54d2f3d519ec46a3815684d41c33f198bcb09fb998f7dcbf68 AS node-runtime

FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58

LABEL org.opencontainers.image.title="FlowBlind run and verify study v2"
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
    FLOWBLIND_PREPARATION_ROOT=/mnt/preparation \
    FLOWBLIND_OUTPUT_ROOT=/output \
    FLOWBLIND_TOOL_ROLE=run-and-verify-study

WORKDIR /app

RUN addgroup --system --gid 10001 flowblind \
 && adduser --system --uid 10001 --ingroup flowblind --no-create-home flowblind \
 && mkdir -p /app/runtime /mnt/input /mnt/preparation /output \
 && printf '{"type":"module"}\n' > /app/package.json \
 && chown flowblind:flowblind /output

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/lib/x86_64-linux-gnu/libatomic.so.1* /usr/lib/x86_64-linux-gnu/
RUN node --version
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
CMD ["node", "/app/runtime/flowblind-run-and-verify-study-v2.js"]
