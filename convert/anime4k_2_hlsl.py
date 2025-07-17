import torch 
import math
import re
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument("pth", help="Path to the input pth file")
parser.add_argument("out", help="Path to the output folder")

args = parser.parse_args()
params = torch.load(args.pth, weights_only=True)['params']
out_hlsl = args.out if args.out[-5:]==".hlsl" else args.out+".hlsl"

a = len([x for x in params.keys() if "conv_mid" in x]) / 2 + 1
c = len(params["conv_head.bias"])
b = params["conv_tail.weight"].shape[1] / 2 / c

num_conv = int(a)
num_feat = c
block_stack = int(b)
num_text = num_feat // 4

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
//!PASS 1
//!DESC First Pass
//!IN INPUT
//!OUT {out_tex}
//!BLOCK_SIZE 16
//!NUM_THREADS 64

void Pass1(uint2 blockStart, uint3 threadId) {{
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
 
 	MF4 na{b} = max(-a{b}, 0);
	MF4 nb{b} = max(-b{b}, 0);
	MF4 nc{b} = max(-c{b}, 0);
	MF4 nd{b} = max(-d{b}, 0);
	MF4 ne{b} = max(-e{b}, 0);
	MF4 nf{b} = max(-f{b}, 0);
	MF4 ng{b} = max(-g{b}, 0);
	MF4 nh{b} = max(-h{b}, 0);
	MF4 ni{b} = max(-i{b}, 0);

	a{b} = max(a{b}, 0);
	b{b} = max(b{b}, 0);
	c{b} = max(c{b}, 0);
	d{b} = max(d{b}, 0);
	e{b} = max(e{b}, 0);
	f{b} = max(f{b}, 0);
	g{b} = max(g{b}, 0);
	h{b} = max(h{b}, 0);
	i{b} = max(i{b}, 0);
'''

def cal_weight(j, b, negative=False):
 	return f'''
	target{j} = MulAdd({'n' if negative else ""}a{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
	target{j} = MulAdd({'n' if negative else ""}b{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
	target{j} = MulAdd({'n' if negative else ""}c{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
	target{j} = MulAdd({'n' if negative else ""}d{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
	target{j} = MulAdd({'n' if negative else ""}e{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
	target{j} = MulAdd({'n' if negative else ""}f{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
	target{j} = MulAdd({'n' if negative else ""}g{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
	target{j} = MulAdd({'n' if negative else ""}h{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
	target{j} = MulAdd({'n' if negative else ""}i{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
'''

cal_bias = '''
    {define}target = MF4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000);
'''

put_value = '''
	conv2d_{a}_{b}[gxy] = target;
'''

cal_1st = '''
			{define}target = MF4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000);
			target = MulAdd(src[i - 1][j - 1], MF3x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
			target = MulAdd(src[i - 1][j], MF3x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
			target = MulAdd(src[i - 1][j + 1], MF3x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
			target = MulAdd(src[i][j - 1], MF3x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
			target = MulAdd(src[i][j], MF3x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
			target = MulAdd(src[i][j + 1], MF3x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
			target = MulAdd(src[i + 1][j - 1], MF3x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
			target = MulAdd(src[i + 1][j], MF3x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
			target = MulAdd(src[i + 1][j + 1], MF3x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target);
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
	OUTPUT[gxy] = MF4(MF3(target1.x, target2.x, target3.x) + INPUT.SampleLevel(sam1, pos, 0).rgb, 1);

	++gxy.x;
	pos.x += outputPt.x;
	OUTPUT[gxy] = MF4(MF3(target1.y, target2.y, target3.y) + INPUT.SampleLevel(sam1, pos, 0).rgb, 1);

	++gxy.y;
	pos.y += outputPt.y;
	OUTPUT[gxy] = MF4(MF3(target1.w, target2.w, target3.w) + INPUT.SampleLevel(sam1, pos, 0).rgb, 1);

	--gxy.x;
	pos.x -= outputPt.x;
	OUTPUT[gxy] = MF4(MF3(target1.z, target2.z, target3.z) + INPUT.SampleLevel(sam1, pos, 0).rgb, 1);
}}
'''

def lastpass_weight(j, b, negative=False):
 	return f'''
	target{j} = MulAdd({'n' if negative else ""}g{b}, MF4x4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000), target{j});'''
###############################################################

hlsl = '''//!MAGPIE EFFECT
//!VERSION 4
//!SORT_NAME anime4k
//!USE MulAdd
//!CAPABILITY FP16

#include "..\\StubDefs.hlsli"

//!TEXTURE
Texture2D INPUT;

//!TEXTURE
//!WIDTH INPUT_WIDTH * 2
//!HEIGHT INPUT_HEIGHT * 2
Texture2D OUTPUT;
'''

for i in range(num_conv):
    for j in range(num_text):
        hlsl+=tex_define.format(a=i+1,b=j)
        
hlsl+='''
//!SAMPLER
//!FILTER POINT
SamplerState sam;

//!SAMPLER
//!FILTER LINEAR
SamplerState sam1;
'''

### First pass
out_tex = ", ".join([f"conv2d_1_{b}" for b in range(num_text)]) 
calculation = ''
for b in range(num_text):
    calculation += cal_1st.format(b=b, define="MF4 " if b==0 else "")
hlsl+=pass_1st.format(out_tex=out_tex, calculation=calculation)

### Middle pass
for pass_no in range(2, num_conv+1):
    in_tex = ", ".join([f"conv2d_{pass_no-1}_{b}" for b in range(num_text)]) 
    out_tex = ", ".join([f"conv2d_{pass_no}_{b}" for b in range(num_text)]) 
    calculation = ''
    for b in range(num_text):
        calculation += get_pixel.format(a=pass_no-1, b=b)

    for i in range(num_text):
        calculation += cal_bias.format(define="MF4 " if i==0 else "")
        for b in range(num_text):
            calculation += cal_weight(j="", b=b)
        for b in range(num_text):
            calculation += cal_weight(j="", b=b, negative=True)
        calculation += put_value.format(a=pass_no, b=i)

    hlsl+= pass_define.format(pass_no=pass_no,in_tex=in_tex,out_tex=out_tex,calculation=calculation)

#### Last pass
pass_no += 1

last_in_texture = [f"conv2d_{pass_no-block_stack+i}_{b}" for i in range(block_stack) for b in range(num_text)]
in_tex = ", ".join(last_in_texture) 
calculation = ''
for i, tex in enumerate(last_in_texture):
    calculation += f"\n\tMF4 g{i} = {tex}.SampleLevel(sam, pos, 0);"
calculation += "\n"
for i, tex in enumerate(last_in_texture):
    calculation += f"\n\tMF4 ng{i} = max(-g{i}, 0);"
calculation += "\n"
for i, tex in enumerate(last_in_texture):
    calculation += f"\n\tg{i} = max(g{i}, 0);"
calculation += "\n"

for i in range(3):
	calculation += f'''
  
	MF4 target{i+1} = MF4(0.0000000000, 0.0000000000, 0.0000000000, 0.0000000000);'''
	for j in range(block_stack):
		for k in range(num_text):
			b = j * num_text + k
			calculation += lastpass_weight(j=i+1, b=b)
		for k in range(num_text):
			b = j * num_text + k
			calculation += lastpass_weight(j=i+1, b=b, negative=True)

hlsl+= last_pass.format(pass_no=pass_no,in_tex=in_tex,calculation=calculation)



def convert(weight, bias, data, doswap=False):
    swap = [0,2,1,3]
    out_chan, in_chan, width, height = weight.shape
    for to in range(math.ceil(out_chan/4)):
        for o in range(min(4, out_chan)):
            o = swap[o] if doswap else o
            data.append(float(bias.data[to*4+o]))
        for ti in range(math.ceil(in_chan/4)):
            for w in range(width):
                for h in range(height):
                    for i in range(min(4, in_chan)):
                        for o in range(min(4, out_chan)):
                            o = swap[o] if doswap else o
                            # data.append(float(weight[to*4+o, ti*4+i, w, h]))
                            data.append(float(weight[to*4+o, ti*4+i, h, w]))


# model = model['params_ema']
# model = model['params']
num_conv = len([i for i in params.keys() if ".bias" in i])
data = []
if True:
	
	layers = [i[:-7] for i in params.keys() if ".weight" in i]
	data = []
	for i in layers:
		# convert(params[i+".weight"], params[i+".bias"], data, doswap= "tail" in i)
		convert(params[i+".weight"], params[i+".bias"], data)
			
	data_iter = iter(data)
	def replace_match(match):
		return str(next(data_iter))

	pattern = r'-?\d+(\.\d{2,})(e-?\d+)?'

	hlsl = re.sub(pattern, replace_match, hlsl)
with open(out_hlsl,"w") as f:
	f.write(hlsl)


try: 
	next(data_iter)
except StopIteration: 
	print("done")
else:
	print("Fail")