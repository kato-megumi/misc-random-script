
import sys
import shutil
import yaml
import os
import cv2
import os
from os.path import join
import numpy as np
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
import shutil
from misc import resize, ringing, FilterDict, Filter

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

    img_lr = cv2.imread(join(lr_folder, file))
    img_hr = cv2.imread(join(hr_folder, file))
    original_size = img_lr.shape[:2][::-1]
    lr_size = original_size
    
    for actions in action_lr:
        action, property = next(iter(actions.items()))
        if action in FilterDict:
            factor = eval(str(property))
            lr_size = [int(i*factor) for i in original_size]
            img_lr = resize(img_lr, lr_size, interpolation=FilterDict[action])
        elif action == "ringing":
            img_lr = ringing(img_lr, *property)
    lr_good_img = resize(img_hr, lr_size, interpolation=Filter.CV2_LANCZOS)

    hr_size = [i * scale for i in lr_size]
    if hr_size != list(img_hr.shape[:2][::-1]):
        img_hr = resize(img_hr, hr_size, interpolation=FilterDict[action_hr])

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

        if x > img_lr.shape[1] - tile_size:
            x = img_lr.shape[1] - tile_size
        if y > img_lr.shape[0] - tile_size:
            y = img_lr.shape[0] - tile_size
        
        out[y : y + tile_size, x : x + tile_size] = 0
        
        if not DRY_RUN:
            cutted_hr = img_hr[
                y * 2 : y * 2 + tile_size * 2, x * 2 : x * 2 + tile_size * 2
            ]
            cutted_lr = img_lr[y : y + tile_size, x : x + tile_size]
            if (cutted_hr.shape != (tile_size*2, tile_size*2, 3) or cutted_hr.shape != (tile_size*2, tile_size*2, 3) ):
                print(lr_folder, file)
                exit()
            
            out_name = uuid.uuid4().hex
            cv2.imwrite(join(output_folder, "hr", f"{out_name}.png"), cutted_hr)
            cv2.imwrite(join(output_folder, "lr", f"{out_name}.png"), cutted_lr)
        
        count += 1
        if count >= MAX_TILE:
            # print("count over max: ", lr_folder, file)
            break
    
    # if count >= 20:
    #     print(f"\thigh count: {file} {count}")
    # if count == 0:
    #     print((f"\t{file}: {np.max(convolved) / (tile_size**2)}"))
        
    return count


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
            threshold = item['threshold'] if 'threshold' in item else default_threshold
            for lr_folder, hr_folder in zip(lr_folders, hr_folders):
                for root, dirs, files in os.walk(lr_folder):
                    config = {
                      "threshold": threshold,
                      "scale": scale,
                      "tile_size": tile_size,
                      "action_hr": item["action_hr"] if "action_hr" in item else default_action_hr,
                      "action_lr": item["action_lr"],
                      "lr_folder": lr_folder,
                      "hr_folder": hr_folder,
                      "output_folder": output_folder,}
                    results = [executor.submit(cut, file, config) for file in files]
                    results = [future.result() for future in as_completed(results)]
                    print(item["action_lr"], threshold, sum(results))
                    
        executor.shutdown(wait=True)
    

