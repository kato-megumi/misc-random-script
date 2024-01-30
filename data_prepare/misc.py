from PIL import Image
import colorsys
import random

def blend(*name_list, crop=False):
    blend_image = Image.open(name_list[0])
    for name in name_list:
        img = Image.open(name)
        # blend_image.paste(img, (0, 0), img)
        blend_image = Image.alpha_composite(blend_image, img)
    if crop:
        blend_image = blend_image.crop(blend_image.getbbox())
    result_image = Image.new(mode="RGBA", size=blend_image.size, color="gray")
    result_image.paste(blend_image, (0, 0), blend_image)
    return result_image


def random_hsv_color():
    hue = random.random()
    saturation = random.uniform(0.5, 0.75)  
    brightness = random.uniform(0.5, 1.0)  
    # Convert HSV to RGB
    rgb_color = colorsys.hsv_to_rgb(hue, saturation, brightness)
    # Scale the RGB values to the range [0, 255]
    scaled_rgb = [int(val * 255) for val in rgb_color]
    # Return the color in RGB format
    return tuple(scaled_rgb)

def random_color():
    return (random.randrange(255), random.randrange(255), random.randrange(255))
