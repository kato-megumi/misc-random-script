import argparse
import logging
import shutil
from pathlib import Path
from hashlib import sha256
import imagehash
from thefuzz import fuzz

from PIL import Image


# Set up logging
logging.basicConfig(level=logging.INFO)

# Prompt the user for the file paths and the alignment mode
parser = argparse.ArgumentParser()
parser.add_argument("--hr", type=str, help="Path to the HR (ground-truth) folder of images")
parser.add_argument("--lr", type=str, help="Path to the LR (low-res) folder of images")
parser.add_argument("folder", type=str, help="Path to the folder that have HR and LR folders")
parser.add_argument("--exact", action="store_true", required=False, default=False, help="Check using exact match")
parser.add_argument("--delete", type=bool, required=False, default=False, help="Delete duplicates instead of moving them to a temporary directory")

# Parse arguments
args = parser.parse_args()

if args.folder:
    HR_PATH = Path(args.folder) / "hr"
    LR_PATH = Path(args.folder) / "lr"
elif args.lr and args.hr:
    HR_PATH = Path(args.hr)
    LR_PATH = Path(args.lr)
else:
    parser.error("Either --lr and --hr or folder must be provided")



if not HR_PATH.exists():
    logging.error(f"The `--hr` path specified does not exist: {HR_PATH}")
if HR_PATH.is_file():
    logging.error(f"The `--hr` path specified is a file path, not a directory: {HR_PATH}")

if not LR_PATH.exists():
    logging.error(f"The `--lr` path specified does not exist: {HR_PATH}")
if LR_PATH.is_file():
    logging.error(f"The `--lr` path specified is a file path, not a directory: {HR_PATH}")

HR_MOVED_PATH = HR_PATH.parent / f"{HR_PATH.name}_dupes"
LR_MOVED_PATH = LR_PATH.parent / f"{LR_PATH.name}_dupes"

if not args.delete:
    HR_MOVED_PATH.mkdir(parents=True, exist_ok=True)
    LR_MOVED_PATH.mkdir(parents=True, exist_ok=True)

# ====

hashed_files = {}
if args.exact:
    hash_types = [lambda x: sha256(x.tobytes()).digest()]
else:
    # hash_types = [imagehash.phash, imagehash.average_hash, imagehash.colorhash, imagehash.dhash]
    hash_types = [imagehash.phash, imagehash.average_hash, imagehash.dhash]

for hash_type in hash_types:
    print("Hash type: {0}".format(hash_type))
    for hr_img_path in sorted(HR_PATH.iterdir(), key=lambda x: x.stat().st_size, reverse=True):
        if hr_img_path.suffix not in (".png", ".jpg", ".jpeg"):
            continue
        with Image.open(hr_img_path) as hr_img:
            image_hash = hash_type(hr_img)
        for prev_file, prev_hash in hashed_files.items():
            if prev_hash == image_hash:
                lr_img_path = LR_PATH / hr_img_path.name
                if args.delete:
                    hr_img_path.unlink()
                    lr_img_path.unlink()
                    op = "Deleted"
                else:
                    shutil.move(hr_img_path, HR_MOVED_PATH / hr_img_path.name)
                    shutil.move(lr_img_path, LR_MOVED_PATH / hr_img_path.name)
                    op = "Moved"
                logging.info(f"{op} duplicate image {hr_img_path.name}. Matching file: {prev_file.name}")
                if (ratio := fuzz.ratio(hr_img_path.stem, prev_file.stem)) < 80:
                    logging.error(f"^^^^^^^^^ {ratio} ^^^^^^^^^")
                break
        else:
            hashed_files[hr_img_path] = image_hash

logging.info("Done!")
