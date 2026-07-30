# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

## Verification state (repo extension)

The five roles above are **triage/routing** labels — they answer "who picks this up, and is it ready?" They are *pre-implementation*: the state machine ends at `ready-for-human` / `wontfix`, and the framework's only notion of verification is confirming a bug claim reproduces before it is turned into a brief.

This repo adds one **post-implementation** label on a separate axis — it answers "is the merged work actually confirmed working?":

| Label | Meaning |
| ----- | ------- |
| `human-verification-required` | Code is complete and merged, but a human must verify it on real hardware / a live session before the issue is closed. No code is expected. |

This is deliberately *not* part of the canonical triage vocabulary — it is a lifecycle state that sits at the top of the [verification ladder](../ONBOARDING.md#verification-ladder), above everything the automated steps can reach (real `uinput` injection, focus-watching on a live desktop, etc.).

Convention:
- Apply `human-verification-required` when a change is merged but its correctness can only be confirmed by a human on real hardware.
- **Keep the issue open** while the label is present — merging is not closing. Remove the label and close only after the human check passes.
