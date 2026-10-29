# The Pitboss

## Versions and patch notes

Every commit gets a new version and an entry in [CHANGELOG.md](CHANGELOG.md), including docs, tests and typo fixes. The only exceptions: commits that only touch `mockups/` or the admin panel get no version bump and no changelog entry, so they never show in the Discord update log.

Versions look like `1.A.B.C`. Bump exactly one part per commit and reset the parts after it to 0. Drop a trailing `.0` (write `1.5.0`, not `1.5.0.0`):

| Change | Bump | Example |
|---|---|---|
| Major change (new big feature, reworked part of the bot or site) | `A` | 1.4.1 → 1.5.0 |
| Minor addition (new option, small feature, behaviour fix) | `B` | 1.4.1 → 1.4.2 |
| Super small update (typo, wording, colour, comment, docs) | `C` | 1.4.1 → 1.4.1.1 |

- **Never go to 2.0 without asking the user first.**
- Add the new section at the top of CHANGELOG.md: `## <version>` and one short bullet per change, written for Discord members. The bot posts these bullets in the bot updates channel after it restarts (cogs/updates.py), so keep them short and plain.
- In the same commit: write the entry. After committing, tag it: `git tag -a v<version> -m v<version>`, then push with `git push origin main --tags`.
- The version is read from the top `## ` heading of CHANGELOG.md. There is no other version file to keep in sync.
