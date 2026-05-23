#!/usr/bin/env bash
# Build RetroChimera container images and push to ACR.
#
# Usage:
#   ./build-acr.sh <target> <acr-name> [options]
#
# Targets:
#   deps        - Conda/pip dependencies (~3.6 GB, rebuild on version bumps)
#   checkpoint  - Pistachio model checkpoint (~4 GB, build once)
#   bb          - eMolecules building blocks (~200 MB, rebuild monthly)
#   main        - Full runtime image (pulls deps + checkpoint + bb from ACR, uses Dockerfile.fast)
#   allinone    - Standalone image (no ACR dependencies, uses default Dockerfile)
#   all         - Build deps, checkpoint, bb, then main (in dependency order)
#
# Options:
#   --deps-tag TAG         Tag for deps image (default: 1.1.0)
#   --checkpoint-tag TAG   Tag for checkpoint image (default: v1)
#   --bb-tag TAG           Tag for building blocks image (default: 2026-04)
#   --main-tag TAG         Tag for main/allinone image (default: latest)
#   --bb-url URL           Override eMolecules download URL
#
# Examples:
#   ./build-acr.sh all mdqacr
#   ./build-acr.sh main mdqacr
#   ./build-acr.sh bb mdqacr --bb-tag 2026-05
#   ./build-acr.sh allinone mdqacr

set -euo pipefail

TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"

TARGET="${1:?Usage: $0 <deps|checkpoint|bb|main|allinone|all> <acr-name> [options]}"
ACR_NAME="${2:?Usage: $0 <target> <acr-name> [options]}"
shift 2

DEPS_TAG="1.1.0"
CHECKPOINT_TAG="v1"
BB_TAG="2026-04"
MAIN_TAG="latest"
BB_URL=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --deps-tag)       DEPS_TAG="$2"; shift 2 ;;
        --checkpoint-tag) CHECKPOINT_TAG="$2"; shift 2 ;;
        --bb-tag)         BB_TAG="$2"; shift 2 ;;
        --main-tag)       MAIN_TAG="$2"; shift 2 ;;
        --bb-url)         BB_URL="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

build_deps() {
    echo ""
    echo "=== Building retrochimera-deps:${DEPS_TAG} ==="
    az acr build -r "$ACR_NAME" \
        -t "retrochimera-deps:${DEPS_TAG}" \
        -f "${TOOL_DIR}/Dockerfile.deps" \
        "$TOOL_DIR"
}

build_checkpoint() {
    echo ""
    echo "=== Building retrochimera-checkpoint:${CHECKPOINT_TAG} ==="
    az acr build -r "$ACR_NAME" \
        -t "retrochimera-checkpoint:${CHECKPOINT_TAG}" \
        -f "${TOOL_DIR}/Dockerfile.checkpoint" \
        "$TOOL_DIR"
}

build_bb() {
    echo ""
    echo "=== Building retrochimera-bb:${BB_TAG} ==="
    local extra_args=()
    if [[ -n "$BB_URL" ]]; then
        extra_args+=(--build-arg "BUILDING_BLOCKS_URL=${BB_URL}")
    fi
    az acr build -r "$ACR_NAME" \
        -t "retrochimera-bb:${BB_TAG}" \
        -f "${TOOL_DIR}/Dockerfile.bb" \
        "${extra_args[@]}" \
        "$TOOL_DIR"
}

build_main() {
    echo ""
    echo "=== Building retrochimera:${MAIN_TAG} ==="
    az acr build -r "$ACR_NAME" \
        -t "retrochimera:${MAIN_TAG}" \
        -f "${TOOL_DIR}/Dockerfile.fast" \
        --build-arg "DEPS_IMAGE=${ACR_NAME}.azurecr.io/retrochimera-deps:${DEPS_TAG}" \
        --build-arg "CHECKPOINT_IMAGE=${ACR_NAME}.azurecr.io/retrochimera-checkpoint:${CHECKPOINT_TAG}" \
        --build-arg "BB_IMAGE=${ACR_NAME}.azurecr.io/retrochimera-bb:${BB_TAG}" \
        "$TOOL_DIR"
}

build_allinone() {
    echo ""
    echo "=== Building retrochimera:${MAIN_TAG} (all-in-one) ==="
    local extra_args=()
    if [[ -n "$BB_URL" ]]; then
        extra_args+=(--build-arg "BUILDING_BLOCKS_URL=${BB_URL}")
    fi
    az acr build -r "$ACR_NAME" \
        -t "retrochimera:${MAIN_TAG}" \
        -f "${TOOL_DIR}/Dockerfile" \
        "${extra_args[@]}" \
        "$TOOL_DIR"
}

case "$TARGET" in
    deps)       build_deps ;;
    checkpoint) build_checkpoint ;;
    bb)         build_bb ;;
    main)       build_main ;;
    allinone)   build_allinone ;;
    all)
        build_deps
        build_checkpoint
        build_bb
        build_main
        echo ""
        echo "=== All images built successfully ==="
        ;;
    *)
        echo "Unknown target: $TARGET" >&2
        echo "Valid targets: deps, checkpoint, bb, main, allinone, all" >&2
        exit 1
        ;;
esac
