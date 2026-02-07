"""MagPie HLSL effect shader writer (.hlsl)."""

from ..ir import Anime4KCNN
from ..utils import (
    HLSL_LETTER_OFFSETS,
    SPATIAL_OFFSETS_3x3,
    bias_to_mf4_str,
    conv_tex_name,
    format_float,
    variant_label,
    weight_to_mf3x4_str,
    weight_to_mf4x4_str,
)


def write_hlsl(ir: Anime4KCNN, path: str) -> None:
    """Write IR -> MagPie HLSL effect shader."""
    label = variant_label(ir)
    num_feat = ir.num_feat
    n_tex = num_feat // 4
    out = []

    # Header
    out.append(f"// Anime4K_Upscale_CNN_x2_{label}")
    out.append("")
    out.append("//!MAGPIE EFFECT")
    out.append("//!VERSION 4")
    out.append("//!SORT_NAME Anime4K_Upscale")
    out.append("//!USE MulAdd")
    out.append("//!CAPABILITY FP16")
    out.append("")

    # Texture declarations
    out.append("//!TEXTURE")
    out.append("Texture2D INPUT;")
    out.append("")
    out.append("//!TEXTURE")
    out.append("//!WIDTH INPUT_WIDTH * 2")
    out.append("//!HEIGHT INPUT_HEIGHT * 2")
    out.append("Texture2D OUTPUT;")
    out.append("")

    # Intermediate textures
    all_tex_names = []
    for layer_idx in range(ir.block_depth):
        for ti in range(n_tex):
            tn = conv_tex_name(layer_idx, ti)
            all_tex_names.append(tn)
            out.append("//!TEXTURE")
            out.append("//!WIDTH INPUT_WIDTH")
            out.append("//!HEIGHT INPUT_HEIGHT")
            out.append("//!FORMAT R16G16B16A16_FLOAT")
            out.append(f"Texture2D {tn};")
            out.append("")

    # Samplers
    out.append("//!SAMPLER")
    out.append("//!FILTER POINT")
    out.append("SamplerState sam;")
    out.append("")
    out.append("//!SAMPLER")
    out.append("//!FILTER LINEAR")
    out.append("SamplerState sam1;")
    out.append("")

    # ─── Pass 1: Initial conv ───
    out_textures = [conv_tex_name(0, ti) for ti in range(n_tex)]
    out.append("//!PASS 1")
    out.append("//!DESC Conv-4x3x3x3")
    out.append("//!IN INPUT")
    out.append(f"//!OUT {', '.join(out_textures)}")
    out.append("//!BLOCK_SIZE 16")
    out.append("//!NUM_THREADS 64")
    out.append("")
    out.append("void Pass1(uint2 blockStart, uint3 threadId) {")
    out.append("\tuint2 gxy = (Rmp8x8(threadId.x) << 1) + blockStart;")
    out.append("\tuint2 inputSize = GetInputSize();")
    out.append("\tif (gxy.x >= inputSize.x || gxy.y >= inputSize.y) {")
    out.append("\t\treturn;")
    out.append("\t}")
    out.append("")
    out.append("\tfloat2 inputPt = GetInputPt();")
    out.append("\t")
    out.append("\tuint i, j;")
    out.append("")
    out.append("\tMF3 src[4][4];")
    out.append("\t[unroll]")
    out.append("\tfor (i = 0; i <= 2; i += 2) {")
    out.append("\t\t[unroll]")
    out.append("\t\tfor (j = 0; j <= 2; j += 2) {")
    out.append("\t\t\tfloat2 tpos = (gxy + uint2(i, j)) * inputPt;")
    out.append("\t\t\tconst MF4 sr = INPUT.GatherRed(sam, tpos);")
    out.append("\t\t\tconst MF4 sg = INPUT.GatherGreen(sam, tpos);")
    out.append("\t\t\tconst MF4 sb = INPUT.GatherBlue(sam, tpos);")
    out.append("")
    out.append("\t\t\t// w z")
    out.append("\t\t\t// x y")
    out.append("\t\t\tsrc[i][j] = MF3(sr.w, sg.w, sb.w);")
    out.append("\t\t\tsrc[i][j + 1] = MF3(sr.x, sg.x, sb.x);")
    out.append("\t\t\tsrc[i + 1][j] = MF3(sr.z, sg.z, sb.z);")
    out.append("\t\t\tsrc[i + 1][j + 1] = MF3(sr.y, sg.y, sb.y);")
    out.append("\t\t}")
    out.append("\t}")
    out.append("")
    out.append("\t[unroll]")
    out.append("\tfor (i = 1; i <= 2; ++i) {")
    out.append("\t\t[unroll]")
    out.append("\t\tfor (j = 1; j <= 2; ++j) {")
    out.append("\t\t\tuint2 destPos = gxy + uint2(i - 1, j - 1);")
    out.append("")
    out.append("\t\t\tif (i != 1 || j != 1) {")
    out.append("\t\t\t\tif (destPos.x >= inputSize.x || destPos.y >= inputSize.y) {")
    out.append("\t\t\t\t\tcontinue;")
    out.append("\t\t\t\t}")
    out.append("\t\t\t}")
    out.append("")

    # Generate MulAdd calls for each output texture
    # Spatial src indices: [i-1][j-1] through [i+1][j+1]
    src_offsets = [
        ("i - 1", "j - 1"), ("i - 1", "j"), ("i - 1", "j + 1"),
        ("i", "j - 1"), ("i", "j"), ("i", "j + 1"),
        ("i + 1", "j - 1"), ("i + 1", "j"), ("i + 1", "j + 1"),
    ]

    for t in range(n_tex):
        out_start = t * 4
        tidx = t + 1
        bvals = ", ".join(format_float(ir.head_bias[out_start + k]) for k in range(4))
        out.append(f"\t\t\tMF4 target{tidx} = {{ {bvals} }};")

        for si, (si_expr, sj_expr) in enumerate(src_offsets):
            ox, oy = SPATIAL_OFFSETS_3x3[si]
            ky, kx = ox + 1, oy + 1
            mstr = weight_to_mf3x4_str(ir.head_weight, out_start, 0, ky, kx)
            out.append(f"\t\t\ttarget{tidx} = MulAdd(src[{si_expr}][{sj_expr}], {mstr}, target{tidx});")
        out.append("")

    # Write outputs
    for t in range(n_tex):
        tn = conv_tex_name(0, t)
        out.append(f"\t\t\t{tn}[destPos] = target{t + 1};")

    out.append("\t\t}")
    out.append("\t}")
    out.append("}")
    out.append("")

    # ─── Pass 2..N (hidden layers) ───
    letters = "abcdefghi"
    for mid_idx in range(ir.block_depth - 1):
        pass_num = mid_idx + 2
        layer_idx = mid_idx + 1
        prev_layer = mid_idx
        w = ir.mid_weights[mid_idx]
        b = ir.mid_biases[mid_idx]
        in_channels = w.shape[1]

        in_textures = [conv_tex_name(prev_layer, ti) for ti in range(n_tex)]
        out_textures = [conv_tex_name(layer_idx, ti) for ti in range(n_tex)]

        out.append(f"//!PASS {pass_num}")
        out.append(f"//!DESC Conv-4x3x3x{in_channels}")
        out.append(f"//!IN {', '.join(in_textures)}")
        out.append(f"//!OUT {', '.join(out_textures)}")
        out.append("//!BLOCK_SIZE 8")
        out.append("//!NUM_THREADS 64")
        out.append("")
        out.append(f"void Pass{pass_num}(uint2 blockStart, uint3 threadId) {{")
        out.append("\tuint2 gxy = Rmp8x8(threadId.x) + blockStart;")
        out.append("\tuint2 inputSize = GetInputSize();")
        out.append("\tif (gxy.x >= inputSize.x || gxy.y >= inputSize.y) {")
        out.append("\t\treturn;")
        out.append("\t}")
        out.append("")
        out.append("\tfloat2 inputPt = GetInputPt();")
        out.append("\tfloat2 pos = (gxy + 0.5f) * inputPt;")
        out.append("")

        # Sample all input textures at 9 spatial positions
        offset_exprs = {
            "a": "pos + float2(-inputPt.x, -inputPt.y)",
            "b": "pos + float2(-inputPt.x, 0)",
            "c": "pos + float2(-inputPt.x, inputPt.y)",
            "d": "pos + float2(0, -inputPt.y)",
            "e": "pos",
            "f": "pos + float2(0, inputPt.y)",
            "g": "pos + float2(inputPt.x, -inputPt.y)",
            "h": "pos + float2(inputPt.x, 0)",
            "i": "pos + float2(inputPt.x, inputPt.y)",
        }

        out.append("\t// [ a, d, g ]")
        out.append("\t// [ b, e, h ]")
        out.append("\t// [ c, f, i ]")

        for ti in range(n_tex):
            tex = in_textures[ti]
            suffix = str(ti + 1)
            for letter in letters:
                expr = offset_exprs[letter]
                out.append(f"\tMF4 {letter}{suffix} = {tex}.SampleLevel(sam, {expr}, 0);")
            out.append("")

            # Negated versions
            if ir.factor == 2:
                for letter in letters:
                    out.append(f"\tMF4 n{letter}{suffix} = max(-{letter}{suffix}, 0);")
                out.append("")
                for letter in letters:
                    out.append(f"\t{letter}{suffix} = max({letter}{suffix}, 0);")
                out.append("")

        # MulAdd for each output texture
        for t in range(n_tex):
            out_start = t * 4
            bvals = ", ".join(format_float(b[out_start + k]) for k in range(4))

            if t == 0:
                out.append(f"\tMF4 target = MF4({bvals});")
            else:
                out.append(f"\ttarget = MF4({bvals});")

            # Positive samples: for each texture, for each spatial position
            for ti in range(n_tex):
                suffix = str(ti + 1)
                in_s = ti * 4
                for letter in letters:
                    ox, oy = HLSL_LETTER_OFFSETS[letter]
                    ky, kx = ox + 1, oy + 1
                    mstr = weight_to_mf4x4_str(w, out_start, in_s, ky, kx)
                    out.append(f"\ttarget = MulAdd({letter}{suffix}, {mstr}, target);")

            # Negative samples
            if ir.factor == 2:
                for ti in range(n_tex):
                    suffix = str(ti + 1)
                    in_s = num_feat + ti * 4
                    for letter in letters:
                        ox, oy = HLSL_LETTER_OFFSETS[letter]
                        ky, kx = ox + 1, oy + 1
                        mstr = weight_to_mf4x4_str(w, out_start, in_s, ky, kx)
                        out.append(f"\ttarget = MulAdd(n{letter}{suffix}, {mstr}, target);")

            out_tex = out_textures[t]
            out.append(f"\t{out_tex}[gxy] = target;")
            if t < n_tex - 1:
                out.append("")

        out.append("}")
        out.append("")

    # ─── Last pass: Aggregation + Depth-to-Space ───
    last_pass_num = ir.block_depth + 1
    stack_start_layer = ir.block_depth - ir.n_stack
    agg_in_textures = []
    for li in range(ir.n_stack):
        layer = stack_start_layer + li
        for ti in range(n_tex):
            agg_in_textures.append(conv_tex_name(layer, ti))

    total_in = ir.tail_weight.shape[1]
    total_samplers = n_tex * ir.n_stack
    n_tpg = n_tex

    out.append(f"//!PASS {last_pass_num}")
    out.append(f"//!DESC Conv-4x{ir.tail_kernel}x{ir.tail_kernel}x{total_in}, Depth-to-Space")
    out.append(f"//!IN INPUT, {', '.join(agg_in_textures)}")
    out.append("//!OUT OUTPUT")
    out.append("//!BLOCK_SIZE 16")
    out.append("//!NUM_THREADS 64")
    out.append("")
    out.append(f"void Pass{last_pass_num}(uint2 blockStart, uint3 threadId) {{")
    out.append("\tuint2 gxy = (Rmp8x8(threadId.x) << 1) + blockStart;")
    out.append("\tuint2 outputSize = GetOutputSize();")
    out.append("\tif (gxy.x >= outputSize.x || gxy.y >= outputSize.y) {")
    out.append("\t\treturn;")
    out.append("\t}")
    out.append("")
    out.append("\tfloat2 inputPt = GetInputPt();")
    out.append("\tfloat2 pos = ((gxy >> 1) + 0.5f) * inputPt;")
    out.append("")

    # Sample all aggregation inputs (no spatial offset for 1x1 kernel)
    for gi in range(total_samplers):
        tex = agg_in_textures[gi]
        out.append(f"\tMF4 g{gi} = {tex}.SampleLevel(sam, pos, 0);")
    out.append("")

    # CReLU
    if ir.factor == 2:
        for gi in range(total_samplers):
            out.append(f"\tMF4 ng{gi} = max(-g{gi}, 0);")
        out.append("")
        for gi in range(total_samplers):
            out.append(f"\tg{gi} = max(g{gi}, 0);")
        out.append("")

    # MulAdd for 3 output groups (target1, target2, target3)
    for t in range(3):
        out_start = t * 4
        tidx = t + 1
        bstr = bias_to_mf4_str(ir.tail_bias, out_start)
        out.append(f"\tMF4 target{tidx} = {bstr};")

        # Positive samples
        for gi in range(total_samplers):
            layer_idx = gi // n_tpg
            tex_idx = gi % n_tpg
            in_s = layer_idx * num_feat * ir.factor + tex_idx * 4
            mstr = weight_to_mf4x4_str(ir.tail_weight, out_start, in_s, 0, 0)
            out.append(f"\ttarget{tidx} = MulAdd(g{gi}, {mstr}, target{tidx});")

        # Negative samples
        if ir.factor == 2:
            for gi in range(total_samplers):
                layer_idx = gi // n_tpg
                tex_idx = gi % n_tpg
                in_s = layer_idx * num_feat * ir.factor + num_feat + tex_idx * 4
                mstr = weight_to_mf4x4_str(ir.tail_weight, out_start, in_s, 0, 0)
                out.append(f"\ttarget{tidx} = MulAdd(ng{gi}, {mstr}, target{tidx});")

        out.append("")

    # Depth-to-space output
    out.append("\tfloat2 outputPt = GetOutputPt();")
    out.append("")
    out.append("\tpos -= 0.5f * outputPt;")
    out.append("\tOUTPUT[gxy] = MF4(MF3(target1.x, target2.x, target3.x) + INPUT.SampleLevel(sam1, pos, 0).rgb, 1);")
    out.append("")
    out.append("\t++gxy.x;")
    out.append("\tpos.x += outputPt.x;")
    out.append("\tOUTPUT[gxy] = MF4(MF3(target1.y, target2.y, target3.y) + INPUT.SampleLevel(sam1, pos, 0).rgb, 1);")
    out.append("\t")
    out.append("\t++gxy.y;")
    out.append("\tpos.y += outputPt.y;")
    out.append("\tOUTPUT[gxy] = MF4(MF3(target1.w, target2.w, target3.w) + INPUT.SampleLevel(sam1, pos, 0).rgb, 1);")
    out.append("")
    out.append("\t--gxy.x;")
    out.append("\tpos.x -= outputPt.x;")
    out.append("\tOUTPUT[gxy] = MF4(MF3(target1.z, target2.z, target3.z) + INPUT.SampleLevel(sam1, pos, 0).rgb, 1);")
    out.append("}")
    out.append("")

    with open(path, "w") as f:
        f.write("\n".join(out))


__all__ = ["write_hlsl"]
