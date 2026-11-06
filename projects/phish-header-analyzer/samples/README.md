# Synthetic mail examples

I wrote these messages for this project. None came from an inbox. Addresses use reserved `.test` domains and documentation IP ranges. The messages contain no working credentials, real recipients or live lure destinations.

The labels describe the scenario I constructed, not ground truth that a header analyzer could independently establish. In particular, route anomalies are ambiguous and incomplete exports are not automatically benign.

| File | Scenario | Expected score |
| --- | --- | ---: |
| `benign/direct.eml` | Matching sender details, reported checks pass | 0 |
| `benign/bulk-mail.eml` | Newsletter uses a separate return domain | 10 |
| `benign/forwarded.eml` | Forwarding breaks SPF, DKIM and DMARC report pass | 20 |
| `benign/bounce.eml` | Delivery notice uses a null return path | 0 |
| `benign/incomplete-export.eml` | Missing route and unreadable authentication | 0, with uncertainty |
| `phishing/credential-lure.eml` | Failed checks, misleading sender and hidden IP link | 100 |
| `phishing/display-spoof.eml` | Authentication passes for a misleading display name | 35 |
| `phishing/forged-auth.eml` | A lookalike receiver name claims authentication passes | 45 |
| `phishing/route-anomaly.eml` | Backwards timestamp and over-one-hour gap | 15 |

These scores assume `--trusted-authserv-id mx.receiver.test --brand 'North Bank=bank.test'`. The trusted ID is appropriate for these invented fixtures only. A real export requires independent knowledge of its receiving system.

`cases.json` records the expected rule codes and scores by hand. The corpus test analyzes every file, compares those expectations, and checks physical evidence lines against the original bytes. Other tests exercise encoded content, multiple signatures, malformed fields and CLI errors.
