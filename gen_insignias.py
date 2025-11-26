import os, math
from PIL import Image, ImageDraw, ImageFont

# Carpeta de salida dentro del proyecto Flask
OUT_DIR = os.path.join("static", "img", "insignias")
os.makedirs(OUT_DIR, exist_ok=True)

def create_hex_badge(filename, inner_color, border_color, icon_text):
    size = 600
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Centro y radios
    cx = cy = size // 2
    r_outer = 260
    r_inner = 220

    # Hexágono exterior
    pts_outer = [
        (
            cx + r_outer * math.cos(math.radians(60 * i - 30)),
            cy + r_outer * math.sin(math.radians(60 * i - 30)),
        )
        for i in range(6)
    ]
    draw.polygon(pts_outer, fill=border_color)

    # Hexágono interior
    pts_inner = [
        (
            cx + r_inner * math.cos(math.radians(60 * i - 30)),
            cy + r_inner * math.sin(math.radians(60 * i - 30)),
        )
        for i in range(6)
    ]

    # Degradado vertical
    top_color = tuple(min(255, c + 40) for c in inner_color)
    bottom_color = tuple(max(0, c - 40) for c in inner_color)

    min_y = min(y for _, y in pts_inner)
    max_y = max(y for _, y in pts_inner)

    for y in range(int(min_y), int(max_y) + 1):
        t = (y - min_y) / max(1, (max_y - min_y))
        r = int(top_color[0] * (1 - t) + bottom_color[0] * t)
        g = int(top_color[1] * (1 - t) + bottom_color[1] * t)
        b = int(top_color[2] * (1 - t) + bottom_color[2] * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    # Máscara para recortar el degradado al hexágono interior
    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.polygon(pts_inner, fill=255)
    img = Image.composite(img, img, mask)

    draw = ImageDraw.Draw(img)

    # Texto/icono principal
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 190)
    except:
        font = ImageFont.load_default()

    # En Pillow 10+ ya no existe textsize, usamos textbbox
    bbox = draw.textbbox((0, 0), icon_text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text((cx - w / 2, cy - h / 2 - 20), icon_text, font=font, fill=(255, 255, 255, 255))

    # Pequeña "Q" de QuestCash
    try:
        font_small = ImageFont.truetype("DejaVuSans-Bold.ttf", 60)
    except:
        font_small = ImageFont.load_default()

    q_text = "Q"
    # Igual usamos textbbox para la Q pequeña
    bbox_q = draw.textbbox((0, 0), q_text, font=font_small)
    wq = bbox_q[2] - bbox_q[0]
    hq = bbox_q[3] - bbox_q[1]
    draw.text((cx - wq / 2, cy + r_inner / 2), q_text, font=font_small, fill=(255, 255, 255, 200))

    out_path = os.path.join(OUT_DIR, filename)
    img.save(out_path)
    print("Guardada:", out_path)

def main():
    create_hex_badge("primer_ahorro.png",  (37, 99, 235), (220, 230, 245), "$")
    create_hex_badge("primera_meta.png",   (16, 185, 129), (220, 240, 230), "1")
    create_hex_badge("primer_reto.png",    (236, 72, 153), (245, 220, 235), "🏁")
    create_hex_badge("racha_7_dias.png",   (249, 115, 22), (245, 230, 215), "7")

if __name__ == "__main__":
    main()