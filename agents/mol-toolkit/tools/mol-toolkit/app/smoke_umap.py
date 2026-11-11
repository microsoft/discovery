"""Verify real UMAP execution on the ten-candidate Tanimoto-distance workflow."""

from importlib.metadata import version

import numpy as np
from umap import UMAP


def main() -> None:
    fingerprints = np.random.RandomState(42).randint(0, 2, size=(10, 64))
    intersections = fingerprints @ fingerprints.T
    counts = np.diag(intersections)
    unions = counts[:, None] + counts[None, :] - intersections
    similarities = intersections / unions
    distances = 1.0 - similarities
    np.fill_diagonal(distances, 0.0)

    embedding = UMAP(
        n_components=2,
        metric="precomputed",
        n_neighbors=min(15, distances.shape[0] - 1),
        init="random",
        random_state=42,
        n_jobs=1,
    ).fit_transform(distances)

    if embedding.shape != (10, 2) or not np.isfinite(embedding).all():
        raise RuntimeError("UMAP must produce ten finite two-dimensional coordinates")
    print(f"UMAP_SMOKE_OK: umap-learn={version('umap-learn')}, shape={embedding.shape}")


if __name__ == "__main__":
    main()
