# Investigation method

The analyzer makes observations about a saved message. It cannot prove who sent it or whether its content is safe. Results are deterministic: the same bytes and configuration produce the same JSON, including the SHA-256 fingerprint. There is no current-time comparison and no network dependency during analysis.

## Evidence and trace

`parser.py` retains the raw top-level header text and physical start/end lines while Python's email package decodes MIME, the format for mail parts and encodings. Header unfolding preserves a separate source copy. Received fields are prepended during transport, so `received.py` reverses their physical order and compares adjacent parseable timestamps in UTC. A missing time zone stays unknown. The analyzer never sorts timestamps to make the route look consistent and never compares across a hop with an unreadable date.

The `from` and `by` host names are extracted as reported text, without DNS or IP ownership verification. The route before the receiving organization's boundary can be forged. A negative gap can be clock skew; a long gap can be queueing. No route continuity or geographic claim is inferred.

## Authentication trust

`authentication.py` uses the `authres` parser for Authentication-Results syntax, including comments, quoted strings and repeated methods. A receiver is identified by its `authserv-id`, the name before the first semicolon. Up to 100 parsed results stay in the report. If that limit is exceeded, partial analysis is disclosed and authentication failure points are suppressed because a later pass may be missing. Only exact configured IDs, ignoring case and a terminal dot, can contribute failure points. Similar-looking suffixes do not match.

The investigator must establish the export's origin and that the receiving system removes untrusted incoming results with its own ID. This program cannot establish that boundary from a file. Even a matching ID can be forged. An untrusted pass never cancels a trusted failure. A trusted DKIM pass suppresses DKIM failure points because messages can carry several signatures. Conflicting trusted SPF or DMARC statuses are disclosed as uncertainty and receive no failure points. Errors and missing methods add uncertainty, not a verdict.

These are recorded claims, not fresh SPF evaluation, DKIM cryptographic verification, DNS policy discovery or independent DMARC alignment. A reported DMARC pass may coexist with an SPF failure when an aligned DKIM signature survives forwarding.

## Identities and links

`identity.py` requires one valid mailbox per sender field. Multiple fields or mailboxes remain ambiguous; it does not silently select the first From. A null Return-Path (`<>`) is treated as a normal bounce possibility. Domains are case-normalized, stripped of a terminal dot and converted to ASCII IDNA form. Comparisons are exact. The analyzer does not guess organizational domains or equate subdomains, and does not call these comparisons DMARC alignment.

Display-name checks catch an apparent email address whose domain differs from the actual mailbox. Arbitrary brand names require an investigator-provided exact name/domain mapping; there is no built-in brand reputation list. Name matching normalizes Unicode and case. A domain controlled by an attacker can pass all authentication checks while impersonating someone in the display name.

`urls.py` decodes base64 and quoted-printable text, parses HTML anchors (including nested link text and entities), and extracts HTTP/HTTPS links from text and headers. It also inspects HTML image sources and form actions. Observations retain original URLs; only Markdown output defangs them and escapes message-controlled formatting. Body evidence identifies decoded MIME parts with a unique depth-first traversal number, not physical lines. Exact repeated URL/text/source combinations are deduplicated. HTTPS and an absence of structural indicators do not establish safety.

## Score

Each rule contributes its listed weight once per message, even if it has repeated evidence. Contributions are added and capped at 100. Nothing subtracts points. The values are transparent heuristics, with no calibrated probability or claim of measured detection accuracy.

| Rule | Points |
| --- | ---: |
| Received timestamp goes backwards | 10 |
| Received gap over 3,600 seconds | 5 |
| Trusted SPF fail / softfail | 10 / 5 |
| Trusted DKIM fail without any trusted DKIM pass | 15 |
| Trusted DMARC fail | 25 |
| Duplicate sender identity field | 10 |
| Return-Path domain differs from From | 10 |
| Reply-To domain differs from From | 15 |
| Displayed email domain differs from mailbox | 20 |
| Configured display name uses unexpected domain | 20 |
| URL has user information before `@` | 15 |
| URL uses an IP host | 10 |
| URL uses an internationalized domain | 5 |
| URL uses HTTP | 5 |
| Link text suggests a different destination host | 20 |
| URL is malformed | 5 |

Priority is routine below 20, elevated from 20 to 49, and high from 50 to 100. Routine includes incomplete messages. Every note carries uncertainty warnings and next steps. Benign samples deliberately trigger some rules, demonstrating why the score is a review aid.

## Boundaries and output

Inputs over 10 MiB, more than 1,000 headers, or a header over 64 KiB are rejected. MIME inspection stops after 200 parts or depth 30, text is limited to 1 MiB per part, authentication observations to 100, and URL observations to 200; partial analysis is disclosed. Attachments, named MIME parts, nested message attachments and non-text parts are skipped with uncertainty. Deeply malformed mail can exceed Python's parser nesting limit and is rejected by the CLI. A file within these limits can still be adversarial; use an isolated environment for hostile inputs.

This is a focused parser, not a complete mail gateway or browser: CSS links, obfuscated strings, QR codes, JavaScript, redirects, attachment content, reputation, lookalike brand spelling and full Unicode confusable detection are outside its scope. Unknown charsets use replacement decoding with a warning. Original mail and reports can contain sensitive information. No private mail is bundled, and the tool never uploads inputs. Run it in an empty output directory when saving real reports.

The command exits 0 after producing a note, including a high-score or incomplete note. Usage errors, limits, unreadable files and attempts to overwrite an output file exit 2. JSON schema version 1 contains `score`, `priority`, `findings`, `uncertainties`, `received`, `authentication` and `urls`, plus source and fingerprint fields. JSON intentionally retains original evidence and live URL strings; treat it as untrusted data. Evidence excerpts are limited to 4,096 characters in JSON, with a `truncated` flag. Markdown further limits each excerpt to 1,000 characters and labels truncation; the original fingerprint and header line range identify where to inspect the full evidence.

## Standards I used

- [RFC 5321, section 4.4](https://www.rfc-editor.org/rfc/rfc5321.html#section-4.4): mail relays prepend Received fields.
- [RFC 8601, especially section 7](https://www.rfc-editor.org/rfc/rfc8601.html#section-7): Authentication-Results syntax and the trust boundary.
- [RFC 9989](https://www.rfc-editor.org/rfc/rfc9989.html): DMARC and alignment of authenticated domains with the visible sender. This tool reads reported results rather than implementing the protocol.
- [RFC 7960](https://www.rfc-editor.org/rfc/rfc7960.html): why forwarding and mailing lists complicate authentication.
