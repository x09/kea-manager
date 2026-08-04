"""Каталог известных DHCP-опций и валидация их значений.

Опции соответствуют пространству имён Kea (dhcp4 / dhcp6). В редакторе
пользователь задаёт значение в поле ``data`` в том же строковом формате,
что и в конфигурации Kea. Здесь описаны наиболее востребованные опции из
задания и функции проверки значений.

Форматы данных Kea (кратко):
  - ipv4-address / ipv6-address        один адрес
  - список адресов                     через запятую: "10.0.0.1, 10.0.0.2"
  - string                             произвольная строка
  - fqdn-list                          список доменов через запятую
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional

from ..util import validators as V


class OptionDef(NamedTuple):
    name: str            # каноническое имя опции Kea
    label: str           # человекочитаемая подпись
    family: int          # 4, 6 или 0 (оба)
    kind: str            # тип значения (см. ниже)
    hint: str            # подсказка по формату


# Типы значений для валидации
KIND_IPV4_LIST = "ipv4-list"
KIND_IPV6_LIST = "ipv6-list"
KIND_STRING = "string"
KIND_FQDN_LIST = "fqdn-list"
KIND_CSR = "classless-static-route"
KIND_RAW = "raw"


# --- Каталог опций DHCPv4 ---------------------------------------------------
_V4: List[OptionDef] = [
    OptionDef("routers", _("Основной шлюз (routers)"), 4, KIND_IPV4_LIST,
              _("Один или несколько IPv4 через запятую: 192.0.2.1")),
    OptionDef("domain-name-servers", _("DNS-серверы (domain-name-servers)"), 4,
              KIND_IPV4_LIST, _("IPv4 через запятую: 192.0.2.1, 192.0.2.2")),
    OptionDef("domain-name", _("Доменное имя (domain-name)"), 4, KIND_STRING,
              _("Строка: example.org")),
    OptionDef("domain-search", _("Поисковый домен (domain-search)"), 4,
              KIND_FQDN_LIST, _("Домены через запятую: a.example.org, b.example.org")),
    OptionDef("classless-static-route",
              _("Статические маршруты (classless-static-route)"), 4, KIND_CSR,
              _("Список 'подсеть - шлюз' через запятую: "
              "192.0.5.0/24 - 192.0.2.2")),
    OptionDef("time-servers", _("NTP-серверы (time-servers)"), 4, KIND_IPV4_LIST,
              _("IPv4 через запятую: 192.0.2.10")),
]

# --- Каталог опций DHCPv6 ---------------------------------------------------
_V6: List[OptionDef] = [
    OptionDef("dns-servers", _("DNS-серверы (dns-servers)"), 6, KIND_IPV6_LIST,
              _("IPv6 через запятую: 2001:db8::1")),
    OptionDef("domain-search", _("Поисковый домен (domain-search)"), 6,
              KIND_FQDN_LIST, _("Домены через запятую: a.example.org")),
    OptionDef("sntp-servers", _("NTP/SNTP-серверы (sntp-servers)"), 6,
              KIND_IPV6_LIST, _("IPv6 через запятую: 2001:db8::10")),
]


def catalog(family: int) -> List[OptionDef]:
    """Вернуть список известных опций для семейства."""
    return list(_V4 if family == 4 else _V6)


def find(family: int, name: str) -> Optional[OptionDef]:
    for o in catalog(family):
        if o.name == name:
            return o
    return None


def _split_csv(value: str) -> List[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def validate_option_data(kind: str, data: str, family: int) -> tuple:
    """Проверить значение опции согласно её типу. Возвращает (ok, msg)."""
    data = (data or "").strip()
    if not data:
        return (False, _("Значение опции не задано"))

    if kind in (KIND_IPV4_LIST, KIND_IPV6_LIST):
        fam = 4 if kind == KIND_IPV4_LIST else 6
        for item in _split_csv(data):
            ok, msg = V.validate_ip(item, fam)
            if not ok:
                return (False, msg)
        return (True, "")

    if kind == KIND_STRING:
        return (True, "")

    if kind == KIND_FQDN_LIST:
        for item in _split_csv(data):
            if " " in item or not item:
                return (False, _("Некорректное доменное имя: {}").format(item))
        return (True, "")

    if kind == KIND_CSR:
        # формат "подсеть - шлюз" через запятую
        for route in _split_csv(data):
            if "-" not in route:
                return (False,
                        _("Маршрут должен быть в формате 'подсеть - шлюз': {}")
                        .format(route))
            net, _sep, gw = route.partition("-")
            ok, msg = V.validate_subnet(net.strip(), 4)
            if not ok:
                return (False, _("Маршрут {}: {}").format(route, msg))
            ok, msg = V.validate_ip(gw.strip(), 4)
            if not ok:
                return (False, _("Маршрут {}: шлюз — {}").format(route, msg))
        return (True, "")

    # KIND_RAW и всё прочее — без проверки
    return (True, "")
