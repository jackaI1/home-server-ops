# Review policy

I use a small, explicit standing-access policy rather than claiming every administrator is over-privileged. A role is a set of permissions; its directory scope is the set of resources those permissions cover. The sample policy is an example to edit, not a universal security standard.

## Evaluation

Only `accountEnabled=true` users receive findings. Disabled accounts are counted but excluded from the checks. All records, including disabled accounts, must still pass validation. Empty collections are allowed.

| Rule ID | Evaluation | Severity |
| --- | --- | --- |
| `StaleAccount` | `lastSuccessfulSignInDateTime < AsOf - staleAfterDays`; exactly 90 days is not stale with the sample threshold. I compare the full timestamp, not rounded days. | Medium |
| `NoMfa` | A registration record explicitly has `isMfaRegistered=false`. The registered method names remain in the evidence. | High |
| `UnapprovedRole` | No policy entry approves this user's identity AND this assignment's exact directory scope for the role definition ID. | High |
| `TooManyRoles` | Count of distinct effective role definition IDs exceeds `maxRolesPerUser`. Multiple grants of the same role count once. | High |
| `MissingSignInEvidence` | The last successful sign-in field or the entire `signInActivity` object is explicitly null. Null does not prove the person never signed in; Graph does not backfill all historical activity. | Review |
| `MissingMfaEvidence` | No registration record was exported for this user. Missing data does not prove no MFA. | Review |

`staleAfterDays` and `maxRolesPerUser` must be positive integers. Each `roleRules` entry specifies `roleDefinitionId`, `allowedUserIds`, `allowedGroupIds`, and `allowedDirectoryScopes`, with arrays even when empty. Role names are displayed but all matching uses IDs. A missing rule denies that role by default. An approved identity is either an explicit user ID or a direct member of an approved group. Identity approval applies regardless of which assignment granted that same role; scope must still match. There are no wildcard approvals. Unknown policy references and duplicate role rules are errors.

In the sample, only the emergency account may hold Global Administrator at `/` (the whole directory). The Support team may hold Helpdesk Administrator at `/`. User Administrator has no approval. No person may have more than two distinct roles. A support operator with a Helpdesk role, an unapproved group-based Global Administrator role, and an unapproved User Administrator role therefore gets two `UnapprovedRole` findings and a `TooManyRoles` finding.

## Exceptions

The input is a JSON object with an `exceptions` array; `{"exceptions": []}` means none. Each exception needs:

- `userId` and `ruleId`: the exact person and check to except.
- `roleDefinitionId`: required only for `UnapprovedRole`. That exception covers all assignments and scopes of that role for that user; review its breadth before approving it.
- `owner` and `reason`: nonempty accountability fields, not verified identities or an approval workflow.
- `expiresOn`: a full ISO 8601 timestamp with timezone. It must be strictly after the review time to apply.

I reject duplicate exception keys (user, rule, role). Only the four policy violation rules can be excepted; missing-evidence rules cannot. I retain excepted findings with their evidence and exception details. `exceptions.csv` and the markdown register include every supplied exception as `Applied`, `Expired`, or `Unmatched`. An expired exception is expired even if it matches no finding. An active approval that matches no finding is `Unmatched`. The report includes expired approval details on the matching open finding so they are easy to revisit.

## Limits and handling

The output is a review queue, not a compliance certificate or a recommendation to delete accounts automatically. MFA registration differs from MFA enforcement, capability under authentication policy, and phishing resistance. This tool does not inspect Conditional Access policies or verify exception approval.

Only exported active directory role assignments to users and role-assignable groups are supported. Eligible PIM roles, historic activations, service principals, nested/non-user group members, and app-scoped assignments are outside this version. Unsupported assignment principals, unknown role references, and incomplete membership data cause an error. Export only relevant role-assignable groups with their direct user members. Do not silently remove unsupported assignments and describe that reduced export as a full tenant review.

The export must be a complete, authorized snapshot of the intended review population. The tool can detect unconsumed page links and broken references, but cannot detect rows someone omitted or a permission-filtered export that lacks a page link. Collect the files close together, check export permissions and collection counts, record the collection time separately, and choose an appropriate review date. Input hashes identify file bytes; they do not prove that the source was trustworthy. Do not edit input files during a run.

All inputs are validated before output creation. A failed review exits nonzero and writes no new reports; old files in a reused output directory are not removed. Use a fresh output directory and only trust it if the command succeeds. Output writes are not a multi-file transaction; discard a directory after a disk or permission error. CSV cells that could start formulas are prefixed with an apostrophe, and markdown escapes HTML, pipes and line breaks. Reports can contain private account details, so store them locally with appropriate access controls.
