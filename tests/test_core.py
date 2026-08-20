"""Тесты ядра kea-manager: JSONC-парсер, валидаторы, round-trip модели.

Запуск:  python3 -m unittest discover -s tests
Не требует tkinter.
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest

# Позволяем запускать из корня проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kea_manager.util import jsonc, validators as V
from kea_manager.model import DhcpConfig, KeaProject
from kea_manager.model import options as OPT
from kea_manager.model import leases as LEASES
from kea_manager.model import ha as HA
from kea_manager.model import classes as CLS
from kea_manager.model import leases as LEASES2  # noqa: F401 (алиас не нужен)
from kea_manager.model import statistics as STATS
from kea_manager.model.backend import Endpoint, ApiBackend, FileBackend
from kea_manager.util import ctrlsocket
from kea_manager.util import settings as SETTINGS


class TestJsonc(unittest.TestCase):
    def test_line_comments(self):
        text = '{ "a": 1, // comment\n "b": 2 }'
        self.assertEqual(jsonc.loads(text), {"a": 1, "b": 2})

    def test_hash_comments(self):
        text = '{ "a": 1, # comment\n "b": 2 }'
        self.assertEqual(jsonc.loads(text), {"a": 1, "b": 2})

    def test_block_comments(self):
        text = '{ "a": 1, /* multi\nline */ "b": 2 }'
        self.assertEqual(jsonc.loads(text), {"a": 1, "b": 2})

    def test_comment_chars_inside_string(self):
        text = '{ "url": "http://example.com/path", "hash": "a#b" }'
        self.assertEqual(
            jsonc.loads(text),
            {"url": "http://example.com/path", "hash": "a#b"},
        )

    def test_trailing_comma(self):
        text = '{ "list": [1, 2, 3,], "obj": {"x": 1,}, }'
        self.assertEqual(jsonc.loads(text), {"list": [1, 2, 3], "obj": {"x": 1}})

    def test_key_order_preserved(self):
        text = '{ "z": 1, "a": 2, "m": 3 }'
        self.assertEqual(list(jsonc.loads(text).keys()), ["z", "a", "m"])


class TestInputMask(unittest.TestCase):
    """Предикаты масок ввода (без tkinter — чистые функции)."""

    def setUp(self):
        from kea_manager.ui import inputmask
        self.m = inputmask

    def test_mac_partial(self):
        for ok in ["", "a", "aa", "aa:", "aa:bb", "aa:bb:cc:dd:ee:ff"]:
            self.assertTrue(self.m.is_partial_mac(ok), ok)
        for bad in ["ag", "aaa", "aa:bb:cc:dd:ee:ff:00", "zz"]:
            self.assertFalse(self.m.is_partial_mac(bad), bad)

    def test_ipv4_partial(self):
        for ok in ["", "1", "19", "192", "192.", "192.168.0.1", "255.255.255.0"]:
            self.assertTrue(self.m.is_partial_ipv4(ok), ok)
        for bad in ["256", "1.2.3.4.5", "12a", "1234", "300.1.1.1"]:
            self.assertFalse(self.m.is_partial_ipv4(bad), bad)

    def test_ipv6_partial(self):
        for ok in ["", "2001", "2001:db8", "2001:db8::1", "::1", "fe80::"]:
            self.assertTrue(self.m.is_partial_ipv6(ok), ok)
        for bad in ["12345", "xyz", "2001:db8:::::::1:2:3"]:
            self.assertFalse(self.m.is_partial_ipv6(bad), bad)

    def test_ip_dispatch(self):
        self.assertTrue(self.m.is_partial_ip("192.168.0.1"))
        self.assertTrue(self.m.is_partial_ip("2001:db8::1"))
        self.assertFalse(self.m.is_partial_ip("300.0.0.1"))


class TestValidators(unittest.TestCase):
    def test_ip(self):
        self.assertTrue(V.validate_ip("192.0.2.1", 4)[0])
        self.assertTrue(V.validate_ip("2001:db8::1", 6)[0])
        self.assertFalse(V.validate_ip("192.0.2.1", 6)[0])
        self.assertFalse(V.validate_ip("999.0.0.1")[0])

    def test_subnet(self):
        self.assertTrue(V.validate_subnet("192.0.2.0/24", 4)[0])
        self.assertFalse(V.validate_subnet("192.0.2.0", 4)[0])
        self.assertFalse(V.validate_subnet("192.0.2.0/33", 4)[0])

    def test_hw(self):
        self.assertTrue(V.validate_hw_address("aa:bb:cc:dd:ee:ff")[0])
        self.assertTrue(V.validate_hw_address("AA-BB-CC-DD-EE-FF")[0])
        self.assertFalse(V.validate_hw_address("aa:bb:cc:dd:ee")[0])
        self.assertFalse(V.validate_hw_address("zz:bb:cc:dd:ee:ff")[0])

    def test_pool(self):
        self.assertTrue(V.validate_pool("192.0.2.10 - 192.0.2.20", 4)[0])
        self.assertTrue(V.validate_pool("192.0.2.0/24", 4)[0])
        self.assertFalse(V.validate_pool("192.0.2.20 - 192.0.2.10", 4)[0])

    def test_pool_in_subnet(self):
        self.assertTrue(
            V.validate_pool_in_subnet("192.0.2.10 - 192.0.2.20", "192.0.2.0/24")[0]
        )
        self.assertFalse(
            V.validate_pool_in_subnet("192.0.3.10 - 192.0.3.20", "192.0.2.0/24")[0]
        )

    def test_pools_overlap(self):
        self.assertTrue(
            V.pools_overlap("192.0.2.10 - 192.0.2.20", "192.0.2.15 - 192.0.2.25")
        )
        self.assertFalse(
            V.pools_overlap("192.0.2.10 - 192.0.2.20", "192.0.2.30 - 192.0.2.40")
        )

    def test_lease_timers(self):
        self.assertTrue(V.validate_lease_timers(4000, 1000, 2000)[0])
        self.assertFalse(V.validate_lease_timers(4000, 3000, 2000)[0])
        self.assertFalse(V.validate_lease_timers(1000, 500, 2000)[0])
        self.assertTrue(V.validate_lease_timers(4000)[0])


class TestRoundTrip(unittest.TestCase):
    SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "sample", "kea-dhcp4.conf")

    def test_load_preserves_unknown_keys(self):
        cfg = DhcpConfig.load(self.SAMPLE, 4)
        # известные секции
        self.assertEqual(cfg.get_global("valid-lifetime"), 4000)
        self.assertEqual(len(cfg.subnets()), 1)
        # неизвестные редактору ключи должны сохраниться
        self.assertIn("control-socket", cfg.dhcp)
        self.assertIn("lease-database", cfg.dhcp)

    def test_save_and_reload(self):
        cfg = DhcpConfig.load(self.SAMPLE, 4)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out.conf")
            cfg.save(out)
            reloaded = DhcpConfig.load(out, 4)
            self.assertEqual(reloaded.dhcp, cfg.dhcp)
            # control-socket пережил round-trip
            self.assertEqual(
                reloaded.dhcp["control-socket"]["socket-name"],
                "/run/kea/kea4-ctrl-socket",
            )

    def test_add_subnet_and_pool(self):
        cfg = DhcpConfig.new(4)
        sub = cfg.add_subnet("10.0.0.0/24")
        self.assertEqual(sub["id"], 1)
        DhcpConfig.add_pool(sub, "10.0.0.100 - 10.0.0.200")
        self.assertEqual(len(cfg.subnets()[0]["pools"]), 1)
        # следующий id не должен конфликтовать
        sub2 = cfg.add_subnet("10.0.1.0/24")
        self.assertEqual(sub2["id"], 2)


class TestProject(unittest.TestCase):
    def test_dhcp6_optional(self):
        proj = KeaProject()
        self.assertFalse(proj.dhcp6_configured)
        proj.enable_dhcp6()
        self.assertTrue(proj.dhcp6_configured)
        proj.disable_dhcp6()
        self.assertFalse(proj.dhcp6_configured)

    def test_save_dir_skips_unconfigured_v6(self):
        proj = KeaProject()
        proj.dhcp4.add_subnet("192.0.2.0/24")
        with tempfile.TemporaryDirectory() as d:
            written = proj.save_dir(d)
            self.assertEqual(len(written), 1)
            self.assertTrue(os.path.isfile(os.path.join(d, "kea-dhcp4.conf")))
            self.assertFalse(os.path.isfile(os.path.join(d, "kea-dhcp6.conf")))

    def test_save_dir_writes_v6_when_configured(self):
        proj = KeaProject()
        proj.enable_dhcp6()
        proj.dhcp6.add_subnet("2001:db8::/64")
        with tempfile.TemporaryDirectory() as d:
            written = proj.save_dir(d)
            self.assertEqual(len(written), 2)
            self.assertTrue(os.path.isfile(os.path.join(d, "kea-dhcp6.conf")))


class TestReservations(unittest.TestCase):
    def test_add_update_remove(self):
        cfg = DhcpConfig.new(4)
        sub = cfg.add_subnet("192.0.2.0/24")
        r = DhcpConfig.add_reservation(
            sub, "aa:bb:cc:dd:ee:ff", "192.0.2.10", "host1")
        self.assertEqual(r["hw-address"], "aa:bb:cc:dd:ee:ff")
        self.assertEqual(len(DhcpConfig.reservations_of(sub)), 1)

        DhcpConfig.update_reservation(
            sub, 0, "aa:bb:cc:dd:ee:ff", "192.0.2.11", None)
        r = DhcpConfig.reservations_of(sub)[0]
        self.assertEqual(r["ip-address"], "192.0.2.11")
        self.assertNotIn("hostname", r)  # hostname очищен

        DhcpConfig.remove_reservation(sub, 0)
        self.assertEqual(len(DhcpConfig.reservations_of(sub)), 0)

    def test_reservation_round_trip(self):
        cfg = DhcpConfig.new(4)
        sub = cfg.add_subnet("192.0.2.0/24")
        DhcpConfig.add_reservation(sub, "aa:bb:cc:dd:ee:ff", "192.0.2.10")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "r.conf")
            cfg.save(out)
            re = DhcpConfig.load(out, 4)
            got = DhcpConfig.reservations_of(re.subnets()[0])[0]
            self.assertEqual(got["ip-address"], "192.0.2.10")


class TestOptions(unittest.TestCase):
    def test_set_update_option(self):
        cfg = DhcpConfig.new(4)
        sub = cfg.add_subnet("192.0.2.0/24")
        DhcpConfig.set_option(sub, "routers", "192.0.2.1")
        opts = DhcpConfig.options_of(sub)
        self.assertEqual(len(opts), 1)
        # повторный set по тому же имени обновляет, а не дублирует
        DhcpConfig.set_option(sub, "routers", "192.0.2.254", always_send=True)
        opts = DhcpConfig.options_of(sub)
        self.assertEqual(len(opts), 1)
        self.assertEqual(opts[0]["data"], "192.0.2.254")
        self.assertTrue(opts[0]["always-send"])

    def test_global_options(self):
        cfg = DhcpConfig.new(4)
        DhcpConfig.set_option(cfg.dhcp, "domain-name", "example.org")
        self.assertEqual(cfg.global_options()[0]["name"], "domain-name")

    def test_catalog_and_validation(self):
        self.assertTrue(any(o.name == "routers" for o in OPT.catalog(4)))
        # корректные значения
        self.assertTrue(
            OPT.validate_option_data(OPT.KIND_IPV4_LIST, "192.0.2.1, 192.0.2.2", 4)[0])
        self.assertTrue(
            OPT.validate_option_data(OPT.KIND_STRING, "example.org", 4)[0])
        self.assertTrue(
            OPT.validate_option_data(
                OPT.KIND_CSR, "192.0.5.0/24 - 192.0.2.2", 4)[0])
        # ошибки
        self.assertFalse(
            OPT.validate_option_data(OPT.KIND_IPV4_LIST, "not-an-ip", 4)[0])
        self.assertFalse(
            OPT.validate_option_data(OPT.KIND_CSR, "192.0.5.0/24", 4)[0])

    def test_option_round_trip(self):
        cfg = DhcpConfig.new(4)
        DhcpConfig.set_option(cfg.dhcp, "domain-name-servers", "192.0.2.1")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "o.conf")
            cfg.save(out)
            re = DhcpConfig.load(out, 4)
            self.assertEqual(
                re.global_options()[0]["name"], "domain-name-servers")


V4_HEADER = ("address,hwaddr,client_id,valid_lifetime,expire,subnet_id,"
             "fqdn_fwd,fqdn_rev,hostname,state,user_context,pool_id")


class TestLeases(unittest.TestCase):
    def _write(self, d, name, lines):
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(V4_HEADER + "\n")
            for ln in lines:
                fh.write(ln + "\n")
        return path

    def test_basic_parse(self):
        future = int(time.time()) + 3600
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "kea-leases4.csv", [
                f"192.0.2.10,aa:bb:cc:dd:ee:01,,4000,{future},1,0,0,host1,0,,0",
                f"192.0.2.11,aa:bb:cc:dd:ee:02,,4000,{future},1,0,0,host2,0,,0",
            ])
            recs = LEASES.read_leases(path, 4)
            self.assertEqual(len(recs), 2)
            self.assertEqual(recs[0].address, "192.0.2.10")
            self.assertEqual(recs[0].hostname, "host1")
            self.assertTrue(recs[0].is_active())

    def test_dedup_last_wins(self):
        future = int(time.time()) + 3600
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "kea-leases4.csv", [
                f"192.0.2.10,aa:bb:cc:dd:ee:01,,4000,{future},1,0,0,old,0,,0",
                f"192.0.2.10,aa:bb:cc:dd:ee:01,,4000,{future},1,0,0,new,0,,0",
            ])
            recs = LEASES.read_leases(path, 4)
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0].hostname, "new")

    def test_deleted_lease_excluded(self):
        future = int(time.time()) + 3600
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "kea-leases4.csv", [
                f"192.0.2.10,aa:bb:cc:dd:ee:01,,4000,{future},1,0,0,h,0,,0",
                # valid_lifetime == 0 => удалена
                f"192.0.2.10,aa:bb:cc:dd:ee:01,,0,{future},1,0,0,h,0,,0",
            ])
            recs = LEASES.read_leases(path, 4)
            self.assertEqual(len(recs), 0)

    def test_inactive_filter(self):
        future = int(time.time()) + 3600
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "kea-leases4.csv", [
                # state 2 = expired-reclaimed
                f"192.0.2.20,aa:bb:cc:dd:ee:03,,4000,{future},1,0,0,h,2,,0",
            ])
            self.assertEqual(len(LEASES.read_leases(path, 4)), 0)
            self.assertEqual(
                len(LEASES.read_leases(path, 4, include_inactive=True)), 1)

    def test_lfc_merge(self):
        future = int(time.time()) + 3600
        with tempfile.TemporaryDirectory() as d:
            # .2 — завершённый LFC (старое имя), основной — свежее
            self._write(d, "kea-leases4.csv.2", [
                f"192.0.2.10,aa:bb:cc:dd:ee:01,,4000,{future},1,0,0,lfc,0,,0",
            ])
            path = self._write(d, "kea-leases4.csv", [
                f"192.0.2.10,aa:bb:cc:dd:ee:01,,4000,{future},1,0,0,fresh,0,,0",
            ])
            recs = LEASES.read_leases(path, 4)
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0].hostname, "fresh")

    def test_guess_lease_path(self):
        body = {"lease-database": {"type": "memfile",
                                   "name": "/custom/leases.csv"}}
        self.assertEqual(LEASES.guess_lease_path(body, 4), "/custom/leases.csv")
        # без lease-database — путь по умолчанию
        self.assertEqual(
            LEASES.guess_lease_path({}, 4), "/var/lib/kea/kea-leases4.csv")
        # не memfile — None
        self.assertIsNone(
            LEASES.guess_lease_path({"lease-database": {"type": "mysql"}}, 4))


class TestControlSocket(unittest.TestCase):
    """Тест клиента через фейковый AF_UNIX сервер в отдельном потоке."""

    def _serve(self, sock_path, response):
        import socket as _s

        ready = threading.Event()

        def handler():
            srv = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
            srv.bind(sock_path)
            srv.listen(1)
            srv.settimeout(5)
            ready.set()  # сокет готов принимать соединения
            try:
                conn, _ = srv.accept()
                conn.recv(65536)  # прочитать команду
                conn.sendall(response.encode("utf-8"))
                conn.close()
            except OSError:
                pass
            finally:
                srv.close()

        t = threading.Thread(target=handler, daemon=True)
        t.start()
        ready.wait(timeout=5)  # дождаться готовности сервера
        return t

    def test_guess_socket_path(self):
        body = {"control-socket": {"socket-type": "unix",
                                   "socket-name": "/run/kea/s4"}}
        self.assertEqual(ctrlsocket.guess_socket_path(body), "/run/kea/s4")
        body2 = {"control-sockets": [
            {"socket-type": "unix", "socket-name": "/run/kea/s4b"}]}
        self.assertEqual(ctrlsocket.guess_socket_path(body2), "/run/kea/s4b")
        self.assertIsNone(ctrlsocket.guess_socket_path({}))

    def test_lease_del_success(self):
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "sock")
            t = self._serve(sp, '{"result":0,"text":"IPv4 lease deleted."}')
            client = ctrlsocket.KeaControlSocket(sp, timeout=5)
            text = client.lease_del(4, "192.0.2.10")
            t.join(timeout=5)
            self.assertIn("deleted", text)

    def test_lease_del_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "sock")
            t = self._serve(sp, '{"result":3,"text":"Lease not found."}')
            client = ctrlsocket.KeaControlSocket(sp, timeout=5)
            with self.assertRaises(ctrlsocket.CommandError) as ctx:
                client.lease_del(4, "192.0.2.99")
            t.join(timeout=5)
            self.assertEqual(ctx.exception.result, ctrlsocket.RESULT_EMPTY)

    def test_list_response_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "sock")
            t = self._serve(sp, '[{"result":0,"arguments":["lease4-del"]}]')
            client = ctrlsocket.KeaControlSocket(sp, timeout=5)
            self.assertTrue(client.has_lease_cmds(4))
            t.join(timeout=5)

    def test_connection_error(self):
        client = ctrlsocket.KeaControlSocket("/nonexistent/sock", timeout=2)
        with self.assertRaises(ctrlsocket.ControlSocketError):
            client.lease_del(4, "192.0.2.10")


class TestHA(unittest.TestCase):
    def test_enable_disable(self):
        cfg = DhcpConfig.new(4)
        self.assertFalse(HA.is_ha_enabled(cfg.dhcp))
        ha0 = HA.enable_ha(cfg.dhcp)
        self.assertTrue(HA.is_ha_enabled(cfg.dhcp))
        self.assertIn("mode", ha0)
        # запись libdhcp_ha.so появилась в hooks-libraries
        self.assertIsNotNone(HA.find_ha_entry(cfg.dhcp))
        HA.disable_ha(cfg.dhcp)
        self.assertFalse(HA.is_ha_enabled(cfg.dhcp))

    def test_disable_preserves_other_hooks(self):
        cfg = DhcpConfig.new(4)
        HA.hooks_libraries(cfg.dhcp).append(
            {"library": "/usr/lib64/kea/hooks/libdhcp_lease_cmds.so"})
        HA.enable_ha(cfg.dhcp)
        HA.disable_ha(cfg.dhcp)
        libs = cfg.dhcp["hooks-libraries"]
        self.assertEqual(len(libs), 1)
        self.assertTrue(libs[0]["library"].endswith("libdhcp_lease_cmds.so"))

    def test_peers_and_validation(self):
        cfg = DhcpConfig.new(4)
        ha0 = HA.enable_ha(cfg.dhcp)
        ha0["mode"] = HA.MODE_LOAD_BALANCING
        ha0["this-server-name"] = "server1"
        HA.add_peer(ha0, "server1", "http://10.0.0.1:8000/", "primary", True)
        HA.add_peer(ha0, "server2", "http://10.0.0.2:8000/", "secondary", True)
        ok, msg = HA.validate_ha(ha0)
        self.assertTrue(ok, msg)
        # недопустимая роль для load-balancing
        ok, _ = HA.validate_role("standby", HA.MODE_LOAD_BALANCING)
        self.assertFalse(ok)
        # this-server-name должен совпадать с одним из peers
        ha0["this-server-name"] = "ghost"
        self.assertFalse(HA.validate_ha(ha0)[0])

    def test_url_validation(self):
        self.assertTrue(HA.validate_url("http://127.0.0.1:8000/")[0])
        self.assertFalse(HA.validate_url("127.0.0.1:8000")[0])

    def test_ha_round_trip(self):
        cfg = DhcpConfig.new(4)
        ha0 = HA.enable_ha(cfg.dhcp)
        ha0["mode"] = HA.MODE_HOT_STANDBY
        ha0["this-server-name"] = "s1"
        HA.add_peer(ha0, "s1", "http://10.0.0.1:8000/", "primary")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "ha.conf")
            cfg.save(out)
            re = DhcpConfig.load(out, 4)
            r_ha = HA.get_ha_config(re.dhcp)
            self.assertEqual(r_ha["mode"], "hot-standby")
            self.assertEqual(HA.peers_of(r_ha)[0]["name"], "s1")


class TestClientClasses(unittest.TestCase):
    def test_add_update_remove(self):
        cfg = DhcpConfig.new(4)
        CLS.add_class(cfg.dhcp, "VOIP", "option[60].text == 'CiscoIPPhone'")
        self.assertEqual(CLS.class_names(cfg.dhcp), ["VOIP"])
        # дубликат имени запрещён
        with self.assertRaises(ValueError):
            CLS.add_class(cfg.dhcp, "VOIP")
        CLS.update_class(cfg.dhcp, 0, "VOIP2", None)
        c = CLS.classes_of(cfg.dhcp)[0]
        self.assertEqual(c["name"], "VOIP2")
        self.assertNotIn("test", c)  # test очищен
        CLS.remove_class(cfg.dhcp, 0)
        self.assertEqual(len(CLS.classes_of(cfg.dhcp)), 0)

    def test_name_validation(self):
        self.assertTrue(CLS.validate_class_name("phones")[0])
        self.assertFalse(CLS.validate_class_name("")[0])
        self.assertFalse(CLS.validate_class_name("VENDOR_CLASS_x")[0])

    def test_class_with_options_round_trip(self):
        cfg = DhcpConfig.new(4)
        c = CLS.add_class(cfg.dhcp, "VOIP", "option[60].text == 'X'")
        DhcpConfig.set_option(c, "tftp-server-name", "10.10.10.50")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "c.conf")
            cfg.save(out)
            re = DhcpConfig.load(out, 4)
            rc = CLS.find_class(re.dhcp, "VOIP")
            self.assertIsNotNone(rc)
            self.assertEqual(rc["option-data"][0]["name"], "tftp-server-name")

    def test_pool_client_class_link(self):
        cfg = DhcpConfig.new(4)
        sub = cfg.add_subnet("10.10.10.0/24")
        DhcpConfig.add_pool(sub, "10.10.10.100 - 10.10.10.200",
                            client_class="VOIP")
        self.assertEqual(
            DhcpConfig.pools_of(sub)[0]["client-class"], "VOIP")


class _FakeKeaHTTP:
    """Фейковый HTTP-сервер Kea для тестов API-клиента."""

    def __init__(self, handler_fn):
        import http.server

        self.received = []
        parent = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                auth = self.headers.get("Authorization")
                parent.received.append({"body": json.loads(body), "auth": auth})
                status, payload = handler_fn(json.loads(body), auth)
                data = payload.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._H = H

    def __enter__(self):
        import http.server
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), self._H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestHttpClient(unittest.TestCase):
    def test_send_command_ok(self):
        def handler(req, auth):
            return 200, json.dumps({"result": 0, "text": "ok",
                                    "arguments": ["list-commands"]})
        with _FakeKeaHTTP(handler) as srv:
            c = ctrlsocket.KeaHttpClient("127.0.0.1", srv.port)
            resp = c.send_command("list-commands")
            self.assertEqual(resp["result"], 0)
            self.assertEqual(srv.received[0]["body"]["command"], "list-commands")

    def test_basic_auth_header(self):
        def handler(req, auth):
            return 200, json.dumps({"result": 0})
        with _FakeKeaHTTP(handler) as srv:
            c = ctrlsocket.KeaHttpClient("127.0.0.1", srv.port,
                                         username="admin", password="secret")
            c.send_command("status-get")
            self.assertTrue(srv.received[0]["auth"].startswith("Basic "))

    def test_http_401(self):
        def handler(req, auth):
            return 401, "unauthorized"
        with _FakeKeaHTTP(handler) as srv:
            c = ctrlsocket.KeaHttpClient("127.0.0.1", srv.port)
            with self.assertRaises(ctrlsocket.ControlSocketError):
                c.send_command("status-get")

    def test_command_error(self):
        def handler(req, auth):
            return 200, json.dumps({"result": 1, "text": "bad"})
        with _FakeKeaHTTP(handler) as srv:
            c = ctrlsocket.KeaHttpClient("127.0.0.1", srv.port)
            with self.assertRaises(ctrlsocket.CommandError):
                c.send_command("config-set", {"Dhcp4": {}})


class TestMutualTLS(unittest.TestCase):
    """mutual TLS: сервер с CERT_REQUIRED принимает только клиента с сертификатом."""

    @classmethod
    def _gen_certs(cls, d):
        import subprocess
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(here, "tools", "gen-tls-certs.sh")
        subprocess.run(["sh", script, d, "127.0.0.1"],
                       check=True, capture_output=True)

    def _serve(self, d):
        import ssl as _ssl
        import http.server

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                data = json.dumps({"result": 0, "text": "3.2.0"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(d + "/server-cert.pem", d + "/server-key.pem")
        ctx.load_verify_locations(d + "/ca-cert.pem")
        ctx.verify_mode = _ssl.CERT_REQUIRED
        httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return httpd

    def test_client_cert_required(self):
        import shutil
        if shutil.which("openssl") is None:
            self.skipTest("openssl недоступен")
        with tempfile.TemporaryDirectory() as d:
            self._gen_certs(d)
            httpd = self._serve(d)
            try:
                port = httpd.server_address[1]
                # без клиентского сертификата — отказ
                c = ctrlsocket.KeaHttpClient(
                    "127.0.0.1", port, use_tls=True, verify=True,
                    ca_cert=d + "/ca-cert.pem", timeout=5)
                with self.assertRaises(ctrlsocket.ControlSocketError):
                    c.send_command("version-get")
                # с клиентским сертификатом — успех
                c2 = ctrlsocket.KeaHttpClient(
                    "127.0.0.1", port, use_tls=True, verify=True,
                    ca_cert=d + "/ca-cert.pem",
                    client_cert=d + "/client-cert.pem",
                    client_key=d + "/client-key.pem", timeout=5)
                resp = c2.send_command("version-get")
                self.assertEqual(resp["result"], 0)
            finally:
                httpd.shutdown()

    def test_endpoint_passes_cert_params(self):
        from kea_manager.model.backend import Endpoint
        ep = Endpoint(host="h", port=1, use_tls=True,
                      client_cert="/c.pem", client_key="/k.pem",
                      ca_cert="/ca.pem")
        cl = ep.client()
        self.assertEqual(cl.client_cert, "/c.pem")
        self.assertEqual(cl.client_key, "/k.pem")
        self.assertEqual(cl.ca_cert, "/ca.pem")


class TestApiBackend(unittest.TestCase):
    def test_config_get_load(self):
        cfg_body = {"Dhcp4": {"valid-lifetime": 4000,
                              "subnet4": [{"id": 1, "subnet": "192.0.2.0/24"}]}}

        def handler(req, auth):
            if req["command"] == "config-get":
                return 200, json.dumps({"result": 0, "arguments": cfg_body})
            return 200, json.dumps({"result": 0})

        with _FakeKeaHTTP(handler) as srv:
            be = ApiBackend(Endpoint(host="127.0.0.1", port=srv.port))
            proj = be.load()
            self.assertEqual(proj.dhcp4.get_global("valid-lifetime"), 4000)
            self.assertEqual(len(proj.dhcp4.subnets()), 1)
            self.assertFalse(proj.dhcp6_configured)

    def test_config_get_strips_hash(self):
        # config-get в Kea возвращает служебный ключ hash, который
        # config-set не принимает — он должен отбрасываться при загрузке
        cfg_body = {"Dhcp4": {"valid-lifetime": 4000},
                    "hash": "ABCDEF0123456789"}

        def handler(req, auth):
            if req["command"] == "config-get":
                return 200, json.dumps({"result": 0, "arguments": cfg_body})
            return 200, json.dumps({"result": 0})

        with _FakeKeaHTTP(handler) as srv:
            be = ApiBackend(Endpoint(host="127.0.0.1", port=srv.port))
            proj = be.load()
            self.assertNotIn("hash", proj.dhcp4.root)
            self.assertIn("Dhcp4", proj.dhcp4.root)

    def test_apply_does_not_send_hash(self):
        cfg_body = {"Dhcp4": {"valid-lifetime": 4000}, "hash": "XYZ"}
        sent = []

        def handler(req, auth):
            if req["command"] == "config-get":
                return 200, json.dumps({"result": 0, "arguments": cfg_body})
            if req["command"] in ("config-test", "config-set"):
                sent.append(req.get("arguments", {}))
            return 200, json.dumps({"result": 0, "text": "ok"})

        with _FakeKeaHTTP(handler) as srv:
            be = ApiBackend(Endpoint(host="127.0.0.1", port=srv.port))
            proj = be.load()
            be.save(proj, write=False)
            for args in sent:
                self.assertNotIn("hash", args)

    def test_apply_sends_test_set_write(self):
        commands = []

        def handler(req, auth):
            commands.append(req["command"])
            return 200, json.dumps({"result": 0, "text": "ok"})

        with _FakeKeaHTTP(handler) as srv:
            be = ApiBackend(Endpoint(host="127.0.0.1", port=srv.port))
            from kea_manager.model import DhcpConfig, KeaProject
            proj = KeaProject(dhcp4=DhcpConfig.new(4))
            proj.dhcp4.add_subnet("10.0.0.0/24")
            results = be.save(proj, write=True)
            self.assertEqual(commands, ["config-test", "config-set",
                                        "config-write"])
            self.assertEqual(len(results), 1)

    def test_read_leases_api(self):
        page = {"result": 0, "arguments": {"leases": [
            {"ip-address": "192.0.2.5", "hw-address": "aa:bb:cc:dd:ee:ff",
             "hostname": "h", "cltt": 1000, "valid-lft": 4000,
             "subnet-id": 1, "state": 0}]}}
        empty = {"result": 0, "arguments": {"leases": []}}
        calls = {"n": 0}

        def handler(req, auth):
            if req["command"] == "lease4-get-page":
                calls["n"] += 1
                return 200, json.dumps(page if calls["n"] == 1 else empty)
            return 200, json.dumps({"result": 0})

        with _FakeKeaHTTP(handler) as srv:
            c = ctrlsocket.KeaHttpClient("127.0.0.1", srv.port)
            recs = LEASES.read_leases_api(c, 4)
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0].address, "192.0.2.5")
            self.assertEqual(recs[0].expire, 5000)  # cltt + valid-lft


class TestStatistics(unittest.TestCase):
    def test_parse_response(self):
        resp = {"result": 0, "arguments": {
            "pkt4-received": [[1234, "2026-08-05 12:00:00"]],
            "assigned-addresses": [[50, "..."]],
        }}
        m = STATS.parse_stat_response(resp)
        self.assertEqual(m["pkt4-received"], 1234)
        self.assertEqual(m["assigned-addresses"], 50)

    def test_parse_empty(self):
        self.assertEqual(STATS.parse_stat_response({}), {})
        self.assertEqual(STATS.parse_stat_response({"arguments": []}), {})

    def test_group_metrics(self):
        m = {"pkt4-received": 1, "pkt4-ack-sent": 2,
             "assigned-addresses": 3,
             "subnet[1].assigned-addresses": 4}
        g = STATS.group_metrics(m)
        self.assertEqual(len(g["packets"]), 2)
        self.assertTrue(any("assigned" in n for n, _ in g["addresses"]))
        self.assertTrue(any("subnet[1]" in n for n, _ in g["subnets"]))

    def test_extract_subnet_id(self):
        self.assertEqual(
            STATS.extract_subnet_id("subnet[42].assigned-addresses"), 42)
        self.assertIsNone(STATS.extract_subnet_id("pkt4-received"))

    def test_compute_rate(self):
        s1 = STATS.Snapshot(1000.0, {"x": 100})
        s2 = STATS.Snapshot(1010.0, {"x": 200})
        self.assertEqual(STATS.compute_rate(s1, s2, "x"), 10.0)
        # без предыдущего снимка — None
        self.assertIsNone(STATS.compute_rate(None, s2, "x"))
        # нулевой интервал — None
        s3 = STATS.Snapshot(1000.0, {"x": 300})
        self.assertIsNone(STATS.compute_rate(s1, s3, "x"))

    def test_top_subnet(self):
        m = {
            "subnet[1].assigned-addresses": 50,
            "subnet[1].total-addresses": 254,
            "subnet[2].assigned-addresses": 200,
            "subnet[2].total-addresses": 254,
        }
        top = STATS.top_subnet_by_usage(m)
        self.assertIsNotNone(top)
        self.assertEqual(top[0], 2)  # subnet[2] загружен сильнее
        self.assertGreater(top[1], 70)

    def test_top_subnet_none(self):
        self.assertIsNone(STATS.top_subnet_by_usage({"pkt4-received": 5}))


class TestHooks(unittest.TestCase):
    def test_enable_disable(self):
        from kea_manager.model import hooks as H
        cfg = DhcpConfig.new(4)
        self.assertFalse(H.is_loaded(cfg.dhcp, "libdhcp_lease_cmds.so"))
        H.enable(cfg.dhcp, "libdhcp_lease_cmds.so", "/usr/lib64/kea/hooks")
        self.assertTrue(H.is_loaded(cfg.dhcp, "libdhcp_lease_cmds.so"))
        entry = H.find_entry(cfg.dhcp, "libdhcp_lease_cmds.so")
        self.assertTrue(entry["library"].endswith("libdhcp_lease_cmds.so"))
        H.disable(cfg.dhcp, "libdhcp_lease_cmds.so")
        self.assertFalse(H.is_loaded(cfg.dhcp, "libdhcp_lease_cmds.so"))

    def test_disable_preserves_others(self):
        from kea_manager.model import hooks as H
        cfg = DhcpConfig.new(4)
        H.enable(cfg.dhcp, "libdhcp_lease_cmds.so")
        H.enable(cfg.dhcp, "libdhcp_run_script.so")
        H.disable(cfg.dhcp, "libdhcp_lease_cmds.so")
        self.assertTrue(H.is_loaded(cfg.dhcp, "libdhcp_run_script.so"))
        self.assertEqual(len(cfg.dhcp["hooks-libraries"]), 1)

    def test_params_roundtrip(self):
        from kea_manager.model import hooks as H
        cfg = DhcpConfig.new(4)
        H.enable(cfg.dhcp, "libdhcp_run_script.so")
        H.set_parameters(cfg.dhcp, "libdhcp_run_script.so",
                         {"name": "/x.sh", "sync": False})
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "h.conf")
            cfg.save(out)
            re = DhcpConfig.load(out, 4)
            p = H.get_parameters(re.dhcp, "libdhcp_run_script.so")
            self.assertEqual(p["name"], "/x.sh")

    def test_match_by_filename_any_dir(self):
        from kea_manager.model import hooks as H
        cfg = DhcpConfig.new(4)
        # хук прописан с нестандартным каталогом — находим по имени файла
        cfg.dhcp["hooks-libraries"] = [
            {"library": "/opt/custom/path/libdhcp_ha.so"}]
        self.assertTrue(H.is_loaded(cfg.dhcp, "libdhcp_ha.so"))

    def test_d2_hook_marked_not_applicable(self):
        from kea_manager.model import hooks as H
        hd = H.known_by_name("libddns_gss_tsig.so")
        self.assertIsNotNone(hd)
        self.assertFalse(hd.dhcp_applicable)


class TestSettings(unittest.TestCase):
    """Настройки в ini — через подмену XDG_CONFIG_HOME на temp."""

    def setUp(self):
        self._old = os.environ.get("XDG_CONFIG_HOME")
        self._tmp = tempfile.mkdtemp()
        os.environ["XDG_CONFIG_HOME"] = self._tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old

    def test_empty_when_no_file(self):
        self.assertEqual(SETTINGS.load(), {})

    def test_save_and_load_connection_no_password(self):
        SETTINGS.save_connection(
            tls=True, verify=False, username="admin",
            host4="192.168.150.10", port4=8123,
            v6_enabled=True, host6="::1", port6=8124)
        data = SETTINGS.load()
        conn = data["connection"]
        self.assertEqual(conn["username"], "admin")
        self.assertEqual(conn["host4"], "192.168.150.10")
        self.assertEqual(conn["port4"], "8123")
        self.assertTrue(conn["tls"])
        self.assertFalse(conn["verify"])
        self.assertTrue(conn["v6_enabled"])
        # пароль не должен присутствовать нигде в файле
        with open(SETTINGS.config_path(), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("password", text.lower())

    def test_save_last_directory(self):
        SETTINGS.save_last_directory("/etc/kea")
        self.assertEqual(SETTINGS.load()["last"]["directory"], "/etc/kea")

    def test_window_geometry(self):
        self.assertIsNone(SETTINGS.get_window_geometry())
        SETTINGS.set_window_geometry("1024x700+120+60")
        self.assertEqual(SETTINGS.get_window_geometry(), "1024x700+120+60")

    def test_hooks_dir_and_custom(self):
        self.assertEqual(SETTINGS.get_hooks_dir(), "/usr/lib64/kea/hooks")
        SETTINGS.set_hooks_dir("/opt/kea/hooks")
        self.assertEqual(SETTINGS.get_hooks_dir(), "/opt/kea/hooks")
        self.assertEqual(SETTINGS.get_custom_hooks(), [])
        SETTINGS.set_custom_hooks(["libdhcp_x.so", "libdhcp_y.so",
                                   "libdhcp_x.so"])
        self.assertEqual(SETTINGS.get_custom_hooks(),
                         ["libdhcp_x.so", "libdhcp_y.so"])

    def test_ini_location(self):
        self.assertTrue(SETTINGS.config_path().endswith(
            os.path.join("kea-manager", "kea-manager.ini")))

    def test_server_list_crud(self):
        self.assertEqual(SETTINGS.list_servers(), [])
        SETTINGS.save_server(SETTINGS.ServerEntry(
            name="prod", kind="api", host4="192.168.150.10", port4="8123",
            username="admin"))
        SETTINGS.save_server(SETTINGS.ServerEntry(
            name="lab", kind="file", directory="/etc/kea"))
        names = [s.name for s in SETTINGS.list_servers()]
        self.assertIn("prod", names)
        self.assertIn("lab", names)
        prod = SETTINGS.get_server("prod")
        self.assertEqual(prod.kind, "api")
        self.assertEqual(prod.host4, "192.168.150.10")
        self.assertEqual(prod.describe(), "http://192.168.150.10:8123")
        lab = SETTINGS.get_server("lab")
        self.assertEqual(lab.describe(), "файлы: /etc/kea")
        # обновление по имени не плодит дубликат
        SETTINGS.save_server(SETTINGS.ServerEntry(
            name="prod", kind="api", host4="10.0.0.1", port4="8000"))
        self.assertEqual(len([s for s in SETTINGS.list_servers()
                              if s.name == "prod"]), 1)
        self.assertEqual(SETTINGS.get_server("prod").host4, "10.0.0.1")
        # удаление
        SETTINGS.remove_server("prod")
        self.assertIsNone(SETTINGS.get_server("prod"))
        self.assertEqual(len(SETTINGS.list_servers()), 1)

    def test_server_no_password_stored(self):
        SETTINGS.save_server(SETTINGS.ServerEntry(
            name="prod", kind="api", host4="10.0.0.1", username="admin"))
        with open(SETTINGS.config_path(), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("password", text.lower())


class TestI18n(unittest.TestCase):
    def tearDown(self):
        # вернуть русский по умолчанию, чтобы не влиять на другие тесты
        from kea_manager import i18n
        i18n.install("ru")

    def test_locale_dirs_include_system(self):
        from kea_manager import i18n
        dirs = i18n.locale_dirs()
        self.assertIn("/usr/share/kea-manager/locale", dirs)
        self.assertIn("/usr/share/locale", dirs)
        # каталог внутри пакета — первым
        self.assertTrue(dirs[0].endswith(os.path.join("kea_manager", "locale")))

    def test_english_translation(self):
        from kea_manager import i18n
        i18n.install("en")
        import builtins
        self.assertEqual(builtins._("Сохранить"), "Save")
        self.assertEqual(builtins._("Отмена"), "Cancel")

    def test_russian_is_identity(self):
        from kea_manager import i18n
        i18n.install("ru")
        import builtins
        self.assertEqual(builtins._("Сохранить"), "Сохранить")

    def test_unknown_lang_falls_back(self):
        from kea_manager import i18n
        self.assertEqual(i18n.install("de"), "ru")

    def test_settings_language(self):
        # использует изолированный XDG из TestSettings-подобной установки
        old = os.environ.get("XDG_CONFIG_HOME")
        tmp = tempfile.mkdtemp()
        os.environ["XDG_CONFIG_HOME"] = tmp
        try:
            self.assertEqual(SETTINGS.get_language(), "ru")
            SETTINGS.set_language("en")
            self.assertEqual(SETTINGS.get_language(), "en")
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old


class TestPoCompile(unittest.TestCase):
    def test_compile_roundtrip(self):
        import importlib.util
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "pocompile", os.path.join(here, "tools", "pocompile.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        po = ('msgid ""\nmsgstr ""\n"Content-Type: text/plain; '
              'charset=UTF-8\\n"\n\nmsgid "Привет"\nmsgstr "Hello"\n')
        entries = mod.parse_po(po)
        self.assertEqual(entries["Привет"], "Hello")
        with tempfile.TemporaryDirectory() as d:
            po_path = os.path.join(d, "t.po")
            open(po_path, "w", encoding="utf-8").write(po)
            mod.compile_file(po_path)
            mo_path = os.path.join(d, "t.mo")
            self.assertTrue(os.path.isfile(mo_path))
            import gettext
            with open(mo_path, "rb") as fh:
                tr = gettext.GNUTranslations(fh)
            self.assertEqual(tr.gettext("Привет"), "Hello")


class TestFileBackend(unittest.TestCase):
    def test_roundtrip(self):
        from kea_manager.model import DhcpConfig, KeaProject
        with tempfile.TemporaryDirectory() as d:
            proj = KeaProject(dhcp4=DhcpConfig.new(4))
            proj.dhcp4.add_subnet("192.0.2.0/24")
            be = FileBackend(d)
            be.save(proj)
            proj2 = be.load()
            self.assertEqual(len(proj2.dhcp4.subnets()), 1)


if __name__ == "__main__":
    unittest.main()
