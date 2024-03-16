import os
import shutil
import sys

if __name__ == '__main__':
    if len(sys.argv) != 3:
        exit()
    folder1 = sys.argv[1]
    folder2 = sys.argv[2]

# remove image in folder2 if it isnt in folder1
list1 = os.listdir(folder1)
for name in os.listdir(folder2):
    if name not in list1:
        print(f"Missing {name} in {folder1}")
        os.remove(os.path.join(folder2, name))

# remove image in folder1 if it isnt in folder2
list2 = os.listdir(folder2)
for name in os.listdir(folder1):
    if name not in list2:
        print(f"Missing {name} in {folder2}")
        os.remove(os.path.join(folder1, name))