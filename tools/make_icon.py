"""Генерация иконки приложения kea-manager в нескольких размерах (PNG).

Дизайн: скруглённый синий бейдж с вертикальным градиентом; в центре —
стилизованный сервер-хаб DHCP, от него линии к четырём клиентским узлам
(сервер раздаёт адреса). Рисуем на большом холсте (супер-сэмплинг) и
уменьшаем до нужных размеров для чётких краёв.

Запуск: python3 tools/make_icon.py [OUTDIR]   (по умолчанию icons/)
Требует Pillow.
"""

import os
import sys

from PIL import Image, ImageDraw

SIZES = [32, 64, 128, 256]

# палитра
BG_TOP = (33, 118, 208)     # синий сверху
BG_BOTTOM = (13, 71, 161)   # тёмно-синий снизу
NODE = (255, 255, 255)      # белые узлы
HUB = (255, 255, 255)
HUB_FACE = (227, 242, 253)  # светло-голубой «экран» сервера
LINE = (144, 202, 249)      # линии связи
ACCENT = (255, 193, 7)      # жёлтый акцент (LED)


def _rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def _gradient(size):
    grad = Image.new("RGB", (size, size), BG_TOP)
    top, bot = BG_TOP, BG_BOTTOM
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        for x in range(size):
            grad.putpixel((x, y), (r, g, b))
    return grad


def _draw_icon(S):
    """Нарисовать иконку на холсте SxS (большой, для супер-сэмплинга)."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # фон-градиент со скруглением
    grad = _gradient(S).convert("RGBA")
    mask = _rounded_mask(S, int(S * 0.22))
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    cx = cy = S / 2

    # координаты четырёх клиентских узлов (по углам «креста»)
    off = S * 0.30
    clients = [
        (cx - off, cy - off),
        (cx + off, cy - off),
        (cx - off, cy + off),
        (cx + off, cy + off),
    ]

    # линии связи хаб->клиент
    lw = max(2, int(S * 0.016))
    for (x, y) in clients:
        d.line([(cx, cy), (x, y)], fill=LINE, width=lw)

    # клиентские узлы (кружки)
    rr = S * 0.055
    for (x, y) in clients:
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=NODE)

    # центральный сервер-хаб (скруглённый прямоугольник со «слотами»)
    hw, hh = S * 0.26, S * 0.30
    box = [cx - hw / 2, cy - hh / 2, cx + hw / 2, cy + hh / 2]
    d.rounded_rectangle(box, radius=int(S * 0.03), fill=HUB)
    # слоты сервера + LED
    slot_h = hh * 0.16
    pad = hw * 0.16
    for i in range(3):
        yy = box[1] + hh * (0.20 + i * 0.28)
        d.rounded_rectangle(
            [box[0] + pad, yy, box[2] - pad, yy + slot_h],
            radius=int(slot_h / 2), fill=HUB_FACE)
        # жёлтый LED слева в каждом слоте
        led = slot_h * 0.5
        lx = box[0] + pad + led
        ly = yy + slot_h / 2
        d.ellipse([lx - led / 2, ly - led / 2, lx + led / 2, ly + led / 2],
                  fill=ACCENT)
    return img


def main(argv):
    outdir = argv[0] if argv else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
    os.makedirs(outdir, exist_ok=True)

    SS = 1024  # большой холст для супер-сэмплинга
    base = _draw_icon(SS)

    written = []
    for sz in SIZES:
        im = base.resize((sz, sz), Image.LANCZOS)
        path = os.path.join(outdir, f"kea-manager-{sz}.png")
        im.save(path)
        written.append(path)

    # плюс «главный» файл без размера в имени (256px) и .ico для полноты
    main_png = os.path.join(outdir, "kea-manager.png")
    base.resize((256, 256), Image.LANCZOS).save(main_png)
    written.append(main_png)
    try:
        ico = os.path.join(outdir, "kea-manager.ico")
        base.resize((256, 256), Image.LANCZOS).save(
            ico, sizes=[(s, s) for s in SIZES])
        written.append(ico)
    except Exception:
        pass

    for p in written:
        print("создан:", p)


if __name__ == "__main__":
    main(sys.argv[1:])
