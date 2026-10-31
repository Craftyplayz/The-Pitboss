# The Pitboss

## Versions and patch notes

**Before every commit, ask the user whether it should get a version and a [CHANGELOG.md](CHANGELOG.md) entry.** Show the bullet you'd write so they can say yes, no or reword it. Changelog entries are posted in the Discord update log, so the user decides what members see. If they say no, commit without a version bump, changelog entry or tag.

Never ask for commits that only touch `mockups/` or the admin panel: those never get a version or changelog entry.

**Unreleased notes:** while the user is still working on something, keep its notes under a `### Unreleased` heading at the top of CHANGELOG.md, above the first `## ` version. The bot only reads `## ` headings, so nothing there is posted. When the user approves, turn it into `## <version>` (or fold it into the next version) and remove the heading.

Versions look like `1.A.B.C`. Bump exactly one part per versioned commit and reset the parts after it to 0. Drop a trailing `.0` (write `1.5.0`, not `1.5.0.0`):

| Change | Bump | Example |
|---|---|---|
| Major change (new big feature, reworked part of the bot or site) | `A` | 1.4.1 → 1.5.0 |
| Minor addition (new option, small feature, behaviour fix) | `B` | 1.4.1 → 1.4.2 |
| Super small update (typo, wording, colour, comment, docs) | `C` | 1.4.1 → 1.4.1.1 |

- **Never go to 2.0 without asking the user first.**
- Add the new section at the top of CHANGELOG.md: `## <version>` and one short bullet per change, written for Discord members. The bot posts these bullets in the bot updates channel after it restarts (cogs/updates.py), so keep them short and plain.
- In the same commit: write the entry. After committing, tag it: `git tag -a v<version> -m v<version>`, then push with `git push origin main --tags`.
- The version is read from the top `## ` heading of CHANGELOG.md. There is no other version file to keep in sync.
