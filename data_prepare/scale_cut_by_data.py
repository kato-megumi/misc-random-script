import argparse
import os
from os.path import join
import cv2
import numpy as np
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
import shutil
from misc import Filter, resize

DRY_RUN = False

MAX_TILE = 100 # unlimited

# SCALE = [
    # (40/80, Filter.LANCZOS, 18),    # 282
    # (40/80, Filter.MITCHELL, 18),   # 154
    # (40/80, Filter.BSPLINE, 18),    # 48
    # (40/80, Filter.CATROM, 18),     # 220
    # (40/80, Filter.CV2_LANCZOS, 18),  # 397
    # (40/80, Filter.CV2_CUBIC, 18),     # 392
    # (40/80, Filter.CV2_LINEAR, 18),    # 261
    # (50/80, Filter.CV2_LANCZOS, 20),  # 473
    # (50/80, Filter.CV2_CUBIC, 20),     # 447
    # (50/80, Filter.CV2_LINEAR, 18),    # 379
    # (60/80, Filter.CV2_LANCZOS, 22),  # 476
    # (60/80, Filter.CV2_CUBIC, 22),     # 435
    # (60/80, Filter.CV2_LINEAR, 18),    # 394
    # (70/80, Filter.CV2_LANCZOS, 22),  # 476
    # (70/80, Filter.CV2_CUBIC, 22),     # 436
    # (70/80, Filter.CV2_LINEAR, 18),    # 382
    # (80/80, Filter.CV2_NEAREST, 18),   # 694
    # (96/80, Filter.CV2_LANCZOS, 20),  # 467
    # (96/80, Filter.CV2_CUBIC, 20),     # 382
    # (96/80, Filter.CV2_LINEAR, 18),    # 
# ]
# SCALE = [(96/80, Filter.CV2_LANCZOS, 20),]
# SCALE = [(96/80, Filter.CV2_LINEAR, 12),]
# HR_SCALE = Filter.CV2_LANCZOS

SCALE = [
    (40/80, Filter.LANCZOS, 18),    # 282
    (60/80, Filter.LANCZOS, 20),    # 47
    (80/80, Filter.NEAREST, 18),    # 694
]
HR_SCALE = Filter.CV2_LANCZOS

def cut(file, lr_folder, hr_folder, lr_cut_folder, hr_cut_folder, tile_size, scale_list):
    scale, inter, threshold = scale_list
    base, ext = os.path.splitext(file)
    img_lr = cv2.imread(join(lr_folder, file))
    img_hr = cv2.imread(join(hr_folder, file))
    lr_size = [int(img_lr.shape[1] * scale), int(img_lr.shape[0] * scale)]
    hr_size = [i * 2 for i in lr_size]
    if scale != 1:
        img_lr = resize(img_lr, lr_size, interpolation=inter)
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
            
            for scale in SCALE:
                for root, dirs, files in os.walk(lr_folder):
                    results = [executor.submit(cut, file, lr_folder, hr_folder, lr_cut_folder, hr_cut_folder, tile_size, scale) for file in files]
                    results = [future.result() for future in as_completed(results)]
                    print(scale, sum(results))
                    
        executor.shutdown(wait=True)