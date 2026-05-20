# Five quality properties (per AC)

Every acceptance criterion must satisfy all five. Failures across them are exactly what the clarify passes detect.

## 1. Testable

The AC names explicit inputs, explicit outputs, and an explicit condition relating them. A reader can construct at least one observable input/output pair that satisfies or fails the AC.

**Pass:** `WHEN a user submits credentials that match a valid account, THE Platform SHALL return a session token in the response body.`
- Inputs: credentials match valid account
- Output: session token in response body
- Condition: explicit (token returned on match)

**Fail:** `THE Platform SHALL authenticate users.`
- No inputs named, no observable output, no testable condition.

## 2. Solution-free

The AC describes WHAT the system does, not HOW. Implementation choices (technology, schema, algorithm) belong in `design.md`, not in specs.

**Pass:** `WHEN a record is marked as deleted, THE Platform SHALL exclude it from user-facing views while retaining it for administrative access.`
- Describes behavior; mechanism (soft delete? archive table? tombstone column?) is left to design.

**Fail:** `THE Platform SHALL implement soft deletion via a deleted_at timestamp column to retain records for audit.`
- Prescribes the mechanism. Locks in a specific data model.

## 3. Unambiguous

Two independent readers would formalize the AC identically. Pass 1 of clarify catches violations by paraphrasing 3 times and detecting semantic divergence.

**Pass:** `WHEN a Property Owner confirms deletion, THE Platform SHALL mark the Property record as deleted such that it is no longer visible in any user-facing view.`
- Single interpretation: mark as deleted; hide from user views; retain for admin.

**Fail:** `WHEN a Property Owner confirms deletion, THE Platform SHALL remove the Property record.`
- "Remove" could mean hard-delete OR soft-delete + hide. Two interpretations.

## 4. Consistent

The AC does not contradict any other AC in the spec corpus. Pass 2 of clarify checks pairwise.

**Pass:**
- R1: `WHEN a Property Owner confirms deletion, THE Platform SHALL mark the Property record as deleted such that it is no longer visible in any user-facing view.`
- R2: `WHILE a Property record is marked as deleted, THE Platform SHALL retain the record for admin/audit access.`
- These reinforce each other (delete = hide-but-retain).

**Fail:**
- R1: `WHEN a Property Owner confirms deletion, THE Platform SHALL remove the Property record.`
- R2: `THE Platform SHALL implement soft deletion to retain records.`
- R1's "remove" (hard delete) contradicts R2's "retain" (soft delete).

## 5. Complete

The AC corpus covers the behavior space. For every event/state combination the system can encounter, at least one AC defines behavior. Pass 3 of clarify checks priority-bounded.

**Pass:** the spec includes:
- WHEN nominal delete confirms (R1)
- IF the property doesn't exist (R-error)
- IF the property has active leases (R-error)
- IF the user is not the owner (R-error)
- WHEN the user cancels the prompt (R2)

**Fail:** the spec only includes R1 above. "What happens if the property has active leases?" is unanswered.

---

# Canonical AC ID format

Every Requirement gets a canonical AC ID computed from its parent capability and its name. This ID is the contract used by the verify gate's AC↔test mapping check.

```
<capability>.<requirement-slug>
```

Where `<requirement-slug>` is the requirement name with:
1. Lowercased
2. Non-alnum chars (anything not `[a-z0-9]`) replaced with `-`
3. Repeated `-` collapsed to one
4. Leading and trailing `-` stripped

## Examples

| Capability | Requirement name | Slug | Canonical AC ID |
|---|---|---|---|
| `user-export` | `User can export data` | `user-can-export-data` | `user-export.user-can-export-data` |
| `order-system` | `Refund handling for canceled orders` | `refund-handling-for-canceled-orders` | `order-system.refund-handling-for-canceled-orders` |
| `auth` | `MFA enrollment (TOTP)` | `mfa-enrollment-totp` | `auth.mfa-enrollment-totp` |
| `payment` | `Payment SHALL retry on 5xx` | `payment-shall-retry-on-5xx` | `payment.payment-shall-retry-on-5xx` |

## How tests cite ACs

Tests cite the canonical AC ID literally in any of:
- A comment: `# AC: user-export.user-can-export-data`
- A docstring: `"""Implements user-export.user-can-export-data"""`
- A test name: `def test_user_export_user_can_export_data():`
- A string literal: `AC = "user-export.user-can-export-data"`

The verify gate greps for the literal ID; no parsing of structure is required.

## Test exemption marker

Tests that don't correspond to any AC (fixture builders, helpers, CI smoke tests) MAY include `# spec-exempt: <reason>` in the first 10 lines. The reverse-check honors the exemption.
