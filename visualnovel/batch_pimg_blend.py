"""Batch decompile .pimg files with PsbDecompile.exe and composite layer images.

Current workflow per file <name>.pimg inside --input folder:
    1. Run PsbDecompile.exe <name>.pimg  -> produces <name>.json and asset folder <name>/.
    2. Parse <name>.json (expects 'layers' array with diff_id, layer_id, position, opacity, etc.).
    3. For each visible layer produce a composited PNG: <output_dir>/<name>/<name>_<layerName>.png
         - A per-stem subfolder is created; filenames keep the original stem as a prefix.

Image lookup rules:
    - Base image: <assets_dir>/<diff_id><ext>
    - Overlay image: <assets_dir>/<layer_id><ext>
    - assets_dir defaults to folder named after JSON (<input>/<name>/)
    - If <diff_id><ext> not found we fall back (see diff_id handling below).
    - If primary --ext is absent, we try common extensions: .png, .webp, .jpg, .jpeg, .bmp

diff_id handling:
    - diff_id present & file exists: use as new base and remember it (last_base).
    - diff_id present but file missing: warn and fall back to last_base or blank.
    - diff_id is None: reuse last_base; if none yet, start with a transparent canvas.

Canvas size:
    - Output canvas forced to JSON (width,height) if provided; else base / overlay size.
    - Smaller bases are pasted at top-left (no auto-centering).

Performance features:
    - In-memory caching of decoded images.
    - Reusable scratch canvases per diff_id (avoids repeated allocations & copies).
    - Optional parallel processing with --jobs (per .pimg file).

Usage (PowerShell example):
    python batch_pimg_blend.py --input pimg_dir --tool "~/Downloads/Ulysses-FreeMoteToolkit/PsbDecompile.exe" --out out_all --jobs 8

Flags:
    --force   Re-run decompile even if JSON exists.
    --ext     Primary image extension (default .png).
    --jobs    Parallel workers (0 auto, 1 sequential).

Requires: Pillow
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import concurrent.futures as _fut
from dataclasses import dataclass
from typing import Dict, Any, Optional, Sequence

try:
    from PIL import Image  # type: ignore
except ImportError:
    Image = None  # type: ignore


@dataclass
class Layer:
    name: str
    layer_id: int
    diff_id: Optional[int]
    left: int
    top: int
    width: int
    height: int
    opacity: int
    visible: bool

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Layer":
        return cls(
            name=d.get("name", f"layer_{d.get('layer_id')}") or f"layer_{d.get('layer_id')}",
            layer_id=int(d["layer_id"]),
            diff_id=int(d["diff_id"]) if "diff_id" in d else None,
            left=int(d.get("left", 0)),
            top=int(d.get("top", 0)),
            width=int(d.get("width", 0)),
            height=int(d.get("height", 0)),
            opacity=int(d.get("opacity", 255)),
            visible=bool(d.get("visible", 1)),
        )


def load_image(path: str):
    if Image is None:
        raise RuntimeError("Pillow not installed. pip install Pillow")
    try:
        return Image.open(path).convert("RGBA")
    except Exception as e:
        raise RuntimeError(f"Failed to open image {path}: {e}") from e


def apply_opacity(img: Image.Image, alpha: int) -> Image.Image:  # type: ignore
    if alpha >= 255:
        return img
    r, g, b, a = img.split()
    a = a.point(lambda v: v * alpha // 255)
    return Image.merge("RGBA", (r, g, b, a))


def blend_layer(base: Image.Image, overlay: Image.Image, layer: Layer) -> Image.Image:  # type: ignore
    """Blend overlay onto base with simple optimizations.

    Optimizations:
      - Skip cropping if sizes already match metadata.
      - Skip opacity processing if fully opaque.
      - Use alpha_composite when overlay covers full canvas at (0,0) for faster C-path.
    """
    ow, oh = overlay.size
    target_w = layer.width or ow
    target_h = layer.height or oh
    if (ow, oh) != (target_w, target_h):
        overlay = overlay.crop((0, 0, min(target_w, ow), min(target_h, oh)))
    if layer.opacity < 255:
        overlay = apply_opacity(overlay, layer.opacity)
    if layer.left == 0 and layer.top == 0 and overlay.size == base.size:
        # Full-canvas composite path
        return Image.alpha_composite(base, overlay)
    base.paste(overlay, (layer.left, layer.top), overlay)
    return base


COMMON_EXTS = [".png", ".webp", ".jpg", ".jpeg", ".bmp"]

def find_img(stem: str, assets_dir: str, primary_ext: str) -> Optional[str]:
    ext = primary_ext if primary_ext.startswith('.') else '.' + primary_ext
    tried = {ext.lower()}
    candidates = [f"{stem}{ext}"] + [f"{stem}{e}" for e in COMMON_EXTS if e.lower() not in tried]
    for name in candidates:
        p = os.path.join(assets_dir, name)
        if os.path.isfile(p):
            return p
    return None


def decompile(pimg_path: str, tool_path: str):
    cmd = [tool_path, pimg_path]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Decompile failed for {pimg_path}: {e.stderr.decode(errors='ignore')}") from e


def process_layout(json_path: str, out_root: str, ext: str) -> int:
    """Process a single layout JSON and export composited PNGs.

    Returns number of images produced.
    """
    stem = os.path.splitext(os.path.basename(json_path))[0]
    assets_dir = os.path.join(os.path.dirname(json_path), stem)
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    layers_raw = data.get('layers', [])
    layers = [Layer.from_dict(x) for x in layers_raw]
    # Per-stem subfolder
    out_dir = os.path.join(out_root, stem)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    canvas_w = int(data.get('width') or 0)
    canvas_h = int(data.get('height') or 0)
    produced = 0
    img_cache = {}            # path -> Image (decoded once)
    scratch_cache = {}        # diff_id / -1 -> reusable canvas of target size
    last_base_img = None      # last valid base Image (persist across diff_id=None layers)
    last_base_diff_id = None  # diff id for last_base_img
    for layer in layers:
        if not layer.visible:
            continue
        overlay_path = find_img(str(layer.layer_id), assets_dir, ext)
        if not overlay_path:
            print(f"[WARN] Missing overlay for layer_id {layer.layer_id} in {assets_dir}; skip {layer.name}")
            continue
        if overlay_path not in img_cache:
            img_cache[overlay_path] = load_image(overlay_path)
        overlay_img = img_cache[overlay_path]

        base_img = None
        effective_diff_id = layer.diff_id
        if layer.diff_id is not None:
            base_path = find_img(str(layer.diff_id), assets_dir, ext)
            if base_path:
                if base_path not in img_cache:
                    img_cache[base_path] = load_image(base_path)
                base_img = img_cache[base_path]
                last_base_img = base_img
                last_base_diff_id = layer.diff_id
            else:
                print(f"[WARN] Missing base diff_id {layer.diff_id}; using fallback for {layer.name}")

        if base_img is None:
            if last_base_img is not None:
                base_img = last_base_img
                effective_diff_id = last_base_diff_id
            else:
                # Create initial blank canvas (prefer global size)
                if canvas_w > 0 and canvas_h > 0:
                    base_img = Image.new('RGBA', (canvas_w, canvas_h), (0,0,0,0))
                else:
                    base_img = Image.new('RGBA', overlay_img.size, (0,0,0,0))
                effective_diff_id = -1
        try:
            # Prepare reusable scratch canvas for this diff_id
            key = effective_diff_id if effective_diff_id is not None else -1
            scratch = scratch_cache.get(key)
            target_size = (canvas_w, canvas_h) if (canvas_w > 0 and canvas_h > 0) else base_img.size
            if scratch is None or scratch.size != target_size:
                scratch = Image.new('RGBA', target_size, (0,0,0,0))
                scratch_cache[key] = scratch
            else:
                # Clear scratch
                scratch.paste((0,0,0,0), (0,0,scratch.size[0], scratch.size[1]))
            # Paste (top-left) base image
            scratch.paste(base_img, (0,0))
            comp = blend_layer(scratch, overlay_img, layer)
        except RuntimeError as e:
            print(f"[WARN] {e}; skip {layer.name}")
            continue
        out_name = f"{stem}_{layer.name}.png"
        comp.save(os.path.join(out_dir, out_name))
        print(f"[OK] {stem}/{out_name}")
        produced += 1
    return produced


def collect_pimg(folder: str) -> Sequence[str]:
    return [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith('.pimg')]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Batch decompile .pimg and blend layers")
    ap.add_argument('--input', required=True, help='Input directory containing *.pimg')
    ap.add_argument('--tool', default='~/Downloads/Ulysses-FreeMoteToolkit/PsbDecompile.exe', help='Path to PsbDecompile.exe (default: %(default)s)')
    ap.add_argument('--out', default='R:/out', help='Output directory for composited PNGs')
    ap.add_argument('--ext', default='.png', help='Primary source image extension (default: .png)')
    ap.add_argument('--force', action='store_true', help='Force re-decompile even if JSON exists')
    ap.add_argument('--jobs', type=int, default=0, help='Parallel workers (0=auto cores, 1=sequential)')
    return ap.parse_args(argv)


def _worker(pimg: str, tool: str, out_dir: str, ext: str, force: bool) -> tuple[str, int, int, str | None]:
    stem = os.path.splitext(os.path.basename(pimg))[0]
    json_path = os.path.join(os.path.dirname(pimg), f"{stem}.json")
    try:
        need_decompile = force or not os.path.isfile(json_path)
        if need_decompile:
            print(f"[RUN] {stem}: decompile")
            decompile(pimg, tool)
        else:
            print(f"[SKIP] {stem}: already decompiled")
        if not os.path.isfile(json_path):
            return stem, 0, 0, "json_missing"
        produced = process_layout(json_path, out_dir, ext)
        return stem, produced, 0, None
    except Exception as e:  # broad to avoid executor silent fail
        return stem, 0, 1, str(e)


def main():
    args = parse_args()
    tool = os.path.expanduser(args.tool)
    if not os.path.isfile(tool):
        print(f"[ERROR] Tool not found: {tool}")
        return 1
    pimg_files = collect_pimg(args.input)
    if not pimg_files:
        print("[INFO] No .pimg files found")
        return 0
    jobs = args.jobs
    if jobs <= 0:
        try:
            import multiprocessing as _mp
            jobs = max(1, _mp.cpu_count() - 1)
        except Exception:
            jobs = 4
    if jobs == 1:
        results = []
        for p in pimg_files:
            results.append(_worker(p, tool, args.out, args.ext, args.force))
    else:
        print(f"[INFO] Parallel workers: {jobs}")
        results = []
        with _fut.ThreadPoolExecutor(max_workers=jobs) as ex:
            fut_map = {ex.submit(_worker, p, tool, args.out, args.ext, args.force): p for p in pimg_files}
            for fut in _fut.as_completed(fut_map):
                res = fut.result()
                results.append(res)
    total_layers = sum(r[1] for r in results)
    failures = [r for r in results if r[3]]
    if failures:
        print("[SUMMARY] Failures:")
        for stem, _, _, err in failures:
            print(f"  - {stem}: {err}")
    print(f"[SUMMARY] Processed {len(results)} files; produced {total_layers} composited PNG(s); failures {len(failures)}")
    return 0 if not failures else 2


if __name__ == '__main__':
    raise SystemExit(main())
