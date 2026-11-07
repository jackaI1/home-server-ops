# phish-header-analyzer

I built a phishing email-header analyzer to learn how the underlying idea works. This is a learning project.

## Try it

I use Python 3.11 or newer. These commands run a completely synthetic example:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[dev]'
phish-header samples/phishing/credential-lure.eml \
  --trusted-authserv-id mx.receiver.test \
  --brand 'North Bank=bank.test' -o investigation.md
```

Open `investigation.md` in a text editor. The example scores **100/100**, with evidence for failed identity checks, different reply and return addresses, and a link whose label hides its destination. The domains and addresses in the examples are reserved for testing.

For a real message, I export the original email from my mail client and run:

```sh
phish-header /path/to/message.eml
phish-header /path/to/message.eml --format json -o investigation.json
```

Everything runs locally. The tool does not open links, contact mail servers, or send email anywhere. Markdown links are made unclickable, for example `hxxps://bank[.]test`. JSON keeps original values for further analysis. Reports contain message evidence, so I keep real email and reports outside this public repository. Existing output files are never overwritten.

## What I look at

- **Delivery route:** `Received` fields are the relay servers' recorded handoffs. I read them from oldest to newest, compare time zones correctly, and flag backwards timestamps or gaps over an hour.
- **Reported identity checks:** SPF checks whether a server may send for a domain; DKIM checks a domain's signature on a message; DMARC connects those checks to the visible sender's domain. I read these results from `Authentication-Results`, including multiple DKIM signatures.
- **Sender differences:** I compare `From`, `Return-Path` (where delivery errors go), and `Reply-To`. I also check for an email address hidden in a display name. `--brand 'North Bank=bank.test'` adds my own expectation for an exact display name.
- **Links:** I inspect header links and decoded plain-text or HTML content for misleading labels, an address before `@`, numeric hosts, internationalized domains, and unencrypted HTTP.

I do not automatically trust authentication headers. Without `--trusted-authserv-id`, their claims are visible but add no points. I only supply that option when I know which receiving system produced the export and that it strips forged claims bearing its own name. An attacker can copy a receiver's name, so the option alone proves nothing.

## Reading a note

I keep the original file's SHA-256 fingerprint, a reproducible identifier, in every report. Header evidence has physical line numbers. Decoded body evidence names its mail part instead of inventing line numbers. Missing fields, broken dates, ambiguous senders, parser problems, and content limits appear under uncertainties.

A legitimate newsletter can have a separate return address, and forwarding can break SPF. I included both examples. I use the note to guide follow-up through known contacts and receiver logs, not to approve or block a message automatically. Attachments and nested emails are not analyzed; scripts and redirects are not followed.

[Method, scoring rules, limits, and standards](docs/method.md) explain the implementation. [The sample guide](samples/README.md) explains the nine synthetic messages and their hand-labelled expectations.

## Development

```sh
pytest -q
ruff check .
ruff format --check .
```

## Tests and limits

There are 5 test source files in this copy. No test pass count is claimed here: I have not re-run the project suite as part of this move. This is a source snapshot, and running it on a new machine may need environment-specific setup.



The relocated workflow did not complete successfully within the migration batch. Local test sources remain available.

I did not retain a project-specific GitHub Actions workflow. The test sources remain in this folder for local use.
