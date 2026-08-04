"""kea-manager — редактор конфигурации kea-dhcp4/kea-dhcp6.

Поддерживаемая версия Kea: 3.2.0.
Стек: python3 + tkinter, только модули стандартной библиотеки.
"""

__version__ = "1.0.0"
KEA_TARGET_VERSION = "3.2.0"

# Гарантируем наличие _() как функции-идентичности до вызова i18n.install().
# Это защищает импорт модулей (в т.ч. в тестах) от NameError, если строки
# где-то используются на уровне модуля.
import builtins as _builtins  # noqa: E402
if "_" not in _builtins.__dict__:
    _builtins.__dict__["_"] = lambda s: s
