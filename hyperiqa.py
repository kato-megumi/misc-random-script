import shutil
import os
import concurrent.futures
import torch
import pyiqa
from tqdm import tqdm
import cv2

threshold = 0.7

input_dir = 'E:\\VNCG\\RIDDLEJOKER'
output_dir = 'R:\\hyperiqa\\'


device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
iqa_metric = pyiqa.create_metric('hyperiqa', device=device)

def process_image(filename):
    filepath = os.path.join(input_dir, filename)
    image = cv2.imread(filepath)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image = torch.from_numpy(image).unsqueeze(0).permute(0,3,1,2)/255
    score = iqa_metric(image)
    
    # if score >= threshold:
    #     output_filepath = os.path.join(output_dir, filename)
    #     shutil.copy(filepath, output_filepath)
    
    new_filename = f"{int(score*1000)}_{filename}"
    output_filepath = os.path.join(output_dir, new_filename)
    shutil.copy(filepath, output_filepath)

# with concurrent.futures.ThreadPoolExecutor(4) as executor:
#     future_to_filename = {executor.submit(process_image, filename): filename for filename in os.listdir(input_dir)}
#     for future in tqdm(concurrent.futures.as_completed(future_to_filename), total=len(future_to_filename), desc='Processing Images'):
#         try:
#             filename = future_to_filename[future]
#             result = future.result()
#         except Exception as e:
#             print(f'{filename} generated an exception: {e}')
            
for filename in tqdm(os.listdir(input_dir)):
    process_image(filename)