"""Vulkan compute shader writer (.comp)."""

import textwrap

from ..ir import Anime4KCNN
from ..utils import SPATIAL_OFFSETS_3x3, bias_to_vec4_str, weight_to_mat4_str


def write_comp(ir: Anime4KCNN, path: str,
               descriptor_include: str = "../../descriptor_set.h") -> None:
    """Write IR -> Vulkan compute shader (.comp)."""
    num_feat = ir.num_feat
    n_tex = num_feat // 4
    total_passes = 1 + (ir.block_depth - 1) + 1 + 1
    dts_pass = total_passes - 1

    header = textwrap.dedent(f"""\
        #version 450

        #extension GL_GOOGLE_include_directive : require
        #extension GL_EXT_scalar_block_layout : require

        #include "{descriptor_include}"

        layout(constant_id = 8) const int PASS = 0;

        layout(local_size_x = 8, local_size_y = 8, local_size_z = 1) in;

        layout(binding = 0, scalar)
        uniform layers_t {{
            uvec2 u_inputSize;
            uvec2 u_outputSize;
        }};

        vec4 sampleTex(int samplerIdx, ivec2 coord, ivec2 offset) {{
            ivec2 sampleCoord = coord + offset;
            sampleCoord = clamp(sampleCoord, ivec2(0), ivec2(u_inputSize) - ivec2(1));
            return texelFetch(s_samplers[samplerIdx], sampleCoord, 0);
        }}

        vec4 sampleTexCurrent(int samplerIdx, ivec2 coord) {{
            return texelFetch(s_samplers[samplerIdx], coord, 0);
        }}

        void main() {{
            uvec2 coord = uvec2(gl_GlobalInvocationID.xy);
            ivec2 icoord = ivec2(coord);

            if (PASS < {dts_pass}) {{
                if (coord.x >= u_inputSize.x || coord.y >= u_inputSize.y)
                    return;
            }}

    """)

    body = []

    # Pass 0: initial conv
    in_ch = ir.head_weight.shape[1]  # 3 for RGB
    conv_spec = f"Conv-4x3x3x{in_ch}"
    body.append(f"    // ============ PASS 0: Merged {conv_spec} "
                f"(RGB -> {n_tex} feature textures) ============")
    body.append("    if (PASS == 0) {")
    for t in range(n_tex):
        body.append(f"        vec4 result{t} = vec4(0.0);")
    body.append("")

    for t in range(n_tex):
        out_s = t * 4
        rv = f"result{t}"
        first = True
        for ox, oy in SPATIAL_OFFSETS_3x3:
            ky, kx = ox + 1, oy + 1
            mat = weight_to_mat4_str(ir.head_weight, out_s, 0, ky, kx)
            op = "=" if first else "+="
            body.append(f"        {rv} {op} {mat} * sampleTex(0, icoord, ivec2({ox}, {oy}));")
            first = False
        bvec = bias_to_vec4_str(ir.head_bias, out_s)
        body.append(f"        {rv} += {bvec};")
        body.append("")

    for t in range(n_tex):
        body.append(f"        imageStore({['dst', 'dst1', 'dst2'][t]}, icoord, result{t});")
    body.append("        return;")
    body.append("    }")
    body.append("")

    # Hidden layers
    n_inp_tex = num_feat // 4
    for mid_idx in range(ir.block_depth - 1):
        pass_idx = mid_idx + 1
        w = ir.mid_weights[mid_idx]
        b = ir.mid_biases[mid_idx]
        in_channels = w.shape[1]
        conv_spec = f"Conv-4x3x3x{in_channels}"

        body.append(f"    // ============ PASS {pass_idx}: Merged {conv_spec} "
                    f"(layer {pass_idx}) ============")
        body.append(f"    if (PASS == {pass_idx}) {{")
        for t in range(n_tex):
            body.append(f"        vec4 result{t} = vec4(0.0);")
        body.append("")

        for t in range(n_tex):
            out_s = t * 4
            rv = f"result{t}"
            first = True

            # Positive part
            for si in range(n_inp_tex):
                in_s = si * 4
                for ox, oy in SPATIAL_OFFSETS_3x3:
                    ky, kx = ox + 1, oy + 1
                    mat = weight_to_mat4_str(w, out_s, in_s, ky, kx)
                    op = "=" if first else "+="
                    body.append(f"        {rv} {op} {mat} "
                                f"* max(sampleTex({si}, icoord, ivec2({ox}, {oy})), 0.0);")
                    first = False

            # Negative part (CReLU)
            if ir.factor == 2:
                for si in range(n_inp_tex):
                    in_s = num_feat + si * 4
                    for ox, oy in SPATIAL_OFFSETS_3x3:
                        ky, kx = ox + 1, oy + 1
                        mat = weight_to_mat4_str(w, out_s, in_s, ky, kx)
                        body.append(f"        {rv} += {mat} "
                                    f"* max(-sampleTex({si}, icoord, ivec2({ox}, {oy})), 0.0);")

            bvec = bias_to_vec4_str(b, out_s)
            body.append(f"        {rv} += {bvec};")
            body.append("")

        for t in range(n_tex):
            body.append(f"        imageStore({['dst', 'dst1', 'dst2'][t]}, icoord, result{t});")
        body.append("        return;")
        body.append("    }")
        body.append("")

    # Aggregation pass
    agg_pass = ir.block_depth
    total_samplers = n_tex * ir.n_stack
    total_in = ir.tail_weight.shape[1]
    conv_spec = f"Conv-4x{ir.tail_kernel}x{ir.tail_kernel}x{total_in}"
    use_offset = ir.tail_kernel > 1

    body.append(f"    // ============ PASS {agg_pass}: Merged {conv_spec} "
                f"({total_samplers} inputs -> 3 outputs) ============")
    body.append(f"    if (PASS == {agg_pass}) {{")
    for t in range(3):
        body.append(f"        vec4 result{t} = vec4(0.0);")
    body.append("")

    for t in range(3):
        out_s = t * 4
        rv = f"result{t}"
        first = True

        if use_offset:
            half = ir.tail_kernel // 2
            spatial = [(ox, oy) for ox in range(-half, half + 1) for oy in range(-half, half + 1)]
        else:
            spatial = None

        # Positive samples
        for li in range(ir.n_stack):
            layer_base = li * num_feat * ir.factor
            for ti in range(n_tex):
                in_s = layer_base + ti * 4
                if spatial:
                    for ox, oy in spatial:
                        ky, kx = ox + half, oy + half
                        mat = weight_to_mat4_str(ir.tail_weight, out_s, in_s, ky, kx)
                        op = "=" if first else "+="
                        body.append(f"        {rv} {op} {mat} "
                                    f"* max(sampleTex({li * n_tex + ti}, icoord, ivec2({ox}, {oy})), 0.0);")
                        first = False
                else:
                    mat = weight_to_mat4_str(ir.tail_weight, out_s, in_s, 0, 0)
                    op = "=" if first else "+="
                    body.append(f"        {rv} {op} {mat} "
                                f"* max(sampleTexCurrent({li * n_tex + ti}, icoord), 0.0);")
                    first = False

        # Negative samples
        if ir.factor == 2:
            for li in range(ir.n_stack):
                layer_base = li * num_feat * ir.factor
                for ti in range(n_tex):
                    in_s = layer_base + num_feat + ti * 4
                    if spatial:
                        for ox, oy in spatial:
                            ky, kx = ox + half, oy + half
                            mat = weight_to_mat4_str(ir.tail_weight, out_s, in_s, ky, kx)
                            body.append(f"        {rv} += {mat} "
                                        f"* max(-sampleTex({li * n_tex + ti}, icoord, ivec2({ox}, {oy})), 0.0);")
                    else:
                        mat = weight_to_mat4_str(ir.tail_weight, out_s, in_s, 0, 0)
                        body.append(f"        {rv} += {mat} "
                                    f"* max(-sampleTexCurrent({li * n_tex + ti}, icoord), 0.0);")

        bvec = bias_to_vec4_str(ir.tail_bias, out_s)
        body.append(f"        {rv} += {bvec};")
        body.append("")

    for t in range(3):
        body.append(f"        imageStore({['dst', 'dst1', 'dst2'][t]}, icoord, result{t});")
    body.append("        return;")
    body.append("    }")
    body.append("")

    # Depth-to-space pass
    body.append(f"    // ============ PASS {dts_pass}: Depth-to-Space ============")
    body.append(f"    if (PASS == {dts_pass}) {{")
    body.append("        if (coord.x >= u_outputSize.x || coord.y >= u_outputSize.y)")
    body.append("            return;")
    body.append("")
    body.append("        ivec2 subPixel = ivec2(coord) % 2;")
    body.append("        ivec2 inputCoord = ivec2(coord) / 2;")
    body.append("        int channelIdx = subPixel.y * 2 + subPixel.x;")
    body.append("        ")
    body.append("        float c0 = texelFetch(s_samplers[0], inputCoord, 0)[channelIdx];")
    body.append("        float c1 = texelFetch(s_samplers[1], inputCoord, 0)[channelIdx];")
    body.append("        float c2 = texelFetch(s_samplers[2], inputCoord, 0)[channelIdx];")
    body.append("        ")
    body.append("        vec2 originalUV = (vec2(coord) + 0.5) / vec2(u_outputSize);")
    body.append("        vec4 original = texture(s_samplers[3], originalUV);")
    body.append("        ")
    body.append("        vec4 result = vec4(c0 + original.r, c1 + original.g, c2 + original.b, 1.0);")
    body.append("        result = clamp(result, 0.0, 1.0);")
    body.append("        ")
    body.append("        imageStore(dst, ivec2(coord), result);")
    body.append("        return;")
    body.append("    }")
    body.append("")

    full = header + "\n".join(body) + "\n}\n"
    with open(path, "w") as f:
        f.write(full)


__all__ = ["write_comp"]
