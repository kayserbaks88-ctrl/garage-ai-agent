"""Real PostgreSQL tests for complimentary access and registration review.

Set STAFF_TEST_DATABASE_URL to a disposable local PostgreSQL database. Each test uses its own
uniquely named schema, synthetic businesses only, a mocked mailer, and blocks all outbound sockets
from Python so Stripe or any other external service cannot be contacted.
"""
import os
import socket
import unittest
import uuid
from unittest.mock import patch

import psycopg2
from psycopg2 import sql

from trimtech.modules.staff import (accounts_migration, billing_migration, complimentary_access,
                                    complimentary_migration, database, onboarding,
                                    onboarding_migration, registration_review as review,
                                    registration_review_migration as review_migration)


@unittest.skipUnless(os.getenv("STAFF_TEST_DATABASE_URL"), "Requires disposable local PostgreSQL")
class ControlCentreDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ["STAFF_TEST_DATABASE_URL"]
        self.schema = "staff_test_" + uuid.uuid4().hex
        self.admin = psycopg2.connect(self.url)
        self.admin.autocommit = True
        with self.admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        for target in (patch.object(database, "get_connection", self.connect),
                       patch.object(socket.socket, "connect", side_effect=AssertionError("outbound network blocked")),
                       patch.dict(os.environ, {"STAFF_STRIPE_ENABLED": "0", "PLATFORM_ADMIN_NOTIFY_EMAIL": "platform@example.test",
                                               "STAFF_PUBLIC_BASE_URL": "https://staff.example.test",
                                               "PLATFORM_ADMIN_NOTIFY_VERIFIED": "1"})):
            target.start()
            self.addCleanup(target.stop)
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                for statement in database.SCHEMA_STATEMENTS:
                    cursor.execute(statement)
        database.init_staff_database(migrate=True)
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                accounts_migration.migrate(cursor)
                onboarding_migration.migrate(cursor)
                billing_migration.migrate(cursor)
        self.apply_control_centre_migrations()

    def apply_control_centre_migrations(self):
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                complimentary_migration.migrate(cursor)
                review_migration.migrate(cursor)

    def cleanup_schema(self):
        assert self.schema.startswith("staff_test_") and len(self.schema) == 43
        with self.admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.admin.close()

    def connect(self):
        return psycopg2.connect(self.url, options=f"-c search_path={self.schema} -c timezone=UTC")

    # ---- synthetic data -------------------------------------------------
    def business(self, bid, trial="expired", verified=False, active=True):
        email = f"{bid}@example.test"
        database.execute("INSERT INTO sm_businesses(id,name,active) VALUES (%s,%s,%s)", (bid, "Synthetic " + bid, active))
        database.execute("INSERT INTO sm_administrators(id,email,contact_name,password_hash,verified_at) VALUES (%s,%s,'Owner','not-a-login-hash',%s)",
                         (bid + "-admin", email, "2026-01-01T00:00:00Z" if verified else None))
        database.execute("INSERT INTO sm_memberships(administrator_id,business_id) VALUES (%s,%s)", (bid + "-admin", bid))
        if trial == "expired":
            database.execute("""INSERT INTO so_trials(business_id,administrator_id,starts_at,ends_at)
                VALUES (%s,%s,NOW()-INTERVAL '20 days',NOW()-INTERVAL '20 days'+INTERVAL '336 hours')""", (bid, bid + "-admin"))
        elif trial == "active":
            database.execute("""INSERT INTO so_trials(business_id,administrator_id,starts_at,ends_at)
                VALUES (%s,%s,NOW()-INTERVAL '2 days',NOW()-INTERVAL '2 days'+INTERVAL '336 hours')""", (bid, bid + "-admin"))
        elif trial == "pending":
            database.execute("INSERT INTO so_trials(business_id,administrator_id) VALUES (%s,%s)", (bid, bid + "-admin"))
        return email

    def paid(self, bid):
        database.execute("""INSERT INTO sb_accounts(business_id,stripe_account_id,livemode,customer_key,customer_name,customer_email)
            VALUES (%s,'acct_synthetic',FALSE,%s,'Synthetic','x@example.test')""", (bid, "key-" + bid))
        database.execute("""INSERT INTO sb_checkouts(id,business_id,actor_id,price_id,product_id,return_url,status,expires_at)
            VALUES (%s,%s,%s,'price_synthetic','prod_synthetic','https://staff.example.test/return','complete',NOW()+INTERVAL '1 day')""",
                         ("co-" + bid, bid, bid + "-admin"))
        database.execute("""INSERT INTO sb_subscriptions(id,business_id,checkout_id,status,paid_until)
            VALUES (%s,%s,%s,'active',NOW()+INTERVAL '20 days')""", ("sub-" + bid, bid, "co-" + bid))

    def billing_snapshot(self):
        rows = {}
        for table in ("sb_accounts", "sb_checkouts", "sb_subscriptions"):
            rows[table] = database.fetch_all(f"SELECT * FROM {table} ORDER BY 1")
        return rows

    def active(self, bid):
        return database.fetch_one("SELECT active FROM sm_businesses WHERE id=%s", (bid,))["active"]

    def audit_actions(self, bid):
        return [r["action"] for r in database.fetch_all("SELECT action FROM staff_audit WHERE business_id=%s ORDER BY id", (bid,))]

    # ---- migrations -----------------------------------------------------
    def test_migrations_are_checksummed_repeatable_and_additive(self):
        self.apply_control_centre_migrations()
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                complimentary_migration.verify(cursor)
                review_migration.verify(cursor)
        tables = {r["table_name"] for r in database.fetch_all(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
        for name in ("sc_grants", "sc_schema_migrations", "sr_review_batches", "sr_review_items",
                     "sr_registration_notices", "sr_schema_migrations"):
            self.assertIn(name, tables)
        self.assertTrue(review.ready())

    # ---- complimentary access ------------------------------------------
    def test_seven_day_grant_revocation_and_expiry(self):
        self.business("trial-ended")
        before = self.billing_snapshot()
        self.assertEqual(onboarding.access("trial-ended")["state"], "expired")
        result = complimentary_access.grant("trial-ended", "platform:test", 7, "Support request", "trial-ended")
        self.assertEqual(result["days"], 7)
        access = onboarding.access("trial-ended")
        self.assertEqual(access["state"], "active")
        self.assertTrue(access["complimentary"])
        self.assertIn(access["days"], (6, 7))
        self.assertEqual(complimentary_access.history("trial-ended")[0]["state"], "active")
        self.assertEqual(complimentary_access.revoke("trial-ended", "platform:test", "Granted in error"), 1)
        self.assertEqual(onboarding.access("trial-ended")["state"], "expired")
        self.assertEqual(complimentary_access.history("trial-ended")[0]["state"], "revoked")
        self.assertEqual(self.audit_actions("trial-ended"), ["grant", "revoke"])
        with self.assertRaises(complimentary_access.GrantRefused):
            complimentary_access.revoke("trial-ended", "platform:test", "Nothing to revoke")

        complimentary_access.grant("trial-ended", "platform:test", 7, "Second grant", "trial-ended")
        self.assertEqual(onboarding.access("trial-ended")["state"], "active")
        database.execute("""UPDATE sc_grants SET starts_at=NOW()-INTERVAL '8 days',expires_at=NOW()-INTERVAL '1 day'
            WHERE business_id='trial-ended' AND revoked_at IS NULL""")
        self.assertEqual(onboarding.access("trial-ended")["state"], "expired")
        self.assertEqual(complimentary_access.history("trial-ended")[0]["state"], "expired")
        self.assertEqual(self.billing_snapshot(), before)

    def test_grant_refusals_and_lifetime_cap(self):
        self.business("pending", trial="pending")
        self.business("legacy", trial="legacy")
        self.business("paying", trial="expired")
        self.paid("paying")
        self.business("capped")
        self.business("inactive", active=False)
        refusals = [("pending", 7, "pending"), ("legacy", 7, "legacy"), ("paying", 7, "paying"),
                    ("inactive", 7, "inactive"), ("capped", 5, "capped"), ("capped", 7, "wrong-id"),
                    ("missing", 7, "missing")]
        for bid, days, confirmation in refusals:
            with self.assertRaises(complimentary_access.GrantRefused, msg=bid):
                complimentary_access.grant(bid, "platform:test", days, "Reason", confirmation)
        with self.assertRaises(complimentary_access.GrantRefused):
            complimentary_access.grant("capped", "platform:test", 7, "   ", "capped")
        complimentary_access.grant("capped", "platform:test", 30, "One", "capped")
        with self.assertRaises(complimentary_access.GrantRefused):  # active grant already exists
            complimentary_access.grant("capped", "platform:test", 7, "Two", "capped")
        expire = ("UPDATE sc_grants SET starts_at=NOW()-INTERVAL '31 days',expires_at=NOW()-INTERVAL '1 second' "
                  "WHERE business_id='capped' AND expires_at>NOW()")
        database.execute(expire)
        complimentary_access.grant("capped", "platform:test", 30, "Two", "capped")
        database.execute(expire)
        complimentary_access.grant("capped", "platform:test", 30, "Three", "capped")
        database.execute(expire)
        with self.assertRaises(complimentary_access.GrantRefused):  # 30+30+30 used; 90-day lifetime cap
            complimentary_access.grant("capped", "platform:test", 3, "Over cap", "capped")
        self.assertEqual(onboarding.access("paying")["state"], "paid")

    # ---- bulk review ---------------------------------------------------
    def make_population(self):
        for bid in ("sus-1", "sus-2", "sus-3"):
            self.business(bid, trial="pending")
        self.business("sus-expired", trial="expired")
        self.business("genuine-legacy", trial="legacy")
        self.business("genuine-verified", trial="expired", verified=True)
        self.business("genuine-paying", trial="expired")
        self.paid("genuine-paying")
        self.business("genuine-checkout", trial="expired")
        database.execute("""INSERT INTO sb_accounts(business_id,stripe_account_id,livemode,customer_key,customer_name,customer_email)
            VALUES ('genuine-checkout','acct_synthetic',FALSE,'key-gc','Synthetic','x@example.test')""")
        database.execute("""INSERT INTO sb_checkouts(id,business_id,actor_id,price_id,product_id,return_url,status,expires_at)
            VALUES ('co-gc','genuine-checkout','genuine-checkout-admin','p','q','https://staff.example.test/r','expired',NOW()+INTERVAL '1 day')""")
        self.business("genuine-grant", trial="expired")
        complimentary_access.grant("genuine-grant", "platform:test", 3, "Support", "genuine-grant")
        self.business("genuine-staffed", trial="expired")
        employee = database.fetch_one("""INSERT INTO staff_employees(business_id,full_name,phone,hourly_rate,payroll_number)
            VALUES ('genuine-staffed','Pat','07000',12,'1') RETURNING id""")["id"]
        site = database.fetch_one("""INSERT INTO staff_sites(business_id,name,address,latitude,longitude)
            VALUES ('genuine-staffed','Site','1 Test Street',51.5,-0.1) RETURNING id""")["id"]
        database.execute("""INSERT INTO staff_shifts(business_id,employee_id,site_id,site_name,clock_in_at)
            VALUES ('genuine-staffed',%s,%s,'Site',NOW()-INTERVAL '1 day')""", (employee, site))
        self.business("genuine-setup", trial="expired")
        database.execute("INSERT INTO so_setup(business_id,completed) VALUES ('genuine-setup','{\"company\":true}')")
        self.genuine = ["genuine-legacy", "genuine-verified", "genuine-paying", "genuine-checkout",
                        "genuine-grant", "genuine-staffed", "genuine-setup"]
        self.suspicious = ["sus-1", "sus-2", "sus-3", "sus-expired"]

    def test_bulk_deactivation_protects_genuine_businesses_and_is_reversible(self):
        self.make_population()
        before = self.billing_snapshot()
        everything = self.suspicious + self.genuine
        phrase = review.confirmation_phrase("deactivate", len(everything))
        with self.assertRaises(review.ReviewRefused):
            review.apply("deactivate", everything, "platform:test", "Spam", "DEACTIVATE 1")
        self.assertTrue(all(self.active(b) for b in everything))
        with self.assertRaises(review.ReviewRefused):
            review.apply("deactivate", everything, "platform:test", "", phrase)

        result = review.apply("deactivate", everything, "platform:test", "Suspicious sign-ups", phrase)
        self.assertCountEqual(result["applied"], self.suspicious)
        self.assertCountEqual([b for b, _ in result["skipped"]], self.genuine)
        self.assertTrue(all(why.startswith("Protected") for _, why in result["skipped"]))
        for bid in self.genuine:
            self.assertTrue(self.active(bid), bid)
        for bid in self.suspicious:
            self.assertFalse(self.active(bid), bid)
            self.assertEqual(self.audit_actions(bid), ["registration_review_deactivate"])
        for bid in self.genuine:
            self.assertNotIn("registration_review_deactivate", self.audit_actions(bid))
        items = database.fetch_all("SELECT business_id,previous_active,new_active FROM sr_review_items")
        self.assertEqual(sorted(i["business_id"] for i in items), sorted(self.suspicious))
        self.assertTrue(all(i["previous_active"] and not i["new_active"] for i in items))

        again = review.apply("deactivate", self.suspicious, "platform:test", "Repeat", review.confirmation_phrase("deactivate", 4))
        self.assertEqual(again["applied"], [])
        self.assertEqual(again["batch_id"], None)

        restore = ["sus-1", "sus-2", "genuine-legacy"]
        outcome = review.apply("reactivate", restore, "platform:test", "Contacted owner", review.confirmation_phrase("reactivate", 3))
        self.assertCountEqual(outcome["applied"], ["sus-1", "sus-2"])
        self.assertEqual([b for b, _ in outcome["skipped"]], ["genuine-legacy"])
        self.assertTrue(self.active("sus-1") and self.active("sus-2"))
        self.assertFalse(self.active("sus-3"))
        self.assertEqual(self.audit_actions("sus-1"), ["registration_review_deactivate", "registration_review_reactivate"])
        self.assertEqual([h["action"] for h in review.history()], ["reactivate", "deactivate"])
        self.assertEqual(self.billing_snapshot(), before)
        self.assertEqual(database.fetch_one("SELECT COUNT(*) AS n FROM sm_businesses")["n"], len(everything))

    def test_reactivation_only_restores_businesses_deactivated_by_review(self):
        self.business("manual", trial="pending", active=False)
        outcome = review.apply("reactivate", ["manual"], "platform:test", "Try", review.confirmation_phrase("reactivate", 1))
        self.assertEqual(outcome["applied"], [])
        self.assertEqual(outcome["skipped"], [("manual", "Not deactivated by registration review")])
        self.assertFalse(self.active("manual"))

    # ---- notifications (mock mailer) -----------------------------------
    def test_staff_directory_reads_after_both_migrations(self):
        from trimtech.modules.staff import platform_control
        self.make_population()
        data = platform_control.directory()
        self.assertEqual(data["total"], len(self.genuine) + len(self.suspicious))
        self.assertTrue(data["review_ready"])
        summary = platform_control.build_control_centre_summary([], data, garage_available=False)
        self.assertEqual(summary["products"]["staff"]["businesses"], data["total"])

    def test_registration_notice_is_sent_once_and_failures_are_recorded(self):
        email = self.business("notify-ok", trial="pending")
        with patch.object(review, "send_staff_email", return_value=(True, None, "mock-id")) as send:
            self.assertEqual(review.notify(email), "sent")
            self.assertEqual(review.notify(email), "duplicate")
            self.assertEqual(send.call_count, 1)
            recipient, subject, text, body = send.call_args.args[:4]
        self.assertEqual(recipient, "platform@example.test")
        self.assertNotIn(email, text + body)
        self.assertIn("n***@example.test", text)
        self.assertEqual(database.fetch_one("SELECT status FROM sr_registration_notices WHERE business_id='notify-ok'")["status"], "sent")

        failing = self.business("notify-fail", trial="pending")
        with patch.object(review, "send_staff_email", return_value=(False, "provider_http_503", None)) as send:
            self.assertEqual(review.notify(failing), "failed")
            self.assertEqual(review.notify(failing), "duplicate")
            self.assertEqual(send.call_count, 1)
        self.assertEqual(database.fetch_one("SELECT status FROM sr_registration_notices WHERE business_id='notify-fail'")["status"], "failed")

        with patch.object(review, "send_staff_email", return_value=(True, None, "mock-id")) as send:
            self.assertEqual(review.notify(email, "verified"), "sent")
            self.assertEqual(review.notify("nobody@example.test"), "no_business")
        self.assertEqual(send.call_count, 1)

    def test_notification_never_blocks_signup_when_mailer_raises_or_unmigrated(self):
        email = self.business("notify-raise", trial="pending")
        with patch.object(review, "send_staff_email", side_effect=RuntimeError("mock outage")):
            self.assertEqual(review.notify(email), "error")
        # The claim row is kept so an outage cannot cause repeat notices.
        self.assertEqual(database.fetch_one("SELECT status FROM sr_registration_notices WHERE business_id='notify-raise'")["status"], "claimed")
        database.execute("DROP TABLE sr_registration_notices")
        self.assertEqual(review.notify(email, "verified"), "not_migrated")

    def test_stripe_is_never_contacted(self):
        self.business("stripe-guard")
        with self.assertRaises(AssertionError):
            sock = socket.socket()
            self.addCleanup(sock.close)
            sock.connect(("example.invalid", 443))
        complimentary_access.grant("stripe-guard", "platform:test", 3, "Guard", "stripe-guard")
        review.apply("deactivate", ["stripe-guard"], "platform:test", "Guard", review.confirmation_phrase("deactivate", 1))
        self.assertEqual(self.billing_snapshot(), {"sb_accounts": [], "sb_checkouts": [], "sb_subscriptions": []})


if __name__ == "__main__":
    unittest.main()
