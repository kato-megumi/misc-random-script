"""Core IR definition for Anime4K CNN models."""

from dataclasses import dataclass

import numpy as np


@dataclass
class Anime4KCNN:
    """Intermediate representation of an Anime4K CNN model.

    All weights stored in shader convention:
    - PixelShuffle permutation [0,2,1,3] per color group already applied to tail
    - Weight tensors as numpy float32 arrays
    """

    num_feat: int           # Feature channels (e.g. 12 for UL)
    block_depth: int        # Total depth including head (e.g. 7 for UL)
    factor: int             # CReLU factor (2) or PReLU factor (1)
    n_stack: int            # Number of stacked layers for aggregation
    tail_kernel: int        # Aggregation kernel size (1 or 3)

    head_weight: np.ndarray  # [num_feat, 3, 3, 3]
    head_bias: np.ndarray    # [num_feat]

    mid_weights: list        # list of [num_feat, num_feat*factor, 3, 3]
    mid_biases: list         # list of [num_feat]

    tail_weight: np.ndarray  # [12, num_feat*factor*n_stack, tail_k, tail_k]
    tail_bias: np.ndarray    # [12]  (in shader/permuted order)


# PixelShuffle permutation: PyTorch order [0,1,2,3] per color -> shader [0,2,1,3]
# Self-inverse: applying twice gives identity
PIXEL_SHUFFLE_PERM = [0, 2, 1, 3, 4, 6, 5, 7, 8, 10, 9, 11]


__all__ = ["Anime4KCNN", "PIXEL_SHUFFLE_PERM"]
