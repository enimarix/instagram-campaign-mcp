"""Small PS2-sized textures, drawn procedurally (no third-party art). Run once: python engine/make_assets.py"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "assets"
OUT.mkdir(exist_ok=True)
random.seed(7)


def noise(size, base, spread, specks=None):
    img = Image.new("RGB", size)
    for y in range(size[1]):
        for x in range(size[0]):
            k = random.randint(-spread, spread)
            img.putpixel((x, y), tuple(max(0, min(255, c + k)) for c in base))
    if specks:
        d = ImageDraw.Draw(img)
        col, n = specks
        for _ in range(n):
            d.point((random.randrange(size[0]), random.randrange(size[1])), fill=col)
    return img


# damask wallpaper: 64x64 tile (= 0.5 m), beige with a muted, mirrored floral motif
W = 64
wp = Image.new("RGB", (W, W), (178, 154, 116))
dark, mid = (128, 100, 72), (150, 124, 92)
half = Image.new("RGBA", (W // 2, W), (0, 0, 0, 0))
h = ImageDraw.Draw(half)
h.ellipse([20, 8, 34, 30], outline=dark, width=2)           # big petal
h.ellipse([24, 14, 34, 26], fill=mid)
h.arc([8, 26, 36, 54], 200, 340, fill=dark, width=2)        # scroll
h.ellipse([26, 40, 34, 48], fill=dark)                      # bud
h.line([(31, 30), (31, 40)], fill=dark, width=2)            # stem
h.polygon([(31, 52), (24, 60), (31, 64)], fill=mid)         # leaf
for y0 in (0, W // 2):                                      # small accents between motifs
    h.point([(4, y0 + 4), (5, y0 + 5), (3, y0 + 5)], fill=mid)
wp.paste(half, (0, 0), half)
flip = half.transpose(Image.FLIP_LEFT_RIGHT)
wp.paste(flip, (W // 2, 0), flip)
wp.save(OUT / "wallpaper.png")

# billboard tree cards (PS2 foliage): 64x96 RGBA autumn crowns, three variants
palettes = [[(122, 70, 28), (156, 92, 30), (96, 58, 26), (172, 118, 44)],
            [(88, 70, 34), (118, 92, 40), (70, 54, 30), (140, 108, 52)],
            [(140, 58, 26), (170, 82, 34), (110, 46, 24), (190, 120, 50)]]
for i, pal in enumerate(palettes):
    img = Image.new("RGBA", (64, 96), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([29, 60, 34, 95], fill=(50, 36, 26, 255))                 # trunk
    for _ in range(160):                                                   # leaf clumps
        a, r = random.uniform(0, 2 * math.pi), random.uniform(0, 1) ** 0.6
        x, y = 32 + math.cos(a) * r * 28, 38 + math.sin(a) * r * 34
        s = random.randint(2, 5)
        d.ellipse([x - s, y - s, x + s, y + s], fill=(*random.choice(pal), 255))
    img.save(OUT / f"tree{i}.png")

# food and props
noise((32, 32), (176, 96, 34), 26, ((226, 168, 92), 40)).save(OUT / "roast.png")        # glazed skin
noise((32, 32), (232, 218, 172), 14, ((205, 190, 140), 60)).save(OUT / "mash.png")
noise((16, 16), (128, 12, 24), 22, ((190, 40, 60), 20)).save(OUT / "cranberry.png")
noise((16, 16), (196, 132, 62), 18, ((232, 186, 110), 12)).save(OUT / "bread.png")

# wall art: 24x18 pixel landscape painting
art = Image.new("RGB", (24, 18), (120, 150, 170))
d = ImageDraw.Draw(art)
d.rectangle([0, 10, 23, 17], fill=(90, 110, 60))
d.polygon([(2, 10), (8, 3), (14, 10)], fill=(110, 105, 120))
d.polygon([(10, 10), (16, 5), (22, 10)], fill=(95, 90, 110))
d.ellipse([17, 2, 20, 5], fill=(240, 220, 160))
art.save(OUT / "art.png")
print("assets ->", OUT)
