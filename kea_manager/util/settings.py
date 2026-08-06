"""Хранение настроек подключения в ~/.config/kea-manager/kea-manager.ini.

Сохраняются все параметры последнего успешного подключения по API, КРОМЕ
пароля — он в файл не пишется никогда и запрашивается при каждом запуске.

Формат INI (configparser). Пример::

    [connection]
    transport = api
    tls = false
    verify = true
    username = admin
    host4 = 192.168.150.10
    port4 = 8123
    v6_enabled = false
    host6 = 127.0.0.1
    port6 = 8001

    [last]
    directory = /etc/kea

Только стандартная библиотека (configparser, os).
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

APP_DIR_NAME = "kea-manager"
INI_NAME = "kea-manager.ini"

# Префикс секций списка серверов: [server:<имя>]
SERVER_PREFIX = "server:"


@dataclass
class ServerEntry:
    """Сохранённый сервер в списке дерева.

    kind: 'api' — подключение к живому Kea по HTTP(S);
          'file' — локальный каталог с conf-файлами.
    Пароль здесь НЕ хранится (запрашивается при подключении к API).
    """
    name: str
    kind: str = "api"
    # общие для api
    host4: str = "127.0.0.1"
    port4: str = "8000"
    tls: bool = False
    verify: bool = True
    username: str = ""
    v6_enabled: bool = False
    host6: str = "127.0.0.1"
    port6: str = "8001"
    # mutual TLS (клиентский сертификат)
    client_cert: str = ""
    client_key: str = ""
    ca_cert: str = ""
    # для file
    directory: str = ""

    def describe(self) -> str:
        if self.kind == "file":
            return f"файлы: {self.directory}"
        scheme = "https" if self.tls else "http"
        return f"{scheme}://{self.host4}:{self.port4}"


def config_dir() -> str:
    """Каталог настроек: $XDG_CONFIG_HOME/kea-manager или ~/.config/kea-manager."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), INI_NAME)


def load() -> Dict[str, Any]:
    """Прочитать настройки. Возвращает dict (пустой, если файла нет)."""
    path = config_path()
    result: Dict[str, Any] = {}
    if not os.path.isfile(path):
        return result
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return result

    if parser.has_section("connection"):
        c = parser["connection"]
        result["connection"] = {
            "transport": c.get("transport", "api"),
            "tls": c.getboolean("tls", fallback=False),
            "verify": c.getboolean("verify", fallback=True),
            "username": c.get("username", ""),
            "host4": c.get("host4", "127.0.0.1"),
            "port4": c.get("port4", "8000"),
            "v6_enabled": c.getboolean("v6_enabled", fallback=False),
            "host6": c.get("host6", "127.0.0.1"),
            "port6": c.get("port6", "8001"),
        }
    if parser.has_section("last"):
        result["last"] = {
            "directory": parser["last"].get("directory", ""),
        }
    return result


def save_connection(*, tls: bool, verify: bool, username: str,
                    host4: str, port4: int,
                    v6_enabled: bool = False,
                    host6: str = "", port6: int = 0) -> None:
    """Сохранить параметры API-подключения (без пароля)."""
    parser = _read_parser()
    parser["connection"] = {
        "transport": "api",
        "tls": str(bool(tls)).lower(),
        "verify": str(bool(verify)).lower(),
        "username": username or "",
        "host4": host4 or "",
        "port4": str(port4),
        "v6_enabled": str(bool(v6_enabled)).lower(),
        "host6": host6 or "",
        "port6": str(port6 or ""),
    }
    _write_parser(parser)


def save_last_directory(directory: str) -> None:
    """Сохранить последний использованный каталог с conf-файлами."""
    parser = _read_parser()
    if "last" not in parser:
        parser["last"] = {}
    parser["last"]["directory"] = directory or ""
    _write_parser(parser)


# -- внутреннее --------------------------------------------------------------

def _read_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    path = config_path()
    if os.path.isfile(path):
        try:
            parser.read(path, encoding="utf-8")
        except (OSError, configparser.Error):
            pass
    return parser


def get_language(default: str = "ru") -> str:
    """Код языка интерфейса из [ui].language ('ru' или 'en')."""
    parser = _read_parser()
    if parser.has_section("ui"):
        return parser["ui"].get("language", default) or default
    return default


def set_language(lang: str) -> None:
    parser = _read_parser()
    if "ui" not in parser:
        parser["ui"] = {}
    parser["ui"]["language"] = lang
    _write_parser(parser)


def get_window_geometry() -> Optional[str]:
    """Строка геометрии окна (напр. '960x600+100+50') или None."""
    parser = _read_parser()
    if parser.has_section("ui"):
        g = parser["ui"].get("geometry", "")
        return g or None
    return None


def set_window_geometry(geometry: str) -> None:
    parser = _read_parser()
    if "ui" not in parser:
        parser["ui"] = {}
    parser["ui"]["geometry"] = geometry or ""
    _write_parser(parser)


def get_hooks_dir(default: str = "/usr/lib64/kea/hooks") -> str:
    """Каталог с hook-библиотеками (может отличаться между системами)."""
    parser = _read_parser()
    if parser.has_section("hooks"):
        return parser["hooks"].get("directory", default) or default
    return default


def set_hooks_dir(directory: str) -> None:
    parser = _read_parser()
    if "hooks" not in parser:
        parser["hooks"] = {}
    parser["hooks"]["directory"] = directory or ""
    _write_parser(parser)


def get_custom_hooks() -> List[str]:
    """Пользовательские имена хуков (добавленные вручную к встроенному списку)."""
    parser = _read_parser()
    if parser.has_section("hooks"):
        raw = parser["hooks"].get("custom", "")
        return [x.strip() for x in raw.split(",") if x.strip()]
    return []


def set_custom_hooks(names: List[str]) -> None:
    parser = _read_parser()
    if "hooks" not in parser:
        parser["hooks"] = {}
    # запятая — разделитель; имена .so запятых не содержат
    parser["hooks"]["custom"] = ",".join(
        dict.fromkeys(n.strip() for n in names if n.strip()))
    _write_parser(parser)


def list_servers() -> List[ServerEntry]:
    """Вернуть список сохранённых серверов (в порядке секций ini)."""
    parser = _read_parser()
    out: List[ServerEntry] = []
    for section in parser.sections():
        if not section.startswith(SERVER_PREFIX):
            continue
        name = section[len(SERVER_PREFIX):]
        s = parser[section]
        out.append(ServerEntry(
            name=name,
            kind=s.get("kind", "api"),
            host4=s.get("host4", "127.0.0.1"),
            port4=s.get("port4", "8000"),
            tls=s.getboolean("tls", fallback=False),
            verify=s.getboolean("verify", fallback=True),
            username=s.get("username", ""),
            v6_enabled=s.getboolean("v6_enabled", fallback=False),
            host6=s.get("host6", "127.0.0.1"),
            port6=s.get("port6", "8001"),
            client_cert=s.get("client_cert", ""),
            client_key=s.get("client_key", ""),
            ca_cert=s.get("ca_cert", ""),
            directory=s.get("directory", ""),
        ))
    return out


def get_server(name: str) -> Optional[ServerEntry]:
    for s in list_servers():
        if s.name == name:
            return s
    return None


def save_server(entry: ServerEntry) -> None:
    """Добавить или обновить сервер по имени."""
    parser = _read_parser()
    section = SERVER_PREFIX + entry.name
    parser[section] = {
        "kind": entry.kind,
        "host4": entry.host4 or "",
        "port4": str(entry.port4 or ""),
        "tls": str(bool(entry.tls)).lower(),
        "verify": str(bool(entry.verify)).lower(),
        "username": entry.username or "",
        "v6_enabled": str(bool(entry.v6_enabled)).lower(),
        "host6": entry.host6 or "",
        "port6": str(entry.port6 or ""),
        "client_cert": entry.client_cert or "",
        "client_key": entry.client_key or "",
        "ca_cert": entry.ca_cert or "",
        "directory": entry.directory or "",
    }
    _write_parser(parser)


def remove_server(name: str) -> None:
    parser = _read_parser()
    section = SERVER_PREFIX + name
    if parser.has_section(section):
        parser.remove_section(section)
        _write_parser(parser)


def _write_parser(parser: configparser.ConfigParser) -> None:
    d = config_dir()
    try:
        os.makedirs(d, exist_ok=True)
        path = config_path()
        with open(path, "w", encoding="utf-8") as fh:
            parser.write(fh)
        # права 600 — на случай, если позже добавятся чувствительные поля
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        pass  # не критично: настройки просто не сохранятся
