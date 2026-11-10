#!/usr/bin/env python3
"""Recreate the brand icons with rsvg-convert and Pillow; run from any directory."""
import io
from pathlib import Path
import subprocess

from PIL import Image

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 28"><rect width="28" height="28" rx="6" fill="#0b1018"/><path d="M4 20 10 8l5 9 4-7 5 10" stroke="#67d9d0" stroke-width="2.4" fill="none" stroke-linejoin="round"/></svg>'
HERE = Path(__file__).resolve().parent


def render(size):
    png = subprocess.run(
        ['rsvg-convert', '--width', str(size * 4), '--height', str(size * 4)],
        input=SVG, stdout=subprocess.PIPE, check=True,
    ).stdout
    with Image.open(io.BytesIO(png)) as image:
        return image.convert('RGBA').resize((size, size), Image.Resampling.LANCZOS)


def opaque(image):
    # iOS applies its own corner mask; fill transparent corners with the brand
    # background so neither PNG depends on a browser/launcher background color.
    background = Image.new('RGB', image.size, '#0b1018')
    background.paste(image, mask=image.getchannel('A'))
    return background


def main():
    small, large = render(16), render(32)
    large.save(HERE / 'favicon.ico', sizes=[(16, 16), (32, 32)],
               append_images=[small], bitmap_format='bmp')
    opaque(large).save(HERE / 'favicon.png', optimize=True)
    opaque(render(180)).save(HERE / 'apple-touch-icon.png', optimize=True)


if __name__ == '__main__':
    main()
