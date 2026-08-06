"""Главное окно kea-manager в стиле оснастки MS DHCP.

Слева — дерево: Сервер → IPv4 / IPv6 → подсети. Справа — панель редактора
выбранного узла. Узел IPv6 помечается, если служба не сконфигурирована.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Any, Dict, Optional

from ..model import DhcpConfig, KeaProject
from ..model.backend import FileBackend, ApiBackend, Endpoint
from ..util import validators as V
from ..util import ctrlsocket
from ..util import settings
from .panels import (WelcomePanel, ServicePanel, SubnetPanel,
                     ReservationsPanel, OptionsPanel, LeasesPanel,
                     HaPanel, ClassesPanel, HooksPanel)
from .connect import ConnectDialog
from .about import AboutDialog
from .icons import Icons


class MainWindow(tk.Tk):
    def __init__(self, project: Optional[KeaProject] = None,
                 startup_server: Optional[str] = None):
        super().__init__()
        self.title(_("kea-manager — редактор конфигурации Kea DHCP"))
        # восстановить размер/позицию окна из настроек (или значение по умолч.)
        saved_geom = settings.get_window_geometry()
        self.geometry(saved_geom if saved_geom else "960x600")

        # project — конфигурация активного сервера (None, пока не подключён).
        self.project = project
        self.active_server_name: Optional[str] = None
        self.dirty = False
        # соответствие id элемента дерева -> описание узла
        self.node_info: Dict[str, Dict[str, Any]] = {}
        self._current_panel: Optional[tk.Widget] = None

        # иконки создаём после инициализации корневого окна
        self.icons = Icons()
        self._set_window_icon()

        self._build_menu()
        self._build_layout()
        self.refresh_tree()
        self._update_title()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # автоподключение к серверу, переданному при запуске
        if startup_server:
            self.after(100, lambda: self._connect_server(startup_server))

    # ------------------------------------------------------------------ UI
    def _build_menu(self):
        menubar = tk.Menu(self)

        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label=_("Добавить сервер (API)…"),
                             command=self.add_server_api)
        filemenu.add_command(label=_("Добавить сервер (каталог)…"),
                             command=self.add_server_file)
        filemenu.add_separator()
        filemenu.add_command(label=_("Сохранить"), command=self.save)
        filemenu.add_command(label=_("Сохранить в каталог…"), command=self.save_as)
        filemenu.add_separator()
        filemenu.add_command(label=_("Выход"), command=self._on_close)
        menubar.add_cascade(label=_("Файл"), menu=filemenu)

        langmenu = tk.Menu(menubar, tearoff=0)
        from .. import i18n
        cur = i18n.current_language()
        self._lang_var = tk.StringVar(value=cur)
        for code in i18n.SUPPORTED:
            langmenu.add_radiobutton(
                label=i18n.language_label(code), value=code,
                variable=self._lang_var,
                command=lambda c=code: self._set_language(c))
        menubar.add_cascade(label=_("Язык"), menu=langmenu)

        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label=_("О программе"), command=self.show_about)
        menubar.add_cascade(label=_("Справка"), menu=helpmenu)

        self.config(menu=menubar)

    def _set_language(self, code: str):
        from .. import i18n
        if code == i18n.current_language():
            return
        settings.set_language(code)
        messagebox.showinfo(
            _("Смена языка"),
            _("Язык интерфейса изменится после перезапуска приложения."))

    def show_about(self):
        AboutDialog(self)

    def _set_window_icon(self):
        """Установить иконку окна из icons/ (PNG разных размеров).

        Ищем в каталоге рядом с проектом и в системном
        /usr/share/kea-manager/icons. Молча пропускаем, если не найдено.
        """
        import os as _os
        here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        candidates = [
            _os.path.join(here, "..", "icons"),   # корень проекта/icons
            _os.path.join(here, "icons"),         # пакет/icons (если положат)
            "/usr/share/kea-manager/icons",
        ]
        imgs = []
        for base in candidates:
            base = _os.path.normpath(base)
            if not _os.path.isdir(base):
                continue
            for sz in (256, 128, 64, 32):
                p = _os.path.join(base, f"kea-manager-{sz}.png")
                if _os.path.isfile(p):
                    try:
                        imgs.append(tk.PhotoImage(file=p))
                    except tk.TclError:
                        pass
            if imgs:
                break
        if imgs:
            try:
                # несколько размеров — WM сам выберет подходящий
                self.iconphoto(True, *imgs)
                self._icon_refs = imgs  # защита от сборки мусора
            except tk.TclError:
                pass

    def _tb_button(self, parent, text, command, icon_name):
        """Кнопка тулбара с иконкой (если иконка доступна)."""
        img = self.icons.get(icon_name)
        if img is not None:
            btn = ttk.Button(parent, text=text, image=img, compound="left",
                             command=command)
            btn._icon_ref = img  # защита от сборки мусора
            return btn
        return ttk.Button(parent, text=text, command=command)

    def _build_layout(self):
        toolbar = ttk.Frame(self, padding=(6, 4))
        toolbar.pack(side="top", fill="x")
        self._tb_button(toolbar, _("Добавить сервер"), self.add_server_api,
                        "open").pack(side="left")
        self._tb_button(toolbar, _("Сохранить"), self.save, "save").pack(
            side="left", padx=(4, 0))
        ttk.Separator(toolbar, orient="vertical").pack(
            side="left", fill="y", padx=8)
        self._tb_button(toolbar, _("Добавить подсеть"), self.add_subnet,
                        "add").pack(side="left")
        self._tb_button(toolbar, _("Удалить подсеть"), self.delete_selected,
                        "delete").pack(side="left", padx=(4, 0))

        # статусбар внизу (упаковываем до основной области, чтобы он
        # всегда занимал нижнюю кромку окна)
        self._build_statusbar()

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        self._paned = paned

        left = ttk.Frame(paned, width=300)
        self.tree = ttk.Treeview(left, show="tree")
        # активный сервер выделяем зелёным цветом текста
        self.tree.tag_configure("active", foreground="#2e7d32")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Double-1>", self._on_double_click)
        paned.add(left, weight=1)

        self.right = ttk.Frame(paned)
        paned.add(self.right, weight=3)
        self._show_panel(WelcomePanel(self.right))

    def _build_statusbar(self):
        bar = ttk.Frame(self, relief="sunken", padding=(6, 2))
        bar.pack(side="bottom", fill="x")

        # индикатор режима подключения
        self.status_mode_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.status_mode_var).pack(side="left")

        ttk.Separator(bar, orient="vertical").pack(
            side="left", fill="y", padx=8)

        # источник (каталог или адрес сервера)
        self.status_source_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.status_source_var).pack(side="left")

        # признак несохранённых изменений — у правого края
        self.status_dirty_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.status_dirty_var,
                  foreground="#c62828").pack(side="right")

        self._update_statusbar()

    def _update_statusbar(self):
        prefix = f"[{self.active_server_name}] " if self.active_server_name else ""
        backend = getattr(self.project, "backend", None)
        kind = getattr(backend, "kind", None)
        if kind == "api":
            self.status_mode_var.set(prefix + _("Режим: API (control-channel)"))
            self.status_source_var.set(backend.describe())
        elif kind == "file":
            self.status_mode_var.set(prefix + _("Режим: локальные файлы"))
            self.status_source_var.set(backend.describe())
        elif self.project is not None and self.project.directory:
            self.status_mode_var.set(prefix + _("Режим: локальные файлы"))
            self.status_source_var.set(
                _("файлы: {}").format(self.project.directory))
        else:
            self.status_mode_var.set(_("Режим: не подключено"))
            self.status_source_var.set(
                _("выберите сервер в дереве или добавьте новый"))
        self.status_dirty_var.set(
            _("● есть несохранённые изменения") if self.dirty else "")

    # ------------------------------------------------------------- дерево
    def _ins(self, parent, text, icon_name, open=False, tags=()):
        """Вставить узел дерева с иконкой (если доступна)."""
        img = self.icons.get(icon_name)
        if img is not None:
            return self.tree.insert(parent, "end", text=" " + text,
                                    image=img, open=open, tags=tags)
        return self.tree.insert(parent, "end", text=text, open=open,
                                tags=tags)

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.node_info.clear()

        servers = settings.list_servers()
        if not servers:
            hint = self._ins("", _("Нет серверов — «Файл → Добавить сервер…»"),
                             "server")
            self.node_info[hint] = {"type": "empty"}
            return

        for srv in servers:
            is_active = (srv.name == self.active_server_name)
            icon = "server"
            suffix = _("  ● активен") if is_active else ""
            node = self._ins("", f"{srv.name}{suffix}", icon,
                             open=is_active,
                             tags=("active",) if is_active else ())
            self.node_info[node] = {"type": "server", "server": srv.name}
            if is_active and self.project is not None:
                self._insert_server_services(node)

    def _insert_server_services(self, server_node: str):
        # --- IPv4 (всегда сконфигурирован)
        v4 = self._ins(server_node, "IPv4 (kea-dhcp4)", "ipv4", open=True)
        self.node_info[v4] = {"type": "service", "family": 4}
        self._insert_service_children(v4, self.project.dhcp4)

        # --- IPv6 (может быть не сконфигурирован)
        if self.project.dhcp6_configured:
            v6 = self._ins(server_node, "IPv6 (kea-dhcp6)", "ipv6", open=True)
            self.node_info[v6] = {"type": "service", "family": 6}
            self._insert_service_children(v6, self.project.dhcp6)
        else:
            v6 = self._ins(server_node,
                           _("IPv6 (kea-dhcp6) — не сконфигурировано"),
                           "ipv6_off")
            self.node_info[v6] = {"type": "service_disabled", "family": 6}

    def _insert_service_children(self, parent: str, cfg: DhcpConfig):
        # Глобальные DHCP-опции службы
        gopt = self._ins(parent, _("Глобальные DHCP-опции"), "options")
        self.node_info[gopt] = {
            "type": "global_options", "family": cfg.family}
        # Классы клиентов
        classes = self._ins(parent, _("Классы клиентов"), "classes")
        self.node_info[classes] = {"type": "classes", "family": cfg.family}
        # Высокая доступность
        ha = self._ins(parent, _("Высокая доступность (HA)"), "ha")
        self.node_info[ha] = {"type": "ha", "family": cfg.family}
        # Hook-библиотеки
        hooks = self._ins(parent, _("Hook-библиотеки"), "options")
        self.node_info[hooks] = {"type": "hooks", "family": cfg.family}
        # Аренды
        leases = self._ins(parent, _("Аренды"), "leases")
        self.node_info[leases] = {"type": "leases", "family": cfg.family}
        # Подсети
        self._insert_subnets(parent, cfg)

    def _insert_subnets(self, parent: str, cfg: DhcpConfig):
        for idx, sub in enumerate(cfg.subnets()):
            label = f"{sub.get('subnet', '?')}  (id {sub.get('id', '?')})"
            node = self._ins(parent, label, "subnet", open=True)
            self.node_info[node] = {
                "type": "subnet", "family": cfg.family,
                "index": idx, "subnet": sub,
            }
            # дочерние узлы подсети
            pools = self._ins(node, _("Пулы"), "pools")
            self.node_info[pools] = {
                "type": "pools", "family": cfg.family, "subnet": sub}
            res = self._ins(node, _("Резервирования"), "reservations")
            self.node_info[res] = {
                "type": "reservations", "family": cfg.family, "subnet": sub}
            opt = self._ins(node, _("DHCP-опции"), "options")
            self.node_info[opt] = {
                "type": "subnet_options", "family": cfg.family, "subnet": sub}

    def _selected_info(self) -> Optional[Dict[str, Any]]:
        sel = self.tree.selection()
        if not sel:
            return None
        return self.node_info.get(sel[0])

    # ------------------------------------------------------------ панели
    def _show_panel(self, panel: tk.Widget):
        if self._current_panel is not None:
            self._current_panel.destroy()
        self._current_panel = panel
        panel.pack(fill="both", expand=True)

    def _on_select(self, _event=None):
        info = self._selected_info()
        if not info:
            return
        t = info["type"]
        cfg = self.project.service(info.get("family")) if info.get("family") else None
        if t == "service":
            panel = ServicePanel(self.right, on_change=self._mark_dirty)
            self._show_panel(panel)
            panel.load(cfg)
        elif t in ("subnet", "pools"):
            panel = SubnetPanel(self.right, on_change=self._on_subnet_changed)
            self._show_panel(panel)
            panel.load(cfg, info["subnet"])
        elif t == "reservations":
            panel = ReservationsPanel(self.right, on_change=self._mark_dirty)
            self._show_panel(panel)
            panel.load(cfg, info["subnet"])
        elif t == "subnet_options":
            panel = OptionsPanel(self.right, on_change=self._mark_dirty)
            self._show_panel(panel)
            sub = info["subnet"]
            title = _("подсеть {}").format(sub.get('subnet', '?'))
            panel.load(cfg, sub, title)
        elif t == "global_options":
            panel = OptionsPanel(self.right, on_change=self._mark_dirty)
            self._show_panel(panel)
            # контейнер — тело службы; option-data лежит прямо в нём
            cfg.global_options()  # гарантируем наличие ключа
            panel.load(cfg, cfg.dhcp, _("глобальные настройки службы"))
        elif t == "leases":
            panel = LeasesPanel(self.right, on_change=lambda: None)
            self._show_panel(panel)
            backend = self.project.backend if self._is_api else None
            panel.load(cfg, api_backend=backend)
        elif t == "ha":
            panel = HaPanel(self.right, on_change=self._mark_dirty)
            self._show_panel(panel)
            panel.load(cfg)
        elif t == "hooks":
            panel = HooksPanel(self.right, on_change=self._mark_dirty)
            self._show_panel(panel)
            panel.load(cfg)
        elif t == "classes":
            panel = ClassesPanel(self.right, on_change=self._mark_dirty)
            self._show_panel(panel)
            panel.load(cfg)
        elif t == "service_disabled":
            self._show_disabled_v6_panel()
        else:
            self._show_panel(WelcomePanel(self.right))

    def _show_disabled_v6_panel(self):
        panel = ttk.Frame(self.right, padding=12)
        ttk.Label(panel, text=_("DHCP IPv6 не сконфигурирован"),
                  font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(
            panel,
            text=_("Файл kea-dhcp6.conf не будет создан при сохранении.\n"
                 "Нажмите кнопку ниже, чтобы начать конфигурировать IPv6."),
            justify="left",
        ).pack(anchor="w", pady=(8, 8))
        ttk.Button(panel, text=_("Сконфигурировать IPv6"),
                   command=self._enable_v6).pack(anchor="w")
        self._show_panel(panel)

    # ------------------------------------------------------- двойной клик
    def _on_double_click(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        info = self.node_info.get(row)
        if not info:
            return
        if info.get("type") == "server":
            name = info["server"]
            if name == self.active_server_name:
                return  # уже активен
            self._connect_server(name)

    # ------------------------------------------------------- контекст-меню
    def _on_right_click(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
        info = self._selected_info()
        if not info:
            return
        menu = tk.Menu(self, tearoff=0)
        t = info["type"]
        if t == "server":
            name = info["server"]
            if name != self.active_server_name:
                menu.add_command(
                    label=_("Подключиться"),
                    command=lambda: self._connect_server(name))
            menu.add_command(
                label=_("Изменить…"),
                command=lambda: self._edit_server(name))
            menu.add_command(
                label=_("Удалить сервер"),
                command=lambda: self.remove_server(name))
        elif t in ("service", "global_options"):
            menu.add_command(label=_("Добавить подсеть"), command=self.add_subnet)
        elif t in ("subnet", "pools", "reservations", "subnet_options"):
            menu.add_command(label=_("Добавить подсеть"), command=self.add_subnet)
            menu.add_command(label=_("Удалить подсеть"), command=self.delete_selected)
        elif t == "service_disabled":
            menu.add_command(label=_("Сконфигурировать IPv6"),
                             command=self._enable_v6)
        if menu.index("end") is not None:
            menu.tk_popup(event.x_root, event.y_root)

    def _edit_server(self, name: str):
        """Изменить параметры сохранённого сервера (только тип API)."""
        srv = settings.get_server(name)
        if srv is None:
            return
        if srv.kind == "file":
            messagebox.showinfo(
                _("Изменение"),
                _("Для файлового сервера измените каталог удалением и "
                "повторным добавлением."))
            return
        initial = {
            "tls": srv.tls, "verify": srv.verify, "username": srv.username,
            "host4": srv.host4, "port4": srv.port4,
            "v6_enabled": srv.v6_enabled, "host6": srv.host6,
            "port6": srv.port6,
            "client_cert": srv.client_cert, "client_key": srv.client_key,
            "ca_cert": srv.ca_cert,
        }
        dlg = ConnectDialog(self, initial=initial)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        settings.save_server(self._entry_from_values(name, dlg.values()))
        self.refresh_tree()

    # -------------------------------------------------------- операции
    def _enable_v6(self):
        self.project.enable_dhcp6()
        self._mark_dirty()
        self.refresh_tree()

    def add_subnet(self):
        info = self._selected_info()
        if info and info.get("type") == "service_disabled":
            messagebox.showinfo("IPv6", _("Сначала сконфигурируйте IPv6."))
            return
        family = info.get("family") if info else None
        if family is None:
            family = 4  # по умолчанию IPv4
        cfg = self.project.service(family)
        if cfg is None:
            return

        dlg = _SubnetDialog(self, family)
        self.wait_window(dlg)
        if dlg.result:
            cfg.add_subnet(dlg.result["subnet"], dlg.result.get("id"))
            self._mark_dirty()
            self.refresh_tree()

    def _resolve_subnet_index(self, info: Dict[str, Any]) -> Optional[int]:
        """По узлу (подсеть или её потомок) найти индекс подсети в службе."""
        if info.get("type") == "subnet":
            return info.get("index")
        sub = info.get("subnet")
        if sub is None:
            return None
        cfg = self.project.service(info["family"])
        for i, s in enumerate(cfg.subnets()):
            if s is sub:
                return i
        return None

    def delete_selected(self):
        info = self._selected_info()
        if not info or info.get("type") not in (
                "subnet", "pools", "reservations", "subnet_options"):
            messagebox.showinfo(_("Удаление"), _("Выберите подсеть для удаления."))
            return
        idx = self._resolve_subnet_index(info)
        if idx is None:
            return
        sub = info["subnet"]
        if not messagebox.askyesno(
                _("Удаление"),
                _("Удалить подсеть {}?").format(sub.get('subnet'))):
            return
        cfg = self.project.service(info["family"])
        cfg.remove_subnet(idx)
        self._mark_dirty()
        self.refresh_tree()

    def _on_subnet_changed(self):
        self._mark_dirty()
        self.refresh_tree()

    # --------------------------------------------------- серверы: список
    def add_server_api(self):
        """Добавить сервер типа API: диалог параметров + сохранение в ini."""
        dlg = ConnectDialog(self)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        vals = dlg.values()
        name = self._ask_server_name(default=vals.get("host4", ""))
        if not name:
            return
        settings.save_server(self._entry_from_values(name, vals))
        self.refresh_tree()
        # сразу подключимся к добавленному серверу
        self._connect_server(name)

    @staticmethod
    def _entry_from_values(name, vals):
        """Собрать ServerEntry(kind=api) из значений диалога подключения."""
        return settings.ServerEntry(
            name=name, kind="api",
            host4=vals["host4"], port4=str(vals["port4"]),
            tls=vals["tls"], verify=vals["verify"],
            username=vals["username"], v6_enabled=vals["v6_enabled"],
            host6=vals["host6"], port6=str(vals["port6"]),
            client_cert=vals.get("client_cert", ""),
            client_key=vals.get("client_key", ""),
            ca_cert=vals.get("ca_cert", ""))

    def add_server_file(self):
        """Добавить сервер типа «локальный каталог»."""
        directory = filedialog.askdirectory(title=_("Каталог с conf-файлами Kea"))
        if not directory:
            return
        name = self._ask_server_name(default=os.path.basename(directory.rstrip("/")))
        if not name:
            return
        entry = settings.ServerEntry(name=name, kind="file", directory=directory)
        settings.save_server(entry)
        self.refresh_tree()
        self._connect_server(name)

    def _ask_server_name(self, default: str = "") -> Optional[str]:
        from tkinter import simpledialog
        name = simpledialog.askstring(
            _("Имя сервера"),
            _("Название сервера (отображается в дереве):"),
            initialvalue=default, parent=self)
        if name is None:
            return None
        name = name.strip()
        if not name:
            messagebox.showerror(_("Ошибка"), _("Имя не может быть пустым"))
            return None
        if settings.get_server(name) is not None:
            if not messagebox.askyesno(
                    _("Перезапись"),
                    _("Сервер {!r} уже есть. Перезаписать параметры?")
                    .format(name)):
                return None
        return name

    def _connect_server(self, name: str):
        """Подключиться к серверу из списка (сделать активным)."""
        if name != self.active_server_name and not self._confirm_discard():
            return
        srv = settings.get_server(name)
        if srv is None:
            return
        if srv.kind == "file":
            backend = FileBackend(srv.directory)
        else:
            backend = self._build_api_backend(srv)
            if backend is None:
                return
        try:
            project = backend.load()
        except ctrlsocket.ControlSocketError as exc:
            messagebox.showerror(_("Ошибка подключения"), str(exc))
            return
        except ctrlsocket.CommandError as exc:
            messagebox.showerror(_("Ошибка сервера"), exc.text or str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(_("Ошибка"), str(exc))
            return
        project.backend = backend
        self.project = project
        self.active_server_name = name
        self.dirty = False
        self.refresh_tree()
        self._show_panel(WelcomePanel(self.right))
        self._update_title()

    def _build_api_backend(self, srv):
        """Собрать ApiBackend из записи сервера, запросив пароль."""
        from tkinter import simpledialog
        password = None
        if srv.username:
            password = simpledialog.askstring(
                _("Пароль"),
                _("Пароль для {}@{}:").format(srv.username, srv.name),
                show="*", parent=self)
            if password is None:  # отмена
                return None
        try:
            port4 = int(srv.port4)
        except ValueError:
            messagebox.showerror(
                _("Ошибка"), _("Некорректный порт: {}").format(srv.port4))
            return None
        certs = dict(
            client_cert=srv.client_cert or None,
            client_key=srv.client_key or None,
            ca_cert=srv.ca_cert or None)
        ep4 = Endpoint(host=srv.host4, port=port4, use_tls=srv.tls,
                       username=srv.username or None, password=password,
                       verify=srv.verify, **certs)
        ep6 = None
        if srv.v6_enabled:
            try:
                port6 = int(srv.port6)
            except ValueError:
                port6 = port4
            ep6 = Endpoint(host=srv.host6, port=port6, use_tls=srv.tls,
                           username=srv.username or None, password=password,
                           verify=srv.verify, **certs)
        return ApiBackend(ep4, ep6)

    def remove_server(self, name: str):
        if not messagebox.askyesno(
                _("Удаление сервера"),
                _("Удалить сервер {!r} из списка?").format(name)):
            return
        settings.remove_server(name)
        if name == self.active_server_name:
            self.active_server_name = None
            self.project = None
            self._show_panel(WelcomePanel(self.right))
        self.refresh_tree()
        self._update_title()

    @property
    def _is_api(self) -> bool:
        b = getattr(self.project, "backend", None)
        return b is not None and getattr(b, "kind", None) == "api"

    def save(self):
        if self.project is None:
            messagebox.showinfo(
                _("Сохранение"), _("Сначала подключитесь к серверу."))
            return
        if self._is_api:
            self._apply_api()
            return
        directory = getattr(self.project.backend, "directory", None) \
            or self.project.directory
        if not directory:
            self.save_as()
            return
        self._do_save(directory)

    def save_as(self):
        directory = filedialog.askdirectory(title=_("Куда сохранить conf-файлы"))
        if not directory:
            return
        self.project.backend = FileBackend(directory)
        self._do_save(directory)

    def _do_save(self, directory: str):
        try:
            written = self.project.save_dir(directory)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(_("Ошибка сохранения"), str(exc))
            return
        self.dirty = False
        self._update_title()
        files = "\n".join(os.path.basename(p) for p in written)
        messagebox.showinfo(
            _("Сохранено"),
            _("Записаны файлы в {}:\n{}\n\n"
              "Перезагрузите службы Kea вручную, чтобы применить изменения.")
            .format(directory, files))

    def _apply_api(self):
        if not messagebox.askyesno(
                _("Применить на сервер"),
                _("Применить конфигурацию к работающему серверу Kea?\n\n"
                "Будет выполнено: config-test → config-set → config-write.\n"
                "Изменения вступят в силу немедленно, без перезапуска.")):
            return
        try:
            results = self.project.backend.save(self.project, write=True)
        except ctrlsocket.CommandError as exc:
            messagebox.showerror(
                _("Отклонено сервером"),
                _("Сервер отверг конфигурацию:\n{}").format(
                    exc.text or str(exc)))
            return
        except ctrlsocket.ControlSocketError as exc:
            messagebox.showerror(_("Ошибка соединения"), str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(_("Ошибка"), str(exc))
            return
        self.dirty = False
        self._update_title()
        messagebox.showinfo(_("Применено"), "\n".join(results))

    # ----------------------------------------------------------- служебное
    def _mark_dirty(self):
        self.dirty = True
        self._update_title()

    def _update_title(self):
        if self.project is None:
            loc = _("не подключено")
        else:
            backend = getattr(self.project, "backend", None)
            if backend is not None:
                loc = backend.describe()
            else:
                loc = self.project.directory or _("новый проект")
        if self.active_server_name:
            loc = f"{self.active_server_name} — {loc}"
        star = "*" if self.dirty else ""
        self.title(f"kea-manager — {loc} {star}")
        # синхронизируем статусбар (если он уже построен)
        if hasattr(self, "status_mode_var"):
            self._update_statusbar()

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return messagebox.askyesno(
            _("Несохранённые изменения"),
            _("Есть несохранённые изменения. Продолжить без сохранения?"))

    def _on_close(self):
        if self._confirm_discard():
            # сохранить размер/позицию окна для следующего запуска
            try:
                settings.set_window_geometry(self.winfo_geometry())
            except Exception:  # noqa: BLE001 — не мешаем закрытию
                pass
            self.destroy()


class _SubnetDialog(tk.Toplevel):
    """Диалог создания подсети."""

    def __init__(self, master, family: int):
        super().__init__(master)
        self.title(_("Новая подсеть"))
        self.transient(master)
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.family = family
        self.result: Optional[Dict[str, Any]] = None

        example = "192.0.2.0/24" if family == 4 else "2001:db8::/64"
        ttk.Label(self, text=_("Подсеть IPv{} (CIDR):").format(family)).grid(
            row=0, column=0, sticky="w", padx=6, pady=6)
        self.subnet_var = tk.StringVar(value=example)
        entry = ttk.Entry(self, textvariable=self.subnet_var, width=30)
        entry.grid(row=0, column=1, padx=6, pady=6)
        entry.focus_set()
        entry.select_range(0, tk.END)

        ttk.Label(self, text=_("ID (необязательно):")).grid(
            row=1, column=0, sticky="w", padx=6, pady=6)
        self.id_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.id_var, width=10).grid(
            row=1, column=1, sticky="w", padx=6, pady=6)

        row = ttk.Frame(self)
        row.grid(row=2, column=0, columnspan=2, sticky="e", padx=6, pady=6)
        ttk.Button(row, text="OK", command=self._ok).pack(side="right", padx=4)
        ttk.Button(row, text=_("Отмена"), command=self.destroy).pack(side="right")
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def _ok(self):
        cidr = self.subnet_var.get().strip()
        ok, msg = V.validate_subnet(cidr, self.family)
        if not ok:
            messagebox.showerror(_("Ошибка"), msg, parent=self)
            return
        result: Dict[str, Any] = {"subnet": cidr}
        id_raw = self.id_var.get().strip()
        if id_raw:
            try:
                result["id"] = int(id_raw)
            except ValueError:
                messagebox.showerror(_("Ошибка"), _("ID должен быть целым"), parent=self)
                return
        self.result = result
        self.destroy()
