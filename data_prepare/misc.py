from PIL import Image
import colorsys
import random
from chainner_ext import resize as resize_chainner
from chainner_ext import ResizeFilter 
import cv2
import numpy as np
from enum import IntEnum
import math

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

def fast_gaussian_blur(
    img: np.ndarray,
    sigma_x: float,
    sigma_y: float | None = None,
) -> np.ndarray:
    """
    Computes a channel-wise gaussian blur of the given image using a fast approximation.

    The maximum error of the approximation is guaranteed to be less than 0.1%.
    In addition to that, the error is guaranteed to be smoothly distributed across the image.
    There are no sudden spikes in error anywhere.

    Specifically, the method is implemented by downsampling the image, blurring the downsampled
    image, and then upsampling the blurred image. This is much faster than blurring the full image.
    Unfortunately, OpenCV's `resize` method has unfortunate artifacts when upscaling, so we
    apply a small gaussian blur to the image after upscaling to smooth out the artifacts. This
    single step almost doubles the runtime of the method, but it is still much faster than
    blurring the full image.
    """
    if sigma_y is None:
        sigma_y = sigma_x
    if sigma_x == 0 or sigma_y == 0:
        return img.copy()

    h, w, _ = get_h_w_c(img)

    def get_scale_factor(sigma: float) -> float:
        if sigma < 11:
            return 1
        if sigma < 15:
            return 1.25
        if sigma < 20:
            return 1.5
        if sigma < 25:
            return 2
        if sigma < 30:
            return 2.5
        if sigma < 50:
            return 3
        if sigma < 100:
            return 4
        if sigma < 200:
            return 6
        return 8

    def get_sizing(size: int, sigma: float, f: float) -> tuple[int, float, float]:
        """
        Return the size of the downsampled image, the sigma of the downsampled gaussian blur,
        and the sigma of the upscaled gaussian blur.
        """
        if f <= 1:
            # just use simple gaussian, the error is too large otherwise
            return size, 0, sigma

        size_down = math.ceil(size / f)
        f = size / size_down
        sigma_up = f
        sigma_down = math.sqrt(sigma**2 - sigma_up**2) / f
        return size_down, sigma_down, sigma_up

    # Handling different sigma values for x and y is difficult, so we take the easy way out
    # and just use the smaller one. There are potentially better ways of combining them, but
    # this is good enough for now.
    scale_factor = min(get_scale_factor(sigma_x), get_scale_factor(sigma_y))
    h_down, y_down_sigma, y_up_sigma = get_sizing(h, sigma_y, scale_factor)
    w_down, x_down_sigma, x_up_sigma = get_sizing(w, sigma_x, scale_factor)

    if h != h_down or w != w_down:
        # downsampled gaussian blur
        img = cv2.resize(img, (w_down, h_down), interpolation=cv2.INTER_AREA)
        img = cv2.GaussianBlur(
            img,
            (0, 0),
            sigmaX=x_down_sigma,
            sigmaY=y_down_sigma,
            borderType=cv2.BORDER_REFLECT,
        )
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR)

    if x_up_sigma != 0 or y_up_sigma != 0:
        # post blur to smooth out artifacts
        img = cv2.GaussianBlur(
            img,
            (0, 0),
            sigmaX=x_up_sigma,
            sigmaY=y_up_sigma,
            borderType=cv2.BORDER_REFLECT,
        )

    return img

def calculate_ssim(
    img1: np.ndarray,
    img2: np.ndarray,
) -> float:
    """Calculates mean localized Structural Similarity Index (SSIM)
    between two images."""

    c1 = 0.01**2
    c2 = 0.03**2

    kernel = cv2.getGaussianKernel(11, 1.5)
    window = np.outer(kernel, kernel.transpose())  # type: ignore

    mu1 = cv2.filter2D(img1, -1, window)[5:-5, 5:-5]
    mu2 = cv2.filter2D(img2, -1, window)[5:-5, 5:-5]
    mu1_sq = np.power(mu1, 2)
    mu2_sq = np.power(mu2, 2)
    mu1_mu2 = np.multiply(mu1, mu2)
    sigma1_sq = cv2.filter2D(img1**2, -1, window)[5:-5, 5:-5] - mu1_sq
    sigma2_sq = cv2.filter2D(img2**2, -1, window)[5:-5, 5:-5] - mu2_sq
    sigma12 = cv2.filter2D(img1 * img2, -1, window)[5:-5, 5:-5] - mu1_mu2

    ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / (
        (mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2)
    )

    return float(np.mean(ssim_map))

def get_h_w_c(image: np.ndarray) -> tuple[int, int, int]:
    """Returns the height, width, and number of channels."""
    h, w = image.shape[:2]
    c = 1 if image.ndim == 2 else image.shape[2]
    return h, w, c

def unsharp_mask_node(
    img: np.ndarray,
    radius: float,
    amount: float,
    threshold: float,
) -> np.ndarray:
    if radius == 0 or amount == 0:
        return img

    blurred = fast_gaussian_blur(img, radius)

    threshold /= 100
    if threshold == 0:
        img = cv2.addWeighted(img, amount + 1, blurred, -amount, 0)
    else:
        diff = img - blurred
        diff = np.sign(diff) * np.maximum(0, np.abs(diff) - threshold)
        img = img + diff * amount

    return img

def ringing(image, size: tuple):
    img = resize(image, size, interpolation = Filter.LANCZOS).astype(np.float32) / 255
    img = unsharp_mask_node(img, 3, 0.0929, 0.91) * 255
    return img.astype(np.uint8)
