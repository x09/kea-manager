"""Модель конфигурации Kea с сохранением неизвестных ключей (round-trip).

Философия round-trip
--------------------
Редактор НЕ строит собственную типизированную модель поверх конфигурации.
Вместо этого он хранит полный распарсенный ``dict`` ровно так, как он был
прочитан из файла, и предоставляет удобные методы доступа к отдельным
секциям (subnet4, pools, таймеры и т.д.). Любые ключи, которые редактор
не знает, остаются в словаре нетронутыми и записываются обратно при
сохранении. Это защищает реальные конфигурации от потери ручных настроек.

Классы
------
- ``DhcpConfig``  — одна служба (Dhcp4 или Dhcp6), обёртка над её dict.
- ``KeaProject``  — проект целиком: две службы + пути к файлам.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Optional

from ..util import jsonc


# Корневой ключ службы -> имя семейства
FAMILY_BY_ROOT = {"Dhcp4": 4, "Dhcp6": 6}
ROOT_BY_FAMILY = {4: "Dhcp4", 6: "Dhcp6"}
SUBNET_KEY = {4: "subnet4", 6: "subnet6"}


class DhcpConfig:
    """Обёртка над конфигурацией одной службы (kea-dhcp4 или kea-dhcp6).

    Хранит:
      - ``root``: полный dict файла, например {"Dhcp4": {...}} плюс, возможно,
        соседние секции верхнего уровня (Logging и т.п.), которые нужно
        сохранить как есть.
      - ``family``: 4 или 6.
      - ``path``: путь к файлу (может быть None для новой конфигурации).
      - ``configured``: считается ли служба «настроенной» (для отметки в дереве).
    """

    def __init__(self, family: int, root: Optional[Dict[str, Any]] = None,
                 path: Optional[str] = None, configured: bool = False):
        if family not in ROOT_BY_FAMILY:
            raise ValueError(f"family должен быть 4 или 6, получен {family!r}")
        self.family = family
        self.path = path
        self.configured = configured
        self.root: Dict[str, Any] = root if root is not None else self._empty_root()

    # -- построение / загрузка -------------------------------------------

    def _empty_root(self) -> Dict[str, Any]:
        rootkey = ROOT_BY_FAMILY[self.family]
        return {rootkey: {SUBNET_KEY[self.family]: []}}

    @classmethod
    def new(cls, family: int) -> "DhcpConfig":
        """Создать пустую, но помеченную как настроенную конфигурацию."""
        return cls(family=family, configured=True)

    @classmethod
    def load(cls, path: str, family: int) -> "DhcpConfig":
        """Загрузить конфигурацию из файла (round-trip)."""
        data = jsonc.load(path)
        if not isinstance(data, dict):
            raise ValueError("Ожидался JSON-объект на верхнем уровне")
        rootkey = ROOT_BY_FAMILY[family]
        if rootkey not in data:
            raise ValueError(
                f"В файле {path!r} отсутствует секция {rootkey!r}"
            )
        return cls(family=family, root=data, path=path, configured=True)

    # -- сохранение -------------------------------------------------------

    def save(self, path: Optional[str] = None) -> str:
        """Сохранить конфигурацию в файл в формате JSON."""
        target = path or self.path
        if not target:
            raise ValueError("Не задан путь для сохранения")
        jsonc.dump(self.root, target)
        self.path = target
        return target

    def to_json(self) -> str:
        return jsonc.dumps(self.root)

    # -- доступ к телу службы --------------------------------------------

    @property
    def rootkey(self) -> str:
        return ROOT_BY_FAMILY[self.family]

    @property
    def dhcp(self) -> Dict[str, Any]:
        """Тело секции Dhcp4/Dhcp6 (создаётся при отсутствии)."""
        body = self.root.setdefault(self.rootkey, {})
        if not isinstance(body, dict):
            raise ValueError(f"Секция {self.rootkey} должна быть объектом")
        return body

    # -- глобальные таймеры аренды ---------------------------------------

    def get_global(self, key: str, default: Any = None) -> Any:
        return self.dhcp.get(key, default)

    def set_global(self, key: str, value: Any) -> None:
        if value is None:
            self.dhcp.pop(key, None)
        else:
            self.dhcp[key] = value

    # -- подсети ----------------------------------------------------------

    @property
    def subnet_key(self) -> str:
        return SUBNET_KEY[self.family]

    def subnets(self) -> List[Dict[str, Any]]:
        return self.dhcp.setdefault(self.subnet_key, [])

    def next_subnet_id(self) -> int:
        """Вернуть свободный числовой id для новой подсети."""
        used = {s.get("id") for s in self.subnets() if isinstance(s.get("id"), int)}
        i = 1
        while i in used:
            i += 1
        return i

    def add_subnet(self, subnet_cidr: str, subnet_id: Optional[int] = None,
                   pools: Optional[List[str]] = None) -> Dict[str, Any]:
        """Добавить новую подсеть. Возвращает созданный dict подсети."""
        if subnet_id is None:
            subnet_id = self.next_subnet_id()
        entry: Dict[str, Any] = {"id": subnet_id, "subnet": subnet_cidr}
        if pools:
            entry["pools"] = [{"pool": p} for p in pools]
        self.subnets().append(entry)
        return entry

    def remove_subnet(self, index: int) -> None:
        subs = self.subnets()
        if 0 <= index < len(subs):
            del subs[index]
        else:
            raise IndexError(f"Нет подсети с индексом {index}")

    # -- пулы конкретной подсети -----------------------------------------

    @staticmethod
    def pools_of(subnet: Dict[str, Any]) -> List[Dict[str, Any]]:
        return subnet.setdefault("pools", [])

    @staticmethod
    def add_pool(subnet: Dict[str, Any], pool: str,
                 client_class: Optional[str] = None) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"pool": pool}
        if client_class:
            entry["client-class"] = client_class
        DhcpConfig.pools_of(subnet).append(entry)
        return entry

    @staticmethod
    def remove_pool(subnet: Dict[str, Any], index: int) -> None:
        pools = DhcpConfig.pools_of(subnet)
        if 0 <= index < len(pools):
            del pools[index]
        else:
            raise IndexError(f"Нет пула с индексом {index}")

    # -- резервирования конкретной подсети (этап 2) ----------------------

    @staticmethod
    def reservations_of(subnet: Dict[str, Any]) -> List[Dict[str, Any]]:
        return subnet.setdefault("reservations", [])

    @staticmethod
    def add_reservation(subnet: Dict[str, Any], hw_address: str,
                        ip_address: Optional[str] = None,
                        hostname: Optional[str] = None) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"hw-address": hw_address}
        if ip_address:
            entry["ip-address"] = ip_address
        if hostname:
            entry["hostname"] = hostname
        DhcpConfig.reservations_of(subnet).append(entry)
        return entry

    @staticmethod
    def update_reservation(subnet: Dict[str, Any], index: int,
                           hw_address: str,
                           ip_address: Optional[str] = None,
                           hostname: Optional[str] = None) -> Dict[str, Any]:
        res = DhcpConfig.reservations_of(subnet)
        if not (0 <= index < len(res)):
            raise IndexError(f"Нет резервирования с индексом {index}")
        entry = res[index]
        entry["hw-address"] = hw_address
        # ip-address / hostname: задать либо убрать
        if ip_address:
            entry["ip-address"] = ip_address
        else:
            entry.pop("ip-address", None)
        if hostname:
            entry["hostname"] = hostname
        else:
            entry.pop("hostname", None)
        return entry

    @staticmethod
    def remove_reservation(subnet: Dict[str, Any], index: int) -> None:
        res = DhcpConfig.reservations_of(subnet)
        if 0 <= index < len(res):
            del res[index]
        else:
            raise IndexError(f"Нет резервирования с индексом {index}")

    # -- DHCP-опции (этап 3): option-data на уровне службы и подсети ------

    def global_options(self) -> List[Dict[str, Any]]:
        """option-data в теле службы (глобальные опции)."""
        return self.dhcp.setdefault("option-data", [])

    @staticmethod
    def options_of(container: Dict[str, Any]) -> List[Dict[str, Any]]:
        """option-data произвольного контейнера (подсеть, пул, класс)."""
        return container.setdefault("option-data", [])

    @staticmethod
    def set_option(container: Dict[str, Any], name: str, data: str,
                   always_send: Optional[bool] = None) -> Dict[str, Any]:
        """Добавить или обновить опцию по имени в option-data контейнера."""
        opts = DhcpConfig.options_of(container)
        entry = None
        for o in opts:
            if o.get("name") == name:
                entry = o
                break
        if entry is None:
            entry = {"name": name}
            opts.append(entry)
        entry["data"] = data
        if always_send is not None:
            if always_send:
                entry["always-send"] = True
            else:
                entry.pop("always-send", None)
        return entry

    @staticmethod
    def remove_option(container: Dict[str, Any], index: int) -> None:
        opts = DhcpConfig.options_of(container)
        if 0 <= index < len(opts):
            del opts[index]
        else:
            raise IndexError(f"Нет опции с индексом {index}")

    # -- служебное --------------------------------------------------------

    def clone(self) -> "DhcpConfig":
        return DhcpConfig(
            family=self.family,
            root=copy.deepcopy(self.root),
            path=self.path,
            configured=self.configured,
        )


class KeaProject:
    """Проект целиком: обе службы DHCPv4 и DHCPv6.

    Служба DHCPv6 может быть «не сконфигурирована» — в этом случае её файл
    не создаётся, а в дереве UI узел IPv6 помечается особой пиктограммой.
    """

    DEFAULT_V4_NAME = "kea-dhcp4.conf"
    DEFAULT_V6_NAME = "kea-dhcp6.conf"

    def __init__(self, dhcp4: Optional[DhcpConfig] = None,
                 dhcp6: Optional[DhcpConfig] = None,
                 directory: Optional[str] = None):
        # DHCPv4 существует всегда (базовый сценарий проекта)
        self.dhcp4 = dhcp4 or DhcpConfig.new(4)
        # DHCPv6 может быть None -> не сконфигурирована
        self.dhcp6 = dhcp6
        self.directory = directory
        # Активный бэкенд (FileBackend или ApiBackend). Для офлайн-режима,
        # загруженного через load_dir, остаётся None до явной установки.
        self.backend = None

    # -- признаки состояния ----------------------------------------------

    @property
    def dhcp6_configured(self) -> bool:
        return self.dhcp6 is not None and self.dhcp6.configured

    def enable_dhcp6(self) -> DhcpConfig:
        """Включить конфигурирование DHCPv6 (создать пустую конфигурацию)."""
        if self.dhcp6 is None:
            self.dhcp6 = DhcpConfig.new(6)
        else:
            self.dhcp6.configured = True
        return self.dhcp6

    def disable_dhcp6(self) -> None:
        """Пометить DHCPv6 как не конфигурируемую (файл не будет записан)."""
        if self.dhcp6 is not None:
            self.dhcp6.configured = False

    # -- загрузка / сохранение -------------------------------------------

    @classmethod
    def load_dir(cls, directory: str,
                 v4_name: Optional[str] = None,
                 v6_name: Optional[str] = None) -> "KeaProject":
        """Загрузить проект из каталога с conf-файлами."""
        v4_name = v4_name or cls.DEFAULT_V4_NAME
        v6_name = v6_name or cls.DEFAULT_V6_NAME
        v4_path = os.path.join(directory, v4_name)
        v6_path = os.path.join(directory, v6_name)

        dhcp4 = (DhcpConfig.load(v4_path, 4)
                 if os.path.isfile(v4_path) else DhcpConfig.new(4))
        dhcp6 = DhcpConfig.load(v6_path, 6) if os.path.isfile(v6_path) else None
        return cls(dhcp4=dhcp4, dhcp6=dhcp6, directory=directory)

    def save_dir(self, directory: Optional[str] = None) -> List[str]:
        """Сохранить обе службы. DHCPv6 записывается только если настроена.

        Возвращает список записанных путей.
        """
        directory = directory or self.directory
        if not directory:
            raise ValueError("Не задан каталог для сохранения")
        os.makedirs(directory, exist_ok=True)
        written = []

        v4_path = self.dhcp4.path or os.path.join(directory, self.DEFAULT_V4_NAME)
        self.dhcp4.save(v4_path)
        written.append(v4_path)

        if self.dhcp6_configured:
            v6_path = self.dhcp6.path or os.path.join(directory, self.DEFAULT_V6_NAME)
            self.dhcp6.save(v6_path)
            written.append(v6_path)

        self.directory = directory
        return written

    def service(self, family: int) -> Optional[DhcpConfig]:
        return self.dhcp4 if family == 4 else self.dhcp6
