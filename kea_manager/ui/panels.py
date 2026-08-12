"""Панели редактирования правой части окна.

Каждая панель — это ttk.Frame, который умеет:
  - ``load(...)``  наполнить поля из модели;
  - ``apply()``    записать значения обратно в модель (с валидацией).

Панели не знают про дерево — они лишь получают ссылки на объекты модели и
вызывают колбэк ``on_change`` при успешном изменении, чтобы главное окно
могло обновить заголовки/дерево и пометить проект как изменённый.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Callable, Dict, Optional

from ..model import DhcpConfig
from ..model import options as opts
from ..model import leases as leasemod
from ..model import ha as hamod
from ..model import classes as classmod
from ..model import hooks as hooksmod
from ..model import statistics as statmod
from ..util import settings
from ..util import validators as V
from ..util import ctrlsocket
from . import inputmask


PAD = {"padx": 6, "pady": 4}


class BasePanel(ttk.Frame):
    def __init__(self, master, on_change: Optional[Callable[[], None]] = None):
        super().__init__(master, padding=12)
        self.on_change = on_change or (lambda: None)

    def _notify(self):
        self.on_change()


class WelcomePanel(BasePanel):
    """Заставка, когда ничего не выбрано."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        ttk.Label(
            self,
            text="kea-manager",
            font=("TkDefaultFont", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            self,
            text=_("Выберите узел в дереве слева, чтобы редактировать "
                 "конфигурацию.\n\nСервер → IPv4 / IPv6 → подсети и пулы."),
            justify="left",
        ).pack(anchor="w", pady=(8, 0))


class ServicePanel(BasePanel):
    """Общие (глобальные) настройки службы DHCPv4/DHCPv6."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.cfg: Optional[DhcpConfig] = None

        self.title_var = tk.StringVar()
        ttk.Label(self, textvariable=self.title_var,
                  font=("TkDefaultFont", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", **PAD)

        self.vars: Dict[str, tk.StringVar] = {}
        rows = [
            ("valid-lifetime", _("Время аренды, сек (valid-lifetime):")),
            ("renew-timer", _("Renew timer, сек (T1):")),
            ("rebind-timer", _("Rebind timer, сек (T2):")),
        ]
        for i, (key, label) in enumerate(rows, start=1):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", **PAD)
            var = tk.StringVar()
            self.vars[key] = var
            ttk.Entry(self, textvariable=var, width=18).grid(
                row=i, column=1, sticky="w", **PAD)

        ttk.Label(self, text=_("Интерфейсы (через запятую):")).grid(
            row=4, column=0, sticky="w", **PAD)
        self.interfaces_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.interfaces_var, width=32).grid(
            row=4, column=1, sticky="w", **PAD)

        ttk.Button(self, text=_("Применить"), command=self.apply).grid(
            row=5, column=0, sticky="w", **PAD)

    def load(self, cfg: DhcpConfig):
        self.cfg = cfg
        fam = "IPv4" if cfg.family == 4 else "IPv6"
        self.title_var.set(_("Общие настройки службы DHCP {}").format(fam))
        for key, var in self.vars.items():
            val = cfg.get_global(key)
            var.set("" if val is None else str(val))
        ic = cfg.get_global("interfaces-config", {}) or {}
        ifaces = ic.get("interfaces", []) if isinstance(ic, dict) else []
        self.interfaces_var.set(", ".join(ifaces))

    def apply(self):
        if self.cfg is None:
            return
        vl = self.vars["valid-lifetime"].get().strip()
        rt = self.vars["renew-timer"].get().strip()
        rbt = self.vars["rebind-timer"].get().strip()
        if vl:
            ok, msg = V.validate_lease_timers(vl, rt or None, rbt or None)
            if not ok:
                messagebox.showerror(_("Ошибка"), msg)
                return
        # запись
        self.cfg.set_global("valid-lifetime", int(vl) if vl else None)
        self.cfg.set_global("renew-timer", int(rt) if rt else None)
        self.cfg.set_global("rebind-timer", int(rbt) if rbt else None)

        raw = self.interfaces_var.get().strip()
        ifaces = [x.strip() for x in raw.split(",") if x.strip()]
        if ifaces:
            ic = self.cfg.get_global("interfaces-config")
            if not isinstance(ic, dict):
                ic = {}
            ic["interfaces"] = ifaces
            self.cfg.set_global("interfaces-config", ic)
        self._notify()
        messagebox.showinfo(_("Готово"), _("Общие настройки применены."))


class SubnetPanel(BasePanel):
    """Редактор одной подсети: CIDR, id и список пулов."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.cfg: Optional[DhcpConfig] = None
        self.subnet: Optional[Dict[str, Any]] = None

        ttk.Label(self, text=_("Подсеть"), font=("TkDefaultFont", 13, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", **PAD)

        ttk.Label(self, text="ID:").grid(row=1, column=0, sticky="w", **PAD)
        self.id_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.id_var, width=10).grid(
            row=1, column=1, sticky="w", **PAD)

        ttk.Label(self, text=_("Подсеть (CIDR):")).grid(row=2, column=0, sticky="w", **PAD)
        self.subnet_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.subnet_var, width=28).grid(
            row=2, column=1, sticky="w", **PAD)
        ttk.Button(self, text=_("Применить"), command=self.apply).grid(
            row=2, column=2, sticky="w", **PAD)

        # -- пулы
        ttk.Label(self, text=_("Пулы адресов:")).grid(
            row=3, column=0, sticky="w", **PAD)
        self.pool_list = tk.Listbox(self, height=8, width=44)
        self.pool_list.grid(row=4, column=0, columnspan=2, sticky="we", **PAD)

        btns = ttk.Frame(self)
        btns.grid(row=4, column=2, sticky="n", **PAD)
        ttk.Button(btns, text=_("Добавить…"), command=self._add_pool).pack(
            fill="x", pady=2)
        ttk.Button(btns, text=_("Удалить"), command=self._del_pool).pack(
            fill="x", pady=2)

    def load(self, cfg: DhcpConfig, subnet: Dict[str, Any]):
        self.cfg = cfg
        self.subnet = subnet
        self.id_var.set(str(subnet.get("id", "")))
        self.subnet_var.set(subnet.get("subnet", ""))
        self._refresh_pools()

    def _refresh_pools(self):
        self.pool_list.delete(0, tk.END)
        if self.subnet is None:
            return
        for p in DhcpConfig.pools_of(self.subnet):
            label = p.get("pool", "?")
            if p.get("client-class"):
                label += f"   [class: {p['client-class']}]"
            self.pool_list.insert(tk.END, label)

    def apply(self):
        if self.subnet is None or self.cfg is None:
            return
        fam = self.cfg.family
        cidr = self.subnet_var.get().strip()
        ok, msg = V.validate_subnet(cidr, fam)
        if not ok:
            messagebox.showerror(_("Ошибка"), msg)
            return
        id_raw = self.id_var.get().strip()
        try:
            new_id = int(id_raw)
        except ValueError:
            messagebox.showerror(_("Ошибка"), _("ID подсети должен быть целым числом"))
            return
        self.subnet["id"] = new_id
        self.subnet["subnet"] = cidr
        self._notify()
        messagebox.showinfo(_("Готово"), _("Подсеть сохранена."))

    def _add_pool(self):
        if self.subnet is None or self.cfg is None:
            return
        known = classmod.class_names(self.cfg.dhcp)
        dlg = PoolDialog(self, self.subnet.get("subnet", ""), self.cfg.family,
                         known_classes=known)
        self.wait_window(dlg)
        if dlg.result:
            DhcpConfig.add_pool(self.subnet, dlg.result["pool"],
                                dlg.result.get("client_class"))
            self._refresh_pools()
            self._notify()

    def _del_pool(self):
        if self.subnet is None:
            return
        sel = self.pool_list.curselection()
        if not sel:
            return
        DhcpConfig.remove_pool(self.subnet, sel[0])
        self._refresh_pools()
        self._notify()


class PoolDialog(tk.Toplevel):
    """Модальный диалог ввода пула с валидацией относительно подсети."""

    NO_CLASS = _("(без класса)")

    def __init__(self, master, subnet_cidr: str, family: int,
                 known_classes: Optional[list] = None):
        super().__init__(master)
        self.title(_("Добавить пул"))
        self.transient(master)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.subnet_cidr = subnet_cidr
        self.family = family
        self.result: Optional[Dict[str, Any]] = None

        ttk.Label(self, text=_("Подсеть: {}").format(subnet_cidr)).pack(
            anchor="w", **PAD)
        ttk.Label(
            self,
            text=_("Диапазон 'A - B' или подсеть 'A/prefix':"),
        ).pack(anchor="w", **PAD)
        self.var = tk.StringVar()
        entry = ttk.Entry(self, textvariable=self.var, width=36)
        entry.pack(fill="x", **PAD)
        entry.focus_set()

        ttk.Label(self, text=_("Класс клиентов (client-class):")).pack(
            anchor="w", **PAD)
        self.class_var = tk.StringVar(value=self.NO_CLASS)
        values = [self.NO_CLASS] + list(known_classes or [])
        ttk.Combobox(self, textvariable=self.class_var, values=values,
                     state="readonly", width=34).pack(fill="x", **PAD)

        row = ttk.Frame(self)
        row.pack(fill="x", **PAD)
        ttk.Button(row, text="OK", command=self._ok).pack(side="right", padx=4)
        ttk.Button(row, text=_("Отмена"), command=self.destroy).pack(side="right")
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def _ok(self):
        pool = self.var.get().strip()
        ok, msg = V.validate_pool(pool, self.family)
        if not ok:
            messagebox.showerror(_("Ошибка"), msg, parent=self)
            return
        if self.subnet_cidr:
            ok, msg = V.validate_pool_in_subnet(pool, self.subnet_cidr)
            if not ok:
                messagebox.showerror(_("Ошибка"), msg, parent=self)
                return
        cc = self.class_var.get()
        client_class = None if cc == self.NO_CLASS else cc
        self.result = {"pool": pool, "client_class": client_class}
        self.destroy()


# ==========================================================================
# Этап 2: резервирования
# ==========================================================================

class ReservationsPanel(BasePanel):
    """Список резервирований подсети с добавлением/редактированием."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.cfg: Optional[DhcpConfig] = None
        self.subnet: Optional[Dict[str, Any]] = None

        ttk.Label(self, text=_("Резервирования адресов"),
                  font=("TkDefaultFont", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", **PAD)
        self.subnet_label = ttk.Label(self, text="")
        self.subnet_label.grid(row=1, column=0, columnspan=2, sticky="w", **PAD)

        cols = ("hw", "ip", "host")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=10)
        self.tree.heading("hw", text=_("MAC-адрес"))
        self.tree.heading("ip", text=_("IP-адрес"))
        self.tree.heading("host", text=_("Имя хоста"))
        self.tree.column("hw", width=150)
        self.tree.column("ip", width=140)
        self.tree.column("host", width=140)
        self.tree.grid(row=2, column=0, sticky="nsew", **PAD)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        btns = ttk.Frame(self)
        btns.grid(row=2, column=1, sticky="n", **PAD)
        ttk.Button(btns, text=_("Добавить…"), command=self._add).pack(fill="x", pady=2)
        ttk.Button(btns, text=_("Изменить…"), command=self._edit).pack(fill="x", pady=2)
        ttk.Button(btns, text=_("Удалить"), command=self._del).pack(fill="x", pady=2)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

    def load(self, cfg: DhcpConfig, subnet: Dict[str, Any]):
        self.cfg = cfg
        self.subnet = subnet
        self.subnet_label.configure(
            text=_("Подсеть: {} (id {})").format(
                subnet.get('subnet', '?'), subnet.get('id', '?')))
        self._refresh()

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        if self.subnet is None:
            return
        for i, r in enumerate(DhcpConfig.reservations_of(self.subnet)):
            self.tree.insert("", "end", iid=str(i), values=(
                r.get("hw-address", ""),
                r.get("ip-address", ""),
                r.get("hostname", ""),
            ))

    def _selected_index(self) -> Optional[int]:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _add(self):
        if self.subnet is None or self.cfg is None:
            return
        dlg = ReservationDialog(self, self.subnet.get("subnet", ""), self.cfg.family)
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            DhcpConfig.add_reservation(
                self.subnet, r["hw"], r.get("ip"), r.get("host"))
            self._refresh()
            self._notify()

    def _edit(self):
        idx = self._selected_index()
        if idx is None or self.subnet is None or self.cfg is None:
            return
        cur = DhcpConfig.reservations_of(self.subnet)[idx]
        dlg = ReservationDialog(
            self, self.subnet.get("subnet", ""), self.cfg.family,
            initial={
                "hw": cur.get("hw-address", ""),
                "ip": cur.get("ip-address", ""),
                "host": cur.get("hostname", ""),
            })
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            DhcpConfig.update_reservation(
                self.subnet, idx, r["hw"], r.get("ip"), r.get("host"))
            self._refresh()
            self._notify()

    def _del(self):
        idx = self._selected_index()
        if idx is None or self.subnet is None:
            return
        DhcpConfig.remove_reservation(self.subnet, idx)
        self._refresh()
        self._notify()


class ReservationDialog(tk.Toplevel):
    """Диалог создания/редактирования резервирования."""

    def __init__(self, master, subnet_cidr: str, family: int,
                 initial: Optional[Dict[str, str]] = None):
        super().__init__(master)
        self.title(_("Резервирование"))
        self.transient(master)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.subnet_cidr = subnet_cidr
        self.family = family
        self.result: Optional[Dict[str, str]] = None
        initial = initial or {}

        ttk.Label(self, text=_("MAC-адрес (hw-address):")).grid(
            row=0, column=0, sticky="w", **PAD)
        self.hw_var = tk.StringVar(value=initial.get("hw", ""))
        e = inputmask.masked_entry(self, self.hw_var, "mac", width=30)
        e.grid(row=0, column=1, **PAD)
        e.focus_set()

        ip_kind = "ipv4" if family == 4 else "ipv6"
        ttk.Label(self, text=_("IP-адрес (ip-address):")).grid(
            row=1, column=0, sticky="w", **PAD)
        self.ip_var = tk.StringVar(value=initial.get("ip", ""))
        inputmask.masked_entry(self, self.ip_var, ip_kind, width=30).grid(
            row=1, column=1, **PAD)

        ttk.Label(self, text=_("Имя хоста (hostname):")).grid(
            row=2, column=0, sticky="w", **PAD)
        self.host_var = tk.StringVar(value=initial.get("host", ""))
        ttk.Entry(self, textvariable=self.host_var, width=30).grid(
            row=2, column=1, **PAD)

        row = ttk.Frame(self)
        row.grid(row=3, column=0, columnspan=2, sticky="e", **PAD)
        ttk.Button(row, text="OK", command=self._ok).pack(side="right", padx=4)
        ttk.Button(row, text=_("Отмена"), command=self.destroy).pack(side="right")
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def _ok(self):
        hw = self.hw_var.get().strip()
        ip = self.ip_var.get().strip()
        host = self.host_var.get().strip()

        ok, msg = V.validate_hw_address(hw)
        if not ok:
            messagebox.showerror(_("Ошибка"), msg, parent=self)
            return
        if not ip and not host:
            messagebox.showerror(
                _("Ошибка"), _("Задайте IP-адрес и/или имя хоста"), parent=self)
            return
        if ip:
            ok, msg = V.validate_ip(ip, self.family)
            if not ok:
                messagebox.showerror(_("Ошибка"), msg, parent=self)
                return
            if self.subnet_cidr:
                import ipaddress
                net = ipaddress.ip_network(self.subnet_cidr, strict=False)
                if ipaddress.ip_address(ip) not in net:
                    messagebox.showerror(
                        _("Ошибка"),
                        _("Адрес {} вне подсети {}").format(
                            ip, self.subnet_cidr),
                        parent=self)
                    return
        self.result = {"hw": hw, "ip": ip, "host": host}
        self.destroy()


# ==========================================================================
# Этап 3: DHCP-опции
# ==========================================================================

class OptionsPanel(BasePanel):
    """Редактор option-data для контейнера (служба или подсеть)."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.cfg: Optional[DhcpConfig] = None
        self.container: Optional[Dict[str, Any]] = None
        self.scope_title = ""

        self.title_var = tk.StringVar()
        ttk.Label(self, textvariable=self.title_var,
                  font=("TkDefaultFont", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", **PAD)

        cols = ("name", "data", "send")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=10)
        self.tree.heading("name", text=_("Опция"))
        self.tree.heading("data", text=_("Значение"))
        self.tree.heading("send", text="always-send")
        self.tree.column("name", width=170)
        self.tree.column("data", width=210)
        self.tree.column("send", width=90, anchor="center")
        self.tree.grid(row=1, column=0, sticky="nsew", **PAD)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        btns = ttk.Frame(self)
        btns.grid(row=1, column=1, sticky="n", **PAD)
        ttk.Button(btns, text=_("Добавить…"), command=self._add).pack(fill="x", pady=2)
        ttk.Button(btns, text=_("Изменить…"), command=self._edit).pack(fill="x", pady=2)
        ttk.Button(btns, text=_("Удалить"), command=self._del).pack(fill="x", pady=2)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

    def load(self, cfg: DhcpConfig, container: Dict[str, Any], scope_title: str):
        self.cfg = cfg
        self.container = container
        self.scope_title = scope_title
        fam = "IPv4" if cfg.family == 4 else "IPv6"
        self.title_var.set(
            _("DHCP-опции {} — {}").format(fam, scope_title))
        self._refresh()

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        if self.container is None:
            return
        for i, o in enumerate(DhcpConfig.options_of(self.container)):
            self.tree.insert("", "end", iid=str(i), values=(
                o.get("name", ""),
                o.get("data", ""),
                _("да") if o.get("always-send") else "",
            ))

    def _selected_index(self) -> Optional[int]:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _add(self):
        if self.container is None or self.cfg is None:
            return
        dlg = OptionDialog(self, self.cfg.family)
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            DhcpConfig.set_option(
                self.container, r["name"], r["data"], r.get("always_send"))
            self._refresh()
            self._notify()

    def _edit(self):
        idx = self._selected_index()
        if idx is None or self.container is None or self.cfg is None:
            return
        cur = DhcpConfig.options_of(self.container)[idx]
        dlg = OptionDialog(self, self.cfg.family, initial={
            "name": cur.get("name", ""),
            "data": cur.get("data", ""),
            "always_send": bool(cur.get("always-send")),
        })
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            # если имя не изменилось — set_option обновит существующую запись;
            # если изменилось — удалим старую и создадим новую
            if r["name"] != cur.get("name"):
                DhcpConfig.remove_option(self.container, idx)
            DhcpConfig.set_option(
                self.container, r["name"], r["data"], r.get("always_send"))
            self._refresh()
            self._notify()

    def _del(self):
        idx = self._selected_index()
        if idx is None or self.container is None:
            return
        DhcpConfig.remove_option(self.container, idx)
        self._refresh()
        self._notify()


class OptionDialog(tk.Toplevel):
    """Диалог добавления/редактирования одной DHCP-опции.

    Позволяет выбрать известную опцию из каталога или ввести произвольную
    (имя + значение). Для известных опций показывается подсказка по формату
    и выполняется проверка значения.
    """

    CUSTOM = _("— произвольная опция —")

    def __init__(self, master, family: int,
                 initial: Optional[Dict[str, Any]] = None):
        super().__init__(master)
        self.title(_("DHCP-опция"))
        self.transient(master)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.family = family
        self.result: Optional[Dict[str, Any]] = None
        initial = initial or {}

        self.catalog = opts.catalog(family)
        labels = [o.label for o in self.catalog] + [self.CUSTOM]

        ttk.Label(self, text=_("Опция:")).grid(row=0, column=0, sticky="w", **PAD)
        self.choice_var = tk.StringVar()
        self.combo = ttk.Combobox(self, textvariable=self.choice_var,
                                   values=labels, state="readonly", width=40)
        self.combo.grid(row=0, column=1, **PAD)
        self.combo.bind("<<ComboboxSelected>>", self._on_choice)

        ttk.Label(self, text=_("Имя опции:")).grid(row=1, column=0, sticky="w", **PAD)
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(self, textvariable=self.name_var, width=42)
        self.name_entry.grid(row=1, column=1, **PAD)

        ttk.Label(self, text=_("Значение (data):")).grid(
            row=2, column=0, sticky="w", **PAD)
        self.data_var = tk.StringVar(value=initial.get("data", ""))
        ttk.Entry(self, textvariable=self.data_var, width=42).grid(
            row=2, column=1, **PAD)

        self.hint_var = tk.StringVar()
        ttk.Label(self, textvariable=self.hint_var, foreground="#546e7a",
                  wraplength=360, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w", **PAD)

        self.send_var = tk.BooleanVar(value=bool(initial.get("always_send")))
        ttk.Checkbutton(self, text=_("always-send (отправлять всегда)"),
                        variable=self.send_var).grid(
            row=4, column=0, columnspan=2, sticky="w", **PAD)

        row = ttk.Frame(self)
        row.grid(row=5, column=0, columnspan=2, sticky="e", **PAD)
        ttk.Button(row, text="OK", command=self._ok).pack(side="right", padx=4)
        ttk.Button(row, text=_("Отмена"), command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())

        # начальное состояние
        init_name = initial.get("name", "")
        known = opts.find(family, init_name) if init_name else None
        if known:
            self.choice_var.set(known.label)
        elif init_name:
            self.choice_var.set(self.CUSTOM)
            self.name_var.set(init_name)
        else:
            self.choice_var.set(labels[0])
        self._on_choice()
        if init_name and not known:
            self.name_var.set(init_name)

    def _current_def(self) -> Optional[opts.OptionDef]:
        label = self.choice_var.get()
        for o in self.catalog:
            if o.label == label:
                return o
        return None

    def _on_choice(self, _event=None):
        odef = self._current_def()
        if odef is not None:
            self.name_var.set(odef.name)
            self.name_entry.configure(state="disabled")
            self.hint_var.set(odef.hint)
        else:
            # произвольная опция
            self.name_entry.configure(state="normal")
            self.hint_var.set(_("Введите имя опции Kea и значение вручную."))

    def _ok(self):
        odef = self._current_def()
        name = self.name_var.get().strip()
        data = self.data_var.get().strip()
        if not name:
            messagebox.showerror(_("Ошибка"), _("Не задано имя опции"), parent=self)
            return
        if not data:
            messagebox.showerror(_("Ошибка"), _("Не задано значение опции"), parent=self)
            return
        if odef is not None:
            ok, msg = opts.validate_option_data(odef.kind, data, self.family)
            if not ok:
                messagebox.showerror(_("Ошибка"), msg, parent=self)
                return
        self.result = {
            "name": name,
            "data": data,
            "always_send": self.send_var.get(),
        }
        self.destroy()


# ==========================================================================
# Этап 4: мониторинг и управление арендами
# ==========================================================================

class LeasesPanel(BasePanel):
    """Просмотр аренд из memfile CSV и принудительное удаление через сокет.

    Пути к файлу аренд и control-socket подставляются из конфигурации
    службы, но их можно переопределить вручную. Удаление затрагивает живую
    службу Kea и требует подтверждения, а также загруженной hook-библиотеки
    lease_cmds.
    """

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.cfg: Optional[DhcpConfig] = None
        self.api_backend = None
        self.records = []

        ttk.Label(self, text=_("Аренды адресов"),
                  font=("TkDefaultFont", 13, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", **PAD)

        # пути (только для чтения: значения берутся из конфигурации службы)
        self.lease_label = ttk.Label(self, text=_("Файл аренд (CSV):"))
        self.lease_label.grid(row=1, column=0, sticky="w", **PAD)
        self.lease_path_var = tk.StringVar()
        self.lease_entry = ttk.Entry(
            self, textvariable=self.lease_path_var, width=48,
            state="readonly")
        self.lease_entry.grid(row=1, column=1, sticky="we", **PAD)

        # строка control-socket нужна только в файловом режиме (для удаления
        # аренды через unix-сокет); в API-режиме удаление идёт по HTTP
        self.socket_label = ttk.Label(self, text="Control-socket:")
        self.socket_label.grid(row=2, column=0, sticky="w", **PAD)
        self.socket_path_var = tk.StringVar()
        self.socket_entry = ttk.Entry(
            self, textvariable=self.socket_path_var, width=48,
            state="readonly")
        self.socket_entry.grid(row=2, column=1, sticky="we", **PAD)

        self.show_inactive_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text=_("Показывать неактивные (отклонённые/освобождённые)"),
                        variable=self.show_inactive_var,
                        command=self.reload).grid(
            row=3, column=0, columnspan=2, sticky="w", **PAD)

        # таблица
        cols = ("addr", "id", "host", "expire", "remain", "state")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=12)
        headers = {
            "addr": (_("Адрес"), 130), "id": ("MAC/DUID", 150),
            "host": (_("Имя хоста"), 120), "expire": (_("Истекает"), 140),
            "remain": (_("Осталось"), 80), "state": (_("Состояние"), 90),
        }
        for c, (title, w) in headers.items():
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w)
        self.tree.grid(row=4, column=0, columnspan=2, sticky="nsew", **PAD)

        btns = ttk.Frame(self)
        btns.grid(row=4, column=2, sticky="n", **PAD)
        ttk.Button(btns, text=_("Обновить"), command=self.reload).pack(
            fill="x", pady=2)
        ttk.Button(btns, text=_("Удалить аренду…"), command=self._delete).pack(
            fill="x", pady=2)

        self.status_var = tk.StringVar()
        ttk.Label(self, textvariable=self.status_var,
                  foreground="#546e7a").grid(
            row=5, column=0, columnspan=3, sticky="w", **PAD)

        self.columnconfigure(1, weight=1)
        self.rowconfigure(4, weight=1)

    def load(self, cfg: DhcpConfig, api_backend=None):
        self.cfg = cfg
        self.api_backend = api_backend
        # автоопределение путей из конфигурации
        lp = leasemod.guess_lease_path(cfg.dhcp, cfg.family)
        self.lease_path_var.set(lp or "")
        sp = ctrlsocket.guess_socket_path(cfg.dhcp)
        self.socket_path_var.set(sp or "")

        # control-socket показываем только в файловом режиме
        if api_backend is not None:
            self.socket_label.grid_remove()
            self.socket_entry.grid_remove()
            # в API-режиме файл аренд на локальной ФС недоступен —
            # аренды читаются по API, путь-подсказка неинформативен
            self.lease_label.grid_remove()
            self.lease_entry.grid_remove()
        else:
            self.socket_label.grid()
            self.socket_entry.grid()
            self.lease_label.grid()
            self.lease_entry.grid()

        self.reload()

    def reload(self):
        if self.cfg is None:
            return
        self.tree.delete(*self.tree.get_children())
        self.records = []
        if getattr(self, "api_backend", None) is not None:
            self._reload_api()
        else:
            self._reload_file()
        for i, r in enumerate(self.records):
            self.tree.insert("", "end", iid=str(i), values=(
                r.address, r.identifier, r.hostname,
                r.expire_str(), r.remaining_str(), r.state_label))

    def _reload_file(self):
        path = self.lease_path_var.get().strip()
        if not path:
            self.status_var.set(_("Путь к файлу аренд не задан."))
            return
        try:
            self.records = leasemod.read_leases(
                path, self.cfg.family,
                include_inactive=self.show_inactive_var.get())
        except FileNotFoundError:
            self.status_var.set(_("Файл аренд не найден: {}").format(path))
            return
        except Exception as exc:  # noqa: BLE001
            self.status_var.set(
                _("Ошибка чтения файла аренд: {}").format(exc))
            return
        self.status_var.set(
            _("Аренд показано: {} (из файла)").format(len(self.records)))

    def _reload_api(self):
        client = self.api_backend.lease_client(self.cfg.family)
        try:
            self.records = leasemod.read_leases_api(
                client, self.cfg.family,
                include_inactive=self.show_inactive_var.get())
        except ctrlsocket.CommandError as exc:
            if exc.result == ctrlsocket.RESULT_UNSUPPORTED:
                self.status_var.set(
                    _("lease{4,6}-get-page не поддерживается: "
                    "загрузите hook libdhcp_lease_cmds."))
            else:
                self.status_var.set(
                    _("Ошибка сервера: {}").format(exc.text or exc))
            return
        except ctrlsocket.ControlSocketError as exc:
            self.status_var.set(_("Ошибка соединения: {}").format(exc))
            return
        self.status_var.set(
            _("Аренд показано: {} (по API)").format(len(self.records)))

    def _selected_record(self):
        sel = self.tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        if 0 <= idx < len(self.records):
            return self.records[idx]
        return None

    def _delete(self):
        if self.cfg is None:
            return
        rec = self._selected_record()
        if rec is None:
            messagebox.showinfo(_("Удаление"), _("Выберите аренду в таблице."))
            return
        api = getattr(self, "api_backend", None)
        if api is None:
            sock_path = self.socket_path_var.get().strip()
            if not sock_path:
                messagebox.showerror(
                    _("Удаление"),
                    _("Не задан путь к control-socket.\n"
                    "Он берётся из секции control-socket конфигурации службы."))
                return
        if not messagebox.askyesno(
                _("Подтверждение"),
                _("Принудительно удалить аренду {} ({})?\n\n"
                  "Операция затрагивает работающую службу Kea и требует "
                  "загруженной hook-библиотеки lease_cmds.").format(
                      rec.address, rec.identifier)):
            return

        if api is not None:
            client = api.lease_client(self.cfg.family)
        else:
            client = ctrlsocket.KeaControlSocket(sock_path)
        try:
            text = client.lease_del(self.cfg.family, rec.address)
        except ctrlsocket.CommandError as exc:
            if exc.result == ctrlsocket.RESULT_UNSUPPORTED:
                messagebox.showerror(
                    _("Недоступно"),
                    _("Команда удаления аренды не поддерживается сервером.\n"
                    "Загрузите hook-библиотеку libdhcp_lease_cmds в Kea."))
            elif exc.result == ctrlsocket.RESULT_EMPTY:
                messagebox.showwarning(
                    _("Не найдено"),
                    _("Аренда {} не найдена на сервере "
                      "(возможно, файл устарел). Обновите список.").format(
                          rec.address))
            else:
                messagebox.showerror(_("Ошибка"), exc.text or str(exc))
            return
        except ctrlsocket.ControlSocketError as exc:
            messagebox.showerror(_("Ошибка соединения"), str(exc))
            return

        messagebox.showinfo(_("Готово"), text or _("Аренда удалена."))
        self.reload()


# ==========================================================================
# Этап 5: High Availability (HA)
# ==========================================================================

class HaPanel(BasePanel):
    """Настройка режима HA и списка peers."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.cfg: Optional[DhcpConfig] = None
        self.ha0: Optional[Dict[str, Any]] = None

        ttk.Label(self, text=_("Высокая доступность (HA)"),
                  font=("TkDefaultFont", 13, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", **PAD)

        self.enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text=_("Включить HA (libdhcp_ha.so)"),
                        variable=self.enabled_var,
                        command=self._toggle).grid(
            row=1, column=0, columnspan=2, sticky="w", **PAD)

        # контейнер параметров (управляется доступностью)
        self.body = ttk.Frame(self)
        self.body.grid(row=2, column=0, columnspan=3, sticky="nsew", **PAD)
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

        ttk.Label(self.body, text=_("Режим:")).grid(
            row=0, column=0, sticky="w", **PAD)
        self.mode_var = tk.StringVar()
        self.mode_combo = ttk.Combobox(
            self.body, textvariable=self.mode_var, values=hamod.MODES,
            state="readonly", width=20)
        self.mode_combo.grid(row=0, column=1, sticky="w", **PAD)
        self.mode_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_meta())

        ttk.Label(self.body, text=_("Имя этого сервера (this-server-name):")).grid(
            row=1, column=0, sticky="w", **PAD)
        self.this_var = tk.StringVar()
        ttk.Entry(self.body, textvariable=self.this_var, width=24).grid(
            row=1, column=1, sticky="w", **PAD)

        ttk.Label(self.body, text=_("Партнёры (peers):")).grid(
            row=2, column=0, sticky="w", **PAD)
        cols = ("name", "url", "role", "af")
        self.tree = ttk.Treeview(self.body, columns=cols, show="headings",
                                 height=6)
        for c, (t, w) in {"name": (_("Имя"), 110), "url": ("URL", 200),
                          "role": (_("Роль"), 90),
                          "af": ("auto-failover", 100)}.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w)
        self.tree.grid(row=3, column=0, columnspan=2, sticky="nsew", **PAD)
        self.tree.bind("<Double-1>", lambda e: self._edit_peer())

        pbtn = ttk.Frame(self.body)
        pbtn.grid(row=3, column=2, sticky="n", **PAD)
        ttk.Button(pbtn, text=_("Добавить…"), command=self._add_peer).pack(
            fill="x", pady=2)
        ttk.Button(pbtn, text=_("Изменить…"), command=self._edit_peer).pack(
            fill="x", pady=2)
        ttk.Button(pbtn, text=_("Удалить"), command=self._del_peer).pack(
            fill="x", pady=2)

        self.hint = ttk.Label(
            self.body,
            text=_("HA также требует загруженной библиотеки "
                 "libdhcp_lease_cmds.so для обмена арендами."),
            foreground="#546e7a", wraplength=460, justify="left")
        self.hint.grid(row=4, column=0, columnspan=3, sticky="w", **PAD)

        ttk.Button(self.body, text=_("Применить параметры HA"),
                   command=self._apply_meta).grid(
            row=5, column=0, sticky="w", **PAD)

        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(3, weight=1)

    def load(self, cfg: DhcpConfig):
        self.cfg = cfg
        self.ha0 = hamod.get_ha_config(cfg.dhcp)
        enabled = self.ha0 is not None
        self.enabled_var.set(enabled)
        if enabled:
            self.mode_var.set(self.ha0.get("mode", hamod.MODE_HOT_STANDBY))
            self.this_var.set(self.ha0.get("this-server-name", ""))
        else:
            self.mode_var.set(hamod.MODE_HOT_STANDBY)
            self.this_var.set("")
        self._refresh_peers()
        self._update_state()

    def _update_state(self):
        state = "normal" if self.enabled_var.get() else "disabled"
        for child in self.body.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass  # у Frame/Label нет state

    def _toggle(self):
        if self.cfg is None:
            return
        if self.enabled_var.get():
            self.ha0 = hamod.enable_ha(self.cfg.dhcp)
            self.mode_var.set(self.ha0.get("mode", hamod.MODE_HOT_STANDBY))
        else:
            if not messagebox.askyesno(
                    _("Отключить HA"),
                    _("Удалить конфигурацию HA (libdhcp_ha.so)?\n"
                    "Прочие hook-библиотеки останутся без изменений.")):
                self.enabled_var.set(True)
                return
            hamod.disable_ha(self.cfg.dhcp)
            self.ha0 = None
        self._refresh_peers()
        self._update_state()
        self._notify()

    def _refresh_peers(self):
        self.tree.delete(*self.tree.get_children())
        if not self.ha0:
            return
        for i, p in enumerate(hamod.peers_of(self.ha0)):
            af = p.get("auto-failover")
            af_str = "" if af is None else (_("да") if af else _("нет"))
            self.tree.insert("", "end", iid=str(i), values=(
                p.get("name", ""), p.get("url", ""),
                p.get("role", ""), af_str))

    def _apply_meta(self):
        if self.ha0 is None:
            return
        mode = self.mode_var.get()
        ok, msg = hamod.validate_mode(mode)
        if not ok:
            messagebox.showerror(_("Ошибка"), msg)
            return
        self.ha0["mode"] = mode
        this_name = self.this_var.get().strip()
        if this_name:
            self.ha0["this-server-name"] = this_name
        else:
            self.ha0.pop("this-server-name", None)
        self._notify()

    def _selected(self) -> Optional[int]:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _add_peer(self):
        if self.ha0 is None:
            return
        dlg = PeerDialog(self, self.mode_var.get())
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            hamod.add_peer(self.ha0, r["name"], r["url"], r["role"],
                           r.get("auto_failover"))
            self._refresh_peers()
            self._notify()

    def _edit_peer(self):
        idx = self._selected()
        if idx is None or self.ha0 is None:
            return
        cur = hamod.peers_of(self.ha0)[idx]
        dlg = PeerDialog(self, self.mode_var.get(), initial={
            "name": cur.get("name", ""), "url": cur.get("url", ""),
            "role": cur.get("role", ""),
            "auto_failover": cur.get("auto-failover"),
        })
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            hamod.update_peer(self.ha0, idx, r["name"], r["url"], r["role"],
                              r.get("auto_failover"))
            self._refresh_peers()
            self._notify()

    def _del_peer(self):
        idx = self._selected()
        if idx is None or self.ha0 is None:
            return
        hamod.remove_peer(self.ha0, idx)
        self._refresh_peers()
        self._notify()


class PeerDialog(tk.Toplevel):
    """Диалог добавления/редактирования peer HA."""

    def __init__(self, master, mode: str,
                 initial: Optional[Dict[str, Any]] = None):
        super().__init__(master)
        self.title(_("Партнёр HA"))
        self.transient(master)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.mode = mode
        self.result: Optional[Dict[str, Any]] = None
        initial = initial or {}

        ttk.Label(self, text=_("Имя (name):")).grid(row=0, column=0, sticky="w", **PAD)
        self.name_var = tk.StringVar(value=initial.get("name", ""))
        e = ttk.Entry(self, textvariable=self.name_var, width=28)
        e.grid(row=0, column=1, **PAD)
        e.focus_set()

        ttk.Label(self, text="URL:").grid(row=1, column=0, sticky="w", **PAD)
        self.url_var = tk.StringVar(
            value=initial.get("url", "http://127.0.0.1:8000/"))
        ttk.Entry(self, textvariable=self.url_var, width=28).grid(
            row=1, column=1, **PAD)

        ttk.Label(self, text=_("Роль (role):")).grid(row=2, column=0, sticky="w", **PAD)
        self.role_var = tk.StringVar(value=initial.get("role", ""))
        roles = hamod.ROLES_BY_MODE.get(mode, hamod.ALL_ROLES)
        ttk.Combobox(self, textvariable=self.role_var, values=roles,
                     state="readonly", width=25).grid(row=2, column=1, **PAD)

        self.af_var = tk.StringVar(value=self._af_to_str(
            initial.get("auto_failover")))
        ttk.Label(self, text="auto-failover:").grid(
            row=3, column=0, sticky="w", **PAD)
        ttk.Combobox(self, textvariable=self.af_var,
                     values=[_("(не задано)"), _("да"), _("нет")],
                     state="readonly", width=25).grid(row=3, column=1, **PAD)

        row = ttk.Frame(self)
        row.grid(row=4, column=0, columnspan=2, sticky="e", **PAD)
        ttk.Button(row, text="OK", command=self._ok).pack(side="right", padx=4)
        ttk.Button(row, text=_("Отмена"), command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())

    @staticmethod
    def _af_to_str(val):
        if val is None:
            return _("(не задано)")
        return _("да") if val else _("нет")

    def _af_from_str(self):
        v = self.af_var.get()
        if v == _("да"):
            return True
        if v == _("нет"):
            return False
        return None

    def _ok(self):
        name = self.name_var.get().strip()
        url = self.url_var.get().strip()
        role = self.role_var.get().strip()
        if not name:
            messagebox.showerror(_("Ошибка"), _("Не задано имя peer"), parent=self)
            return
        ok, msg = hamod.validate_url(url)
        if not ok:
            messagebox.showerror(_("Ошибка"), msg, parent=self)
            return
        ok, msg = hamod.validate_role(role, self.mode)
        if not ok:
            messagebox.showerror(_("Ошибка"), msg, parent=self)
            return
        self.result = {"name": name, "url": url, "role": role,
                       "auto_failover": self._af_from_str()}
        self.destroy()


# ==========================================================================
# Этап 6: client-classes (политики DHCP)
# ==========================================================================

class ClassesPanel(BasePanel):
    """Список классов клиентов и переход к их редактированию."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.cfg: Optional[DhcpConfig] = None

        ttk.Label(self, text=_("Классы клиентов (client-classes)"),
                  font=("TkDefaultFont", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", **PAD)

        cols = ("name", "test", "opts")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=10)
        self.tree.heading("name", text=_("Имя класса"))
        self.tree.heading("test", text=_("Условие (test)"))
        self.tree.heading("opts", text=_("Опций"))
        self.tree.column("name", width=150)
        self.tree.column("test", width=280)
        self.tree.column("opts", width=60, anchor="center")
        self.tree.grid(row=1, column=0, sticky="nsew", **PAD)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        btns = ttk.Frame(self)
        btns.grid(row=1, column=1, sticky="n", **PAD)
        ttk.Button(btns, text=_("Добавить…"), command=self._add).pack(
            fill="x", pady=2)
        ttk.Button(btns, text=_("Изменить…"), command=self._edit).pack(
            fill="x", pady=2)
        ttk.Button(btns, text=_("Опции класса…"), command=self._edit_options).pack(
            fill="x", pady=2)
        ttk.Button(btns, text=_("Удалить"), command=self._del).pack(
            fill="x", pady=2)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

    def load(self, cfg: DhcpConfig):
        self.cfg = cfg
        self._refresh()

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        if self.cfg is None:
            return
        for i, c in enumerate(classmod.classes_of(self.cfg.dhcp)):
            n_opts = len(c.get("option-data", []) or [])
            self.tree.insert("", "end", iid=str(i), values=(
                c.get("name", ""), c.get("test", ""), n_opts))

    def _selected(self) -> Optional[int]:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _add(self):
        if self.cfg is None:
            return
        dlg = ClassDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            try:
                classmod.add_class(self.cfg.dhcp, dlg.result["name"],
                                   dlg.result.get("test"))
            except ValueError as exc:
                messagebox.showerror(_("Ошибка"), str(exc))
                return
            self._refresh()
            self._notify()

    def _edit(self):
        idx = self._selected()
        if idx is None or self.cfg is None:
            return
        cur = classmod.classes_of(self.cfg.dhcp)[idx]
        dlg = ClassDialog(self, initial={
            "name": cur.get("name", ""), "test": cur.get("test", "")})
        self.wait_window(dlg)
        if dlg.result:
            try:
                classmod.update_class(self.cfg.dhcp, idx, dlg.result["name"],
                                      dlg.result.get("test"))
            except (ValueError, IndexError) as exc:
                messagebox.showerror(_("Ошибка"), str(exc))
                return
            self._refresh()
            self._notify()

    def _edit_options(self):
        idx = self._selected()
        if idx is None or self.cfg is None:
            return
        cur = classmod.classes_of(self.cfg.dhcp)[idx]
        dlg = ClassOptionsDialog(self, self.cfg, cur)
        self.wait_window(dlg)
        self._refresh()
        self._notify()

    def _del(self):
        idx = self._selected()
        if idx is None or self.cfg is None:
            return
        name = classmod.classes_of(self.cfg.dhcp)[idx].get("name", "")
        if not messagebox.askyesno(
                _("Удаление"), _("Удалить класс {!r}?").format(name)):
            return
        classmod.remove_class(self.cfg.dhcp, idx)
        self._refresh()
        self._notify()


class ClassDialog(tk.Toplevel):
    """Диалог имени и test-выражения класса."""

    def __init__(self, master, initial: Optional[Dict[str, str]] = None):
        super().__init__(master)
        self.title(_("Класс клиентов"))
        self.transient(master)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.result: Optional[Dict[str, str]] = None
        initial = initial or {}

        ttk.Label(self, text=_("Имя класса (name):")).grid(
            row=0, column=0, sticky="w", **PAD)
        self.name_var = tk.StringVar(value=initial.get("name", ""))
        e = ttk.Entry(self, textvariable=self.name_var, width=36)
        e.grid(row=0, column=1, **PAD)
        e.focus_set()

        ttk.Label(self, text=_("Условие (test):")).grid(
            row=1, column=0, sticky="nw", **PAD)
        self.test_txt = tk.Text(self, width=44, height=4, wrap="word")
        self.test_txt.grid(row=1, column=1, **PAD)
        self.test_txt.insert("1.0", initial.get("test", ""))

        ttk.Label(
            self,
            text=_("Пример: option[60].text == 'CiscoIPPhone'"),
            foreground="#546e7a").grid(row=2, column=1, sticky="w", **PAD)

        row = ttk.Frame(self)
        row.grid(row=3, column=0, columnspan=2, sticky="e", **PAD)
        ttk.Button(row, text="OK", command=self._ok).pack(side="right", padx=4)
        ttk.Button(row, text=_("Отмена"), command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())

    def _ok(self):
        name = self.name_var.get().strip()
        ok, msg = classmod.validate_class_name(name)
        if not ok:
            messagebox.showerror(_("Ошибка"), msg, parent=self)
            return
        test = self.test_txt.get("1.0", "end").strip()
        self.result = {"name": name, "test": test}
        self.destroy()


class ClassOptionsDialog(tk.Toplevel):
    """Редактор option-data внутри класса (переиспользует OptionsPanel)."""

    def __init__(self, master, cfg: DhcpConfig, class_entry: Dict[str, Any]):
        super().__init__(master)
        self.title(_("Опции класса: {}").format(class_entry.get('name', '')))
        self.transient(master)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.geometry("640x420")

        panel = OptionsPanel(self, on_change=lambda: None)
        panel.pack(fill="both", expand=True)
        panel.load(cfg, class_entry,
                   _("класс {}").format(class_entry.get('name', '')))

        ttk.Button(self, text=_("Закрыть"), command=self.destroy).pack(
            side="bottom", anchor="e", padx=8, pady=6)
        self.bind("<Escape>", lambda e: self.destroy())


# ==========================================================================
# Hook-библиотеки
# ==========================================================================

class HooksPanel(BasePanel):
    """Управление hook-библиотеками: загрузка/выгрузка и параметры.

    Список = встроенный каталог Kea + пользовательские имена (из ini).
    Загрузка = наличие записи в hooks-libraries конфига. Существование
    .so-файла не проверяется (через API это невозможно).
    """

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.cfg: Optional[DhcpConfig] = None

        ttk.Label(self, text=_("Hook-библиотеки"),
                  font=("TkDefaultFont", 13, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", **PAD)

        ttk.Label(
            self,
            text=_("Отметьте библиотеки для загрузки. Они должны быть "
                   "установлены в системе — наличие файлов не проверяется."),
            foreground="#546e7a", wraplength=560, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w", **PAD)

        # каталог хуков
        dirbar = ttk.Frame(self)
        dirbar.grid(row=2, column=0, columnspan=3, sticky="we", **PAD)
        ttk.Label(dirbar, text=_("Каталог библиотек:")).pack(side="left")
        self.dir_var = tk.StringVar()
        ttk.Entry(dirbar, textvariable=self.dir_var, width=40).pack(
            side="left", padx=4)
        ttk.Button(dirbar, text=_("Применить путь"),
                   command=self._apply_dir).pack(side="left")

        # таблица хуков
        cols = ("load", "name", "desc", "params")
        self.tree = ttk.Treeview(self, columns=cols, show="headings",
                                 height=14)
        self.tree.heading("load", text=_("Загрузить"))
        self.tree.heading("name", text=_("Библиотека"))
        self.tree.heading("desc", text=_("Назначение"))
        self.tree.heading("params", text=_("Параметры"))
        self.tree.column("load", width=80, anchor="center")
        self.tree.column("name", width=190)
        self.tree.column("desc", width=210)
        self.tree.column("params", width=80, anchor="center")
        self.tree.grid(row=3, column=0, columnspan=2, sticky="nsew", **PAD)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", lambda e: self._edit_params())

        btns = ttk.Frame(self)
        btns.grid(row=3, column=2, sticky="n", **PAD)
        ttk.Button(btns, text=_("Параметры…"),
                   command=self._edit_params).pack(fill="x", pady=2)
        ttk.Button(btns, text=_("Добавить свой…"),
                   command=self._add_custom).pack(fill="x", pady=2)
        ttk.Button(btns, text=_("Удалить свой"),
                   command=self._del_custom).pack(fill="x", pady=2)

        self.status_var = tk.StringVar()
        ttk.Label(self, textvariable=self.status_var,
                  foreground="#546e7a").grid(
            row=4, column=0, columnspan=3, sticky="w", **PAD)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

    # -- данные -----------------------------------------------------------

    def load(self, cfg: DhcpConfig):
        self.cfg = cfg
        self.dir_var.set(settings.get_hooks_dir())
        self._refresh()

    def _all_hook_names(self):
        """Имена хуков: встроенные + пользовательские + реально загруженные."""
        names = [h.filename for h in hooksmod.KNOWN_HOOKS]
        for n in settings.get_custom_hooks():
            if n not in names:
                names.append(n)
        # хуки, загруженные в конфиг, но неизвестные — тоже показать
        for n in hooksmod.loaded_hooks(self.cfg.dhcp):
            if n not in names:
                names.append(n)
        return names

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        if self.cfg is None:
            return
        for name in self._all_hook_names():
            hd = hooksmod.known_by_name(name)
            loaded = hooksmod.is_loaded(self.cfg.dhcp, name)
            applicable = hd.dhcp_applicable if hd else True
            desc = hd.label if hd else _("пользовательская библиотека")
            check = "☑" if loaded else "☐"
            if not applicable:
                check = "—"  # неактивна (например, D2-хук)
            has_params = hooksmod.get_parameters(self.cfg.dhcp, name)
            pstr = _("есть") if has_params else ""
            self.tree.insert("", "end", iid=name,
                             values=(check, name, desc, pstr))
        self._update_status()

    def _update_status(self):
        n = len(hooksmod.loaded_hooks(self.cfg.dhcp)) if self.cfg else 0
        self.status_var.set(_("Загружено библиотек: {}").format(n))

    # -- взаимодействие ---------------------------------------------------

    def _selected(self) -> Optional[str]:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_click(self, event):
        # клик по колонке «Загрузить» переключает состояние
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        name = self.tree.identify_row(event.y)
        if name:
            self._toggle(name)

    def _toggle(self, name: str):
        if self.cfg is None:
            return
        hd = hooksmod.known_by_name(name)
        if hd and not hd.dhcp_applicable:
            messagebox.showinfo(
                _("Недоступно"),
                _("Библиотека {} не настраивается в DHCP-сервере.\n{}")
                .format(name, hd.note))
            return
        if name == "libdhcp_ha.so":
            messagebox.showinfo(
                _("HA"),
                _("HA настраивается на вкладке «Высокая доступность (HA)»."))
            return
        if hooksmod.is_loaded(self.cfg.dhcp, name):
            hooksmod.disable(self.cfg.dhcp, name)
        else:
            hooksmod.enable(self.cfg.dhcp, name, self.dir_var.get().strip()
                            or hooksmod.DEFAULT_HOOKS_DIR)
        self._refresh()
        self._notify()

    def _apply_dir(self):
        directory = self.dir_var.get().strip()
        settings.set_hooks_dir(directory)
        # обновить путь у всех уже загруженных известных/пользовательских хуков
        if self.cfg is not None and directory:
            for name in hooksmod.loaded_hooks(self.cfg.dhcp):
                if name != "libdhcp_ha.so":
                    hooksmod.set_library_path(self.cfg.dhcp, name, directory)
            self._notify()
        messagebox.showinfo(_("Готово"), _("Путь к библиотекам сохранён."))

    def _edit_params(self):
        name = self._selected()
        if name is None or self.cfg is None:
            return
        if not hooksmod.is_loaded(self.cfg.dhcp, name):
            messagebox.showinfo(
                _("Параметры"),
                _("Сначала загрузите библиотеку (отметьте «Загрузить»)."))
            return
        if name == "libdhcp_ha.so":
            messagebox.showinfo(
                _("HA"),
                _("Параметры HA задаются на вкладке «Высокая доступность»."))
            return
        cur = hooksmod.get_parameters(self.cfg.dhcp, name) or {}
        dlg = HookParamsDialog(self, name, cur)
        self.wait_window(dlg)
        if dlg.result is not None:
            hooksmod.set_parameters(self.cfg.dhcp, name, dlg.result)
            self._refresh()
            self._notify()

    def _add_custom(self):
        from tkinter import simpledialog
        name = simpledialog.askstring(
            _("Своя библиотека"),
            _("Имя файла библиотеки (например, libdhcp_custom.so):"),
            parent=self)
        if not name:
            return
        name = name.strip()
        if not name.endswith(".so"):
            messagebox.showerror(_("Ошибка"),
                                 _("Имя должно оканчиваться на .so"))
            return
        custom = settings.get_custom_hooks()
        if name not in custom:
            custom.append(name)
            settings.set_custom_hooks(custom)
        self._refresh()

    def _del_custom(self):
        name = self._selected()
        if name is None:
            return
        if hooksmod.known_by_name(name) is not None:
            messagebox.showinfo(
                _("Удаление"),
                _("Встроенные библиотеки из списка не удаляются."))
            return
        custom = [n for n in settings.get_custom_hooks() if n != name]
        settings.set_custom_hooks(custom)
        # если была загружена — выгрузим из конфига
        if self.cfg is not None and hooksmod.is_loaded(self.cfg.dhcp, name):
            hooksmod.disable(self.cfg.dhcp, name)
            self._notify()
        self._refresh()


class HookParamsDialog(tk.Toplevel):
    """Редактор parameters хука в виде JSON-текста (generic)."""

    def __init__(self, master, name: str, params: Dict[str, Any]):
        super().__init__(master)
        self.title(_("Параметры: {}").format(name))
        self.transient(master)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.result: Optional[Dict[str, Any]] = None

        ttk.Label(self, text=_("Параметры библиотеки в формате JSON:")).pack(
            anchor="w", padx=8, pady=(8, 2))
        self.txt = tk.Text(self, width=54, height=14, wrap="none")
        self.txt.pack(fill="both", expand=True, padx=8)
        import json as _json
        self.txt.insert("1.0", _json.dumps(params, ensure_ascii=False,
                                           indent=2) if params else "{\n}")

        ttk.Label(
            self,
            text=_("Пустой объект {} — без параметров. См. документацию Kea "
                   "по конкретной библиотеке."),
            foreground="#546e7a", wraplength=420, justify="left").pack(
            anchor="w", padx=8, pady=2)

        row = ttk.Frame(self)
        row.pack(fill="x", padx=8, pady=6)
        ttk.Button(row, text="OK", command=self._ok).pack(side="right", padx=4)
        ttk.Button(row, text=_("Отмена"), command=self.destroy).pack(
            side="right")
        self.bind("<Escape>", lambda e: self.destroy())

    def _ok(self):
        import json as _json
        raw = self.txt.get("1.0", "end").strip()
        if not raw:
            self.result = {}
            self.destroy()
            return
        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError as exc:
            messagebox.showerror(_("Ошибка"),
                                 _("Некорректный JSON: {}").format(exc),
                                 parent=self)
            return
        if not isinstance(data, dict):
            messagebox.showerror(_("Ошибка"),
                                 _("Параметры должны быть JSON-объектом {}"),
                                 parent=self)
            return
        self.result = data
        self.destroy()


# ==========================================================================
# Мониторинг (статистика)
# ==========================================================================

class MonitoringPanel(BasePanel):
    """Мониторинг метрик Kea в реальном времени.

    Dashboard с ключевыми показателями + детальная таблица всех метрик.
    Автообновление с настраиваемым интервалом (только пока панель активна).
    Только для API-режима.
    """

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.cfg: Optional[DhcpConfig] = None
        self.backend = None  # ApiBackend
        self._poll_id = None  # ID задачи after() для отмены
        self._prev_snapshot: Optional[statmod.Snapshot] = None
        self._curr_snapshot: Optional[statmod.Snapshot] = None
        self._interval_sec = 10  # дефолтный интервал

        ttk.Label(self, text=_("Мониторинг"),
                  font=("TkDefaultFont", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", **PAD)

        # панель управления (интервал + кнопка обновить)
        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, columnspan=2, sticky="we", **PAD)
        ttk.Label(controls, text=_("Интервал обновления:")).pack(side="left")
        self.interval_var = tk.StringVar(value="10 сек")
        intervals = ["5 сек", "10 сек", "30 сек", "1 мин", _("вручную")]
        combo = ttk.Combobox(controls, textvariable=self.interval_var,
                             values=intervals, state="readonly", width=12)
        combo.pack(side="left", padx=4)
        combo.bind("<<ComboboxSelected>>", lambda e: self._change_interval())
        ttk.Button(controls, text=_("Обновить сейчас"),
                   command=self._refresh_now).pack(side="left", padx=4)
        self.status_var = tk.StringVar()
        ttk.Label(controls, textvariable=self.status_var,
                  foreground="#546e7a").pack(side="left", padx=8)

        # dashboard (верхняя часть с карточками)
        dash = ttk.LabelFrame(self, text=_("Ключевые показатели"))
        dash.grid(row=2, column=0, columnspan=2, sticky="we", **PAD)
        self._build_dashboard(dash)

        # детальная таблица (все метрики)
        table_frame = ttk.LabelFrame(self, text=_("Все метрики"))
        table_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", **PAD)
        self._build_table(table_frame)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

    def _build_dashboard(self, parent):
        """Карточки с ключевыми показателями + мини-график."""
        # 4 карточки в ряд: пакеты, адреса, ошибки, топ-подсеть
        cards = ttk.Frame(parent)
        cards.pack(fill="x", padx=4, pady=4)
        for i in range(4):
            cards.columnconfigure(i, weight=1, uniform="card")

        self.card_packets = self._card(cards, _("Пакеты получено"), "—")
        self.card_packets.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        self.card_addresses = self._card(cards, _("Адресов выдано"), "—")
        self.card_addresses.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)

        self.card_errors = self._card(cards, _("Ошибки (NAK)"), "—")
        self.card_errors.grid(row=0, column=2, sticky="nsew", padx=2, pady=2)

        self.card_top = self._card(cards, _("Топ-подсеть"), "—")
        self.card_top.grid(row=0, column=3, sticky="nsew", padx=2, pady=2)

        # мини-график динамики (пакеты/сек) — если доступен matplotlib
        self._chart_rates = []  # история значений rate
        self._chart = None
        self._chart_canvas = None
        self._init_chart(parent)

    def _init_chart(self, parent):
        """Инициализировать matplotlib-график (мягкая деградация)."""
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        except Exception:  # noqa: BLE001 — matplotlib недоступен
            return
        fig = Figure(figsize=(6, 1.6), dpi=72)
        self._chart_ax = fig.add_subplot(111)
        self._chart_ax.set_title(_("Пакетов/сек"), fontsize=9)
        self._chart_ax.tick_params(labelsize=7)
        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.get_tk_widget().pack(fill="x", padx=4, pady=(0, 4))
        self._chart = fig
        self._chart_canvas = canvas

    def _update_chart(self, rate: Optional[float]):
        """Добавить точку в график и перерисовать."""
        if self._chart is None or rate is None:
            return
        self._chart_rates.append(rate)
        # держим последние 30 точек
        if len(self._chart_rates) > 30:
            self._chart_rates = self._chart_rates[-30:]
        self._chart_ax.clear()
        self._chart_ax.set_title(_("Пакетов/сек"), fontsize=9)
        self._chart_ax.tick_params(labelsize=7)
        self._chart_ax.plot(self._chart_rates, color="#1565c0", linewidth=1.5)
        self._chart_ax.fill_between(
            range(len(self._chart_rates)), self._chart_rates,
            color="#1565c0", alpha=0.15)
        self._chart_ax.set_ylim(bottom=0)
        try:
            self._chart_canvas.draw_idle()
        except Exception:  # noqa: BLE001
            pass

    def _card(self, parent, title: str, value: str) -> ttk.Frame:
        """Создать карточку dashboard."""
        frame = ttk.Frame(parent, relief="solid", borderwidth=1)
        ttk.Label(frame, text=title, font=("TkDefaultFont", 9),
                  foreground="#546e7a").pack(anchor="w", padx=4, pady=(4, 0))
        lbl = ttk.Label(frame, text=value, font=("TkDefaultFont", 14, "bold"))
        lbl.pack(anchor="w", padx=4, pady=(0, 4))
        frame._value_label = lbl  # сохраним ссылку для обновления
        return frame

    def _build_table(self, parent):
        """Детальная таблица метрик."""
        # фильтр по имени
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill="x", padx=4, pady=2)
        ttk.Label(filter_frame, text=_("Фильтр:")).pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self._apply_filter())
        ttk.Entry(filter_frame, textvariable=self.filter_var, width=30).pack(
            side="left", padx=4)

        cols = ("name", "value", "timestamp")
        self.tree = ttk.Treeview(parent, columns=cols, show="tree headings",
                                 height=12)
        self.tree.heading("#0", text=_("Группа"))
        self.tree.heading("name", text=_("Метрика"))
        self.tree.heading("value", text=_("Значение"))
        self.tree.heading("timestamp", text=_("Обновлено"))
        self.tree.column("#0", width=120)
        self.tree.column("name", width=280)
        self.tree.column("value", width=100, anchor="e")
        self.tree.column("timestamp", width=100)
        self.tree.pack(fill="both", expand=True, padx=4, pady=2)

    # -- данные -----------------------------------------------------------

    def load(self, cfg: DhcpConfig, backend):
        self.cfg = cfg
        self.backend = backend
        # проверка режима API
        if not hasattr(backend, "kind") or backend.kind != "api":
            self._show_not_available()
            return
        self._refresh_now()
        self._schedule_poll()

    def _show_not_available(self):
        """Заглушка для файлового режима."""
        self.status_var.set(_("Доступно только при подключении к API"))
        for w in (self.card_packets, self.card_addresses, self.card_errors,
                  self.card_top):
            w._value_label.config(text="—", foreground="#9e9e9e")

    def _refresh_now(self):
        """Получить статистику с сервера и обновить UI."""
        if self.backend is None or self.cfg is None:
            return
        if not hasattr(self.backend, "kind") or self.backend.kind != "api":
            return
        try:
            # выбираем endpoint в зависимости от семейства
            ep = (self.backend.ep_v4 if self.cfg.family == 4
                  else self.backend.ep_v6)
            if ep is None:
                self.status_var.set(_("Служба не подключена"))
                return
            # Endpoint.client() создаёт клиент с правильным TLS/сертификатами
            client = ep.client(timeout=8)
            resp = client.send_command("statistic-get-all")
            metrics = statmod.parse_stat_response(resp)
            import time
            self._prev_snapshot = self._curr_snapshot
            self._curr_snapshot = statmod.Snapshot(time.time(), metrics)
            self._update_ui()
            self.status_var.set(_("Обновлено: {}").format(
                time.strftime("%H:%M:%S")))
        except Exception as exc:  # noqa: BLE001
            self.status_var.set(_("Ошибка: {}").format(str(exc)[:60]))

    def _update_ui(self):
        """Обновить dashboard и таблицу на основе текущего снимка."""
        if self._curr_snapshot is None:
            return
        snap = self._curr_snapshot
        m = snap.metrics

        # карточка: пакеты получено
        key_pkt = "pkt4-received" if self.cfg.family == 4 else "pkt6-received"
        total_pkt = snap.get(key_pkt, 0)
        rate_pkt = statmod.compute_rate(self._prev_snapshot, snap, key_pkt)
        if rate_pkt is not None:
            self.card_packets._value_label.config(
                text=f"{total_pkt} (↑{rate_pkt:.1f}/сек)")
        else:
            self.card_packets._value_label.config(text=str(total_pkt))
        # обновляем мини-график динамики пакетов
        self._update_chart(rate_pkt)

        # карточка: адреса
        assigned = snap.get("assigned-addresses", 0)
        total_addr = snap.get("total-addresses", 0)
        if total_addr > 0:
            pct = (float(assigned) / float(total_addr)) * 100
            self.card_addresses._value_label.config(
                text=f"{assigned}/{total_addr} ({pct:.1f}%)")
        else:
            self.card_addresses._value_label.config(text=str(assigned))

        # карточка: ошибки (NAK)
        nak_key = "pkt4-nak-sent" if self.cfg.family == 4 else "pkt6-reply-sent"
        nak = snap.get(nak_key, 0)
        self.card_errors._value_label.config(text=str(nak))

        # карточка: топ-подсеть
        top = statmod.top_subnet_by_usage(m)
        if top:
            sid, pct = top
            self.card_top._value_label.config(
                text=f"subnet[{sid}] {pct:.1f}%")
        else:
            self.card_top._value_label.config(text="—")

        # таблица
        self._refresh_table()

    def _refresh_table(self):
        """Обновить детальную таблицу метрик."""
        self.tree.delete(*self.tree.get_children())
        if self._curr_snapshot is None:
            return
        snap = self._curr_snapshot
        groups = statmod.group_metrics(snap.metrics)
        filt = self.filter_var.get().strip().lower()

        for gname, items in [("Пакеты", groups["packets"]),
                             ("Адреса", groups["addresses"]),
                             ("Подсети", groups["subnets"]),
                             ("Прочее", groups["other"])]:
            if not items:
                continue
            gid = self.tree.insert("", "end", text=gname, open=True)
            for name, val in items:
                if filt and filt not in name.lower():
                    continue
                self.tree.insert(gid, "end", values=(name, val, ""))

    def _apply_filter(self):
        """Применить фильтр по имени метрики."""
        self._refresh_table()

    # -- автообновление ---------------------------------------------------

    def _change_interval(self):
        """Изменить интервал обновления."""
        txt = self.interval_var.get()
        if "5" in txt:
            self._interval_sec = 5
        elif "10" in txt:
            self._interval_sec = 10
        elif "30" in txt:
            self._interval_sec = 30
        elif "1" in txt or "мин" in txt.lower():
            self._interval_sec = 60
        else:
            self._interval_sec = 0  # вручную
        self._schedule_poll()

    def _schedule_poll(self):
        """Запланировать следующий опрос."""
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        if self._interval_sec > 0:
            self._poll_id = self.after(self._interval_sec * 1000,
                                       self._do_poll)

    def _do_poll(self):
        """Callback автообновления."""
        self._refresh_now()
        self._schedule_poll()

    def stop_polling(self):
        """Остановить автообновление (вызывается при переключении панели)."""
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
