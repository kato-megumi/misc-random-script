"""CLI entrypoint for Anime4K CNN converter."""

import argparse
import sys

from .parsers import parse_comp, parse_glsl, parse_hlsl, parse_pth
from .utils import variant_label
from .writers import write_comp, write_glsl, write_hlsl, write_pth


FORMAT_PARSERS = {
    ".pth": parse_pth,
    ".safetensors": parse_pth,
    ".comp": parse_comp,
    ".glsl": parse_glsl,
    ".hlsl": parse_hlsl,
}

FORMAT_WRITERS = {
    ".pth": write_pth,
    ".comp": write_comp,
    ".glsl": write_glsl,
    ".hlsl": write_hlsl,
}


def detect_format(path: str) -> str:
    """Detect format from file extension."""
    for ext in FORMAT_PARSERS:
        if path.lower().endswith(ext):
            return ext
    return ""


def convert(input_path: str, output_path: str,
            descriptor_include: str = "../../descriptor_set.h",
            verbose: bool = False) -> None:
    """Convert between any two supported formats."""
    in_fmt = detect_format(input_path)
    out_fmt = detect_format(output_path)

    if not in_fmt:
        print(f"Error: Unknown input format for '{input_path}'", file=sys.stderr)
        sys.exit(1)
    if not out_fmt:
        print(f"Error: Unknown output format for '{output_path}'", file=sys.stderr)
        sys.exit(1)

    # Parse input
    parser = FORMAT_PARSERS[in_fmt]
    ir = parser(input_path)

    label = variant_label(ir)
    if verbose:
        print(f"Architecture: Anime4K CNN x2 {label}")
        print(f"  num_feat={ir.num_feat}, block_depth={ir.block_depth}")
        print(f"  factor={ir.factor}, n_stack={ir.n_stack}, tail_kernel={ir.tail_kernel}")
        total_passes = 1 + (ir.block_depth - 1) + 1 + 1
        print(f"  Total passes: {total_passes}")

    # Write output
    writer = FORMAT_WRITERS[out_fmt]
    if out_fmt == ".comp":
        writer(ir, output_path, descriptor_include)
    else:
        writer(ir, output_path)

    print(f"Converted {in_fmt} -> {out_fmt}: {input_path} -> {output_path} ({label})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Universal converter between Anime4K CNN shader formats"
    )
    parser.add_argument("input", help="Input file (.pth/.safetensors/.comp/.glsl/.hlsl)")
    parser.add_argument("output", help="Output file (.pth/.comp/.glsl/.hlsl)")
    parser.add_argument(
        "--descriptor-include",
        default="../../descriptor_set.h",
        help="Path to descriptor_set.h for .comp output (default: ../../descriptor_set.h)",
    )
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print architecture details")

    args = parser.parse_args()
    convert(args.input, args.output, args.descriptor_include, args.verbose)


__all__ = ["convert", "main"]
