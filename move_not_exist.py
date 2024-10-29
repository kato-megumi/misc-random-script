import os
import shutil
import argparse

def get_files_in_folder(folder):
    """Get a set of files in the given folder."""
    return set(os.listdir(folder))

def move_or_delete_unique_files(folder1, folder2, target_folder=None):
    """Move or delete files that are unique to folder1 or folder2."""
    files_folder1 = get_files_in_folder(folder1)
    files_folder2 = get_files_in_folder(folder2)

    # Find files that are unique to each folder
    unique_files = files_folder1.symmetric_difference(files_folder2)

    if target_folder:
        # Create the target folder if it doesn't exist
        os.makedirs(target_folder, exist_ok=True)

        # Move unique files from both folders to the target folder
        for file in unique_files:
            source_path = os.path.join(folder1, file)
            if os.path.exists(source_path):
                shutil.move(source_path, os.path.join(target_folder, file))
            else:
                source_path = os.path.join(folder2, file)
                shutil.move(source_path, os.path.join(target_folder, file))
    else:
        # Delete unique files from both folders
        for file in unique_files:
            source_path = os.path.join(folder1, file)
            if os.path.exists(source_path):
                os.remove(source_path)
            else:
                source_path = os.path.join(folder2, file)
                os.remove(source_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Compare two folders and move or delete unique files.')
    parser.add_argument('folder1', type=str, help='Path to the first folder')
    parser.add_argument('folder2', type=str, nargs='?', help='Path to the second folder')
    parser.add_argument('target_folder', type=str, nargs='?', help='Path to the target folder for unique files (if not provided, unique files will be deleted)')

    args = parser.parse_args()
    
    if not args.folder2:
        move_or_delete_unique_files(args.folder1 + "/hr", args.folder1 + "/lr", args.folder1 + "/move")
    else:
        move_or_delete_unique_files(args.folder1, args.folder2, args.target_folder)
