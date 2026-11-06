# Export input guide

I can run the sample entirely offline in about two minutes: install PowerShell 7.5+, clone this repository, then run `pwsh -NoProfile -File scripts/Invoke-Review.ps1 -AsOf 2026-11-05T00:00:00Z`. No tenant, token, service account, or paid subscription is needed for the synthetic example.

For an authorized real review I save Graph v1.0 responses in a private folder, keeping the `{"value": [...]}` collection envelope. The tool reads these local files and does not authenticate to Microsoft. It does not include a live collector. The [sample folder](../samples/graph) shows all required fields.

| File | Graph source and required record fields |
| --- | --- |
| `users.json` | `/users?$select=id,displayName,userPrincipalName,accountEnabled,createdDateTime,signInActivity`; `signInActivity` must include `lastSuccessfulSignInDateTime` as a timezone-qualified timestamp or explicit null. A null `signInActivity` object is also accepted as missing evidence. |
| `authentication-registration.json` | `/reports/authenticationMethods/userRegistrationDetails`; keep `id`, boolean `isMfaRegistered`, and array `methodsRegistered`. The `id` is the user ID. A missing record creates a missing-evidence finding. |
| `groups.json` | `/groups?$filter=isAssignableToRole eq true&$select=id,displayName,isAssignableToRole`; add a `members` array to each group from its complete `/groups/{id}/members` response. Each member needs `id` and `@odata.type` equal to `#microsoft.graph.user`. This is the same shape as an expanded `members` relationship. |
| `role-definitions.json` | `/roleManagement/directory/roleDefinitions`; keep `id` and `displayName`, including custom definitions used by assignments or policy. |
| `role-assignments.json` | `/roleManagement/directory/roleAssignments`; keep `id`, `principalId`, `roleDefinitionId`, `directoryScopeId`, and optional null `appScopeId`. |

For every collection, follow all `@odata.nextLink` URLs, combine all `value` arrays, and remove the page link only when every page has been consumed. Do the same for group members and any `members@odata.nextLink` on expanded groups. The module rejects remaining links. A group with no members must have `"members": []`; an empty collection must have `"value": []`. Extra Graph properties such as `@odata.context` are allowed. IDs must be nonempty strings and unique within each collection; the synthetic assignment IDs are opaque strings, as assignment identifiers need not be UUIDs.

All user references in registration, memberships, policy and exceptions must resolve to exported users. Role assignments must resolve to an exported user or role-assignable group and role definition. Duplicate memberships, nested groups, non-user members, omitted sign-in fields, bad types and invalid dates are errors. Timestamps require ISO 8601 with `Z` or an explicit offset; sign-in dates cannot be before account creation or after the review time. Null successful activity is unknown, even if an attempted sign-in date is available.

The Graph APIs have different permission and licensing requirements. For an actual tenant, an administrator should check the current requirements and confirm complete visibility before exporting; sign-in activity and registration reports may need Entra licensing and additional reporting permissions. The sample does not claim live tenant use. I avoid saving access tokens in the repository and keep real data outside version control.

The field choices and distinctions come from Microsoft's documentation:

- [User sign-in activity](https://learn.microsoft.com/en-us/graph/api/resources/signinactivity?view=graph-rest-1.0): successful access differs from an attempted sign-in, and historical successful dates are not fully backfilled.
- [Authentication registration details](https://learn.microsoft.com/en-us/graph/api/resources/userregistrationdetails?view=graph-rest-1.0): registered and policy-allowed MFA capability are separate fields.
- [Directory role assignments](https://learn.microsoft.com/en-us/graph/api/resources/unifiedroleassignment?view=graph-rest-1.0): each assignment links a principal, role definition and scope.
- [Group members](https://learn.microsoft.com/en-us/graph/api/group-list-members?view=graph-rest-1.0): membership is direct, and incomplete permissions can reduce what is returned.
