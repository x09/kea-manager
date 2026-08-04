"""Бэкенды источника конфигурации: файлы и API Kea.

Редактор поддерживает два способа работы с конфигурацией:

  * FileBackend — чтение/запись conf-файлов на диске (офлайн-режим).
    Работает даже при остановленной службе Kea, сохраняет неизвестные
    ключи round-trip.

  * ApiBackend — управление живым сервером Kea по control-channel
    (HTTP/HTTPS). Использует команды config-get / config-test /
    config-set / config-write. Позволяет подключаться с удалённой машины.

Оба бэкенда возвращают/принимают ``DhcpConfig`` — доменная модель и UI не
зависят от способа доступа.

Замечания по ApiBackend:
  * config-get не возвращает комментарии и разворачивает file-inclusion —
    это осознанное ограничение (для API-режима комментарии неважны).
  * config-set применяет конфигурацию в память немедленно (без рестарта);
    config-write сохраняет её на диск сервера.
  * Каждая служба (DHCPv4/DHCPv6) — отдельный HTTP-эндпоинт.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .config import DhcpConfig, KeaProject, ROOT_BY_FAMILY
from ..util import ctrlsocket


# ==========================================================================
# Файловый бэкенд
# ==========================================================================

class FileBackend:
    """Офлайн-режим: работа с conf-файлами в каталоге."""

    kind = "file"

    def __init__(self, directory: str):
        self.directory = directory

    def load(self) -> KeaProject:
        return KeaProject.load_dir(self.directory)

    def save(self, project: KeaProject) -> List[str]:
        return project.save_dir(self.directory)

    def describe(self) -> str:
        return f"файлы: {self.directory}"


# ==========================================================================
# API-бэкенд
# ==========================================================================

@dataclass
class Endpoint:
    """Параметры подключения к одной службе Kea по HTTP(S)."""
    host: str = "127.0.0.1"
    port: int = 8000
    use_tls: bool = False
    username: Optional[str] = None
    password: Optional[str] = None
    verify: bool = True

    def client(self, timeout: float = 10.0) -> ctrlsocket.KeaHttpClient:
        return ctrlsocket.KeaHttpClient(
            self.host, self.port, use_tls=self.use_tls,
            username=self.username, password=self.password,
            timeout=timeout, verify=self.verify)

    def label(self) -> str:
        scheme = "https" if self.use_tls else "http"
        return f"{scheme}://{self.host}:{self.port}"


class ApiBackend:
    """Онлайн-режим: управление живым сервером Kea по control-channel."""

    kind = "api"

    def __init__(self, ep_v4: Endpoint,
                 ep_v6: Optional[Endpoint] = None,
                 timeout: float = 10.0):
        self.ep_v4 = ep_v4
        self.ep_v6 = ep_v6
        self.timeout = timeout

    # -- получение конфигурации ------------------------------------------

    def _config_get(self, ep: Endpoint, family: int) -> DhcpConfig:
        client = ep.client(self.timeout)
        resp = client.send_command("config-get")
        args = resp.get("arguments")
        if not isinstance(args, dict):
            raise ctrlsocket.ControlSocketError(
                "config-get вернул неожиданный формат arguments")
        rootkey = ROOT_BY_FAMILY[family]
        if rootkey not in args:
            raise ctrlsocket.ControlSocketError(
                f"В ответе config-get нет секции {rootkey}")
        # config-get добавляет служебные ключи (напр. "hash" — контрольная
        # сумма конфигурации), которые config-set/config-test не принимают
        # ("Unsupported 'hash' parameter"). Отбрасываем их, оставляя только
        # секции-конфигурации служб.
        for junk in ("hash", "Hash"):
            args.pop(junk, None)
        # args теперь содержит {"Dhcp4": {...}} (+ возможно Logging и т.п.)
        return DhcpConfig(family=family, root=args, configured=True)

    def load(self) -> KeaProject:
        dhcp4 = self._config_get(self.ep_v4, 4)
        dhcp6 = None
        if self.ep_v6 is not None:
            dhcp6 = self._config_get(self.ep_v6, 6)
        proj = KeaProject(dhcp4=dhcp4, dhcp6=dhcp6)
        proj.backend = self
        return proj

    # -- применение конфигурации -----------------------------------------

    def _apply_one(self, ep: Endpoint, cfg: DhcpConfig,
                   write: bool = True, test_first: bool = True) -> str:
        client = ep.client(self.timeout)
        rootkey = cfg.rootkey
        # аргумент команды — тело {"Dhcp4": {...}}; передаём весь root,
        # чтобы сохранить соседние секции (Logging и пр.)
        arguments = cfg.root

        if test_first:
            client.send_command("config-test", arguments)
        client.send_command("config-set", arguments)
        text = f"{rootkey}: конфигурация применена (config-set)"
        if write:
            wresp = client.send_command("config-write")
            wtext = wresp.get("text", "")
            text += f"; сохранена на диск (config-write){': ' + wtext if wtext else ''}"
        return text

    def save(self, project: KeaProject,
             write: bool = True) -> List[str]:
        """Применить конфигурацию обеих служб на сервер.

        Возвращает список текстовых результатов по каждой службе.
        """
        results = [self._apply_one(self.ep_v4, project.dhcp4, write=write)]
        if project.dhcp6_configured and self.ep_v6 is not None:
            results.append(
                self._apply_one(self.ep_v6, project.dhcp6, write=write))
        return results

    def describe(self) -> str:
        s = f"API: {self.ep_v4.label()}"
        if self.ep_v6 is not None:
            s += f", {self.ep_v6.label()}"
        return s

    # -- аренды через API ------------------------------------------------

    def lease_client(self, family: int) -> ctrlsocket.KeaHttpClient:
        ep = self.ep_v4 if family == 4 else (self.ep_v6 or self.ep_v4)
        return ep.client(self.timeout)
