"""Модель статистики Kea (statistic-get-all и обработка метрик).

Kea возвращает метрики в формате::

    {
      "result": 0,
      "arguments": {
        "pkt4-received": [[value, "timestamp"]],
        "subnet[1].assigned-addresses": [[50, "..."]],
        ...
      }
    }

Значение — массив из одного элемента ``[value, timestamp]``, где value может
быть числом или строкой. Timestamp — строка ISO-подобного формата.

Группы метрик:
  - **Глобальные**: ``pkt4-*``, ``pkt6-*``, счётчики без префикса subnet.
  - **Per-subnet**: ``subnet[ID].метрика``.
  - **Per-pool**: ``subnet[ID].pool[N].метрика`` (если загружен stat_cmds).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


class Snapshot:
    """Снимок статистики в момент времени.

    Attributes:
        timestamp: Время получения снимка (float, seconds since epoch).
        metrics: Словарь {имя_метрики: значение}.
    """

    def __init__(self, timestamp: float, metrics: Dict[str, Any]):
        self.timestamp = timestamp
        self.metrics = metrics

    def get(self, name: str, default: Any = 0) -> Any:
        return self.metrics.get(name, default)


def parse_stat_response(resp: Dict[str, Any]) -> Dict[str, Any]:
    """Распарсить ответ statistic-get-all.

    Kea возвращает ``arguments: {имя: [[значение, timestamp]]}``. Извлекаем
    только значения → ``{имя: значение}``.
    """
    args = resp.get("arguments", {})
    if not isinstance(args, dict):
        return {}
    out = {}
    for name, val in args.items():
        # формат [[value, ts]] или иногда просто value
        if isinstance(val, list) and len(val) > 0:
            if isinstance(val[0], list) and len(val[0]) > 0:
                out[name] = val[0][0]
            else:
                out[name] = val[0]
        else:
            out[name] = val
    return out


def group_metrics(metrics: Dict[str, Any]) -> Dict[str, List[Tuple[str, Any]]]:
    """Сгруппировать метрики по категориям.

    Returns:
        {"packets": [(name, value), ...], "addresses": [...], "subnets": {...}}
    """
    groups: Dict[str, List[Tuple[str, Any]]] = {
        "packets": [],
        "addresses": [],
        "subnets": [],
        "other": [],
    }
    for name, val in sorted(metrics.items()):
        if name.startswith("pkt"):
            groups["packets"].append((name, val))
        elif "address" in name or "lease" in name:
            if not name.startswith("subnet"):
                groups["addresses"].append((name, val))
            else:
                groups["subnets"].append((name, val))
        elif name.startswith("subnet"):
            groups["subnets"].append((name, val))
        else:
            groups["other"].append((name, val))
    return groups


def extract_subnet_id(metric_name: str) -> Optional[int]:
    """Извлечь ID подсети из имени метрики вида ``subnet[123].assigned``.

    Returns:
        ID подсети или None, если формат не совпадает.
    """
    m = re.match(r"subnet\[(\d+)\]", metric_name)
    return int(m.group(1)) if m else None


def compute_rate(prev: Optional[Snapshot], curr: Snapshot,
                 metric: str) -> Optional[float]:
    """Вычислить rate (изменение/сек) между снимками.

    Returns:
        rate (значение/сек) или None, если данных недостаточно.
    """
    if prev is None:
        return None
    dt = curr.timestamp - prev.timestamp
    if dt <= 0:
        return None
    v_prev = prev.get(metric, 0)
    v_curr = curr.get(metric, 0)
    try:
        delta = float(v_curr) - float(v_prev)
        return delta / dt
    except (ValueError, TypeError):
        return None


def top_subnet_by_usage(metrics: Dict[str, Any]) -> Optional[Tuple[int, float]]:
    """Найти подсеть с наибольшим процентом использования адресов.

    Returns:
        (subnet_id, percent) или None.
    """
    best = None
    best_pct = 0.0
    for name, val in metrics.items():
        sid = extract_subnet_id(name)
        if sid is None:
            continue
        if ".assigned-addresses" in name:
            total_key = f"subnet[{sid}].total-addresses"
            total = metrics.get(total_key, 0)
            try:
                assigned = float(val)
                tot = float(total)
                if tot > 0:
                    pct = (assigned / tot) * 100
                    if pct > best_pct:
                        best_pct = pct
                        best = (sid, pct)
            except (ValueError, TypeError):
                pass
    return best
