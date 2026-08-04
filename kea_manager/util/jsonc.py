"""Парсер JSON с поддержкой комментариев в стиле Kea.

Kea допускает в конфигурационных файлах комментарии трёх видов:
    // однострочный
    #  однострочный
    /* многострочный */

Стандартный модуль ``json`` такие комментарии не понимает, поэтому здесь
реализована предварительная очистка текста от комментариев с аккуратным
пропуском строковых литералов (чтобы не «съесть» // или # внутри строки).

Функция также умеет отбрасывать висящие запятые (trailing commas), которые
иногда встречаются в конфигурациях, отредактированных вручную.

Загрузка выполняется с ``object_pairs_hook`` в обычный ``dict`` — начиная с
Python 3.7 порядок ключей сохраняется, что важно для round-trip записи.
"""

from __future__ import annotations

import json
from typing import Any


def strip_comments(text: str) -> str:
    """Удалить комментарии //, # и /* */ из JSON-текста.

    Строковые литералы сохраняются как есть, включая экранированные кавычки.
    """
    out = []
    i = 0
    n = len(text)
    in_string = False
    escaped = False

    while i < n:
        ch = text[i]

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        # вне строки
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        # /* ... */
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                # незакрытый комментарий — обрываем остаток
                i = n
            else:
                i = end + 2
            out.append(" ")
            continue

        # // ... до конца строки
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i + 2)
            if end == -1:
                i = n
            else:
                i = end  # сам '\n' сохранится на следующей итерации
            continue

        # # ... до конца строки
        if ch == "#":
            end = text.find("\n", i + 1)
            if end == -1:
                i = n
            else:
                i = end
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Убрать висящие запятые перед } или ] (учитывая строки)."""
    out = []
    i = 0
    n = len(text)
    in_string = False
    escaped = False

    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == ",":
            # заглянуть вперёд, пропуская пробелы
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                # висящая запятая — пропускаем
                i += 1
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def loads(text: str) -> Any:
    """Разобрать JSON-текст с комментариями и висящими запятыми."""
    cleaned = strip_comments(text)
    cleaned = _strip_trailing_commas(cleaned)
    return json.loads(cleaned)


def load(path: str, encoding: str = "utf-8") -> Any:
    """Прочитать и разобрать файл конфигурации."""
    with open(path, "r", encoding=encoding) as fh:
        return loads(fh.read())


def dumps(obj: Any, indent: int = 4) -> str:
    """Сериализовать объект в JSON-текст (без комментариев)."""
    return json.dumps(obj, indent=indent, ensure_ascii=False)


def dump(obj: Any, path: str, indent: int = 4, encoding: str = "utf-8") -> None:
    """Записать объект в файл конфигурации в формате JSON."""
    text = dumps(obj, indent=indent)
    with open(path, "w", encoding=encoding) as fh:
        fh.write(text)
        fh.write("\n")
