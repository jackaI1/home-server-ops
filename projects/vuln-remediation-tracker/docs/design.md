# Tracking decisions

An asset is a canonical IP address. A finding is one asset and one CVE (a public vulnerability identifier). Scanner output must contain an explicit CVE; service names alone never invent one.

Each scanner and named scope keeps its own observations. A finding stays active while any observation remains active. An import normally adds evidence only. To close observations, the operator must declare complete coverage for specific assets, using the same scanner and scope as before. Those assets must appear as live hosts in a successful report. The declaration means all relevant ports and vulnerability checks were rerun. The tracker cannot prove that declaration from XML alone.

A requested fix stays pending validation until a qualifying rescan removes the CVE. A positive rescan records recurrence, and a later positive result after closure reopens it. Every import and transition stays in SQLite. Deadlines start at first observation, retain their original value through ordinary rescans, and restart when a fixed finding reopens. NVD scores set 7/14/30/90-day critical/high/medium/low targets; an unknown score gets a visible unknown label and a 30-day target.

NVD enrichment reads a committed subset of public NVD API 2.0 responses. A SHA-256 manifest pins its exact bytes. It is a reproducible historical snapshot, not a current vulnerability feed. Unknown CVEs remain trackable, and no network request occurs during ingestion.
