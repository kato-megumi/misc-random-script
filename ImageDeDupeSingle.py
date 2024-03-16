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
args = parser.parse_args()

HR_PATH = Path(args.input)

# ====
if not HR_PATH.exists():
    logging.error(f"The `--hr` path specified does not exist: {HR_PATH}")
if HR_PATH.is_file():
    logging.error(f"The `--hr` path specified is a file path, not a directory: {HR_PATH}")

HR_MOVED_PATH = HR_PATH.parent / f"{HR_PATH.name}_dupes"

# ====

hashed_files = {}
if args.exact:
    hash_types = [lambda x: sha256(x.tobytes()).digest()]
else:
    # hash_types = [imagehash.phash, imagehash.average_hash, imagehash.colorhash, imagehash.dhash]
    hash_types = [imagehash.phash, imagehash.average_hash, imagehash.dhash]

for hash_type in hash_types:
    print("Hash type: {0}".format(hash_type))
    for hr_img_path in sorted(HR_PATH.iterdir()):
        if hr_img_path.suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        with Image.open(hr_img_path) as hr_img:
            image_hash = hash_type(hr_img)
        for prev_file, prev_hash in hashed_files.items():
            if prev_hash == image_hash:
                hr_img_path.unlink()
                logging.info(f"Deleted duplicate image {hr_img_path.name}. Matching file: {prev_file.name}")
                break
        else:
            hashed_files[hr_img_path] = image_hash

logging.info("Done!")
