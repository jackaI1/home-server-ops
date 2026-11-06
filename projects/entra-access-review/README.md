# entra-access-review

I built a tool for checking account access to learn how the underlying idea works. This is a learning project.

## Using another export

I keep the five JSON files described in [the input guide](docs/input-format.md) in a local folder. JSON is a text format for saving structured records; these files preserve Microsoft Graph's field names and collection format. Graph is Microsoft's API for reading directory data. I edit the [policy](samples/policy.json) and [exceptions](samples/exceptions.json) for those accounts, then run:

```sh
pwsh -NoProfile -File scripts/Invoke-Review.ps1 \
  -ExportPath ./private-exports \
  -PolicyPath ./private-exports/policy.json \
  -ExceptionsPath ./private-exports/exceptions.json \
  -OutputPath ./output \
  -AsOf 2026-11-05T00:00:00Z
```

This multiline example uses a shell such as bash or zsh. In PowerShell I put the command on one line or use a backtick for continuation. The default date, if I omit `-AsOf`, is the current UTC time. I use a new output folder for each real review so I can retain earlier reports. If validation fails, I discard any previous report in that folder and fix the input first.

The tool runs offline and makes no account changes. I use the results to decide what to investigate, then follow a separate approval process for any access changes. Registration does not prove MFA is enforced. This version covers exported active user assignments, including direct members of role-assignable groups; it does not review service principals or inactive, eligible roles from Privileged Identity Management. The [policy notes](docs/policy.md) explain these limits and the exact matching rules.

All committed accounts use `example.invalid` and synthetic identifiers. I keep real exports and review output out of Git; the ignored `private-exports/` and `output/` folders are provided for that purpose.

## How I put it together

The module in `src/EntraAccessReview/` validates all input before creating reports. It rejects broken records, unresolved references, duplicate IDs, and unfinished Graph pages rather than silently dropping them. It builds indexes of group membership and effective role assignments, then applies the policy to each enabled account. Each report includes input hashes, which identify the exact files I reviewed, and a fixed UTC review time. Identical inputs and dates produce identical reports.

I can import the module directly in PowerShell:

```powershell
Import-Module ./src/EntraAccessReview/EntraAccessReview.psd1
Invoke-EntraAccessReview -ExportPath ./samples/graph -PolicyPath ./samples/policy.json -ExceptionsPath ./samples/exceptions.json -OutputPath ./output -AsOf '2026-11-05T00:00:00Z'
```

## Tests and limits

There are 0 test source files in this copy. No test pass count is claimed here: I have not re-run the project suite as part of this move. This is a source snapshot, and running it on a new machine may need environment-specific setup.


Project checks run from this directory through the path-filtered hub workflows: `entra-access-review-test.yml`.
