"""Isolated business-flow tests. No real DB, payment, Telegram or MT5 calls."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from PIL import Image
from server import azt_store as business, store
from server.app import app


def image_proof():
    image = Image.new("RGB", (2, 2), "white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


async def asgi_request(path, *, method="GET", token="", payload=None, query=None):
    captured = []
    data = json.dumps(payload).encode() if payload is not None else b""
    headers = [(b"content-type", b"application/json")]
    if token:
        headers.append((b"authorization", ("Bearer " + token).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "",
             "query_string": urlencode(query or {}).encode(), "headers": headers,
             "server": ("127.0.0.1", 1234), "client": ("127.0.0.1", 1235)}
    async def receive():
        return {"type": "http.request", "body": data, "more_body": False}
    async def send(message):
        captured.append(message)
    await app(scope, receive, send)
    status = next(m["status"] for m in captured if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in captured if m["type"] == "http.response.body")
    try:
        result = json.loads(body)
    except ValueError:
        result = body.decode("utf-8")
    return status, result


class AZTBusinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "test.db"
        self.db_patch = patch.object(store, "DB_PATH", self.database)
        self.db_patch.start()
        self.env_patch = patch.dict(os.environ, {"GOLD_AI_STATE_DIR": str(self.root), "GOLD_AI_OWNER_TELEGRAM_ENABLED": "false"})
        self.env_patch.start()
        self.telegram_patch = patch.object(business, "_telegram", return_value=False)
        self.telegram_patch.start()
        # Existing business tests are offline; the calendar has focused tests.
        self.news_patch = patch("server.usd_news.block_status", return_value=(False, ""))
        self.news_patch.start()
        self.client, self.code = store.create_client("Test Customer")

    def tearDown(self):
        self.news_patch.stop()
        self.telegram_patch.stop()
        self.env_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def req(self, path, **kwargs):
        return asyncio.run(asgi_request(path, **kwargs))

    def test_invalid_stored_risk_policy_returns_unavailable_instead_of_a_wider_limit(self):
        token = self.token()
        for key, invalid, valid in (
            ("global_risk_per_trade_pct", "NaN", "2.0"),
            ("global_max_daily_loss_enabled", "unknown", "1"),
        ):
            with self.subTest(key=key):
                with store.connect() as con:
                    con.execute("UPDATE server_settings SET value=? WHERE key=?", (invalid, key))
                status, response = self.req("/v1/client/risk-policy", token=token)
                self.assertEqual(status, 503)
                self.assertIn("blocked", response["detail"])
                with store.connect() as con:
                    con.execute("UPDATE server_settings SET value=? WHERE key=?", (valid, key))
        with store.connect() as con:
            con.execute("UPDATE clients SET risk_per_trade_pct=? WHERE id=?", (float("inf"), self.client.id))
        self.assertEqual(self.req("/v1/client/risk-policy", token=token)[0], 503)

    def priced(self, amount="25", accounts=1):
        return business.save_plan("STARTER", amount=amount, duration_days=30, max_mt5_accounts=accounts)

    def payment(self, client_id=None, transaction_hash=None):
        return business.submit_payment(client_id or self.client.id, "STARTER", "USDT_TRC20", transaction_hash=transaction_hash or "a" * 64)

    def token(self, login=123, server="Broker"):
        account = business.authorize_account(self.client.id, login, server)
        return store.create_session(self.client.id, account["id"])

    def test_migration_is_idempotent_preserves_legacy_records(self):
        store.enqueue_instruction(self.client.id, "signal", "{}")
        for _ in range(3):
            with store.connect() as con:
                self.assertEqual(con.execute("SELECT count(*) FROM clients").fetchone()[0], 1)
                self.assertEqual(con.execute("SELECT count(*) FROM instructions").fetchone()[0], 1)
        self.assertIsNone(business.plans()[0]["amount"])

    def test_first_legacy_upgrade_backups_before_changes_and_not_again(self):
        legacy = self.root / "legacy.db"
        with sqlite3.connect(legacy) as con:
            con.execute("CREATE TABLE clients(id INTEGER PRIMARY KEY,name TEXT UNIQUE,status TEXT,pairing_code TEXT,mt5_login INTEGER,mt5_server TEXT,telegram_username TEXT,created_utc TEXT)")
            con.execute("INSERT INTO clients VALUES(1,'Preserved','ACTIVE','secret-pairing',NULL,'','','2026-01-01T00:00:00+00:00')")
        con.close()
        with patch.object(store, "DB_PATH", legacy):
            with store.connect() as upgraded:
                self.assertEqual(upgraded.execute("SELECT name FROM clients").fetchone()[0], "Preserved")
            backups = list(self.root.glob("legacy.pre_azt_*.backup.db"))
            self.assertEqual(len(backups), 1)
            with sqlite3.connect(backups[0]) as snapshot:
                self.assertEqual(snapshot.execute("SELECT name FROM clients").fetchone()[0], "Preserved")
                self.assertIsNone(snapshot.execute("SELECT name FROM sqlite_master WHERE name='azt_plans'").fetchone())
                self.assertNotIn("archived_utc", {row[1] for row in snapshot.execute("PRAGMA table_info(clients)")})
            snapshot.close()
            with store.connect():
                pass
            self.assertEqual(list(self.root.glob("legacy.pre_azt_*.backup.db")), backups)

    def test_new_trials_are_timed_and_legacy_blank_trials_receive_expiry_once(self):
        sub = store.subscription_for_client(self.client.id)
        self.assertEqual(sub["status"], "TRIAL")
        self.assertGreater(business.parse_utc(sub["expires_utc"]), business.utc_now())
        with store.connect() as con:
            con.execute("UPDATE subscriptions SET expires_utc='' WHERE client_id=?", (self.client.id,))
        first = store.subscription_for_client(self.client.id)
        self.assertEqual(first["expires_utc"], store.subscription_for_client(self.client.id)["expires_utc"])

    def test_expiry_blocks_access_without_manual_expire_and_reminder_is_idempotent(self):
        now = business.utc_now()
        store.set_subscription(self.client.id, plan_code="STARTER", status="ACTIVE", starts_utc=business.utc_iso(now-timedelta(days=30)), expires_utc=business.utc_iso(now-timedelta(seconds=1)))
        self.assertFalse(store.subscription_access(self.client.id)["allowed"])
        self.assertEqual(business.maintenance_tick()["reminders"], 1)
        self.assertEqual(business.maintenance_tick()["reminders"], 0)
        self.assertEqual(store.subscription_for_client(self.client.id)["status"], "EXPIRED")
        self.assertEqual(len(business.messages(self.client.id)), 1)

    def test_expiring_status_and_custom_reminder_days(self):
        now = business.utc_now()
        store.set_subscription(self.client.id, plan_code="STARTER", status="ACTIVE", starts_utc=business.utc_iso(now), expires_utc=business.utc_iso(now+timedelta(hours=20)))
        self.assertEqual(business.subscription_summary(self.client.id)["effective_status"], "EXPIRING SOON")
        with patch("server.workspace_settings.load_settings", return_value={"reminder_days": [1, 0]}):
            self.assertEqual(business.maintenance_tick()["reminders"], 1)
            self.assertEqual(business.maintenance_tick()["reminders"], 0)

    def test_active_renewal_extends_existing_expiry_expired_renewal_starts_now(self):
        now = business.utc_now()
        future = now + timedelta(days=10)
        store.set_subscription(self.client.id, plan_code="STARTER", status="ACTIVE", starts_utc=business.utc_iso(now), expires_utc=business.utc_iso(future))
        first = business.renew_subscription(self.client.id, 30)
        self.assertAlmostEqual((business.parse_utc(first["expires_utc"])-future).total_seconds(), 30*86400, delta=1)
        store.set_subscription(self.client.id, plan_code="STARTER", status="EXPIRED", starts_utc=business.utc_iso(now-timedelta(days=40)), expires_utc=business.utc_iso(now-timedelta(days=10)))
        second = business.renew_subscription(self.client.id, 30)
        self.assertAlmostEqual((business.parse_utc(second["expires_utc"])-now).total_seconds(), 30*86400, delta=2)

    def test_archive_revokes_sessions_hides_active_list_and_preserves_history(self):
        token = self.token()
        business.send_message(self.client.id, "History", "Keep this")
        store.enqueue_instruction(self.client.id, "trade", "{}")
        business.archive_client(self.client.id)
        self.assertIsNone(store.client_for_token(token))
        self.assertEqual(store.list_clients(), [])
        self.assertIsNone(store.find_by_pairing_code(self.code))
        with store.connect() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM instructions").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT count(*) FROM azt_messages").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT status FROM clients").fetchone()[0], "REVOKED")

    def test_edit_preserves_risk_and_rejects_invalid_timezone(self):
        updated = business.edit_client(self.client.id, name="Renamed", max_mt5_accounts=2, display_timezone="EAT")
        self.assertEqual(updated["display_timezone"], "Africa/Kampala")
        self.assertEqual(updated["risk_per_trade_pct"], self.client.risk_per_trade_pct)
        with self.assertRaises(ValueError):
            business.set_preferences(self.client.id, "Fake/Zone")

    def test_timestamps_require_offset_and_are_stored_true_utc(self):
        now = business.utc_iso("2026-10-27T15:00:00+03:00")
        self.assertEqual(now, "2026-10-27T12:00:00+00:00")
        with self.assertRaises(ValueError):
            business.utc_iso("2026-10-27T15:00:00")

    def test_messages_work_without_telegram_and_read_scope_cannot_cross_clients(self):
        other, _ = store.create_client("Other")
        result = business.send_message(self.client.id, "Hello", "Visible inside the client", also_telegram=True)
        self.assertFalse(result["telegram_queued"])
        self.assertFalse(business.mark_message_read(other.id, result["id"]))
        self.assertEqual(len(business.messages(self.client.id, True)), 1)
        self.assertTrue(business.mark_message_read(self.client.id, result["id"]))
        self.assertEqual(business.messages(self.client.id, True), [])

    def test_broadcast_only_active_unarchived_clients(self):
        paused, _ = store.create_client("Paused")
        archived, _ = store.create_client("Archived")
        store.set_status(paused.name, "PAUSED")
        business.archive_client(archived.id)
        self.assertEqual(business.broadcast_message("Notice", "Hello")["sent"], 1)
        self.assertEqual(business.messages(paused.id), [])

    def test_unpriced_plan_cannot_create_payable_or_approved_free_checkout(self):
        with self.assertRaisesRegex(ValueError, "not priced"):
            self.payment()
        legacy = store.create_payment_request(self.client.id, plan_code="STARTER", amount=0)
        with self.assertRaisesRegex(ValueError, "Legacy/unpriced"):
            business.review_payment(legacy["id"], True)

    def test_payment_snapshot_manual_pending_approval_and_idempotent_extension(self):
        self.priced()
        before = store.subscription_for_client(self.client.id)["expires_utc"]
        payment = self.payment()
        self.assertEqual(payment["status"], "PENDING")
        self.assertEqual(before, store.subscription_for_client(self.client.id)["expires_utc"])
        self.priced("99")
        self.assertEqual(payment["amount"], 25)
        first = business.review_payment(payment["id"], True)
        expiry = store.subscription_for_client(self.client.id)["expires_utc"]
        self.assertEqual(first["status"], "APPROVED")
        business.review_payment(payment["id"], True)
        self.assertEqual(expiry, store.subscription_for_client(self.client.id)["expires_utc"])
        with self.assertRaises(ValueError):
            business.review_payment(payment["id"], False)

    def test_payment_rejection_does_not_extend_access(self):
        self.priced()
        before = store.subscription_for_client(self.client.id)["expires_utc"]
        payment = self.payment()
        business.review_payment(payment["id"], False, note="Unverified transfer")
        self.assertEqual(before, store.subscription_for_client(self.client.id)["expires_utc"])

    def test_duplicate_transaction_and_wrong_proof_rejected(self):
        self.priced()
        self.payment(transaction_hash="A"*64)
        with self.assertRaises(ValueError):
            self.payment(transaction_hash="a"*64)
        with self.assertRaises(ValueError):
            business.submit_payment(self.client.id, "STARTER", "MTN", proof="a local path is not proof")
        with self.assertRaises(ValueError):
            business.submit_payment(self.client.id, "STARTER", "BINANCE", proof="data:image/png;base64,AAAA")
        payment = business.submit_payment(self.client.id, "STARTER", "MTN", proof=image_proof())
        self.assertTrue(payment["proof"].startswith("data:image/png;base64,"))

    def test_payment_methods_exact_public_addresses_and_networks(self):
        methods = {m["code"]: m for m in business.payment_methods()}
        self.assertEqual(methods["MTN"]["address"], "0781920398")
        self.assertEqual(methods["USDT_TRC20"]["network"], "TRC20 / Tron")
        self.assertEqual(methods["BTC_BEP20"]["address"], "0x37e801c682cc4fb65cd501ae450149c274b6ba6c")
        self.assertEqual(methods["BINANCE"]["address"], "1035801756")
        self.assertTrue(all(m["network"] for m in methods.values()))

    def test_referrals_disabled_until_configured_and_only_paid_approval_rewards(self):
        referrer, _ = store.create_client("Referrer")
        code = business.referral_summary(referrer.id)["code"]
        business.link_referral(self.client.id, code)
        self.priced()
        payment = self.payment()
        business.review_payment(payment["id"], True)
        self.assertEqual(business.referral_summary(referrer.id)["reward_history"], [])

    def test_referral_percentage_reward_deduplicates_and_default_is_first_payment_only(self):
        referrer, _ = store.create_client("Referrer")
        business.link_referral(self.client.id, business.referral_summary(referrer.id)["code"])
        business.set_referral_settings(enabled=True, mode="PERCENT", value=20, recurring=False)
        self.priced()
        payment = self.payment()
        self.assertEqual(business.referral_summary(referrer.id)["reward_history"], [])
        business.review_payment(payment["id"], True)
        business.review_payment(payment["id"], True)
        rewards = business.referral_summary(referrer.id)
        self.assertEqual(rewards["pending_rewards"], {"USD": 5})
        second = self.payment(transaction_hash="b"*64)
        business.review_payment(second["id"], True)
        self.assertEqual(len(business.referral_summary(referrer.id)["reward_history"]), 1)

    def test_referral_no_self_referral_cycles_or_recipient_change(self):
        other, _ = store.create_client("Other")
        own = business.referral_summary(self.client.id)["code"]
        theirs = business.referral_summary(other.id)["code"]
        with self.assertRaises(ValueError):
            business.link_referral(self.client.id, own)
        business.link_referral(self.client.id, theirs)
        with self.assertRaises(ValueError):
            business.link_referral(other.id, own)

    def test_promo_limits_one_use_duration_and_account_allowance(self):
        business.save_promo("AZT-GIVEAWAY", duration_days=30, max_redemptions=1, max_mt5_accounts=2)
        summary = business.redeem_promo(self.client.id, "AZT-GIVEAWAY")
        self.assertEqual(summary["max_mt5_accounts"], 2)
        with self.assertRaises(ValueError):
            business.redeem_promo(self.client.id, "AZT-GIVEAWAY")
        other, _ = store.create_client("Other")
        with self.assertRaises(ValueError):
            business.redeem_promo(other.id, "AZT-GIVEAWAY")
        self.assertEqual(business.promos()[0]["remaining_uses"], 0)
        self.assertEqual(business.promo_redemptions("AZT-GIVEAWAY")[0]["client_name"], self.client.name)

    def test_repeated_promo_when_allowed_never_multiplies_account_slots(self):
        business.save_promo("REPEAT", duration_days=1, max_redemptions=3, max_mt5_accounts=2, one_use_per_user=False)
        for _ in range(3):
            self.assertEqual(business.redeem_promo(self.client.id, "REPEAT")["max_mt5_accounts"], 2)

    def test_promo_does_not_downgrade_existing_paid_plan(self):
        business.save_plan("PRO", amount=50, max_mt5_accounts=3)
        business.renew_subscription(self.client.id, 30, plan_code="PRO", max_mt5_accounts=3)
        business.save_promo("GIFT", max_mt5_accounts=2)
        result = business.redeem_promo(self.client.id, "GIFT")
        self.assertEqual(result["subscription"]["plan_code"], "PRO")
        self.assertEqual(result["subscription"]["status"], "ACTIVE")
        self.assertEqual(result["subscription"]["access_kind"], "PAID")
        self.assertEqual(result["max_mt5_accounts"], 3)

    def test_atomic_promo_capacity_prevents_parallel_over_redemption(self):
        others = [store.create_client(f"Other {i}")[0] for i in range(4)]
        business.save_promo("LIMIT", max_redemptions=1)
        def redeem(client):
            try:
                business.redeem_promo(client.id, "LIMIT")
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(redeem, others)), 1)

    def test_expired_and_disabled_promo_cannot_be_redeemed(self):
        business.save_promo("EXPIRED", expires_utc=business.utc_iso(business.utc_now()-timedelta(seconds=1)))
        business.save_promo("DISABLED", enabled=False)
        for code in ("EXPIRED", "DISABLED"):
            with self.assertRaises(ValueError):
                business.redeem_promo(self.client.id, code)

    def test_account_limits_cross_client_binding_and_per_account_delivery(self):
        business.set_account_limit(self.client.id, 2)
        first = business.authorize_account(self.client.id, 123, "Broker")
        second = business.authorize_account(self.client.id, 456, "Broker")
        with self.assertRaises(ValueError):
            business.authorize_account(self.client.id, 789, "Broker")
        other, _ = store.create_client("Other")
        with self.assertRaises(ValueError):
            business.authorize_account(other.id, 123, "Broker")
        since = business.utc_iso(business.utc_now()-timedelta(seconds=1))
        store.enqueue_instruction(self.client.id, "new", "{}")
        row = business.next_account_instruction(self.client.id, first["id"], since)
        business.acknowledge_account_instruction(self.client.id, first["id"], row["id"], "EXECUTED", "ticket 1")
        self.assertIsNone(business.next_account_instruction(self.client.id, first["id"], since))
        self.assertEqual(business.next_account_instruction(self.client.id, second["id"], since)["id"], row["id"])
        self.assertFalse(business.acknowledge_account_instruction(other.id, second["id"], row["id"], "EXECUTED", "not theirs"))

    def test_no_backlog_before_start_boundary(self):
        token = self.token()
        context = business.session_context(token)
        store.enqueue_instruction(self.client.id, "old", "{}")
        with store.connect() as con:
            con.execute("UPDATE instructions SET created_utc=?", (business.utc_iso(business.utc_now()-timedelta(days=1)),))
        self.assertIsNone(business.next_account_instruction(self.client.id, context["account_id"], context["created_utc"]))

    def test_parallel_fetch_same_account_reserves_once_before_ack(self):
        token = self.token()
        account_id = business.session_context(token)["account_id"]
        since = business.utc_iso(business.utc_now()-timedelta(seconds=1))
        store.enqueue_instruction(self.client.id, "parallel", "{}")
        def fetch(_):
            return business.next_account_instruction(self.client.id, account_id, since)
        with ThreadPoolExecutor(max_workers=8) as pool:
            offered = list(pool.map(fetch, range(8)))
        rows = [row for row in offered if row is not None]
        self.assertEqual(len(rows), 1)
        with store.connect() as con:
            reserved = con.execute("SELECT * FROM account_instruction_deliveries").fetchall()
        self.assertEqual(len(reserved), 1)
        self.assertEqual(reserved[0]["status"], "DISPATCHED")
        self.assertTrue(reserved[0]["dispatched_utc"].endswith("+00:00"))
        self.assertEqual(reserved[0]["acked_utc"], "")

    def test_parallel_fetch_different_accounts_each_reserves_once(self):
        business.set_account_limit(self.client.id, 2)
        first = business.authorize_account(self.client.id, 123, "Broker")["id"]
        second = business.authorize_account(self.client.id, 456, "Broker")["id"]
        since = business.utc_iso(business.utc_now()-timedelta(seconds=1))
        store.enqueue_instruction(self.client.id, "two-accounts", "{}")
        account_ids = [first, second] * 4
        def fetch(account_id):
            return account_id, business.next_account_instruction(self.client.id, account_id, since)
        with ThreadPoolExecutor(max_workers=8) as pool:
            offered = list(pool.map(fetch, account_ids))
        self.assertEqual(sum(account == first and row is not None for account, row in offered), 1)
        self.assertEqual(sum(account == second and row is not None for account, row in offered), 1)
        self.assertEqual(len({row["id"] for _, row in offered if row is not None}), 1)

    def test_parallel_http_polls_with_two_sessions_same_account_offer_once(self):
        first = self.token()
        context = business.session_context(first)
        second = store.create_session(self.client.id, context["account_id"])
        store.enqueue_instruction(self.client.id, "http-parallel", json.dumps({"market": "GOLD"}))
        since = business.utc_iso(business.utc_now()-timedelta(seconds=1))
        def poll(token):
            return self.req("/v1/instructions/next", token=token, query={"since": since})
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(poll, [first, second] * 4))
        self.assertTrue(all(status == 200 for status, _ in replies))
        self.assertEqual(sum(body["available"] for _, body in replies), 1)

    def test_lost_dispatch_response_is_not_reoffered_after_new_session_or_restart(self):
        token = self.token()
        context = business.session_context(token)
        since = business.utc_iso(business.utc_now()-timedelta(seconds=1))
        store.enqueue_instruction(self.client.id, "lost-response", "{}")
        dispatched = business.next_account_instruction(self.client.id, context["account_id"], since)
        self.assertIsNotNone(dispatched)
        # Drop the result without an ACK, then open a new session/connection as
        # after a client/server restart. No lease may reset this reservation.
        newer = store.create_session(self.client.id, context["account_id"])
        reopened = business.session_context(newer)
        self.assertIsNone(business.next_account_instruction(self.client.id, reopened["account_id"], since))
        with store.connect() as con:
            con.execute("UPDATE account_instruction_deliveries SET dispatched_utc='2000-01-01T00:00:00+00:00'")
        self.assertIsNone(business.next_account_instruction(self.client.id, reopened["account_id"], since))
        self.assertTrue(business.acknowledge_account_instruction(self.client.id, reopened["account_id"], dispatched["id"], "ERROR_REVIEW", "Delivery outcome needs manual reconciliation"))
        self.assertIsNone(business.next_account_instruction(self.client.id, reopened["account_id"], since))

    def test_reserved_ack_finishes_once_same_result_is_idempotent_conflict_rejected(self):
        token = self.token()
        account_id = business.session_context(token)["account_id"]
        since = business.utc_iso(business.utc_now()-timedelta(seconds=1))
        store.enqueue_instruction(self.client.id, "reserved-ack", "{}")
        row = business.next_account_instruction(self.client.id, account_id, since)
        self.assertTrue(business.acknowledge_account_instruction(self.client.id, account_id, row["id"], "EXECUTED", "ticket=42"))
        self.assertTrue(business.acknowledge_account_instruction(self.client.id, account_id, row["id"], "EXECUTED", "ticket=42"))
        self.assertFalse(business.acknowledge_account_instruction(self.client.id, account_id, row["id"], "REJECTED", "different outcome"))
        with store.connect() as con:
            saved = con.execute("SELECT * FROM account_instruction_deliveries").fetchone()
        self.assertEqual(saved["status"], "EXECUTED")
        self.assertTrue(saved["dispatched_utc"])
        self.assertTrue(saved["acked_utc"])

    def test_different_signals_are_serialized_until_current_account_acknowledges(self):
        token = self.token()
        account_id = business.session_context(token)["account_id"]
        since = business.utc_iso(business.utc_now()-timedelta(seconds=1))
        for index in range(3):
            store.enqueue_instruction(self.client.id, f"different-{index}", "{}")
        def poll(_):
            return business.next_account_instruction(self.client.id, account_id, since)
        with ThreadPoolExecutor(max_workers=8) as pool:
            offered = list(pool.map(poll, range(8)))
        claims = [row for row in offered if row is not None]
        self.assertEqual(len(claims), 1)
        with store.connect() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM account_instruction_deliveries WHERE status='DISPATCHED'").fetchone()[0], 1)
        self.assertTrue(business.acknowledge_account_instruction(self.client.id, account_id, claims[0]["id"], "EXECUTED", "ticket=42"))
        second = business.next_account_instruction(self.client.id, account_id, since)
        self.assertIsNotNone(second)
        self.assertNotEqual(second["id"], claims[0]["id"])
        self.assertIsNone(business.next_account_instruction(self.client.id, account_id, since))

    def test_unresolved_dispatch_timeout_alerts_once_and_never_releases_account(self):
        token = self.token()
        account_id = business.session_context(token)["account_id"]
        since = business.utc_iso(business.utc_now()-timedelta(seconds=1))
        store.enqueue_instruction(self.client.id, "unresolved", "{}")
        store.enqueue_instruction(self.client.id, "later", "{}")
        row = business.next_account_instruction(self.client.id, account_id, since)
        with store.connect() as con:
            con.execute("UPDATE account_instruction_deliveries SET dispatched_utc=?", (business.utc_iso(business.utc_now()-timedelta(seconds=61)),))
        with patch("server.telegram_notifications.enqueue_owner_event") as owner_alert:
            first = business.maintenance_tick()
            second = business.maintenance_tick()
        self.assertEqual((first["execution_reviews"], second["execution_reviews"]), (1, 0))
        owner_alert.assert_called_once()
        self.assertEqual(len([message for message in business.messages(self.client.id) if message["title"] == "Execution needs review"]), 1)
        self.assertIsNone(business.next_account_instruction(self.client.id, account_id, since))
        delivery = business.instruction_deliveries(self.client.id)[0]
        self.assertEqual((delivery["instruction_id"], delivery["status"]), (row["id"], "DISPATCHED"))
        self.assertEqual(delivery["signal_key"], "unresolved")

    def test_explicit_owner_resolution_unblocks_only_later_signal_without_reoffering(self):
        token = self.token()
        account_id = business.session_context(token)["account_id"]
        since = business.utc_iso(business.utc_now()-timedelta(seconds=1))
        store.enqueue_instruction(self.client.id, "needs-review", "{}")
        store.enqueue_instruction(self.client.id, "fresh-later", "{}")
        first = business.next_account_instruction(self.client.id, account_id, since)
        with self.assertRaises(ValueError):
            business.resolve_delivery(self.client.id, account_id, first["id"], "")
        other, _ = store.create_client("Other")
        with self.assertRaises(ValueError):
            business.resolve_delivery(other.id, account_id, first["id"], "Not their delivery")
        self.assertTrue(business.resolve_delivery(self.client.id, account_id, first["id"], "Broker account checked; no automatic resubmission"))
        self.assertFalse(business.resolve_delivery(self.client.id, account_id, first["id"], "Repeated review"))
        second = business.next_account_instruction(self.client.id, account_id, since)
        self.assertEqual(second["signal_key"], "fresh-later")
        self.assertNotEqual(second["id"], first["id"])
        history = {row["instruction_id"]: row for row in business.instruction_deliveries(self.client.id)}
        self.assertEqual(history[first["id"]]["status"], "ERROR_REVIEW")
        self.assertIn("Broker account checked", history[first["id"]]["ack_message"])
        self.assertEqual(len([event for event in business.system_events() if event["kind"] == "EXECUTION_REVIEW_RESOLVED"]), 1)

    def test_unresolved_account_does_not_block_other_authorized_account(self):
        business.set_account_limit(self.client.id, 2)
        first = business.authorize_account(self.client.id, 123, "Broker")["id"]
        second = business.authorize_account(self.client.id, 456, "Broker")["id"]
        since = business.utc_iso(business.utc_now()-timedelta(seconds=1))
        store.enqueue_instruction(self.client.id, "shared-fresh", "{}")
        store.enqueue_instruction(self.client.id, "another-fresh", "{}")
        one = business.next_account_instruction(self.client.id, first, since)
        self.assertIsNone(business.next_account_instruction(self.client.id, first, since))
        two = business.next_account_instruction(self.client.id, second, since)
        self.assertEqual(one["id"], two["id"])

    def test_disable_account_revokes_only_its_session(self):
        token = self.token()
        context = business.session_context(token)
        business.disable_account(self.client.id, context["account_id"])
        self.assertIsNone(store.client_for_token(token))

    def test_ack_retry_is_idempotent_and_preserves_confirmed_execution_metadata(self):
        token = self.token()
        store.enqueue_instruction(self.client.id, "executed", json.dumps({"strategy_id": "PULLBACK", "stop_loss": 10, "take_profit": 20}))
        with store.connect() as con:
            instruction = con.execute("SELECT id FROM instructions").fetchone()[0]
        request = {"instruction_id": instruction, "status": "EXECUTED", "message": "Done; ticket=42; volume=.01; risk=0.9%"}
        with patch("server.trade_telemetry.record_execution") as record:
            self.assertEqual(self.req("/v1/instructions/ack", method="POST", token=token, payload=request)[0], 200)
            self.assertEqual(self.req("/v1/instructions/ack", method="POST", token=token, payload=request)[0], 200)
        self.assertEqual(record.call_args.args[:3], (self.client.id, "Broker|123", "42"))
        self.assertEqual(record.call_args.kwargs["risk_pct"], .9)
        with store.connect() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM account_instruction_deliveries").fetchone()[0], 1)

    def test_account_limit_reduction_blocks_excess_session_after_plan_change(self):
        business.set_account_limit(self.client.id, 2)
        self.token(123)
        second = self.token(456)
        with store.connect() as con:
            con.execute("UPDATE clients SET max_mt5_accounts=0 WHERE id=?", (self.client.id,))
            con.execute("UPDATE subscriptions SET max_mt5_accounts=1 WHERE client_id=?", (self.client.id,))
        self.assertFalse(business.trade_access(second)["allowed"])

    def test_session_cannot_bind_foreign_account_and_hosted_mode_blocks_pc_policy(self):
        token = self.token()
        context = business.session_context(token)
        other, _ = store.create_client("Other")
        with self.assertRaises(ValueError):
            store.create_session(other.id, context["account_id"])
        store.set_execution_mode(self.client.id, "HOSTED")
        self.assertFalse(business.trade_access(token)["allowed"])
        self.assertEqual(self.req("/v1/client/risk-policy", token=token)[0], 403)

    def test_disabled_account_can_be_reenabled_by_admin_within_limit(self):
        token = self.token()
        context = business.session_context(token)
        business.disable_account(self.client.id, context["account_id"])
        business.enable_account(self.client.id, context["account_id"])
        self.assertEqual(business.authorize_account(self.client.id, 123, "Broker")["status"], "ACTIVE")

    def test_referral_link_is_real_scoped_invitation_without_identity_disclosure(self):
        token = self.token()
        status, summary = self.req("/v1/azt/referrals", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(summary["link"].startswith("http://127.0.0.1:1234/ref/AZT-"))
        status, page = self.req("/ref/" + summary["code"])
        self.assertEqual(status, 200)
        self.assertIn(summary["code"], page)
        self.assertNotIn(self.client.name, page)
        self.assertNotIn(self.code, page)

    def test_payment_does_not_override_explicit_pause(self):
        self.priced()
        payment = self.payment()
        store.set_status(self.client.name, "PAUSED")
        business.review_payment(payment["id"], True)
        self.assertFalse(business.subscription_summary(self.client.id)["allowed"])
        self.assertEqual(store.client_by_id(self.client.id).status, "PAUSED")

    def test_authenticated_routes_deny_anonymous_and_cannot_read_other_messages(self):
        status, _ = self.req("/v1/azt/messages")
        self.assertEqual(status, 401)
        token = self.token()
        other, _ = store.create_client("Other")
        message = business.send_message(other.id, "Private", "Other client's content")
        status, body = self.req("/v1/azt/messages", token=token)
        self.assertEqual((status, body["messages"]), (200, []))
        status, _ = self.req(f"/v1/azt/messages/{message['id']}/read", method="POST", token=token)
        self.assertEqual(status, 404)

    def test_api_expired_client_can_pay_but_cannot_execute(self):
        token = self.token()
        store.set_subscription(self.client.id, plan_code="STARTER", status="EXPIRED", starts_utc=business.utc_iso(), expires_utc=business.utc_iso(business.utc_now()-timedelta(seconds=1)))
        self.assertEqual(self.req("/v1/azt/payment-methods", token=token)[0], 200)
        self.assertEqual(self.req("/v1/client/risk-policy", token=token)[0], 403)
        self.assertEqual(self.req("/v1/instructions/next", token=token)[0], 403)

    def test_api_news_lock_is_temporary_and_no_instruction_is_delivered(self):
        token = self.token()
        store.set_news_lock(True)
        self.assertEqual(self.req("/v1/client/risk-policy", token=token)[0], 409)
        status, body = self.req("/v1/instructions/next", token=token)
        self.assertEqual((status, body["available"]), (200, False))

    def test_api_authorize_second_account_with_allowance_and_read_only_expired_token(self):
        business.set_account_limit(self.client.id, 2)
        for login in (123, 456):
            status, body = self.req("/v1/client/authorize", method="POST", payload={"pairing_code": self.code, "mt5_login": login, "mt5_server": "Broker"})
            self.assertEqual(status, 200)
            self.assertTrue(body["allowed"])
            self.assertTrue(body["session_token"])
        store.set_status(self.client.name, "PAUSED")
        _, body = self.req("/v1/client/authorize", method="POST", payload={"pairing_code": self.code, "mt5_login": 123, "mt5_server": "Broker"})
        self.assertFalse(body["allowed"])
        self.assertTrue(body["session_token"])

    def test_api_telemetry_rejects_forged_account_identity(self):
        token = self.token()
        status, _ = self.req("/v1/client/telemetry", method="POST", token=token, payload={"snapshot": {"account": {"login": 999, "server": "Broker"}, "observed_utc": business.utc_iso()}})
        self.assertEqual(status, 400)

    def test_api_telemetry_and_journal_are_scoped_to_current_client(self):
        token = self.token()
        snapshot = {"account": {"login": 123, "server": "Broker", "currency": "USD", "balance": 1000, "equity": 1000}, "observed_utc": business.utc_iso(), "positions": [], "trades": []}
        self.assertEqual(self.req("/v1/client/telemetry", method="POST", token=token, payload={"snapshot": snapshot})[0], 200)
        status, body = self.req("/v1/azt/overview", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(body["telemetry"]["accounts"][0]["account_key"], "Broker|123")
        self.assertEqual(self.req("/v1/azt/journal", token=token)[0], 200)


if __name__ == "__main__":
    unittest.main()
