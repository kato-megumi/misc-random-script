"""MagPie HLSL effect shader parser (.hlsl)."""

import re

import numpy as np

from ..ir import Anime4KCNN
from ..utils import _parse_float_list, mat4_to_weights, HLSL_LETTER_OFFSETS


def parse_hlsl(path: str) -> Anime4KCNN:
    """Parse MagPie HLSL effect shader -> IR."""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    lines = text.splitlines()

    # Count passes and find their line ranges
    pass_starts = []
    for i, line in enumerate(lines):
        if re.match(r"//!PASS\s+\d+", line.strip()):
            pass_starts.append(i)

    # Extract pass info: desc, in, out, body
    pass_info_list = []
    for pi, start in enumerate(pass_starts):
        end = pass_starts[pi + 1] if pi + 1 < len(pass_starts) else len(lines)
        desc = ""
        in_textures = []
        out_textures = []
        body_lines = []
        in_body = False

        for j in range(start, end):
            s = lines[j].strip()
            if s.startswith("//!DESC "):
                desc = s[8:]
            elif s.startswith("//!IN "):
                in_textures = [x.strip() for x in s[6:].split(",")]
            elif s.startswith("//!OUT "):
                out_textures = [x.strip() for x in s[7:].split(",")]
            elif re.match(r"void Pass\d+\(", s):
                in_body = True
            elif in_body:
                body_lines.append(lines[j])

        pass_info_list.append({
            "desc": desc, "in": in_textures, "out": out_textures,
            "body": body_lines
        })

    total_passes = len(pass_info_list)

    # Classify passes
    # HLSL combines aggregation + DTS in last pass
    # Pass 1: initial conv (Conv-4x3x3x3)
    # Pass 2..N-1: hidden layers
    # Pass N: aggregation + depth-to-space

    # Infer architecture from pass count and descriptions
    # Hidden passes = total_passes - 2 (initial + agg+DTS)
    hidden_count = total_passes - 2
    block_depth = hidden_count + 1

    # num_feat from output textures count of pass 1
    n_textures = len(pass_info_list[0]["out"])
    num_feat = n_textures * 4

    factor = 2  # CReLU default

    # Detect factor from hidden layer body (presence of na1, nb1 etc.)
    if hidden_count > 0:
        has_neg = any("max(-" in line for line in pass_info_list[1]["body"])
        factor = 2 if has_neg else 1

    # Tail kernel from aggregation desc
    tail_kernel = 1
    agg_desc = pass_info_list[-1]["desc"]
    m = re.search(r"Conv-4x(\d+)x(\d+)x", agg_desc)
    if m:
        tail_kernel = int(m.group(1))

    # n_stack from aggregation input textures (excluding INPUT)
    agg_in = [t for t in pass_info_list[-1]["in"] if t != "INPUT"]
    n_stack = len(agg_in) // n_textures

    # Allocate tensors
    head_w = np.zeros((num_feat, 3, 3, 3), dtype=np.float32)
    head_b = np.zeros(num_feat, dtype=np.float32)
    mid_ws = [np.zeros((num_feat, num_feat * factor, 3, 3), dtype=np.float32)
              for _ in range(block_depth - 1)]
    mid_bs = [np.zeros(num_feat, dtype=np.float32) for _ in range(block_depth - 1)]
    tail_in = num_feat * factor * n_stack
    tail_w = np.zeros((12, tail_in, tail_kernel, tail_kernel), dtype=np.float32)
    tail_b = np.zeros(12, dtype=np.float32)

    # ─── Parse Pass 1 (initial conv) ───
    _parse_hlsl_initial(pass_info_list[0]["body"], head_w, head_b, num_feat)

    # ─── Parse Pass 2..N-1 (hidden layers) ───
    for hi in range(hidden_count):
        _parse_hlsl_hidden(pass_info_list[1 + hi]["body"],
                           mid_ws[hi], mid_bs[hi], num_feat, factor)

    # ─── Parse last pass (aggregation + DTS) ───
    _parse_hlsl_aggregation(pass_info_list[-1]["body"],
                            tail_w, tail_b, num_feat, factor, n_stack, tail_kernel)

    return Anime4KCNN(
        num_feat=num_feat, block_depth=block_depth, factor=factor,
        n_stack=n_stack, tail_kernel=tail_kernel,
        head_weight=head_w, head_bias=head_b,
        mid_weights=mid_ws, mid_biases=mid_bs,
        tail_weight=tail_w, tail_bias=tail_b,
    )


def _parse_hlsl_initial(body_lines: list[str], weight: np.ndarray,
                        bias: np.ndarray, num_feat: int) -> None:
    """Parse HLSL initial conv pass (MF3x4 with src[i][j] spatial sampling)."""
    # Spatial mapping: src[i+di][j+dj] -> offset (di, dj)
    # We parse: MulAdd(src[...][...], MF3x4(values), targetN)
    # and: MF4 targetN = { bias } or MF4 targetN = MF4(bias)

    src_pattern = re.compile(
        r"MulAdd\(src\[i\s*([+-]\s*\d+)?\]\[j\s*([+-]\s*\d+)?\],\s*MF3x4\(([^)]+)\),\s*target(\d+)\)"
    )
    bias_pattern = re.compile(
        r"MF4\s+target(\d+)\s*=\s*(?:MF4\(([^)]+)\)|\{\s*([^}]+)\s*\})"
    )

    for line in body_lines:
        s = line.strip()

        # Parse bias initialization
        bm = bias_pattern.search(s)
        if bm:
            tidx = int(bm.group(1))
            vals_str = bm.group(2) or bm.group(3)
            bvals = _parse_float_list(vals_str)
            out_start = (tidx - 1) * 4
            for k2 in range(4):
                if out_start + k2 < bias.shape[0]:
                    bias[out_start + k2] = bvals[k2]
            continue

        # Parse MulAdd with MF3x4
        sm = src_pattern.search(s)
        if sm:
            di_str = sm.group(1)
            dj_str = sm.group(2)
            vals = _parse_float_list(sm.group(3))
            tidx = int(sm.group(4))

            di = int(di_str.replace(" ", "")) if di_str else 0
            dj = int(dj_str.replace(" ", "")) if dj_str else 0
            ky, kx = di + 1, dj + 1
            out_start = (tidx - 1) * 4
            mat4_to_weights(vals, weight, out_start, 0, ky, kx, n_in=3)


def _parse_hlsl_hidden(body_lines: list[str], weight: np.ndarray,
                       bias: np.ndarray, num_feat: int, factor: int) -> None:
    """Parse HLSL hidden layer pass (MulAdd with MF4x4, a1..i3, na1..ni3 vars)."""
    # Patterns for MulAdd(var, MF4x4(values), target)
    muladd_pattern = re.compile(
        r"MulAdd\((n?)([a-i])(\d+),\s*MF4x4\(([^)]+)\),\s*target\)"
    )
    bias_pattern = re.compile(
        r"(?:MF4\s+)?target\s*=\s*MF4\(([^)]+)\)"
    )
    write_pattern = re.compile(r"(\w+)\[(?:gxy|destPos)\]\s*=\s*target")

    current_out = 0  # current output texture index (0, 1, 2)

    for line in body_lines:
        s = line.strip()

        # Bias initialization
        bm = bias_pattern.search(s)
        if bm:
            vals_str = bm.group(1)
            bvals = _parse_float_list(vals_str)
            out_start = current_out * 4
            for k2 in range(4):
                if out_start + k2 < bias.shape[0]:
                    bias[out_start + k2] = bvals[k2]
            continue

        # MulAdd line
        mm = muladd_pattern.search(s)
        if mm:
            is_neg = mm.group(1) == "n"
            letter = mm.group(2)
            tex_digit = int(mm.group(3))
            vals = _parse_float_list(mm.group(4))

            ox, oy = HLSL_LETTER_OFFSETS[letter]
            ky, kx = ox + 1, oy + 1
            sampler_idx = tex_digit - 1  # 1-indexed -> 0-indexed
            out_start = current_out * 4

            if is_neg:
                in_start = num_feat + sampler_idx * 4
            else:
                in_start = sampler_idx * 4

            mat4_to_weights(vals, weight, out_start, in_start, ky, kx)
            continue

        # Write target -> advance output index
        wm = write_pattern.search(s)
        if wm:
            current_out += 1


def _parse_hlsl_aggregation(body_lines: list[str], weight: np.ndarray,
                            bias: np.ndarray, num_feat: int, factor: int,
                            n_stack: int, tail_kernel: int) -> None:
    """Parse HLSL aggregation+DTS pass (last pass with target1/2/3 and g0..gN, ng0..ngN)."""
    n_tpg = num_feat // 4

    muladd_pattern = re.compile(
        r"MulAdd\((n?g)(\d+),\s*MF4x4\(([^)]+)\),\s*target(\d+)\)"
    )
    bias_pattern = re.compile(
        r"MF4\s+target(\d+)\s*=\s*MF4\(([^)]+)\)"
    )

    for line in body_lines:
        s = line.strip()

        # Bias initialization
        bm = bias_pattern.search(s)
        if bm:
            tidx = int(bm.group(1))
            bvals = _parse_float_list(bm.group(2))
            out_start = (tidx - 1) * 4
            for k2 in range(4):
                if out_start + k2 < bias.shape[0]:
                    bias[out_start + k2] = bvals[k2]
            continue

        # MulAdd line
        mm = muladd_pattern.search(s)
        if mm:
            var_prefix = mm.group(1)
            g_idx = int(mm.group(2))
            vals = _parse_float_list(mm.group(3))
            tidx = int(mm.group(4))

            is_neg = var_prefix == "ng"
            out_start = (tidx - 1) * 4

            # Map g_idx to (layer_idx, tex_idx)
            layer_idx = g_idx // n_tpg
            tex_idx = g_idx % n_tpg

            if is_neg:
                in_start = layer_idx * num_feat * factor + num_feat + tex_idx * 4
            else:
                in_start = layer_idx * num_feat * factor + tex_idx * 4

            if tail_kernel == 1:
                ky, kx = 0, 0
            else:
                ky, kx = 0, 0  # For 3x3 tail, would need spatial parsing
            mat4_to_weights(vals, weight, out_start, in_start, ky, kx)


__all__ = ["parse_hlsl"]
