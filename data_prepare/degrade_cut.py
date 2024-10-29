
import sys
import shutil
import yaml
import os
import cv2
import os
from os.path import join
import numpy as np
import uuid
from pathlib import Path
from PIL import Image
from hashlib import sha256
from concurrent.futures import ProcessPoolExecutor, as_completed
import shutil
from misc import resize, ringing, FilterDict, Filter
from time import time

DRY_RUN = False
MAX_TILE = 100 # unlimited


def parse_yaml(file_path):
    with open(file_path, 'r') as file:
        data = yaml.safe_load(file)
    return data

def cut(file, config):
    threshold = config["threshold"]
    scale = config["scale"]
    tile_size = config["tile_size"]
    action_hr = config["action_hr"]
    action_lr = config["action_lr"]
    lr_folder = config["lr_folder"]
    hr_folder = config["hr_folder"]
    output_folder = config["output_folder"]
    repeat = config["repeat"]

    img_lr = cv2.imdecode(np.fromfile(join(lr_folder, file), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    img_lrs = []
    img_hr = cv2.imdecode(np.fromfile(join(hr_folder, file), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    original_size = img_lr.shape[:2][::-1]
    lr_size = original_size
    hr_shift_matrix = None
    
    for _ in range(repeat):
        for actions in action_lr:
            action, property = next(iter(actions.items()))
            if action in FilterDict:
                factor = eval(str(property))
                lr_size = [int(i*factor) for i in original_size]
                img_lr = resize(img_lr, lr_size, interpolation=FilterDict[action])
            elif action == "ringing":
                prop = []
                for p in property:
                    if isinstance(p, list):
                        prop.append(np.random.uniform(p[0],p[1]))
                    else:
                        prop.append(p)
                img_lr = ringing(img_lr, *prop)
                    
            elif action == "shift":
                shift_matrix = np.float32([[1, 0, property[0]], [0, 1, property[1]]])
                hr_shift_matrix = np.float32([[1, 0, property[0]*scale], [0, 1, property[1]*scale]])
                img_lr = cv2.warpAffine(img_lr, shift_matrix, (img_lr.shape[1], img_lr.shape[0]), flags=cv2.INTER_LINEAR)
        img_lrs.append(img_lr)
    
    lr_good_img = resize(img_hr, lr_size, interpolation=Filter.CV2_LANCZOS)
    hr_size = [i * scale for i in lr_size]
    if hr_size != list(img_hr.shape[:2][::-1]):
        img_hr = resize(img_hr, hr_size, interpolation=FilterDict[action_hr])
    if hr_shift_matrix is not None:
        img_hr = cv2.warpAffine(img_hr, hr_shift_matrix, (img_hr.shape[1], img_hr.shape[0]), flags=cv2.INTER_LINEAR)

    gray = cv2.cvtColor(lr_good_img, cv2.COLOR_BGR2GRAY)  # Converting BGR to gray
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    out = np.abs(laplacian)
    count = 0
    while True:
        convolved = cv2.filter2D(
            out,
            -1,
            np.ones((tile_size, tile_size), dtype=np.float64),
            anchor=(0, 0),
            borderType=cv2.BORDER_CONSTANT,
        )
        
        ##### Type 1 - choose best
        # if (average := np.max(convolved) / (tile_size**2)) < threshold:
        #     print((f"{lr_folder} {base} {count+1}"))
        #     break
        # y, x = np.unravel_index(np.argmax(convolved), convolved.shape)

        ##### Type 2 - choose first
        indices = np.where(convolved > (threshold * (tile_size**2)))
        if len(indices[0]) == 0:
            # print((f"{lr_folder} {base} {count+1}"))
            break
        y,x = (indices[0][0], indices[1][0])

        if x > lr_good_img.shape[1] - tile_size:
            x = lr_good_img.shape[1] - tile_size
        if y > lr_good_img.shape[0] - tile_size:
            y = lr_good_img.shape[0] - tile_size
        
        out[y : y + tile_size, x : x + tile_size] = 0
        
        if not DRY_RUN:
            cutted_hr = img_hr[
                y * 2 : y * 2 + tile_size * 2, x * 2 : x * 2 + tile_size * 2
            ]
            if (cutted_hr.shape != (tile_size*2, tile_size*2, 3) and cutted_hr.shape != (tile_size*2, tile_size*2, 4) ):
                print(cutted_hr.shape, tile_size)
                print(lr_folder, file)
                exit()
            
            for image_lr in img_lrs:
                out_name = uuid.uuid4().hex
                cv2.imwrite(join(output_folder, "lr", f"{out_name}.png"), image_lr[y : y + tile_size, x : x + tile_size])
                cv2.imwrite(join(output_folder, "hr", f"{out_name}.png"), cutted_hr)
                count += 1

        if count >= MAX_TILE*repeat:
            # print("count over max: ", lr_folder, file)
            break
    
    # if count >= 20:
    #     print(f"\thigh count: {file} {count}")
    # if count == 0:
    #     print((f"\t{file}: {np.max(convolved) / (tile_size**2)}"))
        
    return count

def hash_image(lr_img_path):
    with Image.open(lr_img_path) as hr_img:
        image_hash = sha256(hr_img.tobytes()).digest()
    return lr_img_path, image_hash

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python degrade_cut.py <config_path>")
        exit()
    
    config = parse_yaml(sys.argv[1])
        
    input_folders = config.get('input_folder', [])
    output_folder = config.get('output_folder', '')
    scale = config.get('scale', 1)
    tile_size = config.get('title_size', 192)
    degrade = config.get('degrade', [])
    default_threshold = config.get('default_threshold', 18)
    default_lr = config.get('default_lr', [0])
    default_hr = config.get('default_hr', [1])
    default_action_hr = config.get('default_action_hr', "CV2_LANCZOS")
        
    if os.path.exists(output_folder):
        shutil.rmtree(output_folder)
    os.makedirs(output_folder, exist_ok=True)
    os.makedirs(f"{output_folder}/hr", exist_ok=True)
    os.makedirs(f"{output_folder}/lr", exist_ok=True)
    
    with ProcessPoolExecutor(max_workers=17) as executor:
        for index, item in enumerate(degrade):
            lr_folders = [input_folders[i] for i in (item['lr'] if 'lr' in item else default_lr)]
            hr_folders = [input_folders[i] for i in (item['hr'] if 'hr' in item else default_hr)]
            thresholds = item['threshold'] if 'threshold' in item else default_threshold
            if isinstance(thresholds, int):
                thresholds = [thresholds]*len(lr_folders)
            for lr_folder, hr_folder, threshold in zip(lr_folders, hr_folders, thresholds):
                for root, dirs, files in os.walk(lr_folder):
                    config = {
                      "threshold": threshold,
                      "scale": scale,
                      "tile_size": tile_size,
                      "action_hr": item["action_hr"] if "action_hr" in item else default_action_hr,
                      "action_lr": item["action_lr"],
                      "lr_folder": lr_folder,
                      "hr_folder": hr_folder,
                      "output_folder": output_folder,
                      "repeat": item["repeat"] if "repeat" in item else 1}
                    results = [executor.submit(cut, file, config) for file in files]
                    results = [future.result() for future in as_completed(results)]
                    print(item["action_lr"], threshold, sum(results))
                    
        executor.shutdown(wait=True)
    
    start = time()
    counter = 0
    lr_path = Path(f"{output_folder}/lr")
    hr_path = Path(f"{output_folder}/hr")
    hashed_files = {}
    unique_hash = set()
    
    with ProcessPoolExecutor() as executor:
        futures = [executor.submit(hash_image, lr_img_path) for lr_img_path in sorted(lr_path.iterdir()) if lr_img_path.suffix in (".png", ".jpg", ".jpeg", ".webp")]
        for future in as_completed(futures):
            lr_img_path, image_hash = future.result()
            hashed_files[lr_img_path] = image_hash
        executor.shutdown(wait=True)
        
    for lr_img_path, image_hash in hashed_files.items():
        if image_hash not in unique_hash:
            unique_hash.add(image_hash)
        else:
            hr_img_path = hr_path / lr_img_path.name
            hr_img_path.unlink()
            lr_img_path.unlink()
            counter += 1
            # print(f"Deleted duplicate image {lr_img_path.name}. Matching file: {prev_file.name}")
    print(f"Deleted {counter} duplicate images in {time()-start} seconds")


