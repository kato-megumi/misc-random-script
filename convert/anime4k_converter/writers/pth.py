"""PyTorch model writer (.pth)."""

from ..ir import Anime4KCNN, PIXEL_SHUFFLE_PERM


def write_pth(ir: Anime4KCNN, path: str) -> None:
    """Write IR -> PyTorch .pth file."""
    import torch

    # Reverse PixelShuffle permutation on tail (shader -> PyTorch order)
    # PIXEL_SHUFFLE_PERM is self-inverse
    tail_w = ir.tail_weight[PIXEL_SHUFFLE_PERM]
    tail_b = ir.tail_bias[PIXEL_SHUFFLE_PERM]

    state_dict = {
        "conv_head.weight": torch.from_numpy(ir.head_weight),
        "conv_head.bias": torch.from_numpy(ir.head_bias),
    }

    for i in range(ir.block_depth - 1):
        state_dict[f"conv_mid.{i}.weight"] = torch.from_numpy(ir.mid_weights[i])
        state_dict[f"conv_mid.{i}.bias"] = torch.from_numpy(ir.mid_biases[i])

    state_dict["conv_tail.weight"] = torch.from_numpy(tail_w)
    state_dict["conv_tail.bias"] = torch.from_numpy(tail_b)

    torch.save(state_dict, path)


__all__ = ["write_pth"]
