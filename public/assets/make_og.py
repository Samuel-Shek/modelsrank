#!/usr/bin/env python3
"""Recreate og.png with Pillow; optional font paths allow use on other systems."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--font', default='/System/Library/Fonts/Supplemental/Arial.ttf')
parser.add_argument('--bold', default='/System/Library/Fonts/Supplemental/Arial Bold.ttf')
args = parser.parse_args()
scale = 3
im = Image.new('RGB', (1200 * scale, 630 * scale), '#0b1018')
draw = ImageDraw.Draw(im)

def line(points, color, width):
    draw.line([(x * scale, y * scale) for x, y in points], fill=color, width=width * scale, joint='curve')

def text(x, y, value, size, color, bold=False):
    font = ImageFont.truetype(args.bold if bold else args.font, size * scale)
    draw.text((x * scale, y * scale), value, font=font, fill=color, anchor='lt')

# The same two paths as the page's brand mark, scaled from its 28-unit viewBox.
line([(80 + x * 5, 70 + y * 5) for x, y in [(3,21),(10,7),(15,17),(19,9),(25,21)]], '#67d9d0', 10)
line([(95,195),(205,195)], '#67d9d0', 10)
text(250, 109, 'Models Rank', 64, '#eef3fa', True)
line([(80,245),(1120,245)], '#273445', 2)
text(80, 295, 'AI Model Rankings', 58, '#eef3fa', True)
text(83, 390, 'Intelligence · Cost · Speed', 34, '#67d9d0')
text(83, 530, 'modelsrank.org', 26, '#9cabbd')
im.resize((1200, 630), Image.Resampling.LANCZOS).save(Path(__file__).with_name('og.png'), optimize=True)
