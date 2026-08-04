"""Диалог подключения к серверу Kea по control-channel (HTTP/HTTPS)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from ..model.backend import Endpoint, ApiBackend

PAD = {"padx": 6, "pady": 4}


class ConnectDialog(tk.Toplevel):
    """Сбор параметров подключения к DHCPv4 и (опц.) DHCPv6 по HTTP(S)."""

    def __init__(self, master, initial: Optional[dict] = None):
        super().__init__(master)
        self.title(_("Подключиться к серверу Kea по API"))
        self.transient(master)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.result: Optional[ApiBackend] = None
        ini = initial or {}

        # -- общие параметры транспорта
        gen = ttk.LabelFrame(self, text=_("Транспорт"), padding=8)
        gen.grid(row=0, column=0, sticky="we", **PAD)

        self.tls_var = tk.BooleanVar(value=bool(ini.get("tls", False)))
        ttk.Checkbutton(gen, text=_("Использовать HTTPS (TLS)"),
                        variable=self.tls_var).grid(
            row=0, column=0, columnspan=2, sticky="w", **PAD)
        self.verify_var = tk.BooleanVar(value=bool(ini.get("verify", True)))
        ttk.Checkbutton(gen, text=_("Проверять сертификат (для HTTPS)"),
                        variable=self.verify_var).grid(
            row=1, column=0, columnspan=2, sticky="w", **PAD)

        ttk.Label(gen, text=_("Логин:")).grid(row=2, column=0, sticky="w", **PAD)
        self.user_var = tk.StringVar(value=ini.get("username", ""))
        ttk.Entry(gen, textvariable=self.user_var, width=24).grid(
            row=2, column=1, sticky="w", **PAD)
        ttk.Label(gen, text=_("Пароль:")).grid(row=3, column=0, sticky="w", **PAD)
        self.pass_var = tk.StringVar()
        ttk.Entry(gen, textvariable=self.pass_var, show="*", width=24).grid(
            row=3, column=1, sticky="w", **PAD)

        # -- DHCPv4
        f4 = ttk.LabelFrame(self, text=_("DHCPv4 (обязательно)"), padding=8)
        f4.grid(row=1, column=0, sticky="we", **PAD)
        ttk.Label(f4, text=_("Хост:")).grid(row=0, column=0, sticky="w", **PAD)
        self.host4_var = tk.StringVar(value=ini.get("host4", "127.0.0.1"))
        ttk.Entry(f4, textvariable=self.host4_var, width=22).grid(
            row=0, column=1, sticky="w", **PAD)
        ttk.Label(f4, text=_("Порт:")).grid(row=0, column=2, sticky="w", **PAD)
        self.port4_var = tk.StringVar(value=str(ini.get("port4", "8000")))
        ttk.Entry(f4, textvariable=self.port4_var, width=8).grid(
            row=0, column=3, sticky="w", **PAD)

        # -- DHCPv6
        f6 = ttk.LabelFrame(self, text=_("DHCPv6 (необязательно)"), padding=8)
        f6.grid(row=2, column=0, sticky="we", **PAD)
        self.v6_var = tk.BooleanVar(value=bool(ini.get("v6_enabled", False)))
        ttk.Checkbutton(f6, text=_("Подключаться к DHCPv6"),
                        variable=self.v6_var).grid(
            row=0, column=0, columnspan=4, sticky="w", **PAD)
        ttk.Label(f6, text=_("Хост:")).grid(row=1, column=0, sticky="w", **PAD)
        self.host6_var = tk.StringVar(value=ini.get("host6", "127.0.0.1"))
        ttk.Entry(f6, textvariable=self.host6_var, width=22).grid(
            row=1, column=1, sticky="w", **PAD)
        ttk.Label(f6, text=_("Порт:")).grid(row=1, column=2, sticky="w", **PAD)
        self.port6_var = tk.StringVar(value=str(ini.get("port6", "8001")))
        ttk.Entry(f6, textvariable=self.port6_var, width=8).grid(
            row=1, column=3, sticky="w", **PAD)

        hint = ttk.Label(
            self,
            text=_("DHCPv4 и DHCPv6 должны слушать разные адрес/порт. "
                 "Логин/пароль — при включённой аутентификации control-socket."),
            foreground="#546e7a", wraplength=420, justify="left")
        hint.grid(row=3, column=0, sticky="w", **PAD)

        row = ttk.Frame(self)
        row.grid(row=4, column=0, sticky="we", **PAD)
        ttk.Button(row, text=_("Проверить соединение"),
                   command=self._test_connection).pack(side="left")
        ttk.Button(row, text=_("Подключиться"), command=self._ok).pack(
            side="right", padx=4)
        ttk.Button(row, text=_("Отмена"), command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())

    def _test_connection(self):
        """Проверить доступность DHCPv4-эндпоинта без загрузки конфигурации."""
        ep = self._make_endpoint(self.host4_var.get(), self.port4_var.get())
        if ep is None:
            return
        from ..util import ctrlsocket
        client = ep.client(timeout=8)
        try:
            ver = client.send_command("version-get")
        except ctrlsocket.CommandError as exc:
            messagebox.showerror(
                _("Проверка соединения"),
                _("Сервер вернул ошибку: {}").format(exc.text or exc),
                parent=self)
            return
        except ctrlsocket.ControlSocketError as exc:
            messagebox.showerror(
                _("Проверка соединения"),
                _("Не удалось подключиться:\n{}").format(exc), parent=self)
            return

        version = ver.get("text", "").splitlines()[0] if ver.get("text") else "?"
        # проверим доступность команд управления арендами
        lease_v4 = lease_v6 = False
        try:
            cmds = client.list_commands()
            lease_v4 = "lease4-del" in cmds
            lease_v6 = "lease6-del" in cmds
        except (ctrlsocket.ControlSocketError, ctrlsocket.CommandError):
            cmds = []

        lease_note = (_("да") if lease_v4 else _("нет")) + \
            (_(" (есть и lease6)") if lease_v6 else "")
        messagebox.showinfo(
            _("Проверка соединения"),
            _("Подключение успешно: {}\n\n"
              "Версия Kea: {}\n"
              "Команд доступно: {}\n"
              "Управление арендами (lease_cmds): {}").format(
                  ep.label(), version, len(cmds), lease_note),
            parent=self)

    def _make_endpoint(self, host: str, port_str: str) -> Optional[Endpoint]:
        host = host.strip()
        if not host:
            messagebox.showerror(_("Ошибка"), _("Не задан хост"), parent=self)
            return None
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror(
                _("Ошибка"),
                _("Некорректный порт: {!r}").format(port_str), parent=self)
            return None
        return Endpoint(
            host=host, port=port, use_tls=self.tls_var.get(),
            username=self.user_var.get().strip() or None,
            password=self.pass_var.get() or None,
            verify=self.verify_var.get())

    def values(self) -> dict:
        """Текущие значения полей (для сохранения настроек, без пароля)."""
        return {
            "tls": self.tls_var.get(),
            "verify": self.verify_var.get(),
            "username": self.user_var.get().strip(),
            "host4": self.host4_var.get().strip(),
            "port4": self.port4_var.get().strip(),
            "v6_enabled": self.v6_var.get(),
            "host6": self.host6_var.get().strip(),
            "port6": self.port6_var.get().strip(),
        }

    def _ok(self):
        ep4 = self._make_endpoint(self.host4_var.get(), self.port4_var.get())
        if ep4 is None:
            return
        ep6 = None
        if self.v6_var.get():
            ep6 = self._make_endpoint(self.host6_var.get(), self.port6_var.get())
            if ep6 is None:
                return
        self.result = ApiBackend(ep4, ep6)
        self.destroy()
