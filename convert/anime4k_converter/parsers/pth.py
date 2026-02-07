"""PyTorch model parser (.pth/.safetensors)."""

import sys
from typing import Any, cast

from ..ir import Anime4KCNN, PIXEL_SHUFFLE_PERM


def parse_pth(path: str) -> Anime4KCNN:
    """Load PyTorch model weights (.pth/.safetensors) -> IR."""
    import torch

    if path.endswith(".safetensors"):
        try:
            from safetensors.torch import load_file
            state_dict = load_file(path)
        except ImportError:
            print("Error: safetensors package required", file=sys.stderr)
            sys.exit(1)
    else:
        state_dict = torch.load(path, map_location="cpu", weights_only=True)

    if not isinstance(state_dict, dict):
        raise TypeError("Expected a state dict mapping")

    # Unwrap nested state dicts
    for key in ("params_ema", "params", "model", "state_dict"):
        if key in state_dict and isinstance(state_dict[key], dict):
            state_dict = state_dict[key]
            break

    if not isinstance(state_dict, dict):
        raise TypeError("Expected a state dict mapping")

    state_dict = cast(dict[str, Any], state_dict)

    def get_key(partial: str) -> str:
        for k in state_dict:
            if partial in k:
                return k
        raise KeyError(f"No key matching '{partial}'")

    head_w = state_dict[get_key("conv_head.weight")].float().numpy()
    head_b = state_dict[get_key("conv_head.bias")].float().numpy()
    num_feat = head_w.shape[0]

    # Count mid layers
    mid_indices = sorted(set(
        int(k.split("conv_mid.")[1].split(".")[0])
        for k in state_dict if "conv_mid." in k and "weight" in k
    ))
    block_depth = len(mid_indices) + 1

    mid_ws, mid_bs = [], []
    for idx in mid_indices:
        mid_ws.append(state_dict[get_key(f"conv_mid.{idx}.weight")].float().numpy())
        mid_bs.append(state_dict[get_key(f"conv_mid.{idx}.bias")].float().numpy())

    # Determine factor
    if mid_indices:
        factor = mid_ws[0].shape[1] // num_feat
    else:
        factor = 2

    tail_w = state_dict[get_key("conv_tail.weight")].float().numpy().copy()
    tail_b = state_dict[get_key("conv_tail.bias")].float().numpy().copy()
    tail_kernel = tail_w.shape[2]
    n_stack = tail_w.shape[1] // (num_feat * factor)

    # Apply PixelShuffle permutation to tail (PyTorch -> shader order)
    tail_w = tail_w[PIXEL_SHUFFLE_PERM]
    tail_b = tail_b[PIXEL_SHUFFLE_PERM]

    return Anime4KCNN(
        num_feat=num_feat, block_depth=block_depth, factor=factor,
        n_stack=n_stack, tail_kernel=tail_kernel,
        head_weight=head_w, head_bias=head_b,
        mid_weights=mid_ws, mid_biases=mid_bs,
        tail_weight=tail_w, tail_bias=tail_b,
    )


__all__ = ["parse_pth"]
