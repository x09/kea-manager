"""Клиент управляющего сокета Kea (unix domain socket).

Kea DHCP-серверы принимают команды в формате JSON через UNIX-сокет,
настроенный параметром ``control-socket`` (или ``control-sockets`` в
новых версиях). Команда имеет вид::

    {"command": "lease4-del", "arguments": {"ip-address": "192.0.2.10"}}

Ответ — JSON: либо map ``{"result": 0, "text": "..."}``, либо список из
одного такого map. Значения ``result``:
    0  успех
    1  ошибка
    2  команда не поддерживается (нет hook-библиотеки)
    3  запрошенный объект не найден (пустой результат)

Удаление аренд (``lease4-del`` / ``lease6-del``) требует загруженной в Kea
hook-библиотеки ``libdhcp_lease_cmds``. Если она не загружена, сервер
вернёт result==2.

Используется только стандартная библиотека (``socket``, ``json``).
"""

from __future__ import annotations

import json
import socket
from typing import Any, Dict, List, Optional

# Значения поля result в ответах Kea
RESULT_SUCCESS = 0
RESULT_ERROR = 1
RESULT_UNSUPPORTED = 2
RESULT_EMPTY = 3


class ControlSocketError(Exception):
    """Ошибка связи с управляющим сокетом Kea."""


class CommandError(Exception):
    """Kea вернула ошибочный результат на команду."""

    def __init__(self, result: int, text: str):
        self.result = result
        self.text = text
        super().__init__(f"[result={result}] {text}")


def normalize_response(raw: str) -> Dict[str, Any]:
    """Разобрать сырой JSON-ответ Kea и вернуть первый map-ответ.

    Ответ может быть map ``{"result":0,...}`` или списком таких map
    (обёртка при обращении к нескольким службам). Бросает
    ControlSocketError при некорректном формате.
    """
    if not raw:
        raise ControlSocketError("Пустой ответ от сервера")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ControlSocketError(
            f"Некорректный JSON в ответе: {exc}: {raw[:200]!r}") from exc

    if isinstance(parsed, list):
        if not parsed:
            raise ControlSocketError("Пустой список в ответе")
        resp = parsed[0]
    else:
        resp = parsed
    if not isinstance(resp, dict):
        raise ControlSocketError(f"Неожиданный формат ответа: {resp!r}")
    return resp


class KeaClientBase:
    """Общая логика команд Kea; транспорт задаётся в ``_send_raw``.

    Подклассы реализуют ``_send_raw(payload: str) -> str`` для конкретного
    транспорта (unix-сокет либо HTTP). Вся высокоуровневая семантика команд
    и обработка кодов result — здесь.
    """

    def _send_raw(self, payload: str) -> str:  # pragma: no cover - абстракция
        raise NotImplementedError

    def send_command(self, command: str,
                     arguments: Optional[Dict[str, Any]] = None,
                     service: Optional[List[str]] = None) -> Dict[str, Any]:
        """Отправить команду и вернуть нормализованный map-ответ.

        Бросает ControlSocketError при проблемах связи и CommandError при
        result != 0 (кроме RESULT_EMPTY, который возвращается как есть).
        """
        req: Dict[str, Any] = {"command": command}
        if arguments is not None:
            req["arguments"] = arguments
        if service:
            req["service"] = service

        raw = self._send_raw(json.dumps(req))
        resp = normalize_response(raw)
        result = resp.get("result", RESULT_ERROR)
        if result not in (RESULT_SUCCESS, RESULT_EMPTY):
            raise CommandError(result, resp.get("text", ""))
        return resp

    # -- высокоуровневые операции ----------------------------------------

    def list_commands(self) -> List[str]:
        """Получить список поддерживаемых команд (для проверки lease_cmds)."""
        resp = self.send_command("list-commands")
        args = resp.get("arguments", [])
        return args if isinstance(args, list) else []

    def has_lease_cmds(self, family: int = 4) -> bool:
        """Проверить, доступна ли команда удаления аренды (hook lease_cmds)."""
        cmd = "lease4-del" if family == 4 else "lease6-del"
        try:
            return cmd in self.list_commands()
        except (ControlSocketError, CommandError):
            return False

    def lease_del(self, family: int, ip_address: str) -> str:
        """Удалить аренду по IP-адресу. Возвращает текст ответа Kea.

        Бросает CommandError, если аренда не найдена или hook не загружен.
        """
        cmd = "lease4-del" if family == 4 else "lease6-del"
        resp = self.send_command(cmd, {"ip-address": ip_address})
        if resp.get("result") == RESULT_EMPTY:
            raise CommandError(RESULT_EMPTY,
                               resp.get("text", "Аренда не найдена"))
        return resp.get("text", "")


class KeaControlSocket(KeaClientBase):
    """Синхронный клиент unix control-socket Kea."""

    def __init__(self, path: str, timeout: float = 5.0):
        self.path = path
        self.timeout = timeout

    def _send_raw(self, payload: str) -> str:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        except AttributeError as exc:  # AF_UNIX недоступен (напр. Windows)
            raise ControlSocketError(
                "UNIX-сокеты не поддерживаются на этой платформе") from exc
        sock.settimeout(self.timeout)
        try:
            try:
                sock.connect(self.path)
            except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
                raise ControlSocketError(
                    f"Не удалось подключиться к сокету {self.path!r}: {exc}"
                ) from exc

            sock.sendall(payload.encode("utf-8"))
            # Kea не всегда закрывает соединение сразу; читаем до EOF или
            # пока не разберём корректный JSON.
            try:
                sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            chunks: List[bytes] = []
            while True:
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    break
                if not data:
                    break
                chunks.append(data)
                buf = b"".join(chunks).decode("utf-8", errors="replace").strip()
                if buf:
                    try:
                        json.loads(buf)
                        return buf
                    except json.JSONDecodeError:
                        continue
            return b"".join(chunks).decode("utf-8", errors="replace").strip()
        finally:
            sock.close()


class KeaHttpClient(KeaClientBase):
    """Клиент control-channel Kea по HTTP/HTTPS.

    В Kea 3.2.0 DHCP-серверы принимают команды напрямую по HTTP(S)
    (control-sockets с socket-type http/https), без отдельного
    Control Agent. Команда отправляется POST-запросом с телом JSON и
    Content-Type application/json.

    Поддерживается базовая аутентификация (basic-auth). Для HTTPS можно
    отключить проверку сертификата (verify=False) — удобно для
    самоподписанных сертификатов в доверенной сети.
    """

    def __init__(self, host: str, port: int, use_tls: bool = False,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 timeout: float = 10.0, verify: bool = True,
                 path: str = "/"):
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.username = username
        self.password = password
        self.timeout = timeout
        self.verify = verify
        self.path = path or "/"

    def _auth_header(self) -> Optional[str]:
        if not self.username:
            return None
        import base64
        token = f"{self.username}:{self.password or ''}".encode("utf-8")
        return "Basic " + base64.b64encode(token).decode("ascii")

    def _send_raw(self, payload: str) -> str:
        import http.client

        if self.use_tls:
            import ssl
            if self.verify:
                ctx = ssl.create_default_context()
            else:
                ctx = ssl._create_unverified_context()
            conn = http.client.HTTPSConnection(
                self.host, self.port, timeout=self.timeout, context=ctx)
        else:
            conn = http.client.HTTPConnection(
                self.host, self.port, timeout=self.timeout)

        headers = {"Content-Type": "application/json",
                   "Accept": "application/json"}
        auth = self._auth_header()
        if auth:
            headers["Authorization"] = auth

        try:
            conn.request("POST", self.path, body=payload.encode("utf-8"),
                         headers=headers)
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status == 401:
                raise ControlSocketError(
                    "Ошибка авторизации (401): проверьте логин и пароль")
            if resp.status >= 400:
                raise ControlSocketError(
                    f"HTTP {resp.status} {resp.reason}: {body[:200]}")
            return body.strip()
        except ControlSocketError:
            raise
        except OSError as exc:
            raise ControlSocketError(
                f"Не удалось подключиться к {self.host}:{self.port}: {exc}"
            ) from exc
        finally:
            conn.close()


def guess_socket_path(dhcp_body: dict) -> Optional[str]:
    """Определить путь control-socket из тела конфигурации службы.

    Поддерживает старый ключ ``control-socket`` (map) и новый
    ``control-sockets`` (список). Возвращает socket-name типа unix.
    """
    if not isinstance(dhcp_body, dict):
        return None
    cs = dhcp_body.get("control-socket")
    if isinstance(cs, dict) and cs.get("socket-type") == "unix":
        return cs.get("socket-name")
    css = dhcp_body.get("control-sockets")
    if isinstance(css, list):
        for entry in css:
            if isinstance(entry, dict) and entry.get("socket-type") == "unix":
                return entry.get("socket-name")
    return None
