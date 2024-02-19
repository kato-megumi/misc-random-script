import argparse
import os
from os.path import join
import cv2
import numpy as np
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
import shutil
from misc import Filter, resize, ringing

DRY_RUN = False

MAX_TILE = 100 # unlimited
SCALE_FACTOR = 2
SCALE_INFO = [
    (1/3, 18),
    (1/2, 22),
    (2/3, 18),
]
HR_SCALE = Filter.CV2_LANCZOS

def cut(file, lr_folder, hr_folder, lr_cut_folder, hr_cut_folder, tile_size, scale_info):
    scale, threshold = scale_info
    img_lr = cv2.imread(join(lr_folder, file))
    img_hr = cv2.imread(join(hr_folder, file))
    lr_size = [int(img_lr.shape[1] * scale), int(img_lr.shape[0] * scale)]
    hr_size = [i * SCALE_FACTOR for i in lr_size]
    img_lr = ringing(img_lr, lr_size)
    img_hr = resize(img_hr, hr_size, interpolation=HR_SCALE)

    gray = cv2.cvtColor(img_lr, cv2.COLOR_BGR2GRAY)  # Converting BGR to gray
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
            cv2.imwrite(join(hr_cut_folder, f"{out_name}.png"), cutted_hr)
            cv2.imwrite(join(lr_cut_folder, f"{out_name}.png"), cutted_lr)
        
        count += 1
        if count >= MAX_TILE:
            # print("count over max: ", lr_folder, file)
            break

    return count

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", help="Path to low res")
    parser.add_argument("-g", help="Path to ground truth")
    parser.add_argument("-s", help="Tile size", type=int, default=192)
    parser.add_argument("-o", help="Path to output", default="Output")
    args = parser.parse_args()
    lr_list = args.l.split(",")
    hr_list = args.g.split(",")
    if len(hr_list) == 0:
        hr_list = lr_list.copy()
    out_path = args.o
    assert len(lr_list) == len(hr_list)
    assert args.s % 8 == 0
    tile_size = args.s
    
    if os.path.exists(out_path):
        shutil.rmtree(out_path)
    os.makedirs(out_path, exist_ok=True)
    os.makedirs(f"{out_path}/hr", exist_ok=True)
    os.makedirs(f"{out_path}/lr", exist_ok=True)
    hr_cut_folder = os.path.abspath(f"{out_path}/hr")
    lr_cut_folder = os.path.abspath(f"{out_path}/lr")
    
    with ProcessPoolExecutor(max_workers=17) as executor:
        for i in range(len(lr_list)):
            lr_folder = os.path.abspath(lr_list[i])
            hr_folder = os.path.abspath(hr_list[i])
            
            for scale in SCALE_INFO:
                for root, dirs, files in os.walk(lr_folder):
                    results = [executor.submit(cut, file, lr_folder, hr_folder, lr_cut_folder, hr_cut_folder, tile_size, scale) for file in files]
                    results = [future.result() for future in as_completed(results)]
                    print(scale, sum(results))
                    
        executor.shutdown(wait=True)