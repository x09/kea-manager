"""Модель конфигурации High Availability (HA) для Kea.

HA в Kea реализуется hook-библиотекой ``libdhcp_ha.so``, которая
подключается в массиве ``hooks-libraries`` тела службы. Параметры HA
находятся в ``parameters.high-availability`` — это массив (обычно из одной
записи) со следующей структурой::

    {
      "hooks-libraries": [
        {
          "library": ".../libdhcp_ha.so",
          "parameters": {
            "high-availability": [
              {
                "this-server-name": "server1",
                "mode": "load-balancing",
                "peers": [
                  {"name": "server1", "url": "http://10.0.0.1:8000/",
                   "role": "primary", "auto-failover": true},
                  {"name": "server2", "url": "http://10.0.0.2:8000/",
                   "role": "secondary", "auto-failover": true}
                ]
              }
            ]
          }
        }
      ]
    }

Round-trip: мы находим/создаём ТОЛЬКО запись libdhcp_ha.so в массиве
hooks-libraries; прочие hook-библиотеки и их параметры не трогаем. Внутри
записи ha меняем только известные ключи, сохраняя остальные.

Замечание: для корректной работы HA Kea также требует загруженной
библиотеки ``libdhcp_lease_cmds.so`` (обмен арендами между партнёрами).
Модель предоставляет проверку её наличия, но не навязывает.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Библиотеки hook (проверяем по окончанию пути, т.к. префикс установки разный)
HA_LIB_SUFFIX = "libdhcp_ha.so"
LEASE_CMDS_LIB_SUFFIX = "libdhcp_lease_cmds.so"

# Путь по умолчанию (может отличаться в дистрибутиве; пользователь исправит)
DEFAULT_HA_LIB = "/usr/lib64/kea/hooks/libdhcp_ha.so"
DEFAULT_LEASE_CMDS_LIB = "/usr/lib64/kea/hooks/libdhcp_lease_cmds.so"

# Режимы HA
MODE_LOAD_BALANCING = "load-balancing"
MODE_HOT_STANDBY = "hot-standby"
MODE_PASSIVE_BACKUP = "passive-backup"
MODES = [MODE_LOAD_BALANCING, MODE_HOT_STANDBY, MODE_PASSIVE_BACKUP]

# Допустимые роли peer по режиму
ROLES_BY_MODE = {
    MODE_LOAD_BALANCING: ["primary", "secondary", "backup"],
    MODE_HOT_STANDBY: ["primary", "standby", "backup"],
    MODE_PASSIVE_BACKUP: ["primary", "backup"],
}
ALL_ROLES = ["primary", "secondary", "standby", "backup"]


def _lib_matches(entry: Dict[str, Any], suffix: str) -> bool:
    lib = entry.get("library", "") if isinstance(entry, dict) else ""
    return isinstance(lib, str) and lib.replace("\\", "/").endswith(suffix)


def hooks_libraries(dhcp_body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Массив hooks-libraries тела службы (создаётся при отсутствии)."""
    return dhcp_body.setdefault("hooks-libraries", [])


def find_ha_entry(dhcp_body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Найти запись hooks-libraries для libdhcp_ha.so."""
    for entry in hooks_libraries(dhcp_body):
        if _lib_matches(entry, HA_LIB_SUFFIX):
            return entry
    return None


def has_lease_cmds_lib(dhcp_body: Dict[str, Any]) -> bool:
    for entry in dhcp_body.get("hooks-libraries", []) or []:
        if _lib_matches(entry, LEASE_CMDS_LIB_SUFFIX):
            return True
    return False


def add_lease_cmds_lib(dhcp_body: Dict[str, Any],
                       library: str = DEFAULT_LEASE_CMDS_LIB) -> None:
    """Добавить libdhcp_lease_cmds.so, если её ещё нет."""
    if not has_lease_cmds_lib(dhcp_body):
        hooks_libraries(dhcp_body).append({"library": library})


def is_ha_enabled(dhcp_body: Dict[str, Any]) -> bool:
    return find_ha_entry(dhcp_body) is not None


def _ha_list(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = entry.setdefault("parameters", {})
    ha = params.setdefault("high-availability", [])
    if not ha:
        ha.append({})
    return ha


def get_ha_config(dhcp_body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Вернуть первую запись high-availability или None."""
    entry = find_ha_entry(dhcp_body)
    if entry is None:
        return None
    ha = _ha_list(entry)
    return ha[0]


def enable_ha(dhcp_body: Dict[str, Any],
              library: str = DEFAULT_HA_LIB) -> Dict[str, Any]:
    """Включить HA: создать запись libdhcp_ha.so при необходимости.

    Возвращает map high-availability[0] для дальнейшего редактирования.
    """
    entry = find_ha_entry(dhcp_body)
    if entry is None:
        entry = {"library": library, "parameters": {"high-availability": [{}]}}
        hooks_libraries(dhcp_body).append(entry)
    ha = _ha_list(entry)
    ha0 = ha[0]
    # значения по умолчанию для новой конфигурации
    ha0.setdefault("mode", MODE_HOT_STANDBY)
    ha0.setdefault("peers", [])
    return ha0


def disable_ha(dhcp_body: Dict[str, Any]) -> None:
    """Удалить запись libdhcp_ha.so из hooks-libraries.

    Прочие hook-библиотеки (в т.ч. lease_cmds) не трогаем. Пустой массив
    hooks-libraries оставляем как есть (Kea это допускает).
    """
    libs = dhcp_body.get("hooks-libraries")
    if not isinstance(libs, list):
        return
    dhcp_body["hooks-libraries"] = [
        e for e in libs if not _lib_matches(e, HA_LIB_SUFFIX)]


# -- операции с peers --------------------------------------------------------

def peers_of(ha0: Dict[str, Any]) -> List[Dict[str, Any]]:
    return ha0.setdefault("peers", [])


def add_peer(ha0: Dict[str, Any], name: str, url: str, role: str,
             auto_failover: Optional[bool] = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"name": name, "url": url, "role": role}
    if auto_failover is not None:
        entry["auto-failover"] = auto_failover
    peers_of(ha0).append(entry)
    return entry


def update_peer(ha0: Dict[str, Any], index: int, name: str, url: str,
                role: str, auto_failover: Optional[bool] = None) -> Dict[str, Any]:
    peers = peers_of(ha0)
    if not (0 <= index < len(peers)):
        raise IndexError(f"Нет peer с индексом {index}")
    p = peers[index]
    p["name"] = name
    p["url"] = url
    p["role"] = role
    if auto_failover is None:
        p.pop("auto-failover", None)
    else:
        p["auto-failover"] = auto_failover
    return p


def remove_peer(ha0: Dict[str, Any], index: int) -> None:
    peers = peers_of(ha0)
    if 0 <= index < len(peers):
        del peers[index]
    else:
        raise IndexError(f"Нет peer с индексом {index}")


# -- валидация ---------------------------------------------------------------

def validate_mode(mode: str) -> tuple:
    if mode not in MODES:
        return (False, f"Неизвестный режим HA: {mode!r}")
    return (True, "")


def validate_url(url: str) -> tuple:
    url = (url or "").strip()
    if not url:
        return (False, "URL peer не задан")
    if not (url.startswith("http://") or url.startswith("https://")):
        return (False, f"URL должен начинаться с http:// или https://: {url!r}")
    return (True, "")


def validate_role(role: str, mode: str) -> tuple:
    allowed = ROLES_BY_MODE.get(mode, ALL_ROLES)
    if role not in allowed:
        return (False,
                f"Роль {role!r} недопустима для режима {mode!r}. "
                f"Разрешены: {', '.join(allowed)}")
    return (True, "")


def validate_ha(ha0: Dict[str, Any]) -> tuple:
    """Проверить согласованность конфигурации HA целиком."""
    mode = ha0.get("mode", "")
    ok, msg = validate_mode(mode)
    if not ok:
        return (False, msg)

    this_name = ha0.get("this-server-name", "")
    peers = peers_of(ha0)
    if not this_name:
        return (False, "Не задано this-server-name")
    if not peers:
        return (False, "Не задан ни один peer")

    names = set()
    for p in peers:
        n = p.get("name", "")
        if not n:
            return (False, "У peer не задано имя")
        if n in names:
            return (False, f"Дублируется имя peer: {n!r}")
        names.add(n)
        ok, msg = validate_url(p.get("url", ""))
        if not ok:
            return (False, f"peer {n!r}: {msg}")
        ok, msg = validate_role(p.get("role", ""), mode)
        if not ok:
            return (False, f"peer {n!r}: {msg}")

    if this_name not in names:
        return (False,
                f"this-server-name {this_name!r} не совпадает ни с одним peer")
    return (True, "")
