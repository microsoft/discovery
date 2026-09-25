FROM node:24.16.0-alpine3.22@sha256:191c9f0080fcbbc6547a85dc0ff7988072214a355aabdc1d2ec55a7dae5eea8a

LABEL org.opencontainers.image.title="FlowBlind prepare study"
LABEL org.opencontainers.image.description="Restart-safe result-free FlowBlind study preparation"
LABEL org.opencontainers.image.version="1.0.0"

RUN addgroup -S -g 10001 flowblind \
 && adduser -S -D -H -u 10001 -G flowblind flowblind \
 && mkdir -p /app/runtime /mnt/input /output \
 && chown flowblind:flowblind /output

WORKDIR /app

COPY --chown=root:root runtime/ /app/runtime/

RUN chmod -R a-w /app/runtime \
 && chmod -R a+rX /app/runtime

ENV NODE_ENV=production
ENV FLOWBLIND_INPUT_ROOT=/mnt/input
ENV FLOWBLIND_OUTPUT_ROOT=/output
ENV FLOWBLIND_TOOL_ROLE=prepare-study

USER 10001:10001

ENTRYPOINT []

CMD ["/bin/sh"]
