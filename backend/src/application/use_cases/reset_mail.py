import json
from src.application.use_cases.identity import now
from src.application.ports.identity import IdentityStore, MessageCipher, Mailer


class DeliverResetMail:
    def __init__(self, store: IdentityStore, cipher: MessageCipher, mailer: Mailer):
        self.store, self.cipher, self.mailer = store, cipher, mailer

    def execute(self, message_id):
        with self.store.transaction(write=True) as db:
            message = db.one("mail_outbox", id=message_id)
            if (
                not message
                or message["sent_at"] is not None
                or message["available_at"] > now()
            ):
                return
            reset = db.one("password_resets", id=message["reset_id"])
            if reset["consumed_at"] is not None or reset["expires_at"] <= now():
                db.change(
                    "mail_outbox",
                    message_id,
                    sent_at=now(),
                    payload="",
                    last_error="expired_or_consumed",
                )
                return
            # Lease survives worker crashes; SMTP timeout is shorter than the lease.
            db.change(
                "mail_outbox",
                message_id,
                available_at=now() + 120,
                attempts=message["attempts"] + 1,
            )
        try:
            payload = json.loads(self.cipher.decrypt(message["payload"]))
            self.mailer.send_reset(payload["recipient"], payload["url"], message_id)
        except Exception:
            with self.store.transaction(write=True) as db:
                db.change(
                    "mail_outbox",
                    message_id,
                    available_at=now() + 60,
                    last_error="delivery_failed",
                )
            raise RuntimeError("Password reset email delivery failed") from None
        with self.store.transaction(write=True) as db:
            db.change(
                "mail_outbox", message_id, sent_at=now(), payload="", last_error=None
            )
