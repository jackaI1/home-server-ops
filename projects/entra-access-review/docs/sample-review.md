# Access review

Policy: Small tenant standing-access policy. Review time (UTC): 2026-11-05T00:00:00.0000000+00:00.
Accounts: 6 exported, 5 enabled and reviewed, 1 disabled and excluded. Findings: 10 total, 8 open, 2 excepted.
Missing evidence is a review finding. This report does not certify compliance or change directory access. MFA registration does not prove MFA is enforced.

## Input fingerprints (SHA-256)

- users.json: EC6E64CE9A8D2C7BADA8C719DBE10568F27514E1B807B1D4748EB3DDDE8BD46E
- groups.json: D238CC9BF344F6FF6AB01A40131CDBBE41CE6B346434B7F39F7D773B97159C00
- role-definitions.json: 4C88F77C69D7D681C62AB0D8D2863F586D7FB544036150AB46F55AAF2696AB46
- role-assignments.json: B328DF07F4B8D83DFB73C291CBAC7CA79C1574EE36550651BA7B453D1B360656
- authentication-registration.json: 3751119490C8EAF94C8C69EAFAC1FA4376D328D431E3AB728DA81185AA0AFA33
- Policy: 110BA05E7221E1FD2A7A06D0BE3323D0606E7850A39C45C493D949DA0BBBFCC1
- Exceptions: 2EBA50C213A9E50278B811DC996F0EA9EF29EE976D0F0F8C5793D2C3A082FDEC

## Findings

| Account (ID) | Rule | Severity | Status | Evidence | Next step | Exception |
| --- | --- | --- | --- | --- | --- | --- |
| demo1@example.invalid (00000000-0000-0000-0000-000000000001) | NoMfa | High | Open | authentication-registration.json: isMfaRegistered=false; methodsRegistered=email. | Register a strong second sign-in method and check the sign-in enforcement policy. |  |
| demo1@example.invalid (00000000-0000-0000-0000-000000000001) | StaleAccount | Medium | Open | users.json: lastSuccessfulSignInDateTime=2026-06-01T00:00:00.0000000+00:00; inactivity=157 days; threshold=90 days (strictly older). | Confirm the account is still needed; disable it through the normal approval process if unused. |  |
| demo1@example.invalid (00000000-0000-0000-0000-000000000001) | UnapprovedRole | High | Open | role-assignments.json: assignment=synthetic-assignment-1; role=62e90394-69f5-4237-9190-012177145e10 (Global Administrator); scope=/; path=direct user assignment; no matching identity-and-scope approval in policy. | Confirm the role and scope are needed; remove excess access or record a time-limited exception. | owner=Demo access owner; reason=Migration approval has expired.; expires=2026-11-01T00:00:00.0000000+00:00 |
| demo2@example.invalid (00000000-0000-0000-0000-000000000002) | TooManyRoles | High | Open | role-assignments.json: distinct effective roles=3; limit=2; roleDefinitionIds=62e90394-69f5-4237-9190-012177145e10,729827e3-9c14-49f7-bb1b-9608f156bbb8,fe930be7-5e62-47db-91af-98c3a49a38b1; assignmentIds=synthetic-assignment-2,synthetic-assignment-3,synthetic-assignment-4. | Review the combined responsibilities and reduce standing privileges. |  |
| demo2@example.invalid (00000000-0000-0000-0000-000000000002) | UnapprovedRole | High | Open | role-assignments.json: assignment=synthetic-assignment-3; role=62e90394-69f5-4237-9190-012177145e10 (Global Administrator); scope=/; path=group=00000000-0000-0000-0000-000000000066 (Old admin group) -&gt; user=00000000-0000-0000-0000-000000000002; no matching identity-and-scope approval in policy. | Confirm the role and scope are needed; remove excess access or record a time-limited exception. |  |
| demo2@example.invalid (00000000-0000-0000-0000-000000000002) | UnapprovedRole | High | Open | role-assignments.json: assignment=synthetic-assignment-4; role=fe930be7-5e62-47db-91af-98c3a49a38b1 (User Administrator); scope=/; path=direct user assignment; no matching identity-and-scope approval in policy. | Confirm the role and scope are needed; remove excess access or record a time-limited exception. |  |
| demo4@example.invalid (00000000-0000-0000-0000-000000000004) | MissingMfaEvidence | Review | Open | authentication-registration.json: no registration record for this user. | Export the registration record; do not assume missing data means no MFA. |  |
| demo4@example.invalid (00000000-0000-0000-0000-000000000004) | MissingSignInEvidence | Review | Open | users.json: signInActivity.lastSuccessfulSignInDateTime=null; this does not prove the account never signed in. | Check sign-in coverage before deciding whether to disable this account. |  |
| demo5@example.invalid (00000000-0000-0000-0000-000000000005) | NoMfa | High | Excepted | authentication-registration.json: isMfaRegistered=false; methodsRegistered=email. | Register a strong second sign-in method and check the sign-in enforcement policy. | owner=Demo security owner; reason=Emergency sign-in account; manual check scheduled.; expires=2026-12-01T00:00:00.0000000+00:00 |
| demo5@example.invalid (00000000-0000-0000-0000-000000000005) | StaleAccount | Medium | Excepted | users.json: lastSuccessfulSignInDateTime=2026-05-01T00:00:00.0000000+00:00; inactivity=188 days; threshold=90 days (strictly older). | Confirm the account is still needed; disable it through the normal approval process if unused. | owner=Demo security owner; reason=Emergency sign-in account; manual check scheduled.; expires=2026-12-01T00:00:00.0000000+00:00 |

## Exception register

| User ID | Rule | Role ID | Status | Owner | Reason | Expires (UTC) |
| --- | --- | --- | --- | --- | --- | --- |
| 00000000-0000-0000-0000-000000000001 | UnapprovedRole | 62e90394-69f5-4237-9190-012177145e10 | Expired | Demo access owner | Migration approval has expired. | 2026-11-01T00:00:00.0000000+00:00 |
| 00000000-0000-0000-0000-000000000005 | NoMfa |  | Applied | Demo security owner | Emergency sign-in account; manual check scheduled. | 2026-12-01T00:00:00.0000000+00:00 |
| 00000000-0000-0000-0000-000000000005 | StaleAccount |  | Applied | Demo security owner | Emergency sign-in account; manual check scheduled. | 2026-12-01T00:00:00.0000000+00:00 |
| 00000000-0000-0000-0000-000000000005 | TooManyRoles |  | Unmatched | Demo security owner | Emergency sign-in account; manual check scheduled. | 2026-12-01T00:00:00.0000000+00:00 |
