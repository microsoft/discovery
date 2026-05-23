# Third-Party Components

This agent's container image embeds the following third-party open-source components.
Each component is governed by its own license. The Discovery wrapper code itself is
licensed under MIT and is governed by the repository's top-level
[`LICENSE`](../../../LICENSE).

## Primary upstream tool & weights

| Component | Version | License | Source | Notes |
|---|---|---|---|---|
| ESM-2 (Evolutionary Scale Modeling) | latest | MIT | https://github.com/facebookresearch/esm | Protein language model. |
| ESM-2 model checkpoints | various sizes | MIT | https://huggingface.co/facebook/esm2_* | Pre-cached weights (typically 650M parameters; 3B available). Model weights distributed under MIT. |
| PyTorch (CUDA 12.1) | latest | BSD-3-Clause-with-patent-grant | https://github.com/pytorch/pytorch | |
| transformers | latest | Apache-2.0 | https://github.com/huggingface/transformers | Model loader. |

## Key Python dependencies (permissive)

| Component | License | Source |
|---|---|---|
| numpy | BSD-3-Clause | https://github.com/numpy/numpy |
| Biopython | Biopython License (BSD-style) | https://biopython.org/ |
| scikit-learn | BSD-3-Clause | https://github.com/scikit-learn/scikit-learn |
| matplotlib | PSF-based / matplotlib license | https://github.com/matplotlib/matplotlib |

## NVIDIA CUDA runtime

| Component | Version | License | Notes |
|---|---|---|---|
| NVIDIA CUDA / cuDNN runtime | 12.1 | NVIDIA Software License Agreement (proprietary) | Distribution permitted under NVIDIA's redistributable runtime terms; CUDA is not open source. |

## License compatibility notes

- ESM-2 (code + weights) is MIT; the wrapper is MIT. Compatible.
