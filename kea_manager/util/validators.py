"""Валидация сетевых параметров конфигурации Kea.

Используется только стандартная библиотека (``ipaddress``). Все функции
возвращают ``(ok: bool, message: str)`` — при ошибке ``message`` содержит
понятное пользователю описание проблемы.
"""

from __future__ import annotations

import ipaddress
from typing import Optional, Tuple

Result = Tuple[bool, str]

OK: Result = (True, "")


def _err(msg: str) -> Result:
    return (False, msg)


# --------------------------------------------------------------------------
# Адреса
# --------------------------------------------------------------------------

def validate_ip(value: str, family: Optional[int] = None) -> Result:
    """Проверить одиночный IP-адрес.

    family: 4, 6 или None (любой).
    """
    value = value.strip()
    if not value:
        return _err("Адрес не задан")
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return _err(f"Некорректный IP-адрес: {value!r}")
    if family == 4 and addr.version != 4:
        return _err(f"Ожидался IPv4-адрес, получен IPv6: {value!r}")
    if family == 6 and addr.version != 6:
        return _err(f"Ожидался IPv6-адрес, получен IPv4: {value!r}")
    return OK


def validate_subnet(value: str, family: Optional[int] = None) -> Result:
    """Проверить подсеть в формате CIDR (например 192.0.2.0/24)."""
    value = value.strip()
    if not value:
        return _err("Подсеть не задана")
    if "/" not in value:
        return _err(f"Подсеть должна быть в формате CIDR (адрес/префикс): {value!r}")
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        return _err(f"Некорректная подсеть {value!r}: {exc}")
    if family == 4 and net.version != 4:
        return _err(f"Ожидалась IPv4-подсеть: {value!r}")
    if family == 6 and net.version != 6:
        return _err(f"Ожидалась IPv6-подсеть: {value!r}")
    return OK


def validate_hw_address(value: str) -> Result:
    """Проверить MAC-адрес (форматы AA:BB:CC:DD:EE:FF или AA-BB-...)."""
    value = value.strip()
    if not value:
        return _err("MAC-адрес не задан")
    sep = ":" if ":" in value else "-" if "-" in value else None
    if sep is None:
        return _err(f"MAC-адрес должен разделяться ':' или '-': {value!r}")
    parts = value.split(sep)
    if len(parts) != 6:
        return _err(f"MAC-адрес должен содержать 6 октетов: {value!r}")
    for p in parts:
        if len(p) != 2 or any(c not in "0123456789abcdefABCDEF" for c in p):
            return _err(f"Некорректный октет {p!r} в MAC-адресе")
    return OK


# --------------------------------------------------------------------------
# Пулы
# --------------------------------------------------------------------------

def parse_pool(value: str) -> Tuple[Optional[ipaddress._BaseAddress],
                                    Optional[ipaddress._BaseAddress],
                                    Optional[ipaddress._BaseNetwork]]:
    """Разобрать строку пула Kea.

    Поддерживаются два формата:
      "192.0.2.10 - 192.0.2.20"  -> (first, last, None)
      "192.0.2.0/24"             -> (net[0], net[-1], net)

    Возвращает (first, last, network|None). Бросает ValueError при ошибке.
    """
    value = value.strip()
    if "-" in value:
        left, _, right = value.partition("-")
        first = ipaddress.ip_address(left.strip())
        last = ipaddress.ip_address(right.strip())
        if first.version != last.version:
            raise ValueError("Границы пула разных версий IP")
        return first, last, None
    if "/" in value:
        net = ipaddress.ip_network(value, strict=False)
        return net.network_address, net.broadcast_address, net
    raise ValueError("Пул должен быть диапазоном 'A - B' или подсетью 'A/prefix'")


def validate_pool(value: str, family: Optional[int] = None) -> Result:
    """Проверить корректность строки пула."""
    value = value.strip()
    if not value:
        return _err("Пул не задан")
    try:
        first, last, _ = parse_pool(value)
    except ValueError as exc:
        return _err(f"Некорректный пул {value!r}: {exc}")
    if family == 4 and first.version != 4:
        return _err(f"Ожидался IPv4-пул: {value!r}")
    if family == 6 and first.version != 6:
        return _err(f"Ожидался IPv6-пул: {value!r}")
    if int(first) > int(last):
        return _err(f"Начало пула больше конца: {value!r}")
    return OK


def validate_pool_in_subnet(pool: str, subnet: str) -> Result:
    """Проверить, что диапазон пула целиком лежит внутри подсети."""
    ok, msg = validate_subnet(subnet)
    if not ok:
        return _err(f"Подсеть некорректна: {msg}")
    ok, msg = validate_pool(pool)
    if not ok:
        return _err(msg)
    net = ipaddress.ip_network(subnet.strip(), strict=False)
    first, last, _ = parse_pool(pool)
    if first.version != net.version:
        return _err("Версия IP пула не совпадает с версией подсети")
    if first not in net or last not in net:
        return _err(f"Пул {pool!r} выходит за границы подсети {subnet!r}")
    return OK


def pools_overlap(pool_a: str, pool_b: str) -> bool:
    """Проверить пересечение двух пулов по диапазонам адресов."""
    a1, a2, _ = parse_pool(pool_a)
    b1, b2, _ = parse_pool(pool_b)
    return int(a1) <= int(b2) and int(b1) <= int(a2)


# --------------------------------------------------------------------------
# Времена аренды / таймеры
# --------------------------------------------------------------------------

def validate_positive_int(value, name: str = "значение",
                          allow_zero: bool = False) -> Result:
    """Проверить целое неотрицательное (или положительное) число."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return _err(f"{name}: ожидалось целое число, получено {value!r}")
    if allow_zero:
        if n < 0:
            return _err(f"{name}: не может быть отрицательным")
    else:
        if n <= 0:
            return _err(f"{name}: должно быть больше нуля")
    return OK


def validate_lease_timers(valid_lifetime, renew_timer=None,
                          rebind_timer=None) -> Result:
    """Проверить согласованность таймеров аренды.

    Требования Kea: renew-timer < rebind-timer < valid-lifetime.
    Параметры renew/rebind необязательны.
    """
    ok, msg = validate_positive_int(valid_lifetime, "valid-lifetime")
    if not ok:
        return _err(msg)
    vl = int(valid_lifetime)

    rt = None
    if renew_timer not in (None, ""):
        ok, msg = validate_positive_int(renew_timer, "renew-timer", allow_zero=True)
        if not ok:
            return _err(msg)
        rt = int(renew_timer)

    rbt = None
    if rebind_timer not in (None, ""):
        ok, msg = validate_positive_int(rebind_timer, "rebind-timer", allow_zero=True)
        if not ok:
            return _err(msg)
        rbt = int(rebind_timer)

    if rt is not None and rbt is not None and rt >= rbt:
        return _err("renew-timer должен быть меньше rebind-timer")
    if rbt is not None and rbt >= vl:
        return _err("rebind-timer должен быть меньше valid-lifetime")
    if rt is not None and rt >= vl:
        return _err("renew-timer должен быть меньше valid-lifetime")
    return OK
