# Trophies plan

Status: plan only, nothing built yet. All numbers are first guesses. Check them against real linked-member data before building (see "Calibration").

## How trophies work

- **Career trophies** have 5 tiers: Bronze, Silver, Gold, Platinum, Diamond. Each tier has its own name. The first tiers come within a few matches; the top tier takes roughly 300 to 500+ matches.
- **Single-match trophies** are earned in one match. They're hard but reachable for a normal player.
- A Player keeps every tier they reach. Only the highest tier of a family shows on the profile.
- **Rarity** = % of Linked Members who hold that trophy tier. "Rarest" = lowest %.

### Where the numbers come from

| Source | What it covers | Stats |
|---|---|---|
| Match history (already fetched) | Every match the Player ever played | kills, deaths, assists, souls, wins, losses, streaks, matches, time played, heroes, souls/min, match length, Untouchable, Feeder |
| Match metadata (fetched by Match Recaps) | Only matches since the Link, plus the 30-day Backfill | healing, damage dealt, damage taken, item purchases, multi-kills |

Metadata stats get added to per-player totals in the database each time a Recap runs.

## Display

- **`/profile`**: a small "Trophies — 37 / 140" section showing the 3 newest and 3 rarest trophies. An **All trophies** button opens the full list.
- **`/trophies [member]`**: the full list, grouped by category, with tier, date earned and rarity. Trophies you don't have yet show as locked, with progress (e.g. "Reaper — 1,204 / 1,500 kills").

---

## Career trophies (count up every match)

### Combat

| Family | Bronze | Silver | Gold | Platinum | Diamond |
|---|---|---|---|---|---|
| **Kills** | First Blood — 10 | Headhunter — 100 | Executioner — 500 | Reaper — 1,500 | Death Incarnate — 3,000 |
| **Deaths** | Respawn — 10 | Frequent Flyer — 100 | Corpse Run — 500 | Revenant — 1,500 | Undying — 3,000 |
| **Assists** | Wingman — 25 | Support Act — 250 | Playmaker — 1,000 | Puppetmaster — 2,500 | The Enabler — 5,000 |
| **Damage dealt** \* | Scrapper — 100k | Bruiser — 1M | Wrecking Ball — 5M | Demolisher — 10M | Annihilator — 15M |
| **Damage taken** \* | Punching Bag — 100k | Tough Skin — 1M | Iron Wall — 5M | Juggernaut — 10M | Unbreakable — 15M |
| **Healing** \* | Band-Aid — 20k | Medic — 200k | Field Surgeon — 750k | Lifeline — 1.5M | Miracle Worker — 2.5M |

\* since Link only. Estimated per-match averages: about 6 kills, 6 deaths, 10 assists, 30k damage dealt and taken, 5k healing.

### Economy

| Family | Bronze | Silver | Gold | Platinum | Diamond |
|---|---|---|---|---|---|
| **Souls earned** | Pocket Change — 100k | Soul Collector — 1M | Soul Hoarder — 5M | Soul Baron — 10M | Soul Tycoon — 15M |

### Results

| Family | Bronze | Silver | Gold | Platinum | Diamond |
|---|---|---|---|---|---|
| **Matches played** | Rookie — 10 | Regular — 50 | Veteran — 150 | Lifer — 300 | The Pitboss — 500 |
| **Time played** | Warm-Up — 5h | Dedicated — 25h | Grinder — 75h | No-Lifer — 150h | Living in the Pit — 250h |
| **Total wins** | Contender — 5 | Victor — 25 | Champion — 75 | Conqueror — 150 | Legend — 300 |
| **Total losses** | Learning Experience — 5 | Hard Knocks — 25 | Glutton for Punishment — 75 | Still Here — 150 | Unbreakable Spirit — 300 |
| **Win streak** (best ever) | On a Roll — 3 | Hot Streak — 5 | Unstoppable — 7 | Dominating — 10 | Godlike — 12 |
| **Lose streak** (worst ever) | Rough Patch — 3 | Tilted — 5 | Cursed — 7 | Rock Bottom — 10 | Uninstall? — 12 |

### Items (since Link only)

The shop has 3 item types: **Weapon**, **Vitality** and **Spirit**. Melee items are part of Weapon. Counts are purchases of that type. Estimate: about 4 per type per match.

| Family | Bronze — 25 | Silver — 100 | Gold — 400 | Platinum — 1,000 | Diamond — 2,000 |
|---|---|---|---|---|---|
| **Weapon** | Armed | Gunslinger | Arms Dealer | Arsenal | Walking Armory |
| **Vitality** | Healthy | Hardy | Fortified | Bulwark | Immortal |
| **Spirit** | Spark | Mystic | Arcanist | Archmage | Spirit Lord |

Extra (optional): **Collector**, for the number of *different* items ever bought: 10 Window Shopper, 30 Bargain Hunter, 60 Collector, 90 Hoarder, every item The Whole Shop.

### Heroes

**Hero mastery**: one family per hero, counting matches on that hero. It shows as "Haze Expert".

| Bronze | Silver | Gold | Platinum | Diamond |
|---|---|---|---|---|
| Tryout — 5 | Regular — 25 | Specialist — 75 | Expert — 150 | Master — 300 |

**Jack of All Trades**: number of different heroes won with.

| Bronze | Silver | Gold | Platinum | Diamond |
|---|---|---|---|---|
| Dabbler — 3 | Flexible — 8 | Versatile — 15 | Jack of All Trades — 25 | Master of All — every hero |

When a new hero comes out, Diamond needs it too. Players who already have Diamond keep it.

**One-Trick**: share of the last 100 matches played on one hero. Needs 100+ matches.

| Bronze | Silver | Gold |
|---|---|---|
| Favourite — 40% | Main — 60% | One-Trick — 80% |

---

## Single-match trophies (hard but reachable)

| Family | Bronze | Silver | Gold | Platinum | Diamond |
|---|---|---|---|---|---|
| **Souls per minute** (match 15+ min) | Farmer — 1,200 | Harvester — 1,400 | Soul Engine — 1,600 | Soul Storm — 1,800 | Soul Singularity — 2,000 |
| **Match length** (win or lose) | Long Haul — 40 min | Endurance — 45 min | Marathon — 50 min | Ultramarathon — 55 min | Forever War — 60 min |
| **Multi-kill** \* (≤10s between kills) | Triple Kill — 3 | Quad Kill — 4 | Penta Kill — 5 | Wipeout — 6 (whole team) | — |
| **Untouchable** (win with 0 deaths) | Clean Sheet — any win | Untouchable — 10+ K+A | Flawless — 20+ K+A | Perfection — 25+ K+A | — |
| **Feeder** (deaths in one match) | Feeder — 12 | Soul Donor — 15 | Open Buffet — 18 | All-You-Can-Eat — 22 | — |

\* since Link only.

---

## Build notes (for later)

- **Storage**: `player_totals(account_id, stat, value)` for since-Link sums. `trophies(account_id, trophy, tier, earned_at, match_id)` for earned trophies, so "newest" and rarity are one query each.
- **Check when building**: does match metadata have damage taken, and kill times (for multi-kills)? If either is missing, drop that family.
- **Calibration**: before building, compute the median per match for each stat across Linked Members. Then scale the thresholds so Diamond takes about 400 matches.

## Open questions

1. Should the "All trophies" button open a list inside Discord, or the web dashboard?
2. Should a Match Recap announce a new trophy ("🏆 Reaper unlocked")?
3. Melee: keep it inside Weapon, or hand-pick a Melee item list?
