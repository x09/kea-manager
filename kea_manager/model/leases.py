"""Чтение файлов аренд Kea (memfile CSV).

Формат memfile — обычный CSV с заголовком. Набор колонок отличается между
kea-dhcp4 и kea-dhcp6 и может расширяться между версиями Kea, поэтому мы
разбираем файл через ``csv.DictReader`` по именам колонок, а не по позициям.

Колонки kea-dhcp4 (типично):
    address, hwaddr, client_id, valid_lifetime, expire, subnet_id,
    fqdn_fwd, fqdn_rev, hostname, state, user_context, pool_id

Колонки kea-dhcp6 (типично):
    address, duid, valid_lifetime, expire, subnet_id, pref_lifetime,
    lease_type, iaid, prefix_len, fqdn_fwd, fqdn_rev, hostname, hwaddr,
    state, user_context, hwtype, hwaddr_source, pool_id

Важные особенности memfile:
  * Файл дописывается в конец: одна и та же аренда (адрес, а для DHCPv6 —
    адрес+iaid+lease_type) может встречаться несколько раз. Актуальной
    является ПОСЛЕДНЯЯ запись.
  * ``expire`` — абсолютное время истечения (Unix timestamp).
  * ``valid_lifetime == 0`` означает удалённую аренду — её нужно исключить.
  * LFC (Lease File Cleanup) периодически пересобирает файл; во время
    работы могут существовать вспомогательные файлы с суффиксами
    ``.1``/``.2``. Наиболее полный набор получается объединением
    основного файла и, при наличии, ``<файл>.2`` (готовый результат LFC),
    с последующей дедупликацией «побеждает последняя запись».

Модуль использует только стандартную библиотеку.
"""

from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# Состояния аренды Kea
STATE_DEFAULT = 0            # выдана/активна
STATE_DECLINED = 1           # отклонена (declined)
STATE_EXPIRED_RECLAIMED = 2  # истекла и освобождена
STATE_RELEASED = 3           # освобождена (release)

STATE_LABELS = {
    STATE_DEFAULT: "активна",
    STATE_DECLINED: "отклонена",
    STATE_EXPIRED_RECLAIMED: "освобождена",
    STATE_RELEASED: "released",
}


@dataclass
class LeaseRecord:
    address: str
    hwaddr: str = ""
    duid: str = ""
    client_id: str = ""
    valid_lifetime: int = 0
    expire: int = 0             # абсолютный Unix timestamp
    subnet_id: str = ""
    hostname: str = ""
    state: int = STATE_DEFAULT
    lease_type: str = ""        # только DHCPv6 (IA_NA / IA_PD)
    raw: Optional[Dict[str, str]] = None

    # -- производные представления ---------------------------------------

    @property
    def identifier(self) -> str:
        """Идентификатор клиента для отображения."""
        return self.hwaddr or self.duid or self.client_id or ""

    @property
    def state_label(self) -> str:
        return STATE_LABELS.get(self.state, str(self.state))

    def is_active(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        return self.state == STATE_DEFAULT and self.expire > now

    def expire_str(self) -> str:
        if not self.expire:
            return ""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.expire))

    def remaining_str(self, now: Optional[float] = None) -> str:
        """Осталось до истечения в человекочитаемом виде."""
        now = now if now is not None else time.time()
        delta = int(self.expire - now)
        if delta <= 0:
            return "истекла"
        days, rem = divmod(delta, 86400)
        hours, rem = divmod(rem, 3600)
        mins, _ = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}д")
        if hours:
            parts.append(f"{hours}ч")
        if mins and not days:
            parts.append(f"{mins}м")
        return " ".join(parts) if parts else "<1м"


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dedup_key(row: Dict[str, str], family: int) -> str:
    """Ключ дедупликации записи аренды."""
    addr = (row.get("address") or "").strip()
    if family == 6:
        # для DHCPv6 одна и та же запись различается адресом + типом + iaid
        return "|".join([
            addr,
            (row.get("lease_type") or "").strip(),
            (row.get("iaid") or "").strip(),
        ])
    return addr


def _row_to_record(row: Dict[str, str], family: int) -> LeaseRecord:
    return LeaseRecord(
        address=(row.get("address") or "").strip(),
        hwaddr=(row.get("hwaddr") or "").strip(),
        duid=(row.get("duid") or "").strip(),
        client_id=(row.get("client_id") or "").strip(),
        valid_lifetime=_to_int(row.get("valid_lifetime")),
        expire=_to_int(row.get("expire")),
        subnet_id=(row.get("subnet_id") or "").strip(),
        hostname=(row.get("hostname") or "").strip(),
        state=_to_int(row.get("state"), STATE_DEFAULT),
        lease_type=(row.get("lease_type") or "").strip(),
        raw=dict(row),
    )


def _read_csv_rows(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return [row for row in reader if row.get("address")]


def candidate_files(path: str) -> List[str]:
    """Список файлов для чтения: основной и, при наличии, LFC-файлы.

    Порядок важен: сначала завершённый LFC-результат (``.2``), затем
    основной файл — более свежие записи из основного перекрывают старые.
    """
    files = []
    lfc2 = path + ".2"
    if os.path.isfile(lfc2):
        files.append(lfc2)
    if os.path.isfile(path):
        files.append(path)
    return files


def read_leases(path: str, family: int = 4,
                include_inactive: bool = False) -> List[LeaseRecord]:
    """Прочитать аренды из memfile CSV с дедупликацией.

    path: путь к kea-leases4.csv / kea-leases6.csv.
    family: 4 или 6.
    include_inactive: включать ли отклонённые/освобождённые аренды.

    Возвращает список актуальных аренд, отсортированный по адресу.
    Бросает FileNotFoundError, если ни одного файла нет.
    """
    files = candidate_files(path)
    if not files:
        raise FileNotFoundError(f"Файл аренд не найден: {path}")

    latest: Dict[str, Dict[str, str]] = {}
    for fpath in files:
        for row in _read_csv_rows(fpath):
            key = _dedup_key(row, family)
            latest[key] = row  # последняя запись побеждает

    records: List[LeaseRecord] = []
    for row in latest.values():
        # valid_lifetime == 0 => удалённая аренда
        if _to_int(row.get("valid_lifetime")) == 0:
            continue
        rec = _row_to_record(row, family)
        if not include_inactive and rec.state in (
                STATE_EXPIRED_RECLAIMED, STATE_RELEASED):
            continue
        records.append(rec)

    records.sort(key=lambda r: _sort_key(r.address))
    return records


def _sort_key(address: str):
    """Ключ сортировки IP-адресов (числовой, с запасным строковым)."""
    try:
        import ipaddress
        return (0, int(ipaddress.ip_address(address)))
    except ValueError:
        return (1, address)


def _api_row_to_record(item: Dict[str, Any], family: int) -> "LeaseRecord":
    """Преобразовать элемент ответа lease{4,6}-get-page в LeaseRecord.

    Поля API отличаются от CSV: cltt + valid-lft вместо абсолютного expire,
    hw-address вместо hwaddr и т.д.
    """
    cltt = _to_int(item.get("cltt"))
    valid = _to_int(item.get("valid-lft"))
    expire = cltt + valid if cltt else 0
    return LeaseRecord(
        address=str(item.get("ip-address", "")),
        hwaddr=str(item.get("hw-address", "")),
        duid=str(item.get("duid", "")),
        client_id=str(item.get("client-id", "")),
        valid_lifetime=valid,
        expire=expire,
        subnet_id=str(item.get("subnet-id", "")),
        hostname=str(item.get("hostname", "")),
        state=_to_int(item.get("state"), STATE_DEFAULT),
        lease_type=str(item.get("type", "")),
        raw=dict(item),
    )


def read_leases_api(client, family: int = 4,
                    include_inactive: bool = False,
                    page_limit: int = 1000) -> List["LeaseRecord"]:
    """Прочитать аренды через control-channel (lease{4,6}-get-page).

    client — объект с методом send_command (KeaHttpClient/KeaControlSocket).
    Постранично обходит все аренды. Требует hook-библиотеку lease_cmds.
    """
    cmd = "lease4-get-page" if family == 4 else "lease6-get-page"
    records: List[LeaseRecord] = []
    from_val = "0.0.0.0" if family == 4 else "::"
    seen_guard = 0
    while True:
        resp = client.send_command(
            cmd, {"from": from_val, "limit": page_limit})
        args = resp.get("arguments", {}) if isinstance(resp, dict) else {}
        items = args.get("leases", []) if isinstance(args, dict) else []
        if not items:
            break
        for it in items:
            rec = _api_row_to_record(it, family)
            if not include_inactive and rec.state in (
                    STATE_EXPIRED_RECLAIMED, STATE_RELEASED):
                continue
            records.append(rec)
        # следующая страница — от последнего адреса
        last_addr = items[-1].get("ip-address")
        if not last_addr or last_addr == from_val:
            break
        from_val = last_addr
        seen_guard += 1
        if seen_guard > 10000:  # страховка от зацикливания
            break
    records.sort(key=lambda r: _sort_key(r.address))
    return records


def guess_lease_path(dhcp_body: dict, family: int) -> Optional[str]:
    """Определить путь к файлу аренд из тела конфигурации службы.

    Ищет lease-database.name при type == memfile. Возвращает путь или
    значение по умолчанию Kea, если не задано.
    """
    ldb = dhcp_body.get("lease-database") if isinstance(dhcp_body, dict) else None
    if isinstance(ldb, dict):
        if ldb.get("type") == "memfile" and ldb.get("name"):
            return ldb["name"]
        # не memfile — путь к CSV неизвестен
        if ldb.get("type") and ldb.get("type") != "memfile":
            return None
    # значение по умолчанию Kea
    return f"/var/lib/kea/kea-leases{family}.csv"
