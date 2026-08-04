"""Точка входа: python3 -m kea_manager [каталог_с_conf].

Если указан каталог, он регистрируется как файловый сервер в списке и
делается активным. Список серверов хранится в
~/.config/kea-manager/kea-manager.ini и подгружается при старте.
"""

import os
import sys


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]

    # установка языка ДО создания UI (смена языка — через перезапуск)
    from . import i18n
    from .util import settings as _settings
    i18n.install(_settings.get_language())

    try:
        from .ui.mainwindow import MainWindow
    except Exception as exc:  # tkinter может отсутствовать
        sys.stderr.write(
            "Не удалось инициализировать графический интерфейс (tkinter).\n"
            f"Причина: {exc}\n"
            "В AltLinux установите пакет: python3-module-tkinter\n")
        return 2

    startup_server = None
    if argv:
        from .util import settings
        directory = os.path.abspath(argv[0])
        if not os.path.isdir(directory):
            sys.stderr.write(f"Каталог не найден: {directory!r}\n")
            return 1
        name = os.path.basename(directory.rstrip("/")) or directory
        settings.save_server(settings.ServerEntry(
            name=name, kind="file", directory=directory))
        startup_server = name

    app = MainWindow(startup_server=startup_server)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
