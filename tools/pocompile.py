"""Компилятор .po -> .mo на чистом Python (без gettext-utils).

Поддерживает базовый синтаксис PO: msgid/msgstr (в т.ч. многострочные),
комментарии (#...), пропуск пустых msgstr. Формат .mo — стандартный
бинарный формат GNU gettext (little-endian).

Запуск:
    python3 tools/pocompile.py path/to/file.po           # -> file.mo рядом
    python3 tools/pocompile.py in.po out.mo
    python3 tools/pocompile.py --all                     # все .po в locale/
"""

import ast
import os
import struct
import sys


def parse_po(text):
    """Разобрать PO-текст в dict {msgid: msgstr} (без пустых записей)."""
    entries = {}
    msgid = None
    msgstr = None
    mode = None  # 'id' | 'str'

    def flush():
        # Пустой msgid — это заголовок каталога (метаданные, в т.ч. charset),
        # его нужно сохранить. Прочие записи с пустым msgstr пропускаем.
        if msgid is not None and msgstr is not None:
            if msgid == "" or msgstr != "":
                entries[msgid] = msgstr

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            flush()
            msgid = _unquote(line[len("msgid "):])
            msgstr = None
            mode = "id"
        elif line.startswith("msgstr "):
            msgstr = _unquote(line[len("msgstr "):])
            mode = "str"
        elif line.startswith('"'):
            piece = _unquote(line)
            if mode == "id":
                msgid += piece
            elif mode == "str":
                msgstr += piece
    flush()
    return entries


def _unquote(s):
    """Снять кавычки со строки PO, обработав экранирование."""
    s = s.strip()
    if not (s.startswith('"') and s.endswith('"')):
        return ""
    # используем ast.literal_eval для корректной обработки \n \t \" и т.п.
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return s[1:-1]


def _pack_full(keys, entries):
    n = len(keys)
    ids = b""
    strs = b""
    idx_k = []
    idx_v = []
    for k in keys:
        kb = k.encode("utf-8")
        idx_k.append((len(kb), len(ids)))
        ids += kb + b"\x00"
    for k in keys:
        vb = entries[k].encode("utf-8")
        idx_v.append((len(vb), len(strs)))
        strs += vb + b"\x00"

    keystart = 7 * 4
    valuestart = keystart + n * 8
    idsstart = valuestart + n * 8
    strsstart = idsstart + len(ids)

    out = struct.pack("Iiiiiii", 0x950412de, 0, n,
                      keystart, valuestart, 0, 0)
    for length, offset in idx_k:
        out += struct.pack("ii", length, idsstart + offset)
    for length, offset in idx_v:
        out += struct.pack("ii", length, strsstart + offset)
    out += ids
    out += strs
    return out


def compile_file(po_path, mo_path=None):
    if mo_path is None:
        mo_path = os.path.splitext(po_path)[0] + ".mo"
    with open(po_path, encoding="utf-8") as fh:
        entries = parse_po(fh.read())
    data = _pack_full(sorted(entries), entries)
    os.makedirs(os.path.dirname(mo_path) or ".", exist_ok=True)
    with open(mo_path, "wb") as fh:
        fh.write(data)
    print(f"{po_path} -> {mo_path} ({len(entries)} строк)")


def compile_all(locale_root):
    for root, _dirs, files in os.walk(locale_root):
        for f in files:
            if f.endswith(".po"):
                compile_file(os.path.join(root, f))


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "--all":
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        compile_all(os.path.join(here, "kea_manager", "locale"))
        return 0
    po = argv[0]
    mo = argv[1] if len(argv) > 1 else None
    compile_file(po, mo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
