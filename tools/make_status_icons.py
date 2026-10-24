"""Recrée les quatre icônes d'état en PNG avec transparence réelle."""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


OUTPUT = Path(__file__).resolve().parent.parent / "status_icons"
SIZE = 1024
SCALE = 4


def polygon_mask(points, *, width=0, joint="curve"):
    mask = Image.new("L", (SIZE * SCALE, SIZE * SCALE), 0)
    draw = ImageDraw.Draw(mask)
    scaled = [(round(x * SCALE), round(y * SCALE)) for x, y in points]
    if width:
        draw.line(scaled, fill=255, width=width * SCALE, joint=joint)
        radius = width * SCALE // 2
        for x, y in (scaled[0], scaled[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    else:
        draw.polygon(scaled, fill=255)
    return mask.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def make_icon(name, color, glyph, *, cutout=False, circle_alpha=255):
    canvas = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    margin = 102 * SCALE
    draw.ellipse((margin, margin, SIZE * SCALE - margin, SIZE * SCALE - margin), fill=color)
    circle_mask = canvas.getchannel("A").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (*color, 0))
    circle_alpha_mask = circle_mask
    if circle_alpha != 255:
        circle_alpha_mask = circle_mask.point(lambda value: value * circle_alpha // 255)
    canvas.putalpha(circle_alpha_mask)

    if glyph == "check":
        points = [(300, 514), (439, 661), (712, 354)]
        stroke_width = 112
    elif glyph == "minus":
        points = [(320, 512), (704, 512)]
        stroke_width = 112
    else:
        points = [(326, 328), (698, 696)]
        stroke_width = 112
    glyph_mask = polygon_mask(points, width=stroke_width)
    if glyph == "x":
        second = polygon_mask([(698, 328), (326, 696)], width=stroke_width)
        glyph_mask = ImageChops.lighter(glyph_mask, second)

    if cutout:
        alpha = canvas.getchannel("A")
        alpha.paste(0, mask=glyph_mask)
        canvas.putalpha(alpha)
    else:
        white = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 0))
        white.putalpha(glyph_mask)
        canvas.alpha_composite(white)

    canvas.save(OUTPUT / name, format="PNG", optimize=True)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    make_icon("01_vert_coche_opaque.png", (0, 255, 0), "check")
    make_icon("02_vert_coche_transparent.png", (0, 255, 0), "check", cutout=True)
    make_icon("03_rouge_croix_transparente.png", (255, 0, 0), "x", cutout=True)
    make_icon("04_rouge_croix_opaque.png", (255, 0, 0), "x")
    make_icon("05_gris_moins_transparent.png", (128, 128, 128), "minus",
              cutout=True, circle_alpha=128)
    make_icon("06_gris_moins_blanc.png", (128, 128, 128), "minus", circle_alpha=128)


if __name__ == "__main__":
    main()
