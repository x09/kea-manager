"""Иконки, генерируемые в рантайме через tkinter.PhotoImage.

Никаких внешних файлов и зависимостей: каждая иконка рисуется программно
как матрица пикселей 16x16 и загружается методом ``PhotoImage.put``.
Прозрачность эмулируется цветом фона дерева (пиксели-«дырки» просто не
закрашиваются — put с пустой строкой оставляет их прозрачными в GIF-модели
tkinter, поэтому фон виджета проступает).

Использование::

    from .icons import Icons
    icons = Icons()          # создать после инициализации корневого окна Tk
    tree.insert(..., image=icons.subnet)

Если по какой-либо причине PhotoImage недоступен, атрибуты становятся
``None`` — вызывающий код должен корректно обрабатывать отсутствие иконки
(в дереве останется только текст).
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Optional

# Палитра (шестнадцатеричные цвета)
_C = {
    "k": "#000000",  # чёрный контур
    "b": "#1565c0",  # синий
    "B": "#0d47a1",  # тёмно-синий
    "g": "#2e7d32",  # зелёный
    "G": "#1b5e20",  # тёмно-зелёный
    "y": "#f9a825",  # жёлтый
    "o": "#ef6c00",  # оранжевый
    "r": "#c62828",  # красный
    "w": "#ffffff",  # белый
    "s": "#90a4ae",  # серый
    "d": "#546e7a",  # тёмно-серый
    ".": "",         # прозрачный
}

# Каждая иконка — список из 16 строк по 16 символов (ключи палитры).
# Рисунки намеренно простые и узнаваемые в масштабе 16x16.

_SERVER = [
    "................",
    "..kkkkkkkkkkkk..",
    "..kBBBBBBBBBBk..",
    "..kBwwwwwwwwBk..",
    "..kBwsssssswBk..",
    "..kBwwwwwwwwBk..",
    "..kBBBBBBBBBBk..",
    "..kkkkkkkkkkkk..",
    "..kBBBBBBBBBBk..",
    "..kBwwwwwwwwBk..",
    "..kBwsssssswBk..",
    "..kBwwwwwwwwBk..",
    "..kBBBBBBBBBBk..",
    "..kkkkkkkkkkkk..",
    "................",
    "................",
]

_IPV4 = [
    "................",
    ".kkkkkkkkkkkkkk.",
    ".kbbbbbbbbbbbbk.",
    ".kbwbwwbwwwbwbk.",
    ".kbwbwbwbwbwwbk.",
    ".kbwwwbwbwbwwbk.",
    ".kbwbwbwbwbwwbk.",
    ".kbwbwwbwwwbwbk.",
    ".kbbbbbbbbbbbbk.",
    ".kkkkkkkkkkkkkk.",
    "................",
    "....kkkkkkkk....",
    "................",
    "................",
    "................",
    "................",
]

_IPV6 = [
    "................",
    ".kkkkkkkkkkkkkk.",
    ".kggggggggggggk.",
    ".kgwgwwgwwwgwgk.",
    ".kgwgwbwbwbwwgk.",
    ".kgwwwbwbwbwwgk.",
    ".kgwgwbwbwbwwgk.",
    ".kgwgwwgwwwgwgk.",
    ".kggggggggggggk.",
    ".kkkkkkkkkkkkkk.",
    "................",
    "....kkkkkkkk....",
    "................",
    "................",
    "................",
    "................",
]

# IPv6 «не сконфигурировано» — серый с красным запретным кружком
_IPV6_OFF = [
    "................",
    ".kkkkkkkkkkkkkk.",
    ".kssssssssssssk.",
    ".kswswwswwwswsk.",
    ".kswswdwdwdwwsk.",
    ".ksrrrbwbwbwwsk.",
    ".krwwrbwbwbwwsk.",
    ".krwwrwswwwswsk.",
    ".krwwrsssssssk..",
    ".ksrrrkkkkkkkk..",
    "....r...........",
    "....kkkkkkkk....",
    "................",
    "................",
    "................",
    "................",
]

_SUBNET = [
    "................",
    "..kkkkkkkkkkkk..",
    "..kbbbbbbbbbbk..",
    "..kbwwwwwwwwbk..",
    "..kbwbbwbbwwbk..",
    "..kbwwwwwwwwbk..",
    "..kbwbbwbbwwbk..",
    "..kbwwwwwwwwbk..",
    "..kbbbbbbbbbbk..",
    "..kkkkkkkkkkkk..",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
]

_POOLS = [
    "................",
    "................",
    "...kk......kk...",
    "..kyyk....kyyk..",
    "..kyyk....kyyk..",
    "...kk......kk...",
    "................",
    "..kkkkkkkkkkkk..",
    "..kbbbbbbbbbbk..",
    "..kbwbwbwbwbbk..",
    "..kbbbbbbbbbbk..",
    "..kbwbwbwbwbbk..",
    "..kbbbbbbbbbbk..",
    "..kkkkkkkkkkkk..",
    "................",
    "................",
]

_RESERV = [
    "................",
    "......kkkk......",
    ".....kyyyyk.....",
    ".....kyGGyk.....",
    "......kGGk......",
    ".....kGGGGk.....",
    "....kGGGGGGk....",
    "...kGGGGGGGGk...",
    "...kGwGGGGwGk...",
    "...kGGGGGGGGk...",
    "...kkkkkkkkkk...",
    "................",
    "................",
    "................",
    "................",
    "................",
]

_OPTIONS = [
    "................",
    ".....kkkkk......",
    "....koooook.....",
    "...kookkookk....",
    "...kokwwkokk....",
    "...kokwwkokk....",
    "...kookkoook....",
    "....koooook.....",
    ".kk..kokok...kk.",
    "kook.kokok..kook",
    "kook.kokok..kook",
    ".kk..kokok...kk.",
    "................",
    "................",
    "................",
    "................",
]

_ADD = [
    "................",
    "................",
    ".......kk.......",
    ".......gg.......",
    ".......gg.......",
    ".......gg.......",
    "..kkkkkggkkkkk..",
    "..gggggggggggg..",
    "..gggggggggggg..",
    "..kkkkkggkkkkk..",
    ".......gg.......",
    ".......gg.......",
    ".......gg.......",
    ".......kk.......",
    "................",
    "................",
]

_DEL = [
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
    "..kkkkkkkkkkkk..",
    "..rrrrrrrrrrrr..",
    "..rrrrrrrrrrrr..",
    "..kkkkkkkkkkkk..",
    "................",
    "................",
    "................",
    "................",
    "................",
    "................",
]

_HA = [
    "................",
    "..kkkk....kkkk..",
    ".kBBBBk..kGGGGk.",
    ".kBwwBk..kGwwGk.",
    ".kBwwBkkkkGwwGk.",
    ".kBBBBkyykGGGGk.",
    "..kkkkkyykkkkk..",
    "....kk.yy.kk....",
    "....kkkyykkk....",
    "..kkkkkyykkkkk..",
    ".kBBBBkyykGGGGk.",
    ".kBwwBkkkkGwwGk.",
    ".kBwwBk..kGwwGk.",
    ".kBBBBk..kGGGGk.",
    "..kkkk....kkkk..",
    "................",
]

_CLASSES = [
    "................",
    "...kkkkkkkkkk...",
    "..koooooooooik..",
    "..koyoyoyoyoik..",
    "..kooooooooiik..",
    "..koyoyoyoyiik..",
    "..kkkkkkkkkiik..",
    "...kbbbbbbbkik..",
    "...kbwbwbwbkik..",
    "...kbbbbbbbkk...",
    "...kbwbwbwbk....",
    "...kbbbbbbbk....",
    "...kkkkkkkkk....",
    "................",
    "................",
    "................",
]

_LEASES = [
    "................",
    "..kkkkkkkkkkkk..",
    "..kwwwwwwwwwwk..",
    "..kwkkkwkkkwwk..",
    "..kwwwwwwwwwwk..",
    "..kwkkkwkkkwwk..",
    "..kwwwwwwwwwwk..",
    "..kwkkkwkkkwwk..",
    "..kwwwwwwwwwwk..",
    "..kkkkkkkkkkkk..",
    ".....koook......",
    "....koooook.....",
    "....kok.kok.....",
    "................",
    "................",
    "................",
]

_OPEN = [
    "................",
    "................",
    "..kkkkk.........",
    ".kyyyyyk........",
    "kyyyyyyykkkkkk..",
    "kyyyyyyyyyyyyk..",
    "kykkkkkkkkkkkk..",
    "kykyyyyyyyyyk...",
    "kkyyyyyyyyyk....",
    ".kyyyyyyyyk.....",
    ".kkkkkkkkk......",
    "................",
    "................",
    "................",
    "................",
    "................",
]

_SAVE = [
    "................",
    "..kkkkkkkkkkkk..",
    "..kbwwwwwwwwbk..",
    "..kbwkkkkkkwbk..",
    "..kbwwwwwwwwbk..",
    "..kbwwwwwwwwbk..",
    "..kbbbbbbbbbbk..",
    "..kbwwwwwwwwbk..",
    "..kbwwbbbbwwbk..",
    "..kbwwbwwbwwbk..",
    "..kbwwbwwbwwbk..",
    "..kbwwbbbbwwbk..",
    "..kkkkkkkkkkkk..",
    "................",
    "................",
    "................",
]


class Icons:
    """Набор иконок приложения. Создавать после появления корневого Tk."""

    _SPECS = {
        "server": _SERVER,
        "ipv4": _IPV4,
        "ipv6": _IPV6,
        "ipv6_off": _IPV6_OFF,
        "subnet": _SUBNET,
        "pools": _POOLS,
        "reservations": _RESERV,
        "options": _OPTIONS,
        "leases": _LEASES,
        "ha": _HA,
        "classes": _CLASSES,
        "add": _ADD,
        "delete": _DEL,
        "open": _OPEN,
        "save": _SAVE,
    }

    def __init__(self):
        self._images: Dict[str, Optional[tk.PhotoImage]] = {}
        for name, spec in self._SPECS.items():
            self._images[name] = self._build(spec)

    @staticmethod
    def _build(rows: List[str]) -> Optional[tk.PhotoImage]:
        try:
            h = len(rows)
            w = len(rows[0]) if rows else 0
            img = tk.PhotoImage(width=w, height=h)
            for y, row in enumerate(rows):
                # собираем непрерывные горизонтальные отрезки одного цвета
                x = 0
                while x < len(row):
                    ch = row[x]
                    color = _C.get(ch, "")
                    if not color:
                        x += 1
                        continue
                    x2 = x
                    while x2 < len(row) and row[x2] == ch:
                        x2 += 1
                    img.put(color, to=(x, y, x2, y + 1))
                    x = x2
            return img
        except Exception:
            return None

    def __getattr__(self, name: str) -> Optional[tk.PhotoImage]:
        # доступ вида icons.subnet
        images = self.__dict__.get("_images", {})
        if name in images:
            return images[name]
        raise AttributeError(name)

    def get(self, name: str) -> Optional[tk.PhotoImage]:
        return self._images.get(name)
