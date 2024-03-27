import argparse
import logging
import shutil
from pathlib import Path
from hashlib import sha256
import imagehash 
import sys

from PIL import Image


# Set up logging
logging.basicConfig(level=logging.INFO)



parser = argparse.ArgumentParser()
parser.add_argument("input", help="Path to the input folder")
parser.add_argument("--exact", action="store_true", required=False, default=False, help="Check using exact match")
parser.add_argument("--delete", action="store_true", required=False, default=False, help="Delete duplicates instead of moving them to a temporary directory")
args = parser.parse_args()

IMG_PATH = Path(args.input)
MOVED_PATH = IMG_PATH.parent / f"{IMG_PATH.name}_dupes"
if not args.delete:
    MOVED_PATH.mkdir(parents=True, exist_ok=True)

# ====
if not IMG_PATH.exists():
    logging.error(f"The path specified does not exist: {IMG_PATH}")
if IMG_PATH.is_file():
    logging.error(f"The path specified is a file path, not a directory: {IMG_PATH}")
# ====

hashed_files = {}
if args.exact:
    hash_types = [lambda x: sha256(x.tobytes()).digest()]
else:
    # hash_types = [imagehash.phash, imagehash.average_hash, imagehash.colorhash, imagehash.dhash]
    hash_types = [imagehash.phash, imagehash.average_hash, imagehash.dhash]

for hash_type in hash_types:
    print("Hash type: {0}".format(hash_type))
    for img_path in sorted(IMG_PATH.iterdir(), key=lambda x: x.stat().st_size, reverse=True):
        if img_path.suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        with Image.open(img_path) as hr_img:
            image_hash = hash_type(hr_img)
        for prev_file, prev_hash in hashed_files.items():
            if prev_hash == image_hash:
                if args.delete:
                    img_path.unlink()
                else:
                    shutil.move(img_path, MOVED_PATH / img_path.name)
                logging.info(f"Duplicate image {img_path.name}. Matching file: {prev_file.name}")
                break
        else:
            hashed_files[img_path] = image_hash

logging.info("Done!")
