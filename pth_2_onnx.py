import torch
import torch.nn as nn
import torch.nn.functional as F
import re
import os
import math
import argparse

import torchvision
from IPython.display import Image, display
from PIL import Image


class CReLU(nn.Module):
    def __init__(self):
        super(CReLU, self).__init__()
    def forward(self, x):
        return F.relu(torch.cat((x, -x), 1))


class anime4k(nn.Module):
    def __init__(self, block_depth=7, block_stack=5, channel=12):
        super(anime4k, self).__init__()
        self.conv_head = nn.Conv2d(3, channel, kernel_size=3, padding=1)
        self.conv_mid = nn.ModuleList(
            [
                nn.Conv2d(channel * 2, channel, kernel_size=3, padding=1)
                for _ in range(block_depth - 1)
            ]
        )
        if block_stack != 1:
            self.conv_tail = nn.Conv2d(
                2 * channel * block_stack, 12, kernel_size=1, padding=0
            )
        else:
            self.conv_tail = nn.Conv2d(2 * channel, 12, kernel_size=3, padding=1)
        self.crelu = CReLU()
        self.block_no_stack = block_depth - block_stack
        self.ps = nn.PixelShuffle(2)

    def forward(self, x):
        out = self.crelu(self.conv_head(x))
        if self.block_no_stack == 0:
            depth_list = [out]
        else:
            depth_list = []
        for i, conv in enumerate(self.conv_mid):
            out = self.crelu(conv(out))
            if i >= self.block_no_stack - 1:
                depth_list.append(out)
        out = self.conv_tail(torch.cat(depth_list, 1))
        out = self.ps(out) + F.interpolate(x, scale_factor=2, mode="bilinear")
        return torch.clamp(out, max=1.0, min=0.0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pth", help="Path to the input pth file")
    parser.add_argument("out", help="Path to the output folder")
    args = parser.parse_args()
    
    base, ext = os.path.splitext(os.path.basename(args.pth))
    out = os.path.join(args.out, f"{base}.onnx")

    device = torch.device("cuda")
    dummy_input = torch.randn(1, 3, 720, 1280).half().to(device)
    model = anime4k().half().to(device)
    model.load_state_dict(torch.load(args.pth, map_location=device)['params'])
    
    torch.onnx.export(
        model,
        dummy_input,
        out,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={
            "input": {0: "batch_size", 2: "height", 3: "width"},
            "output": {0: "batch_size", 2: "height", 3: "width"},
        },
        opset_version=17,
    )