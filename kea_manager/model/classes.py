"""Модель client-classes (политики DHCP) для Kea.

client-classes — массив на уровне тела службы. Каждый класс имеет:
  - name           уникальное имя класса (обязательно);
  - test           логическое выражение (необязательно для базовых классов,
                   но обычно задаётся), напр. "option[60].text == 'CiscoIPPhone'";
  - option-data    список опций, применяемых к клиентам класса (необязательно);
  - прочие ключи   (only-if-required, valid-lifetime и т.д.) — сохраняются
                   round-trip и не затираются.

Классы связываются с пулами/подсетями через ``client-class`` и
``require-client-classes`` (эти поля редактируются в панелях подсети/пула).

Модуль использует только стандартную библиотеку.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def classes_of(dhcp_body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Массив client-classes тела службы (создаётся при отсутствии)."""
    return dhcp_body.setdefault("client-classes", [])


def class_names(dhcp_body: Dict[str, Any]) -> List[str]:
    return [c.get("name", "") for c in classes_of(dhcp_body) if c.get("name")]


def find_class(dhcp_body: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    for c in classes_of(dhcp_body):
        if c.get("name") == name:
            return c
    return None


def add_class(dhcp_body: Dict[str, Any], name: str,
              test: Optional[str] = None) -> Dict[str, Any]:
    if find_class(dhcp_body, name) is not None:
        raise ValueError(f"Класс с именем {name!r} уже существует")
    entry: Dict[str, Any] = {"name": name}
    if test:
        entry["test"] = test
    classes_of(dhcp_body).append(entry)
    return entry


def update_class(dhcp_body: Dict[str, Any], index: int, name: str,
                 test: Optional[str] = None) -> Dict[str, Any]:
    classes = classes_of(dhcp_body)
    if not (0 <= index < len(classes)):
        raise IndexError(f"Нет класса с индексом {index}")
    # проверка уникальности имени среди прочих
    for i, c in enumerate(classes):
        if i != index and c.get("name") == name:
            raise ValueError(f"Класс с именем {name!r} уже существует")
    entry = classes[index]
    entry["name"] = name
    if test:
        entry["test"] = test
    else:
        entry.pop("test", None)
    return entry


def remove_class(dhcp_body: Dict[str, Any], index: int) -> None:
    classes = classes_of(dhcp_body)
    if 0 <= index < len(classes):
        del classes[index]
    else:
        raise IndexError(f"Нет класса с индексом {index}")


# -- связывание с подсетями/пулами -------------------------------------------

def set_client_class(container: Dict[str, Any], name: Optional[str]) -> None:
    """Задать/снять client-class у пула или подсети."""
    if name:
        container["client-class"] = name
    else:
        container.pop("client-class", None)


def require_classes_of(container: Dict[str, Any]) -> List[str]:
    return container.setdefault("require-client-classes", [])


def set_require_classes(container: Dict[str, Any],
                        names: List[str]) -> None:
    names = [n for n in names if n]
    if names:
        container["require-client-classes"] = names
    else:
        container.pop("require-client-classes", None)


# -- валидация ---------------------------------------------------------------

def validate_class_name(name: str) -> tuple:
    name = (name or "").strip()
    if not name:
        return (False, "Имя класса не задано")
    # Kea не разрешает имена, начинающиеся со служебных префиксов
    for prefix in ("VENDOR_CLASS_", "AFTER_", "EXTERNAL_"):
        if name.startswith(prefix):
            return (False,
                    f"Имя класса не должно начинаться с {prefix!r} "
                    "(зарезервировано Kea)")
    return (True, "")
