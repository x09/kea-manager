"""Модель управления hook-библиотеками Kea (hooks-libraries).

Хуки подключаются в массиве ``hooks-libraries`` тела службы Dhcp4/Dhcp6::

    "hooks-libraries": [
        { "library": "/usr/lib64/kea/hooks/libdhcp_lease_cmds.so" },
        { "library": ".../libdhcp_run_script.so",
          "parameters": { "name": "/path/script.sh", "sync": false } }
    ]

Философия:
  * «Загружен» = в hooks-libraries есть запись с данной библиотекой
    (сопоставление по имени файла .so, т.к. каталог установки различается).
  * Round-trip: снятие галки удаляет только эту запись; прочие хуки и их
    параметры не трогаем. Порядок сохранившихся записей не меняем.
  * Проверить реальное существование .so-файла через API нельзя — редактор
    этого не делает; ответственность за наличие библиотек на пользователе.

Каталог известных хуков — из поставки Kea 3.2.0. libddns_gss_tsig.so
относится к службе D2 (kea-dhcp-ddns), в Dhcp4/Dhcp6 не настраивается и
помечается как неактивный.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, NamedTuple, Optional


class HookDef(NamedTuple):
    filename: str        # имя .so
    label: str           # человекочитаемое описание
    has_params: bool     # есть ли осмысленные parameters
    dhcp_applicable: bool  # настраивается ли в kea-dhcp4/6 (D2 — нет)
    note: str = ""


# Встроенный каталог хуков Kea 3.2.0.
KNOWN_HOOKS: List[HookDef] = [
    HookDef("libddns_gss_tsig.so", "GSS-TSIG для DDNS", True, False,
            "Только для службы kea-dhcp-ddns (D2), не для DHCP-серверов."),
    HookDef("libdhcp_bootp.so", "Поддержка BOOTP-клиентов", False, True,
            "Только DHCPv4."),
    HookDef("libdhcp_class_cmds.so", "Команды управления классами", False, True),
    HookDef("libdhcp_ddns_tuning.so", "Тонкая настройка DDNS", True, True),
    HookDef("libdhcp_flex_id.so", "Гибкий идентификатор клиента", True, True),
    HookDef("libdhcp_flex_option.so", "Гибкие значения опций", True, True),
    HookDef("libdhcp_ha.so", "Высокая доступность (HA)", True, True,
            "Настраивается на отдельной вкладке «Высокая доступность (HA)»."),
    HookDef("libdhcp_host_cache.so", "Кэш резерваций (host cache)", True, True),
    HookDef("libdhcp_host_cmds.so", "Команды управления резервациями", False, True),
    HookDef("libdhcp_lease_cmds.so", "Команды управления арендами", False, True,
            "Нужен для управления арендами и для HA."),
    HookDef("libdhcp_lease_query.so", "Lease Query", True, True),
    HookDef("libdhcp_legal_log.so", "Юридическое логирование", True, True),
    HookDef("libdhcp_limits.so", "Ограничения (limits)", True, True),
    HookDef("libdhcp_mysql.so", "Бэкенд MySQL", False, True,
            "Модуль БД; настройка в lease-database/hosts-database."),
    HookDef("libdhcp_perfmon.so", "Мониторинг производительности", True, True),
    HookDef("libdhcp_pgsql.so", "Бэкенд PostgreSQL", False, True,
            "Модуль БД; настройка в lease-database/hosts-database."),
    HookDef("libdhcp_ping_check.so", "Проверка адреса ping", True, True,
            "Преимущественно DHCPv4."),
    HookDef("libdhcp_radius.so", "RADIUS", True, True),
    HookDef("libdhcp_run_script.so", "Запуск внешнего скрипта", True, True),
    HookDef("libdhcp_stat_cmds.so", "Команды статистики", False, True),
    HookDef("libdhcp_subnet_cmds.so", "Команды управления подсетями", False, True),
]

DEFAULT_HOOKS_DIR = "/usr/lib64/kea/hooks"


def known_by_name(filename: str) -> Optional[HookDef]:
    for h in KNOWN_HOOKS:
        if h.filename == filename:
            return h
    return None


def lib_filename(path: str) -> str:
    """Имя .so из полного пути."""
    return os.path.basename((path or "").replace("\\", "/"))


def hooks_libraries(dhcp_body: Dict[str, Any]) -> List[Dict[str, Any]]:
    return dhcp_body.setdefault("hooks-libraries", [])


def find_entry(dhcp_body: Dict[str, Any],
               filename: str) -> Optional[Dict[str, Any]]:
    """Найти запись hooks-libraries по имени .so."""
    for entry in dhcp_body.get("hooks-libraries", []) or []:
        if isinstance(entry, dict) and lib_filename(entry.get("library", "")) \
                == filename:
            return entry
    return None


def is_loaded(dhcp_body: Dict[str, Any], filename: str) -> bool:
    return find_entry(dhcp_body, filename) is not None


def enable(dhcp_body: Dict[str, Any], filename: str,
           directory: str = DEFAULT_HOOKS_DIR) -> Dict[str, Any]:
    """Добавить хук (если ещё не загружен). Возвращает запись."""
    entry = find_entry(dhcp_body, filename)
    if entry is None:
        entry = {"library": os.path.join(directory, filename)}
        hooks_libraries(dhcp_body).append(entry)
    return entry


def disable(dhcp_body: Dict[str, Any], filename: str) -> None:
    """Удалить запись хука из hooks-libraries (прочие не трогаем)."""
    libs = dhcp_body.get("hooks-libraries")
    if not isinstance(libs, list):
        return
    dhcp_body["hooks-libraries"] = [
        e for e in libs
        if not (isinstance(e, dict)
                and lib_filename(e.get("library", "")) == filename)]


def get_parameters(dhcp_body: Dict[str, Any],
                   filename: str) -> Optional[Dict[str, Any]]:
    entry = find_entry(dhcp_body, filename)
    if entry is None:
        return None
    return entry.get("parameters")


def set_parameters(dhcp_body: Dict[str, Any], filename: str,
                   params: Optional[Dict[str, Any]]) -> None:
    """Задать/очистить parameters загруженного хука."""
    entry = find_entry(dhcp_body, filename)
    if entry is None:
        return
    if params:
        entry["parameters"] = params
    else:
        entry.pop("parameters", None)


def set_library_path(dhcp_body: Dict[str, Any], filename: str,
                     directory: str) -> None:
    """Обновить путь к .so у загруженного хука (при смене каталога)."""
    entry = find_entry(dhcp_body, filename)
    if entry is not None:
        entry["library"] = os.path.join(directory, filename)


def loaded_hooks(dhcp_body: Dict[str, Any]) -> List[str]:
    """Список имён .so, загруженных в конфигурации."""
    out = []
    for entry in dhcp_body.get("hooks-libraries", []) or []:
        if isinstance(entry, dict) and entry.get("library"):
            out.append(lib_filename(entry["library"]))
    return out
