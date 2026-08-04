"""Генерация английского перевода kea-manager.po из карты переводов.

Извлекает все msgid из вызовов _() в исходниках, сопоставляет с
английскими переводами из TRANSLATIONS и пишет
kea_manager/locale/en/LC_MESSAGES/kea-manager.po. Строки без перевода
остаются с пустым msgstr (gettext вернёт оригинал) и печатаются в отчёте.
"""

import ast
import glob
import os

TRANSLATIONS = {
    "  ● активен": "  ● active",
    " (есть и lease6)": " (lease6 present too)",
    "(без класса)": "(no class)",
    "(не задано)": "(not set)",
    "DHCP IPv6 не сконфигурирован": "DHCP IPv6 is not configured",
    "DHCP-опции": "DHCP options",
    "DHCP-опции {} — {}": "DHCP options {} — {}",
    "DHCP-опция": "DHCP option",
    "DHCPv4 (обязательно)": "DHCPv4 (required)",
    "DHCPv4 и DHCPv6 должны слушать разные адрес/порт. "
    "Логин/пароль — при включённой аутентификации control-socket.":
        "DHCPv4 and DHCPv6 must listen on different address/port. "
        "Username/password — when control-socket authentication is enabled.",
    "DHCPv6 (необязательно)": "DHCPv6 (optional)",
    "DNS-серверы (dns-servers)": "DNS servers (dns-servers)",
    "DNS-серверы (domain-name-servers)": "DNS servers (domain-name-servers)",
    "HA также требует загруженной библиотеки libdhcp_lease_cmds.so "
    "для обмена арендами.":
        "HA also requires the libdhcp_lease_cmds.so library loaded "
        "for lease sharing.",
    "ID (необязательно):": "ID (optional):",
    "ID должен быть целым": "ID must be an integer",
    "ID подсети должен быть целым числом": "Subnet ID must be an integer",
    "IP-адрес": "IP address",
    "IP-адрес (ip-address):": "IP address (ip-address):",
    "IPv4 через запятую: 192.0.2.1, 192.0.2.2":
        "IPv4, comma-separated: 192.0.2.1, 192.0.2.2",
    "IPv4 через запятую: 192.0.2.10": "IPv4, comma-separated: 192.0.2.10",
    "IPv6 (kea-dhcp6) — не сконфигурировано":
        "IPv6 (kea-dhcp6) — not configured",
    "IPv6 через запятую: 2001:db8::1": "IPv6, comma-separated: 2001:db8::1",
    "IPv6 через запятую: 2001:db8::10": "IPv6, comma-separated: 2001:db8::10",
    "MAC-адрес": "MAC address",
    "MAC-адрес (hw-address):": "MAC address (hw-address):",
    "NTP-серверы (time-servers)": "NTP servers (time-servers)",
    "NTP/SNTP-серверы (sntp-servers)": "NTP/SNTP servers (sntp-servers)",
    "Rebind timer, сек (T2):": "Rebind timer, sec (T2):",
    "Renew timer, сек (T1):": "Renew timer, sec (T1):",
    "always-send (отправлять всегда)": "always-send",
    "kea-manager — редактор конфигурации Kea DHCP":
        "kea-manager — Kea DHCP configuration editor",
    "lease{4,6}-get-page не поддерживается: загрузите hook "
    "libdhcp_lease_cmds.":
        "lease{4,6}-get-page not supported: load the libdhcp_lease_cmds hook.",
    "Адрес": "Address",
    "Адрес {} вне подсети {}": "Address {} is outside subnet {}",
    "Аренд показано: {} (из файла)": "Leases shown: {} (from file)",
    "Аренд показано: {} (по API)": "Leases shown: {} (via API)",
    "Аренда {} не найдена на сервере (возможно, файл устарел). "
    "Обновите список.":
        "Lease {} not found on the server (the file may be stale). "
        "Refresh the list.",
    "Аренда удалена.": "Lease deleted.",
    "Аренды": "Leases",
    "Аренды адресов": "Address leases",
    "Введите имя опции Kea и значение вручную.":
        "Enter the Kea option name and value manually.",
    "Версия {}": "Version {}",
    "Включить HA (libdhcp_ha.so)": "Enable HA (libdhcp_ha.so)",
    "Время аренды, сек (valid-lifetime):":
        "Lease time, sec (valid-lifetime):",
    "Выберите аренду в таблице.": "Select a lease in the table.",
    "Выберите подсеть для удаления.": "Select a subnet to delete.",
    "Выберите узел в дереве слева, чтобы редактировать конфигурацию."
    "\n\nСервер → IPv4 / IPv6 → подсети и пулы.":
        "Select a node in the tree on the left to edit the configuration."
        "\n\nServer → IPv4 / IPv6 → subnets and pools.",
    "Высокая доступность (HA)": "High Availability (HA)",
    "Выход": "Exit",
    "Глобальные DHCP-опции": "Global DHCP options",
    "Готово": "Done",
    "Диапазон 'A - B' или подсеть 'A/prefix':":
        "Range 'A - B' or subnet 'A/prefix':",
    "Для файлового сервера измените каталог удалением и повторным "
    "добавлением.":
        "For a file server, change the directory by removing and re-adding it.",
    "Добавить подсеть": "Add subnet",
    "Добавить пул": "Add pool",
    "Добавить сервер": "Add server",
    "Добавить сервер (API)…": "Add server (API)…",
    "Добавить сервер (каталог)…": "Add server (directory)…",
    "Добавить…": "Add…",
    "Доменное имя (domain-name)": "Domain name (domain-name)",
    "Домены через запятую: a.example.org":
        "Domains, comma-separated: a.example.org",
    "Домены через запятую: a.example.org, b.example.org":
        "Domains, comma-separated: a.example.org, b.example.org",
    "Есть несохранённые изменения. Продолжить без сохранения?":
        "There are unsaved changes. Continue without saving?",
    "Задайте IP-адрес и/или имя хоста":
        "Provide an IP address and/or hostname",
    "Закрыть": "Close",
    "Записаны файлы в {}:\n{}\n\nПерезагрузите службы Kea вручную, "
    "чтобы применить изменения.":
        "Files written to {}:\n{}\n\nReload the Kea services manually "
        "to apply the changes.",
    "Значение": "Value",
    "Значение (data):": "Value (data):",
    "Значение опции не задано": "Option value is not set",
    "Изменение": "Editing",
    "Изменить…": "Edit…",
    "Имя": "Name",
    "Имя (name):": "Name (name):",
    "Имя класса": "Class name",
    "Имя класса (name):": "Class name (name):",
    "Имя не может быть пустым": "Name cannot be empty",
    "Имя опции:": "Option name:",
    "Имя сервера": "Server name",
    "Имя хоста": "Hostname",
    "Имя хоста (hostname):": "Hostname (hostname):",
    "Имя этого сервера (this-server-name):":
        "This server name (this-server-name):",
    "Интерфейсы (через запятую):": "Interfaces (comma-separated):",
    "Использовать HTTPS (TLS)": "Use HTTPS (TLS)",
    "Истекает": "Expires",
    "Каталог с conf-файлами Kea": "Directory with Kea conf files",
    "Класс клиентов": "Client class",
    "Класс клиентов (client-class):": "Client class (client-class):",
    "Классы клиентов": "Client classes",
    "Классы клиентов (client-classes)": "Client classes (client-classes)",
    "Команда удаления аренды не поддерживается сервером.\n"
    "Загрузите hook-библиотеку libdhcp_lease_cmds в Kea.":
        "The lease deletion command is not supported by the server.\n"
        "Load the libdhcp_lease_cmds hook library in Kea.",
    "Куда сохранить conf-файлы": "Where to save conf files",
    "Логин:": "Username:",
    "Маршрут {}: {}": "Route {}: {}",
    "Маршрут {}: шлюз — {}": "Route {}: gateway — {}",
    "Маршрут должен быть в формате 'подсеть - шлюз': {}":
        "Route must be in the format 'subnet - gateway': {}",
    "Название сервера (отображается в дереве):":
        "Server name (shown in the tree):",
    "Не задан путь к control-socket.\nОн берётся из секции control-socket "
    "конфигурации службы.":
        "Control-socket path is not set.\nIt is taken from the control-socket "
        "section of the service configuration.",
    "Не задан хост": "Host is not set",
    "Не задано значение опции": "Option value is not set",
    "Не задано имя peer": "Peer name is not set",
    "Не задано имя опции": "Option name is not set",
    "Не найдено": "Not found",
    "Не удалось подключиться:\n{}": "Failed to connect:\n{}",
    "Недоступно": "Unavailable",
    "Некорректное доменное имя: {}": "Invalid domain name: {}",
    "Некорректный порт: {!r}": "Invalid port: {!r}",
    "Некорректный порт: {}": "Invalid port: {}",
    "Несохранённые изменения": "Unsaved changes",
    "Нет серверов — «Файл → Добавить сервер…»":
        "No servers — “File → Add server…”",
    "Новая подсеть": "New subnet",
    "О программе": "About",
    "Обновить": "Refresh",
    "Общие настройки применены.": "General settings applied.",
    "Общие настройки службы DHCP {}": "General DHCP {} service settings",
    "Один или несколько IPv4 через запятую: 192.0.2.1":
        "One or more IPv4, comma-separated: 192.0.2.1",
    "Опции класса: {}": "Class options: {}",
    "Опции класса…": "Class options…",
    "Опций": "Options",
    "Опция": "Option",
    "Опция:": "Option:",
    "Основной шлюз (routers)": "Default gateway (routers)",
    "Осталось": "Remaining",
    "Отклонено сервером": "Rejected by server",
    "Отключить HA": "Disable HA",
    "Отмена": "Cancel",
    "Ошибка": "Error",
    "Ошибка подключения": "Connection error",
    "Ошибка сервера": "Server error",
    "Ошибка сервера: {}": "Server error: {}",
    "Ошибка соединения": "Connection error",
    "Ошибка соединения: {}": "Connection error: {}",
    "Ошибка сохранения": "Save error",
    "Ошибка чтения файла аренд: {}": "Error reading lease file: {}",
    "Пароль": "Password",
    "Пароль для {}@{}:": "Password for {}@{}:",
    "Пароль:": "Password:",
    "Партнёр HA": "HA peer",
    "Партнёры (peers):": "Peers:",
    "Перезапись": "Overwrite",
    "Подключаться к DHCPv6": "Connect to DHCPv6",
    "Подключение успешно: {}\n\nВерсия Kea: {}\nКоманд доступно: {}\n"
    "Управление арендами (lease_cmds): {}":
        "Connection successful: {}\n\nKea version: {}\nCommands available: {}\n"
        "Lease management (lease_cmds): {}",
    "Подключиться": "Connect",
    "Подключиться к серверу Kea по API": "Connect to Kea server via API",
    "Подсеть": "Subnet",
    "Подсеть (CIDR):": "Subnet (CIDR):",
    "Подсеть IPv{} (CIDR):": "IPv{} subnet (CIDR):",
    "Подсеть сохранена.": "Subnet saved.",
    "Подсеть: {}": "Subnet: {}",
    "Подсеть: {} (id {})": "Subnet: {} (id {})",
    "Подтверждение": "Confirmation",
    "Поисковый домен (domain-search)": "Search domain (domain-search)",
    "Показывать неактивные (отклонённые/освобождённые)":
        "Show inactive (declined/released)",
    "Порт:": "Port:",
    "Применено": "Applied",
    "Применить": "Apply",
    "Применить конфигурацию к работающему серверу Kea?\n\nБудет выполнено: "
    "config-test → config-set → config-write.\nИзменения вступят в силу "
    "немедленно, без перезапуска.":
        "Apply the configuration to the running Kea server?\n\nWill run: "
        "config-test → config-set → config-write.\nChanges take effect "
        "immediately, without a restart.",
    "Применить на сервер": "Apply to server",
    "Применить параметры HA": "Apply HA settings",
    "Пример: option[60].text == 'CiscoIPPhone'":
        "Example: option[60].text == 'CiscoIPPhone'",
    "Принудительно удалить аренду {} ({})?\n\nОперация затрагивает "
    "работающую службу Kea и требует загруженной hook-библиотеки "
    "lease_cmds.":
        "Forcibly delete lease {} ({})?\n\nThis affects the running Kea "
        "service and requires the lease_cmds hook library loaded.",
    "Проверить соединение": "Test connection",
    "Проверка соединения": "Connection test",
    "Проверять сертификат (для HTTPS)": "Verify certificate (for HTTPS)",
    "Пулы": "Pools",
    "Пулы адресов:": "Address pools:",
    "Путь к файлу аренд не задан.": "Lease file path is not set.",
    "Редактор конфигурации Kea DHCP\nПоддерживаемая версия Kea: {}":
        "Kea DHCP configuration editor\nSupported Kea version: {}",
    "Режим:": "Mode:",
    "Режим: API (control-channel)": "Mode: API (control-channel)",
    "Режим: локальные файлы": "Mode: local files",
    "Режим: не подключено": "Mode: not connected",
    "Резервирование": "Reservation",
    "Резервирования": "Reservations",
    "Резервирования адресов": "Address reservations",
    "Роль": "Role",
    "Роль (role):": "Role (role):",
    "Сайт проекта:": "Project website:",
    "Сервер {!r} уже есть. Перезаписать параметры?":
        "Server {!r} already exists. Overwrite its settings?",
    "Сервер вернул ошибку: {}": "Server returned an error: {}",
    "Сервер отверг конфигурацию:\n{}": "Server rejected the configuration:\n{}",
    "Сконфигурировать IPv6": "Configure IPv6",
    "Смена языка": "Language change",
    "Сначала подключитесь к серверу.": "Connect to a server first.",
    "Сначала сконфигурируйте IPv6.": "Configure IPv6 first.",
    "Состояние": "State",
    "Сохранение": "Saving",
    "Сохранено": "Saved",
    "Сохранить": "Save",
    "Сохранить в каталог…": "Save to directory…",
    "Список 'подсеть - шлюз' через запятую: 192.0.5.0/24 - 192.0.2.2":
        "List of 'subnet - gateway', comma-separated: 192.0.5.0/24 - 192.0.2.2",
    "Справка": "Help",
    "Статические маршруты (classless-static-route)":
        "Static routes (classless-static-route)",
    "Строка: example.org": "String: example.org",
    "Транспорт": "Transport",
    "Удаление": "Deletion",
    "Удаление сервера": "Remove server",
    "Удалить": "Delete",
    "Удалить аренду…": "Delete lease…",
    "Удалить класс {!r}?": "Delete class {!r}?",
    "Удалить конфигурацию HA (libdhcp_ha.so)?\nПрочие hook-библиотеки "
    "останутся без изменений.":
        "Remove the HA configuration (libdhcp_ha.so)?\nOther hook libraries "
        "will remain unchanged.",
    "Удалить подсеть": "Delete subnet",
    "Удалить подсеть {}?": "Delete subnet {}?",
    "Удалить сервер": "Remove server",
    "Удалить сервер {!r} из списка?": "Remove server {!r} from the list?",
    "Условие (test)": "Condition (test)",
    "Условие (test):": "Condition (test):",
    "Файл": "File",
    "Файл kea-dhcp6.conf не будет создан при сохранении.\nНажмите кнопку "
    "ниже, чтобы начать конфигурировать IPv6.":
        "The kea-dhcp6.conf file will not be created on save.\nClick the "
        "button below to start configuring IPv6.",
    "Файл аренд (CSV):": "Lease file (CSV):",
    "Файл аренд не найден: {}": "Lease file not found: {}",
    "Хост:": "Host:",
    "Язык": "Language",
    "Язык интерфейса изменится после перезапуска приложения.":
        "The interface language will change after restarting the application.",
    "выберите сервер в дереве или добавьте новый":
        "select a server in the tree or add a new one",
    "глобальные настройки службы": "service global settings",
    "да": "yes",
    "класс {}": "class {}",
    "не подключено": "not connected",
    "нет": "no",
    "новый проект": "new project",
    "подсеть {}": "subnet {}",
    "файлы: {}": "files: {}",
    "— произвольная опция —": "— custom option —",
    "● есть несохранённые изменения": "● unsaved changes",
}

PO_HEADER = '''msgid ""
msgstr ""
"Project-Id-Version: kea-manager 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Language: en\\n"

'''


def _po_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def collect_msgids(root):
    ids = set()
    for f in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        tree = ast.parse(open(f, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "_" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    ids.add(a.value)
    return sorted(ids)


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pkg = os.path.join(here, "kea_manager")
    ids = collect_msgids(pkg)
    out_dir = os.path.join(pkg, "locale", "en", "LC_MESSAGES")
    os.makedirs(out_dir, exist_ok=True)
    po_path = os.path.join(out_dir, "kea-manager.po")

    missing = []
    with open(po_path, "w", encoding="utf-8") as fh:
        fh.write(PO_HEADER)
        for mid in ids:
            tr = TRANSLATIONS.get(mid, "")
            if not tr:
                missing.append(mid)
            fh.write(f'msgid "{_po_escape(mid)}"\n')
            fh.write(f'msgstr "{_po_escape(tr)}"\n\n')

    print(f"Записан {po_path}: {len(ids)} строк, без перевода: {len(missing)}")
    for m in missing:
        print("  НЕТ ПЕРЕВОДА:", repr(m))


if __name__ == "__main__":
    main()
