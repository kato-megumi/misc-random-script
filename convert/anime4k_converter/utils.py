"""Shared utilities for parsing and writing Anime4K CNN formats."""

import struct

import numpy as np

from .ir import Anime4KCNN


def format_float(value: float) -> str:
    """Format a float value using shortest float32 round-trip representation."""
    f32_bytes = struct.pack("f", value)
    f32_val = struct.unpack("f", f32_bytes)[0]

    for digits in range(1, 15):
        s = f"{f32_val:.{digits}g}"
        if struct.pack("f", float(s)) == f32_bytes:
            if "." not in s and "e" not in s.lower():
                s += ".0"
            return s

    s = f"{f32_val:.9g}"
    if "." not in s and "e" not in s.lower():
        s += ".0"
    return s


def variant_label(ir: Anime4KCNN) -> str:
    """Generate a variant label (UL, VL, L, M, S) from architecture parameters."""
    known = {
        (7, 5, 12): "UL",
        (7, 5, 8): "VL",
        (5, 5, 8): "L",
        (5, 3, 8): "M",
        (3, 3, 8): "S",
    }
    key = (ir.block_depth, ir.n_stack, ir.num_feat)
    return known.get(key, f"d{ir.block_depth}_s{ir.n_stack}_f{ir.num_feat}")


def conv_tex_name(layer_idx: int, tex_sub: int) -> str:
    """Generate texture name for a given layer and sub-texture index.

    layer_idx=0: conv2d_tf, conv2d_tf1, conv2d_tf2
    layer_idx=1: conv2d_1_tf, conv2d_1_tf1, conv2d_1_tf2
    etc.
    """
    suffixes = ["_tf", "_tf1", "_tf2"]
    if layer_idx == 0:
        return f"conv2d{suffixes[tex_sub]}"
    return f"conv2d_{layer_idx}{suffixes[tex_sub]}"


def mat4_to_weights(values: list[float], weight: np.ndarray,
                    out_start: int, in_start: int, ky: int, kx: int,
                    n_in: int = 4) -> None:
    """Fill a 4x4 (or 4xN) block of a weight tensor from mat4/MF4x4/MF3x4 values.

    Layout: values[in_col * 4 + out_row] = weight[out_start+out_row, in_start+in_col, ky, kx]
    (Same mapping for both GLSL column-major mat4 and HLSL row-major MF4x4)
    """
    for col in range(n_in):
        for row in range(4):
            in_ch = in_start + col
            out_ch = out_start + row
            if in_ch < weight.shape[1] and out_ch < weight.shape[0]:
                weight[out_ch, in_ch, ky, kx] = values[col * 4 + row]


def weight_to_mat4_str(weight: np.ndarray, out_start: int, in_start: int,
                       ky: int = 0, kx: int = 0) -> str:
    """Extract 4x4 block from weight tensor -> GLSL/COMP mat4 string."""
    values = []
    for j in range(4):
        for i in range(4):
            out_ch, in_ch = out_start + i, in_start + j
            if out_ch < weight.shape[0] and in_ch < weight.shape[1]:
                values.append(format_float(weight[out_ch, in_ch, ky, kx]))
            else:
                values.append("0.0")
    return f"mat4({', '.join(values)})"


def weight_to_mf4x4_str(weight: np.ndarray, out_start: int, in_start: int,
                        ky: int = 0, kx: int = 0) -> str:
    """Extract 4x4 block from weight tensor -> HLSL MF4x4 string."""
    values = []
    for j in range(4):
        for i in range(4):
            out_ch, in_ch = out_start + i, in_start + j
            if out_ch < weight.shape[0] and in_ch < weight.shape[1]:
                values.append(format_float(weight[out_ch, in_ch, ky, kx]))
            else:
                values.append("0.0")
    return f"MF4x4({', '.join(values)})"


def weight_to_mf3x4_str(weight: np.ndarray, out_start: int, in_start: int,
                        ky: int = 0, kx: int = 0) -> str:
    """Extract 3x4 block from weight tensor -> HLSL MF3x4 string (3 input channels)."""
    values = []
    for j in range(3):
        for i in range(4):
            out_ch, in_ch = out_start + i, in_start + j
            if out_ch < weight.shape[0] and in_ch < weight.shape[1]:
                values.append(format_float(weight[out_ch, in_ch, ky, kx]))
            else:
                values.append("0.0")
    return f"MF3x4({', '.join(values)})"


def bias_to_vec4_str(bias: np.ndarray, out_start: int) -> str:
    """Extract 4 bias values -> GLSL/COMP vec4 string."""
    values = []
    for i in range(4):
        out_ch = out_start + i
        if out_ch < bias.shape[0]:
            values.append(format_float(bias[out_ch]))
        else:
            values.append("0.0")
    return f"vec4({', '.join(values)})"


def bias_to_mf4_str(bias: np.ndarray, out_start: int) -> str:
    """Extract 4 bias values -> HLSL MF4 string."""
    values = []
    for i in range(4):
        out_ch = out_start + i
        if out_ch < bias.shape[0]:
            values.append(format_float(bias[out_ch]))
        else:
            values.append("0.0")
    return f"MF4({', '.join(values)})"


def _parse_float_list(text: str) -> list[float]:
    """Parse a comma-separated list of float literals."""
    return [float(x.strip()) for x in text.split(",")]


SPATIAL_OFFSETS_3x3 = [(ox, oy) for ox in range(-1, 2) for oy in range(-1, 2)]

HLSL_LETTER_OFFSETS = {
    "a": (-1, -1), "b": (-1, 0), "c": (-1, 1),
    "d": (0, -1),  "e": (0, 0),  "f": (0, 1),
    "g": (1, -1),  "h": (1, 0),  "i": (1, 1),
}


__all__ = [
    "format_float",
    "variant_label",
    "conv_tex_name",
    "mat4_to_weights",
    "weight_to_mat4_str",
    "weight_to_mf4x4_str",
    "weight_to_mf3x4_str",
    "bias_to_vec4_str",
    "bias_to_mf4_str",
    "_parse_float_list",
    "SPATIAL_OFFSETS_3x3",
    "HLSL_LETTER_OFFSETS",
]
