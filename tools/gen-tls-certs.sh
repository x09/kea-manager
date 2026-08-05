#!/bin/sh
# Генерация самоподписанных TLS-сертификатов для control-socket Kea и
# настройка аутентификации по клиентскому сертификату (mutual TLS).
#
# Создаёт: собственный CA, серверный сертификат (для kea-dhcp4) и клиентский
# сертификат (для kea-manager). Все — подписаны одним CA, самоподписанный
# CA не требует внешнего доверия (это нормально для закрытой сети).
#
# Использование:
#   sh tools/gen-tls-certs.sh [OUTDIR] [ADDR ...]
# по умолчанию OUTDIR=/etc/kea/tls, ADDR=127.0.0.1
#
# ADDR — один или несколько адресов/имён, по которым клиент будет
# подключаться к серверу (по ним TLS сверяет сертификат). Можно передать
# несколько: IP-адреса и DNS-имена. 127.0.0.1 добавляется автоматически.
# Пример: sh tools/gen-tls-certs.sh /etc/kea/tls 192.168.150.10 kea.local
#
# Требует openssl. Скрипт ничего не устанавливает и не перезапускает —
# только создаёт файлы и печатает фрагмент конфигурации Kea.

set -e

OUTDIR="${1:-/etc/kea/tls}"
shift 2>/dev/null || true
if [ "$#" -eq 0 ]; then
    set -- 127.0.0.1
fi
# основной адрес (для CN и для примера конфига) — первый аргумент
PRIMARY="$1"
DAYS=3650

# Собираем список SAN: все переданные адреса + 127.0.0.1.
# IP и DNS-имена различаем простым шаблоном (только цифры и точки => IP).
SAN=""
add_san() {
    _v="$1"
    case "$_v" in
        *[!0-9.]*) _type="DNS" ;;   # есть не-цифра/точка => имя
        *) _type="IP" ;;
    esac
    if [ -z "$SAN" ]; then
        SAN="${_type}:${_v}"
    else
        SAN="${SAN}, ${_type}:${_v}"
    fi
}
for a in "$@"; do
    add_san "$a"
done
# гарантированно добавим localhost, если его не указали
case " $* " in
    *" 127.0.0.1 "*) : ;;
    *) add_san "127.0.0.1" ;;
esac

echo "Каталог вывода : $OUTDIR"
echo "Основной адрес : $PRIMARY"
echo "SAN сертификата: $SAN"
echo

mkdir -p "$OUTDIR"
cd "$OUTDIR"

umask 077

# --- 1. Собственный CA ------------------------------------------------------
if [ ! -f ca-key.pem ]; then
    openssl genrsa -out ca-key.pem 4096
    openssl req -x509 -new -nodes -key ca-key.pem -sha256 -days "$DAYS" \
        -subj "/CN=kea-manager-CA" -out ca-cert.pem
    echo "Создан CA: ca-cert.pem"
else
    echo "CA уже существует, пропускаю."
fi

# --- 2. Серверный сертификат (SAN = все переданные адреса) ------------------
cat > server-ext.cnf <<EOF
subjectAltName = ${SAN}
extendedKeyUsage = serverAuth
EOF

openssl genrsa -out server-key.pem 4096
openssl req -new -key server-key.pem \
    -subj "/CN=${PRIMARY}" -out server.csr
openssl x509 -req -in server.csr -CA ca-cert.pem -CAkey ca-key.pem \
    -CAcreateserial -days "$DAYS" -sha256 \
    -extfile server-ext.cnf -out server-cert.pem
echo "Создан серверный сертификат: server-cert.pem"

# --- 3. Клиентский сертификат (для kea-manager) -----------------------------
cat > client-ext.cnf <<EOF
extendedKeyUsage = clientAuth
EOF

openssl genrsa -out client-key.pem 4096
openssl req -new -key client-key.pem \
    -subj "/CN=kea-manager-client" -out client.csr
openssl x509 -req -in client.csr -CA ca-cert.pem -CAkey ca-key.pem \
    -CAcreateserial -days "$DAYS" -sha256 \
    -extfile client-ext.cnf -out client-cert.pem
echo "Создан клиентский сертификат: client-cert.pem"

# уборка временных файлов
rm -f server.csr client.csr server-ext.cnf client-ext.cnf

# владелец файлов Kea (если запускаем от root и есть пользователь _kea/kea)
for u in _kea kea; do
    if id "$u" >/dev/null 2>&1; then
        chown "$u":"$u" ca-cert.pem server-cert.pem server-key.pem 2>/dev/null || true
        break
    fi
done

echo
echo "======================================================================"
echo "Файлы созданы в $OUTDIR:"
echo "  ca-cert.pem       — CA (нужен и серверу, и клиенту)"
echo "  server-cert.pem   — серверный сертификат (для kea-dhcp4)"
echo "  server-key.pem    — серверный ключ (держать в секрете)"
echo "  client-cert.pem   — клиентский сертификат (для kea-manager)"
echo "  client-key.pem    — клиентский ключ (скопировать на машину клиента)"
echo
echo "Фрагмент для kea-dhcp4.conf (секция Dhcp4.control-sockets):"
cat <<EOF

  "control-sockets": [
    {
      "socket-type": "https",
      "socket-address": "0.0.0.0",
      "socket-port": 8123,
      "trust-anchor": "${OUTDIR}/ca-cert.pem",
      "cert-file": "${OUTDIR}/server-cert.pem",
      "key-file": "${OUTDIR}/server-key.pem",
      "cert-required": true,
      "authentication": {
        "type": "basic",
        "realm": "kea-dhcp4-server",
        "directory": "/etc/kea/creds",
        "clients": [ { "user": "admin", "password-file": "admin.pwd" } ]
      }
    }
  ]

EOF
echo "Пояснения:"
echo "  cert-required: true  — сервер ТРЕБУЕТ клиентский сертификат;"
echo "  блок authentication можно убрать, если хотите ТОЛЬКО сертификат,"
echo "  либо оставить — тогда нужны и сертификат, И логин/пароль."
echo
echo "В kea-manager (диалог подключения, раздел «Сертификаты TLS»):"
echo "  HTTPS (TLS)            : включить"
echo "  CA-сертификат         : ${OUTDIR}/ca-cert.pem  (или снять «Проверять сертификат»)"
echo "  Клиентский сертификат : путь к client-cert.pem"
echo "  Клиентский ключ       : путь к client-key.pem"
echo "======================================================================"
