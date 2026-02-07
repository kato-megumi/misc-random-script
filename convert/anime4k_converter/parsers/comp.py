"""Vulkan compute shader parser (.comp)."""

import re

import numpy as np

from ..ir import Anime4KCNN
from ..utils import _parse_float_list, mat4_to_weights


def parse_comp(path: str) -> Anime4KCNN:
    """Parse Vulkan compute shader (.comp) -> IR."""
    with open(path) as f:
        text = f.read()

    lines = text.splitlines()

    # Extract PASS blocks
    pass_blocks = {}
    i = 0
    while i < len(lines):
        m = re.match(r"\s*if \(PASS == (\d+)\)\s*\{", lines[i])
        if m:
            pass_idx = int(m.group(1))
            block_lines = []
            depth = 1
            i += 1
            while i < len(lines) and depth > 0:
                depth += lines[i].count("{") - lines[i].count("}")
                if depth > 0:
                    block_lines.append(lines[i])
                i += 1
            pass_blocks[pass_idx] = block_lines
        else:
            i += 1

    total_passes = max(pass_blocks.keys()) + 1
    dts_pass = total_passes - 1
    agg_pass = dts_pass - 1

    # Infer num_feat from result variables in pass 0
    n_result = sum(1 for line in pass_blocks[0] if re.search(r"vec4 result\d+", line))
    num_feat = n_result * 4

    # Count hidden passes
    hidden_count = total_passes - 3  # minus initial, aggregation, DTS
    block_depth = hidden_count + 1

    # Detect CReLU
    has_neg = any("max(-sample" in line for line in pass_blocks.get(1, []))
    factor = 2 if has_neg else 1

    # Tail kernel
    agg_uses_offset = any(
        "sampleTex(" in line and "sampleTexCurrent" not in line
        for line in pass_blocks.get(agg_pass, [])
    )
    tail_kernel = 3 if agg_uses_offset else 1

    # n_stack from aggregation sampler count
    agg_samplers = set()
    for line in pass_blocks.get(agg_pass, []):
        for m2 in re.finditer(r"sampleTex(?:Current)?\((\d+)", line):
            agg_samplers.add(int(m2.group(1)))
    n_tpg = num_feat // 4
    n_stack = len(agg_samplers) // n_tpg if agg_samplers else 5

    # Allocate tensors
    head_w = np.zeros((num_feat, 3, 3, 3), dtype=np.float32)
    head_b = np.zeros(num_feat, dtype=np.float32)
    mid_ws = [np.zeros((num_feat, num_feat * factor, 3, 3), dtype=np.float32)
              for _ in range(block_depth - 1)]
    mid_bs = [np.zeros(num_feat, dtype=np.float32) for _ in range(block_depth - 1)]
    tail_in = num_feat * factor * n_stack
    tail_w = np.zeros((12, tail_in, tail_kernel, tail_kernel), dtype=np.float32)
    tail_b = np.zeros(12, dtype=np.float32)

    def parse_and_fill(block_lines, weight, bias, pass_type):
        """Parse mat4/vec4 lines and fill weight/bias tensors."""
        for line in block_lines:
            s = line.strip()

            # mat4 line
            mat_m = re.search(r"result(\d+)\s*[+]?=\s*mat4\(([^)]+)\)", s)
            if mat_m:
                result_idx = int(mat_m.group(1))
                vals = _parse_float_list(mat_m.group(2))
                out_start = result_idx * 4

                is_neg = "max(-sample" in s
                samp_m = re.search(r"sampleTex(?:Current)?\((\d+)", s)
                sampler_idx = int(samp_m.group(1)) if samp_m else 0
                off_m = re.search(r"ivec2\((-?\d+),\s*(-?\d+)\)", s)

                if pass_type == "initial":
                    ox, oy = (int(off_m.group(1)), int(off_m.group(2))) if off_m else (0, 0)
                    mat4_to_weights(vals, weight, out_start, 0, ox + 1, oy + 1, n_in=4)

                elif pass_type == "hidden":
                    ox, oy = (int(off_m.group(1)), int(off_m.group(2))) if off_m else (0, 0)
                    in_start = (num_feat + sampler_idx * 4) if is_neg else (sampler_idx * 4)
                    mat4_to_weights(vals, weight, out_start, in_start, ox + 1, oy + 1)

                elif pass_type == "aggregation":
                    layer_idx = sampler_idx // n_tpg
                    tex_idx = sampler_idx % n_tpg
                    if is_neg:
                        in_start = layer_idx * num_feat * factor + num_feat + tex_idx * 4
                    else:
                        in_start = layer_idx * num_feat * factor + tex_idx * 4
                    if tail_kernel == 1:
                        ky, kx = 0, 0
                    else:
                        ox, oy = (int(off_m.group(1)), int(off_m.group(2))) if off_m else (0, 0)
                        half = tail_kernel // 2
                        ky, kx = ox + half, oy + half
                    mat4_to_weights(vals, weight, out_start, in_start, ky, kx)
                continue

            # bias line (vec4 without mat4)
            if "mat4" not in s:
                bias_m = re.search(r"result(\d+)\s*\+=\s*vec4\(([^)]+)\)", s)
                if bias_m:
                    result_idx = int(bias_m.group(1))
                    vals = _parse_float_list(bias_m.group(2))
                    out_start = result_idx * 4
                    for k2 in range(4):
                        if out_start + k2 < bias.shape[0]:
                            bias[out_start + k2] = vals[k2]

    # Parse each pass
    parse_and_fill(pass_blocks[0], head_w, head_b, "initial")
    for mid_idx in range(block_depth - 1):
        p = mid_idx + 1
        if p in pass_blocks:
            parse_and_fill(pass_blocks[p], mid_ws[mid_idx], mid_bs[mid_idx], "hidden")
    if agg_pass in pass_blocks:
        parse_and_fill(pass_blocks[agg_pass], tail_w, tail_b, "aggregation")

    return Anime4KCNN(
        num_feat=num_feat, block_depth=block_depth, factor=factor,
        n_stack=n_stack, tail_kernel=tail_kernel,
        head_weight=head_w, head_bias=head_b,
        mid_weights=mid_ws, mid_biases=mid_bs,
        tail_weight=tail_w, tail_bias=tail_b,
    )


__all__ = ["parse_comp"]
