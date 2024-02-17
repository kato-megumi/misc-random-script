import os
import sys
import random
from PIL import Image
import shutil
from concurrent.futures import ProcessPoolExecutor


def get_file(folder_paths):
    files_by_folder = {}
    
    for folder_path in folder_paths:
        if not os.path.exists(folder_path):
            print(f"Folder '{folder_path}' does not exist.")
            continue
        
        for file_name in os.listdir(folder_path):
            file_path = os.path.join(folder_path, file_name)
            
            if os.path.isfile(file_path):
                files_by_folder.setdefault(file_name, set()).add(folder_path)
    
    return [file_name for file_name, folders in files_by_folder.items() if len(folders) == len(folder_paths)]
    
def blend(file_name, output_folder, folder_list):
    color = tuple([random.randrange(255) for i in range(3)])
    for index, folder_path in enumerate(folder_list):
        os.makedirs(os.path.join(output_folder, str(index)), exist_ok=True)
        file_path = os.path.join(folder_path, file_name)
        output_file = os.path.join(output_folder, str(index), file_name)
        img = Image.open(file_path)
        base_img = Image.new(mode="RGB", size=(img.size[0]+4, img.size[1]+4), color=color)
        base_img.paste(img, [2,2], img)
        base_img.save(output_file)
    

if __name__ == "__main__":
    folder_list = sys.argv[2:]
    output_folder = sys.argv[1]
    
    if not folder_list:
        print("Please provide at least one folder path.")
        exit()
        
    list_file = get_file(folder_list)
    print(list_file)
    
    with ProcessPoolExecutor(max_workers=17) as executor:
        for file in list_file:
            results = executor.submit(blend, file, output_folder, folder_list)

        executor.shutdown(wait=True)
