import torch
import math
import re
import argparse
import os

REUSETEX = True
MAXTEXTURE = 8

parser = argparse.ArgumentParser()
parser.add_argument("pth", help="Path to the input pth file")
parser.add_argument("out", help="Path to the output folder")

args = parser.parse_args()
params = torch.load(args.pth)['params']
out_hlsl = args.out if args.out[-5:]==".hlsl" else args.out+".hlsl"

num_feat = len(params['body.0.bias'])
num_conv = len([i for i in params.keys() if ".bias" in i]) - 2
num_text = int(num_feat/4)
pass_per_conv = math.ceil(num_text/MAXTEXTURE)

tex_define = """
//!TEXTURE
//!WIDTH INPUT_WIDTH
//!HEIGHT INPUT_HEIGHT
//!FORMAT R16G16B16A16_FLOAT
Texture2D conv2d_{a}_{b};
"""

pass_define = '''
//!PASS {pass_no}
//!DESC Conv-{pass_no}
//!IN {in_tex}
//!OUT {out_tex}
//!BLOCK_SIZE 8
//!NUM_THREADS 64

void Pass{pass_no}(uint2 blockStart, uint3 threadId) {{
    uint2 gxy = Rmp8x8(threadId.x) + blockStart;
    uint2 inputSize = GetInputSize();
    if (gxy.x >= inputSize.x || gxy.y >= inputSize.y) {{
        return;
    }}

    float2 inputPt = GetInputPt();
    float2 pos = (gxy + 0.5f) * inputPt;
    {calculation}
}}
'''

pass_1st = '''
//!PASS {pass_no}
//!DESC First Pass
//!IN INPUT
//!OUT {out_tex}
//!BLOCK_SIZE 16
//!NUM_THREADS 64

void Pass{pass_no}(uint2 blockStart, uint3 threadId) {{
    uint2 gxy = (Rmp8x8(threadId.x) << 1) + blockStart;
    uint2 inputSize = GetInputSize();
    if (gxy.x >= inputSize.x || gxy.y >= inputSize.y) {{
        return;
    }}

    float2 inputPt = GetInputPt();

    uint i, j;

    MF3 src[4][4];
    [unroll]
    for (i = 0; i <= 2; i += 2) {{
        [unroll]
        for (j = 0; j <= 2; j += 2) {{
            float2 tpos = (gxy + uint2(i, j)) * inputPt;
            const MF4 sr = INPUT.GatherRed(sam, tpos);
            const MF4 sg = INPUT.GatherGreen(sam, tpos);
            const MF4 sb = INPUT.GatherBlue(sam, tpos);

            // w z
            // x y
            src[i][j] = MF3(sr.w, sg.w, sb.w);
            src[i][j + 1] = MF3(sr.x, sg.x, sb.x);
            src[i + 1][j] = MF3(sr.z, sg.z, sb.z);
            src[i + 1][j + 1] = MF3(sr.y, sg.y, sb.y);
        }}
    }}

    [unroll]
    for (i = 1; i <= 2; ++i) {{
        [unroll]
        for (j = 1; j <= 2; ++j) {{
            uint2 destPos = gxy + uint2(i - 1, j - 1);

            if (i != 1 || j != 1) {{
                if (destPos.x >= inputSize.x || destPos.y >= inputSize.y) {{
                    continue;
                }}
            }}
            {calculation}
        }}
    }}
}}
'''

get_pixel = '''
    MF4 a{b} = conv2d_{a}_{b}.SampleLevel(sam, pos + float2(-inputPt.x, -inputPt.y), 0);
    MF4 b{b} = conv2d_{a}_{b}.SampleLevel(sam, pos + float2(-inputPt.x, 0), 0);
    MF4 c{b} = conv2d_{a}_{b}.SampleLevel(sam, pos + float2(-inputPt.x, inputPt.y), 0);
    MF4 d{b} = conv2d_{a}_{b}.SampleLevel(sam, pos + float2(0, -inputPt.y), 0);
    MF4 e{b} = conv2d_{a}_{b}.SampleLevel(sam, pos, 0);
    MF4 f{b} = conv2d_{a}_{b}.SampleLevel(sam, pos + float2(0, inputPt.y), 0);
    MF4 g{b} = conv2d_{a}_{b}.SampleLevel(sam, pos + float2(inputPt.x, -inputPt.y), 0);
    MF4 h{b} = conv2d_{a}_{b}.SampleLevel(sam, pos + float2(inputPt.x, 0), 0);
    MF4 i{b} = conv2d_{a}_{b}.SampleLevel(sam, pos + float2(inputPt.x, inputPt.y), 0);
'''

def cal_weight(j, b, define=False, first=False):
     return f'''
    {"MF4 " if define else ""}target{j} {"" if first else "+"}= MulAdd(a{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, -0.1816813, 0.053423163, -0.02265236, 0.06604943, 0.15899086, -0.15651219, 0.2919677, 0.00591133, 0.09306437, 0.047243804, -0.1389423, -0.0076663005), target{j});
    target{j} += MulAdd(b{b}, MF4x4(0.23136483, 0.20969442, -0.25250545, -0.038510673, 0.06916893, -0.19306515, -0.07070081, 0.016512204, 0.05914443, 0.31841832, -0.15109769, 0.058795422, 0.0418041, -0.13008581, 0.15338552, 0.037921127), target{j});
    target{j} += MulAdd(c{b}, MF4x4(0.023348259, 0.15947549, 0.16773324, 0.04159353, 0.113954544, -0.071491666, 0.12837915, -0.043326825, 0.058823302, 0.09453112, 0.017051624, 0.048308555, -0.10970718, -0.25019458, 0.074912935, -0.04076737), target{j});
    target{j} += MulAdd(d{b}, MF4x4(0.036305163, -0.22121401, 0.120393604, -0.05099148, -0.10198376, -0.04498367, -0.08815256, 0.024565894, -0.04884751, -0.036884382, -0.24040928, -0.112012394, 0.005314592, -0.14346673, 0.04090868, 0.040303618), target{j});
    target{j} += MulAdd(e{b}, MF4x4(0.32364944, 0.2346947, 0.13479401, -0.071001865, -0.092296354, -0.13325988, 0.18273465, 0.16443633, -0.138694, -0.1538144, 0.0001256584, 0.23658273, -0.055330865, 0.18081205, -0.14958258, 0.18050644), target{j});
    target{j} += MulAdd(f{b}, MF4x4(0.30818513, -0.10282234, -0.14460294, 0.11525818, 0.15799633, -0.038440127, 0.07736027, -0.113209635, -0.03558696, 0.0027641046, 0.09750022, -0.035741746, -0.06724116, -0.11298426, -0.23708679, -0.08182236), target{j});
    target{j} += MulAdd(g{b}, MF4x4(0.16450825, 0.014239063, -0.15482663, 0.011389393, 0.121237025, -0.056966547, -0.23891398, -0.07385608, -0.0919129, 0.1384911, 0.10602064, -0.08549364, -0.117471084, 0.045140628, -0.055791426, 0.11584021), target{j});
    target{j} += MulAdd(h{b}, MF4x4(0.053284578, 0.084236816, 0.16935693, -0.16279462, -0.060930096, 0.13849908, 0.16018802, -0.007871505, 0.12076791, -0.06930294, -0.16473438, 0.12876272, -0.039502293, -0.064467184, 0.13885021, -0.09353176), target{j});
    target{j} += MulAdd(i{b}, MF4x4(0.04007251, -0.0423664, -0.20841573, 0.025270352, 0.051647697, -0.086622365, -0.108722195, 0.03807204, 0.059649065, -0.0070362207, 0.04048331, 0.06589983, -0.014079206, -0.10045001, 0.09532272, -0.12775785), target{j});
'''

cal_bias_prelu = '''
    target += MF4(-0.09062037, 0.013100331, -0.030562, -0.0064230394);
    target = max(target, 0) + MF4(1.0311057, 0.10512088984, 0.1158760935, 0.046663507819) * min(target, 0);
    conv2d_{a}_{b}[gxy] = target;
'''

cal_1st = '''
            {define}target = MulAdd(src[i - 1][j - 1], MF3x4(-0.27576035, -0.07072761, -0.1630093, -0.11306897, 0.14765891, -0.039999995, 0.04671886, -0.06138944, 0.11445724, 0.10989976, 0.12772457, 0.19654717), target);
            target += MulAdd(src[i - 1][j], MF3x4(-0.076798744, -0.026944768, -0.24994318, 0.2515569, -0.16839856, 0.17563075, 0.30983326, -0.26057217, -0.07267306, -0.16690817, -0.028771983, -0.32779765), target);
            target += MulAdd(src[i - 1][j + 1], MF3x4(-0.22670166, -0.08031973, 0.1576897, -0.09411961, 0.10889907, 0.09876773, -0.12708376, 0.20890583, 0.13792023, 0.046159253, 0.008415701, 0.028718324), target);
            target += MulAdd(src[i][j - 1], MF3x4(0.123937644, -0.0040695923, 0.1577942, -0.25086892, -0.11906424, 0.024612824, 0.04019426, -0.20309904, -0.001790695, -0.022292957, -0.24705121, -0.020513516), target);
            target += MulAdd(src[i][j], MF3x4(-0.12275696, 0.087533146, 0.22975677, 0.3249744, -0.46705425, 0.049937986, -0.3746097, 0.6908184, -0.02694045, 0.10467642, 0.24765752, 0.29053956), target);
            target += MulAdd(src[i][j + 1], MF3x4(-0.085650265, 0.06399875, 0.16803174, -0.000924935, -0.012419805, 0.3505107, -0.013437306, -0.37681264, -0.06174721, 0.3525594, -0.7133205, 0.16013019), target);
            target += MulAdd(src[i + 1][j - 1], MF3x4(0.2400495, 0.08462758, 0.025238732, -0.019882765, -0.09665332, -0.030001955, -0.10374011, -0.2661804, -0.1017717, -0.04910443, 0.102630705, -0.01290848), target);
            target += MulAdd(src[i + 1][j], MF3x4(0.13510828, -0.09396734, -0.30896646, 0.13402982, 0.7047196, -0.09083812, 0.29420912, -0.30652946, 0.089854665, -0.04834406, 0.017005004, -0.22518355), target);
            target += MulAdd(src[i + 1][j + 1], MF3x4(0.28510967, 0.04660653, 0.24457681, -0.21047631, -0.12409636, -0.5526988, -0.1340479, 0.2336875, -0.048938934, -0.31569406, -0.021553513, -0.084858574), target);
            target += MF4(0.0357343, 0.024812812, 0.040654864, -0.002103711);
            target = max(target, 0) + MF4(1.0311057, 0.10512088984, 0.1158760935, 0.046663507819) * min(target, 0);
            conv2d_1_{b}[destPos] = target;
'''

last_pass = '''
//!PASS {pass_no}
//!DESC Conv-{pass_no} Depth-to-Space
//!IN INPUT, {in_tex}
//!OUT OUTPUT
//!BLOCK_SIZE 16
//!NUM_THREADS 64

void Pass{pass_no}(uint2 blockStart, uint3 threadId) {{
    uint2 gxy = (Rmp8x8(threadId.x) << 1) + blockStart;

    const uint2 outputSize = GetOutputSize();
    if (gxy.x >= outputSize.x || gxy.y >= outputSize.y) {{
        return;
    }}

    float2 inputPt = GetInputPt();
    float2 pos = ((gxy >> 1) + 0.5f) * inputPt;

    {calculation}

    float2 outputPt = GetOutputPt();

    pos -= 0.5f * outputPt;
    OUTPUT[gxy] = MF4(MF3(target1.x, target2.x, target3.x) + INPUT.SampleLevel(sam, pos, 0).rgb, 1);

    ++gxy.x;
    pos.x += outputPt.x;
    OUTPUT[gxy] = MF4(MF3(target1.y, target2.y, target3.y) + INPUT.SampleLevel(sam, pos, 0).rgb, 1);

    ++gxy.y;
    pos.y += outputPt.y;
    OUTPUT[gxy] = MF4(MF3(target1.w, target2.w, target3.w) + INPUT.SampleLevel(sam, pos, 0).rgb, 1);

    --gxy.x;
    pos.x -= outputPt.x;
    OUTPUT[gxy] = MF4(MF3(target1.z, target2.z, target3.z) + INPUT.SampleLevel(sam, pos, 0).rgb, 1);
}}
'''

###############################################################

hlsl = '''//!MAGPIE EFFECT
//!VERSION 4
//!SORT_NAME compact
//!USE FP16, MulAdd

#include "..\\StubDefs.hlsli"

//!TEXTURE
Texture2D INPUT;

//!TEXTURE
//!WIDTH INPUT_WIDTH * 2
//!HEIGHT INPUT_HEIGHT * 2
Texture2D OUTPUT;
'''

for i in range(-1, 1) if REUSETEX else range(num_conv+1):
    for j in range(num_text):
        hlsl+=tex_define.format(a=i+1,b=j)

hlsl+='''
//!SAMPLER
//!FILTER POINT
SamplerState sam;
'''

current_pass = 1
### First pass
for p in range(pass_per_conv):
    out_tex = ", ".join([f"conv2d_1_{b}" for b in range(p * MAXTEXTURE, min(p * MAXTEXTURE + MAXTEXTURE, num_text))])
    calculation = ''
    for b in range(len(out_tex.split(","))):
        calculation += cal_1st.format(b=p * MAXTEXTURE + b, define="MF4 " if b%MAXTEXTURE==0 else "")
    hlsl+=pass_1st.format(out_tex=out_tex, calculation=calculation, pass_no=current_pass)
    current_pass += 1

### Middle pass
for conv_no in range(2, num_conv+2):
    in_group = (conv_no-1)%2 if REUSETEX else conv_no-1
    out_group = conv_no%2 if REUSETEX else conv_no
    for p in range(pass_per_conv):
        in_tex = ", ".join([f"conv2d_{in_group}_{b}" for b in range(num_text)])
        out_tex = ", ".join([f"conv2d_{out_group}_{b}" for b in range(p * MAXTEXTURE, min(p * MAXTEXTURE + MAXTEXTURE, num_text))])
        calculation = ''
        for b in range(num_text):
            calculation += get_pixel.format(a=in_group, b=b)

        for i in range(len(out_tex.split(","))):
            for b in range(num_text):
                calculation += cal_weight(j="", b=b, define=(i%MAXTEXTURE==0 and b==0), first=(b==0))
            calculation += cal_bias_prelu.format(a=out_group, b=p * MAXTEXTURE + i)

        hlsl+= pass_define.format(pass_no=current_pass,in_tex=in_tex,out_tex=out_tex,calculation=calculation)
        current_pass += 1

#### Last pass
in_group = conv_no%2 if REUSETEX else conv_no
in_tex = ", ".join([f"conv2d_{in_group}_{b}" for b in range(num_text)])
calculation = ''
for b in range(num_text):
    calculation += get_pixel.format(a=in_group, b=b)

for i in range(3):
    for b in range(num_text):
        calculation += cal_weight(j=i+1, b=b, define=(b==0), first=(b==0))
    calculation += f'''
    target{i+1} += MF4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000);
'''
hlsl+= last_pass.format(pass_no=current_pass,in_tex=in_tex,calculation=calculation)



def convert(weight, bias, data, prelu=None):
    out_chan, in_chan, width, height = weight.shape
    text_per_con = math.ceil(out_chan/4)
    pass_per_conv = math.ceil(text_per_con/MAXTEXTURE)

    for p in range(pass_per_conv):
        for to in range(p * MAXTEXTURE, min(p * MAXTEXTURE + MAXTEXTURE, text_per_con)):
            for ti in range(math.ceil(in_chan/4)):
                for w in range(width):
                    for h in range(height):
                        for i in range(min(4, in_chan)):
                            for o in range(min(4, out_chan)):
                                data.append(float(weight[to*4+o, ti*4+i, h, w]))
            for o in range(min(4, out_chan)):
                data.append(float(bias.data[to*4+o]))

            for o in range(min(4, out_chan)):
                if prelu is not None:
                    data.append(float(prelu.data[to*4+o]))


# model = model['params_ema']
num_conv = len([i for i in params.keys() if ".bias" in i])
data = []
for i in range(num_conv):
    if i == num_conv-1:
        convert(params[f"body.{i*2}.weight"], params[f"body.{i*2}.bias"], data)
    else:
        convert(params[f"body.{i*2}.weight"], params[f"body.{i*2}.bias"], data, prelu=params[f"body.{2*i+1}.weight"])

data_iter = iter(data)
def replace_match(match):
    return str(next(data_iter))

pattern = r'-?\d+(\.\d{2,})(e-?\d+)?'

#debug
print(len(data))
print(len(re.findall(pattern, hlsl)))

new_text = re.sub(pattern, replace_match, hlsl)
with open(out_hlsl,"w") as f:
    f.write(new_text)


try:
    next(data_iter)
except StopIteration:
    print("done")
else:
    print("Fail")