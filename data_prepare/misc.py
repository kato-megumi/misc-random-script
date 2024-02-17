from PIL import Image
import colorsys
import random
from chainner_ext import resize as resize_chainner
from chainner_ext import ResizeFilter 
import cv2
import numpy as np
from enum import IntEnum

# About Chainner and cv2 interpolations
# When upscale: Lanczos4 = lanczos, Cubic = Catmull, and same name is similar
# When downscale everything is different, cv2 look better when downscale


class Filter(IntEnum):
    NEAREST = 0
    LINEAR = 2
    CATROM = 3
    LANCZOS = 1
    BOX = 4
    HERMITE = 5
    MITCHELL = 6
    BSPLINE = 7
    HAMMING = 8
    HANN = 9
    LAGRANGE = 10
    GAUSS = 11
    CV2_NEAREST = 12
    CV2_LANCZOS = 13
    CV2_LINEAR = 14
    CV2_AREA = 15
    CV2_CUBIC = 16

FILTER_MAP: dict[Filter, ResizeFilter] = {
    Filter.NEAREST: ResizeFilter.Nearest,
    Filter.BOX: ResizeFilter.Box,
    Filter.LINEAR: ResizeFilter.Linear,
    Filter.CATROM: ResizeFilter.CubicCatrom,
    Filter.LANCZOS: ResizeFilter.Lanczos,
    Filter.HERMITE: ResizeFilter.Hermite,
    Filter.MITCHELL: ResizeFilter.CubicMitchell,
    Filter.BSPLINE: ResizeFilter.CubicBSpline,
    Filter.HAMMING: ResizeFilter.Hamming,
    Filter.HANN: ResizeFilter.Hann,
    Filter.LAGRANGE: ResizeFilter.Lagrange,
    Filter.GAUSS: ResizeFilter.Gauss,
    Filter.CV2_CUBIC: cv2.INTER_CUBIC,
    Filter.CV2_LANCZOS: cv2.INTER_LANCZOS4,
    Filter.CV2_LINEAR: cv2.INTER_LINEAR,
    Filter.CV2_LINEAR: cv2.INTER_LINEAR,
    Filter.CV2_AREA: cv2.INTER_AREA,
    Filter.CV2_NEAREST: cv2.INTER_NEAREST,
}

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

def resize(image, size, interpolation):
    if interpolation < Filter.CV2_NEAREST:
        out = resize_chainner(image.astype(np.float32) / 255.0, tuple(size), FILTER_MAP[interpolation], False) * 255
    else:
        out = cv2.resize(image, size, interpolation=FILTER_MAP[interpolation])
    return out.astype(np.uint8)