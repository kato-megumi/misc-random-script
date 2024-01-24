from PIL import Image

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