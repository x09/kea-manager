"""Маски ввода для полей MAC/IPv4/IPv6 (tkinter validatecommand).

Идея: подключаем к ttk.Entry проверку на уровне отдельного нажатия
(validate="key"). Функция-предикат получает будущее содержимое поля
(значение %P) и решает, допустимо ли оно как ПРЕФИКС корректного
значения. Если символ недопустим — ввод отклоняется, и синтаксически
неверное значение просто нельзя набрать.

Предикаты намеренно «разрешающие» (проверяют, что строка может стать
корректной), а окончательная строгая проверка остаётся за валидаторами
из util.validators при нажатии OK.
"""

from __future__ import annotations

# tkinter импортируется лениво внутри masked_entry, чтобы предикаты
# (is_partial_*) можно было тестировать в окружении без tkinter.

_HEX = set("0123456789abcdefABCDEF")
_DIGITS = set("0123456789")


# --------------------------------------------------------------------------
# Предикаты «допустим ли префикс»
# --------------------------------------------------------------------------

def is_partial_mac(s: str) -> bool:
    """MAC вида AA:BB:CC:DD:EE:FF — во время набора.

    Разрешаем hex-пары, разделённые ':'. Максимум 6 групп по 2 знака.
    Пустая строка допустима (поле можно очистить).
    """
    if s == "":
        return True
    groups = s.split(":")
    if len(groups) > 6:
        return False
    for i, g in enumerate(groups):
        if len(g) > 2:
            return False
        if any(c not in _HEX for c in g):
            return False
    return True


def is_partial_ipv4(s: str) -> bool:
    """IPv4 вида A.B.C.D — во время набора.

    Разрешаем до 4 октетов (0..255), разделённых точкой.
    """
    if s == "":
        return True
    parts = s.split(".")
    if len(parts) > 4:
        return False
    for p in parts:
        if p == "":
            continue  # частичный ввод: точка только что поставлена
        if len(p) > 3 or any(c not in _DIGITS for c in p):
            return False
        if int(p) > 255:
            return False
    return True


def is_partial_ipv6(s: str) -> bool:
    """IPv6 (hex-группы через ':') — во время набора.

    Разрешаем hex-цифры и ':' (в т.ч. '::'). До 8 групп по 4 знака.
    Строгая проверка адреса — при подтверждении.
    """
    if s == "":
        return True
    # разрешённые символы
    if any(c not in _HEX and c != ":" for c in s):
        return False
    # три и более двоеточия подряд недопустимы («::» — максимум)
    if ":::" in s:
        return False
    # сокращение «::» может встречаться только один раз
    if s.count("::") > 1:
        return False
    if s.count(":") > 7:
        return False
    for g in s.split(":"):
        if len(g) > 4:
            return False
    return True


def is_partial_ip(s: str) -> bool:
    """IPv4 или IPv6 — определяем по наличию ':' или '.'."""
    if s == "":
        return True
    if ":" in s:
        return is_partial_ipv6(s)
    if "." in s:
        return is_partial_ipv4(s)
    # ещё непонятно: может стать и v4 (цифры) и v6 (hex)
    return all(c in _HEX for c in s)


_PREDICATES = {
    "mac": is_partial_mac,
    "ipv4": is_partial_ipv4,
    "ipv6": is_partial_ipv6,
    "ip": is_partial_ip,
}


def masked_entry(master, textvariable, kind: str, **kw) -> ttk.Entry:
    """Создать ttk.Entry с маской ввода заданного типа.

    kind: 'mac', 'ipv4', 'ipv6' или 'ip'. Если тип неизвестен — обычный
    Entry без ограничений (безопасный откат).
    """
    import tkinter as tk
    from tkinter import ttk

    predicate = _PREDICATES.get(kind)
    entry = ttk.Entry(master, textvariable=textvariable, **kw)
    if predicate is None:
        return entry
    try:
        vcmd = (entry.register(lambda proposed: bool(predicate(proposed))),
                "%P")
        entry.configure(validate="key", validatecommand=vcmd)
    except tk.TclError:
        pass  # на всякий случай — без маски
    return entry
