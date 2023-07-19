# clean up manga download from https://dlraw.to/
import os
import argparse
from PIL import Image

def trim_image(image, target_color):
    # Create a mask by comparing pixel colors with the desired color
    mask = image.point(lambda p: p != target_color and 255)
    
    w, h = mask.size
    halfmark = mask.crop((0,0,w,int(h/2)))
    w1,h1,w2,h2 = halfmark.getbbox()
    trimmed_bbox = (w1,h1,w2,h)
    
    # # Find the bounding box of the non-desired color area
    # trimmed_bbox = mask.getbbox()

    # Crop the image using the trimmed bounding box
    trimmed_image = image.crop(trimmed_bbox)
    return trimmed_image

def cut_or_copy_images(input_folder, output_folder):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    for filename in os.listdir(input_folder):
        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, filename)

        with Image.open(input_path) as image:
            
            trimmed_image = trim_image(image, 0x34)

            width, height = trimmed_image.size

            if width > height:
                half_width = width // 2
                left_half = trimmed_image.crop((0, 0, half_width, height))
                right_half = trimmed_image.crop((half_width, 0, width, height))
                
                output_left = os.path.splitext(filename)[0] + "_2" + os.path.splitext(filename)[1]
                output_right = os.path.splitext(filename)[0] + "_1" + os.path.splitext(filename)[1]

                left_half.save(os.path.join(output_folder, output_left))
                right_half.save(os.path.join(output_folder, output_right))
            else:
                trimmed_image.save(output_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_folder", help="Path to the input folder")
    parser.add_argument("output_folder", help="Path to the output folder")
    args = parser.parse_args()

    cut_or_copy_images(args.input_folder, args.output_folder)