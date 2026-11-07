"""Fake secrets are assembled at runtime so this file never contains a real-looking token."""

from __future__ import annotations

import unittest

import helpers  # noqa: F401  (puts the package on sys.path)

from context_bridge import redact

A36 = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"[:36]
FAKE = {
    "github_token": "gh" + "p_" + A36,
    "aws_access_key_id": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "anthropic_api_key": "sk-" + "ant-" + "api03-" + A36,
    "openai_api_key": "sk-" + "proj-" + A36,
    "slack_token": "xo" + "xb-" + "1234567890-abcdefghij",
    "stripe_key": "sk" + "_live_" + "a1b2c3d4e5f6g7h8",
    "google_api_key": "AI" + "za" + "B" * 35,
    "npm_token": "np" + "m_" + A36,
    "jwt": "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0In0." + "abcdefghijklmnop",
}
REAL_LOOKING_EMAIL = "jane.doe" + "@" + "mailbox.ch"
PRIVATE_KEY = "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nAAAAB3NzaC1yc2E\n-----END " + "OPENSSH PRIVATE KEY-----"


def make_iban(country: str, bban: str) -> str:
    """Build a checksum-valid IBAN for tests."""
    digits = "".join(str(int(ch, 36)) for ch in bban + country + "00")
    return f"{country}{98 - int(digits) % 97:02d}{bban}"


class SecretTests(unittest.TestCase):
    def test_each_token_type_is_found_and_redacted(self) -> None:
        for kind, token in FAKE.items():
            text = f"line one\nkey here: {token} end"
            redacted, findings = redact.redact(text)
            self.assertEqual([(f.type, f.line) for f in findings], [(kind, 2)], kind)
            self.assertNotIn(token, redacted, kind)
            self.assertIn(f"[REDACTED:{kind}]", redacted, kind)

    def test_anthropic_key_is_not_reported_twice(self) -> None:
        findings = redact.find(FAKE["anthropic_api_key"])
        self.assertEqual([f.type for f in findings], ["anthropic_api_key"])

    def test_private_key_block(self) -> None:
        text = f"before\n{PRIVATE_KEY}\nafter"
        self.assertTrue(redact.contains_private_key(text))
        redacted, findings = redact.redact(text)
        self.assertEqual(findings[0].type, "private_key")
        self.assertNotIn("AAAAB3NzaC1yc2E", redacted)
        self.assertTrue(redacted.startswith("before\n") and redacted.endswith("\nafter"))

    def test_credential_assignments_and_url_credentials(self) -> None:
        redacted, findings = redact.redact('password = "hunter2hunter2"\nDB=postgres://app:s3cretpass@db:5432/x')
        self.assertEqual([f.type for f in findings], ["credential_assignment", "url_credentials"])
        self.assertNotIn("hunter2hunter2", redacted)
        self.assertNotIn("s3cretpass", redacted)
        self.assertIn("postgres://app:[REDACTED:url_credentials]@db", redacted)

    def test_placeholders_are_not_secrets(self) -> None:
        for text in ("API_KEY=your-api-key-here", "token: ${GITHUB_TOKEN}", "password = os.environ['PW']",
                     "api_key: <insert-key>", "secret = xxxxxxxxxxxx", "token: string"):  # fmt: skip
            self.assertEqual(redact.find(text, pii=False), [], text)

    def test_findings_never_contain_values(self) -> None:
        finding = redact.find(FAKE["github_token"])[0]
        self.assertNotIn(FAKE["github_token"], repr(finding.to_dict()))


class PiiTests(unittest.TestCase):
    def test_email_phone_iban_ahv(self) -> None:
        iban = make_iban("CH", "00762011623852957")
        self.assertTrue(redact.iban_checksum_ok(iban))
        text = f"Mail {REAL_LOOKING_EMAIL}\nTel +41 79 123 45 67 or 044 123 45 67\nIBAN {iban}\nAHV 756.1234.5678.97"
        types = [f.type for f in redact.find(text)]
        self.assertEqual(types, ["email", "phone", "phone", "iban", "ahv_number"])

    def test_example_domains_and_invalid_ibans_are_ignored(self) -> None:
        self.assertEqual(redact.find("dev@example.com, ops@service.test"), [])
        self.assertFalse(redact.iban_checksum_ok("CH0000762011623852957"))

    def test_pii_can_be_disabled(self) -> None:
        self.assertEqual(redact.find(REAL_LOOKING_EMAIL, pii=False), [])

    def test_versions_and_dates_are_not_phone_numbers(self) -> None:
        self.assertEqual(redact.find("version 1.2.3, released 2026-11-07, build 20261107"), [])


if __name__ == "__main__":
    unittest.main()
