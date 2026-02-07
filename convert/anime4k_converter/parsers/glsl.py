"""mpv GLSL hook shader parser (.glsl)."""

import re

import numpy as np

from ..ir import Anime4KCNN
from ..utils import _parse_float_list, mat4_to_weights


def _parse_mpv_passes(text: str) -> list[dict]:
    """Parse mpv GLSL into a list of pass dicts."""
    passes = []
    cur = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("//!DESC "):
            if cur is not None:
                passes.append(cur)
            cur = {"desc": s[8:], "hook": "", "binds": [], "save": "",
                   "width": "", "height": "", "components": 4,
                   "defines": [], "body": []}
            continue
        if cur is None:
            continue
        if s.startswith("//!HOOK "):
            cur["hook"] = s[8:]
        elif s.startswith("//!BIND "):
            cur["binds"].append(s[8:])
        elif s.startswith("//!SAVE "):
            cur["save"] = s[8:]
        elif s.startswith("//!WIDTH "):
            cur["width"] = s[9:]
        elif s.startswith("//!HEIGHT "):
            cur["height"] = s[10:]
        elif s.startswith("//!COMPONENTS "):
            cur["components"] = int(s[14:])
        elif s.startswith("//!WHEN "):
            pass
        elif s.startswith("#define "):
            cur["defines"].append(s)
        elif s.startswith("vec4 hook()"):
            pass
        elif s in ("return result;", "return result0;", "}"):
            pass
        else:
            cur["body"].append(line)
    if cur is not None:
        passes.append(cur)
    return passes


def _classify_glsl_pass(desc: str) -> str:
    """Classify a GLSL pass from its DESC string."""
    if "Depth-to-Space" in desc:
        return "depth_to_space"
    if "Conv-4x1x1x" in desc:
        return "aggregation"
    if "Conv-4x3x3x3" in desc:
        return "initial_conv"
    if re.search(r"Conv-4x3x3x\d+", desc):
        return "hidden_layer"
    return "unknown"


def _group_glsl_passes(passes: list[dict]) -> list[list[dict]]:
    """Group mpv passes into compute pass groups."""
    groups = []
    i = 0
    while i < len(passes):
        p = passes[i]
        if "Depth-to-Space" in p["desc"]:
            groups.append([p])
            i += 1
            continue
        group = [p]
        j = i + 1
        while j < len(passes):
            if passes[j]["desc"] == p["desc"] and passes[j]["binds"] == p["binds"]:
                group.append(passes[j])
                j += 1
            else:
                break
        groups.append(group)
        i = j
    return groups


def _parse_go_defines(defines: list[str]) -> dict:
    """Parse #define go_N / g_N macros -> {index: (texture_name, is_negated)}."""
    result = {}
    for d in defines:
        # Function-like: #define go_N(x_off, y_off) ...
        m = re.match(r"#define go_(\d+)\(x_off,\s*y_off\)\s+(.*)", d)
        if m:
            idx = int(m.group(1))
            expr = m.group(2)
            tex_m = re.search(r"(\w+)_texOff", expr)
            tex_name = tex_m.group(1) if tex_m else f"tex{idx}"
            is_neg = "max(-(" in expr or "max( -(" in expr
            is_pos = "max((" in expr or "max( (" in expr
            result[idx] = (tex_name, True if is_neg else (False if is_pos else None))
            continue
        # Object-like: #define g_N ...
        m = re.match(r"#define g_(\d+)\s+(.*)", d)
        if m:
            idx = int(m.group(1))
            expr = m.group(2)
            tex_m = re.search(r"(\w+)_tex\(", expr)
            tex_name = tex_m.group(1) if tex_m else f"tex{idx}"
            is_neg = "max(-(" in expr or "max( -(" in expr
            is_pos = "max((" in expr or "max( (" in expr
            result[idx] = (tex_name, True if is_neg else (False if is_pos else None))
    return result


def parse_glsl(path: str) -> Anime4KCNN:
    """Parse mpv GLSL hook shader -> IR."""
    with open(path) as f:
        text = f.read()

    # Strip license header
    desc_pos = text.find("//!DESC ")
    if desc_pos == -1:
        raise ValueError("No //!DESC directives found")
    shader_text = text[desc_pos:]

    passes = _parse_mpv_passes(shader_text)
    groups = _group_glsl_passes(passes)

    # Classify groups
    types = [_classify_glsl_pass(g[0]["desc"]) for g in groups]

    # Architecture inference
    n_textures = len(groups[0])  # sub-passes per group = textures per layer
    num_feat = n_textures * 4

    hidden_count = sum(1 for t in types if t == "hidden_layer")
    block_depth = hidden_count + 1  # +1 for head

    # Factor from hidden layer defines
    factor = 2  # default CReLU
    for gi, g in enumerate(groups):
        if types[gi] == "hidden_layer":
            go_map = _parse_go_defines(g[0]["defines"])
            has_neg = any(neg for _, (_, neg) in go_map.items() if neg is True)
            factor = 2 if has_neg else 1
            break

    # Tail kernel
    agg_idx = types.index("aggregation") if "aggregation" in types else -1
    tail_kernel = 1
    if agg_idx >= 0:
        agg_desc = groups[agg_idx][0]["desc"]
        m = re.search(r"Conv-4x(\d+)x(\d+)x", agg_desc)
        if m:
            tail_kernel = int(m.group(1))

    # n_stack from aggregation binds
    if agg_idx >= 0:
        real_binds = [b for b in groups[agg_idx][0]["binds"] if b != "MAIN"]
        n_stack = len(real_binds) // n_textures
    else:
        n_stack = 5

    # Allocate tensors
    head_w = np.zeros((num_feat, 3, 3, 3), dtype=np.float32)
    head_b = np.zeros(num_feat, dtype=np.float32)
    mid_ws = [np.zeros((num_feat, num_feat * factor, 3, 3), dtype=np.float32)
              for _ in range(block_depth - 1)]
    mid_bs = [np.zeros(num_feat, dtype=np.float32) for _ in range(block_depth - 1)]
    tail_in = num_feat * factor * n_stack
    tail_w = np.zeros((12, tail_in, tail_kernel, tail_kernel), dtype=np.float32)
    tail_b = np.zeros(12, dtype=np.float32)

    hidden_idx = 0
    for gi, g in enumerate(groups):
        ptype = types[gi]

        if ptype == "depth_to_space":
            continue

        for sub_idx, mpv_pass in enumerate(g):
            out_start = sub_idx * 4
            go_map = _parse_go_defines(mpv_pass["defines"])

            # Build sampler map: texture_name -> sampler_idx
            sampler_map = {}
            real_idx = 0
            for b in mpv_pass["binds"]:
                if b != "MAIN":
                    sampler_map[b] = real_idx
                    real_idx += 1
                elif ptype == "initial_conv":
                    sampler_map["MAIN"] = 0

            for body_line in mpv_pass["body"]:
                s = body_line.strip()
                if not s:
                    continue

                # Parse mat4 line
                mat_m = re.search(r"mat4\(([^)]+)\)", s)
                if mat_m:
                    vals = _parse_float_list(mat_m.group(1))

                    if ptype == "initial_conv":
                        # go_0(ox, oy) -> MAIN
                        go_call = re.search(r"go_(\d+)\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)", s)
                        if go_call:
                            ox = int(float(go_call.group(2)))
                            oy = int(float(go_call.group(3)))
                            mat4_to_weights(vals, head_w, out_start, 0, ox + 1, oy + 1, n_in=4)

                    elif ptype == "hidden_layer":
                        go_call = re.search(r"go_(\d+)\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)", s)
                        if go_call:
                            go_idx = int(go_call.group(1))
                            ox = int(float(go_call.group(2)))
                            oy = int(float(go_call.group(3)))
                            tex_name, is_neg = go_map[go_idx]
                            samp_idx = sampler_map.get(tex_name, 0)
                            in_start = (num_feat + samp_idx * 4) if is_neg else (samp_idx * 4)
                            mat4_to_weights(vals, mid_ws[hidden_idx], out_start, in_start, ox + 1, oy + 1)

                    elif ptype == "aggregation":
                        g_call = re.search(r"\bg_(\d+)\b", s)
                        if g_call:
                            g_idx = int(g_call.group(1))
                            tex_name, is_neg = go_map[g_idx]
                            samp_idx = sampler_map.get(tex_name, 0)
                            layer_idx = samp_idx // n_textures
                            tex_idx = samp_idx % n_textures
                            if is_neg:
                                in_start = layer_idx * num_feat * factor + num_feat + tex_idx * 4
                            else:
                                in_start = layer_idx * num_feat * factor + tex_idx * 4
                            if tail_kernel == 1:
                                ky, kx = 0, 0
                            else:
                                # For 3x3 aggregation, would need spatial offset extraction
                                ky, kx = 0, 0
                            mat4_to_weights(vals, tail_w, out_start, in_start, ky, kx)
                    continue

                # Parse bias line
                if "mat4" not in s:
                    bias_m = re.search(r"vec4\(([^)]+)\)", s)
                    if bias_m and ("+=" in s or "= vec4" in s):
                        bvals = _parse_float_list(bias_m.group(1))
                        if ptype == "initial_conv":
                            for k2 in range(4):
                                head_b[out_start + k2] = bvals[k2]
                        elif ptype == "hidden_layer":
                            for k2 in range(4):
                                mid_bs[hidden_idx][out_start + k2] = bvals[k2]
                        elif ptype == "aggregation":
                            for k2 in range(4):
                                tail_b[out_start + k2] = bvals[k2]

        if ptype == "hidden_layer":
            hidden_idx += 1

    return Anime4KCNN(
        num_feat=num_feat, block_depth=block_depth, factor=factor,
        n_stack=n_stack, tail_kernel=tail_kernel,
        head_weight=head_w, head_bias=head_b,
        mid_weights=mid_ws, mid_biases=mid_bs,
        tail_weight=tail_w, tail_bias=tail_b,
    )


__all__ = ["parse_glsl"]
