# GOLD_AI Offline Licensing

This folder supports signed, account-bound offline licenses for distribution builds.

- The bot contains only the public verification key.
- The owner's private signing key must never be committed or sent to a client.
- `tools/license_maker.py` creates `license.gold`.
- `licensing.load_and_verify_license(...)` verifies signature, MT5 account and expiry.

This is appropriate for a small trusted test distribution. Because expiry is checked against the local computer clock, it is not equivalent to server-backed licensing against a determined attacker.
