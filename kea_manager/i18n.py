"""Интернационализация kea-manager на базе gettext.

Особенности реализации:
  * Домен перевода — ``kea-manager``.
  * msgid — исходные строки на русском языке. Для русского перевод не
    нужен (gettext вернёт msgid как есть), для английского берётся из .mo.
  * Файлы перевода ищутся в нескольких каталогах-кандидатах, в т.ч.
    системных: ``/usr/share/kea-manager/locale`` и ``/usr/share/locale``.
    Первый существующий каталог с нужным .mo выигрывает.
  * Функция ``_()`` устанавливается в builtins, поэтому доступна во всех
    модулях без импорта. Вызовите ``install(lang)`` один раз при старте,
    ДО создания UI.

Смена языка требует перезапуска приложения (строки в уже построенных
виджетах gettext задним числом не меняет).
"""

from __future__ import annotations

import builtins
import gettext
import os
from typing import List, Optional

DOMAIN = "kea-manager"
SUPPORTED = ("ru", "en")
DEFAULT_LANG = "ru"

_current_lang = DEFAULT_LANG


def locale_dirs() -> List[str]:
    """Каталоги-кандидаты с переводами, в порядке приоритета.

    1. Каталог locale внутри установленного пакета (kea_manager/locale).
    2. Системный /usr/share/kea-manager/locale
       (= /usr/share/kea-manager/../locale нормализованно — см. ниже).
    3. Общесистемный /usr/share/locale.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = [
        os.path.join(here, "locale"),
        "/usr/share/kea-manager/locale",
        # то, что в ТЗ записано как /usr/share/kea-manager/../locale:
        os.path.normpath("/usr/share/kea-manager/../locale"),
        "/usr/share/locale",
    ]
    # убрать дубликаты, сохранив порядок
    seen = set()
    result = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            result.append(d)
    return result


def _find_translation(lang: str) -> Optional[gettext.NullTranslations]:
    """Найти перевод для языка в каталогах-кандидатах."""
    for d in locale_dirs():
        mo = os.path.join(d, lang, "LC_MESSAGES", DOMAIN + ".mo")
        if os.path.isfile(mo):
            try:
                with open(mo, "rb") as fh:
                    return gettext.GNUTranslations(fh)
            except OSError:
                continue
    return None


def install(lang: Optional[str] = None) -> str:
    """Настроить перевод и установить _() в builtins.

    lang: 'ru', 'en' или None (тогда DEFAULT_LANG). Возвращает
    фактически применённый язык.
    """
    global _current_lang
    if lang not in SUPPORTED:
        lang = DEFAULT_LANG
    _current_lang = lang

    if lang == "ru":
        # msgid уже на русском — перевод не требуется
        trans: gettext.NullTranslations = gettext.NullTranslations()
    else:
        found = _find_translation(lang)
        trans = found if found is not None else gettext.NullTranslations()

    builtins.__dict__["_"] = trans.gettext
    return lang


def current_language() -> str:
    return _current_lang


def language_label(lang: str) -> str:
    return {"ru": "Русский", "en": "English"}.get(lang, lang)
