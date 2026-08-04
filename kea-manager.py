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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kea_manager.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
