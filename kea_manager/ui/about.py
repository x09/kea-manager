"""Диалог «О программе» с кликабельной гиперссылкой на сайт проекта."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from .. import __version__, KEA_TARGET_VERSION

PROJECT_URL = "https://github.com/x09/kea-manager"


class AboutDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title(_("О программе"))
        self.transient(master)
        self.resizable(False, False)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="kea-manager",
                  font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text=_("Версия {}").format(__version__)).pack(
            anchor="w")
        ttk.Label(
            frame,
            text=_("Редактор конфигурации Kea DHCP\n"
                   "Поддерживаемая версия Kea: {}").format(KEA_TARGET_VERSION),
            justify="left",
        ).pack(anchor="w", pady=(6, 12))

        ttk.Label(frame, text=_("Сайт проекта:")).pack(anchor="w")
        self.link = tk.Label(
            frame, text=PROJECT_URL, fg="#1565c0", cursor="hand2")
        self.link.pack(anchor="w")
        # подчёркивание для вида ссылки
        f = self.link.cget("font")
        self.link.configure(font=(f, 0, "underline") if isinstance(f, str) else f)
        self.link.bind("<Button-1>", self._open)
        self.link.bind("<Enter>", lambda e: self.link.configure(fg="#0d47a1"))
        self.link.bind("<Leave>", lambda e: self.link.configure(fg="#1565c0"))

        ttk.Button(frame, text=_("Закрыть"), command=self.destroy).pack(
            anchor="e", pady=(16, 0))

        self.bind("<Escape>", lambda e: self.destroy())

    def _open(self, _event=None):
        try:
            webbrowser.open(PROJECT_URL)
        except Exception:
            pass
