#!/usr/bin/env python3
"""Лаунчер kea-manager.

Запуск::

    ./kea-manager.py                 # пустой проект
    ./kea-manager.py /etc/kea        # загрузить conf-файлы из каталога
    python3 kea-manager.py /etc/kea

Файл добавляет свой каталог в sys.path, поэтому его можно запускать из
любого места, не устанавливая пакет.
"""

import os
import sys

# гарантируем, что пакет kea_manager найдётся независимо от cwd
#sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_CANDIDATE_DIRS = [
    os.path.dirname(os.path.abspath(__file__)),
    os.path.dirname(os.path.realpath(__file__)),
    "/usr/share/kea-manager",
    "/usr/local/share/kea-manager",
    os.path.expanduser("~/.local/share/kea-manager"),
]

for _d in _CANDIDATE_DIRS:
    if os.path.isfile(os.path.join(_d, "kea_manager", "__init__.py")):
        if _d not in sys.path:
            sys.path.insert(0, _d)
        break



from kea_manager.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
