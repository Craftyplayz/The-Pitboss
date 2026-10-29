# Trophies plan

Status: plan only, nothing built yet. Thresholds are based on a small sample of real matches. Check them against all Linked Members before building (see "Calibration").

## How trophies work

- **Career trophies** have 7 tiers. Each tier has its own name. A tier's threshold is set so an average player reaches it after a set number of matches:

  | Tier | 1 Bronze | 2 Silver | 3 Gold | 4 Platinum | 5 Diamond | 6 Master | 7 Eternal |
  |---|---|---|---|---|---|---|---|
  | Matches to reach | 2–3 | 8–10 | 40–50 | 80–100 | 200–250 | 400–500 | ~1,000 |

- **Single-match trophies** are earned in one match. They're hard but reachable for a normal player.
- A Player keeps every tier they reach. Only the highest tier of a family shows on the profile.
- **Rarity** = % of Linked Members who hold that trophy tier. "Rarest" = lowest %.

### Where the numbers come from

| Source | What it covers | Stats |
|---|---|---|
| Match history (already fetched) | Every match the Player ever played | kills, deaths, assists, souls, wins, losses, streaks, Daily Grind, matches, time played, heroes, souls/min, match length, Stomp, Untouchable, Feeder |
| Match metadata (fetched by Match Recaps) | Only matches since the Link, plus the 30-day Backfill | healing, damage dealt, damage taken, item purchases, multi-kills, kill style, MVP, accuracy |

Metadata stats get added to per-player totals in the database each time a Recap runs.

### Per-match averages (the baseline)

| Stat | Average | Source |
|---|---|---|
| Kills | 5.1 | 80 matches |
| Deaths | 5.3 | 80 matches |
| Assists | 13 | 80 matches |
| Souls | 36,800 | 80 matches |
| Match length | 36.6 min | 80 matches |
| Win rate | 51% | 80 matches |
| Damage dealt | 26,400 | 12 matches |
| Damage taken | 29,400 | 12 matches |
| Healing | 6,650 | 12 matches |
| Items bought | ~15 total, ~5 per type | 12 matches |

Players often favour one item type, so item tiers assume an even ~5 per type.

## Display

- **`/profile`**: a small "Trophies — 37 / 140" section showing the 3 newest and 3 rarest trophies. An **All trophies** link button opens the Player's trophy page on the web dashboard.
- **Web dashboard trophy page**: the full list, grouped by category, with tier, date earned and rarity. Trophies you don't have yet show as locked, with progress (e.g. "Reaper — 1,204 / 1,250 kills").
- **What's missing**: on the trophy page, trophies that need a set of different things list what the Player hasn't done yet, so they know what to go for:
  - **Collector**: shop items never bought, grouped by Weapon / Vitality / Spirit, with icons.
  - **Jack of All Trades**: heroes never won with. Heroes played but never won with are listed first, as the closest.
  - **Hero mastery**: each hero's next tier and how many more matches it needs (e.g. "Haze: 7 more for Specialist"). Heroes never played are listed separately.
- **`/trophies [member]`**: replies with the same link button.
- **Match Recap**: lists every trophy earned in that match ("🏆 Reaper unlocked"). For the top 2 tiers of a family, it also pings the Member:
  - 7-tier families: Master and Eternal
  - 5-tier families: Platinum and Diamond
  - Smaller families: their top 2 (e.g. Daily Grind 14 and 30 days; One-Trick Main and One-Trick)

---

## Career trophies (count up every match)

Each cell is the tier name, then the threshold.

### Combat

| Family | 1 Bronze | 2 Silver | 3 Gold | 4 Platinum | 5 Diamond | 6 Master | 7 Eternal |
|---|---|---|---|---|---|---|---|
| **Kills** | First Blood — 15 | Headhunter — 50 | Slayer — 250 | Executioner — 500 | Reaper — 1,250 | Death Incarnate — 2,500 | Extinction Event — 5,000 |
| **Deaths** | Respawn — 15 | Frequent Flyer — 50 | Corpse Run — 250 | Graveyard Regular — 500 | Revenant — 1,250 | Undying — 2,500 | Eternal Return — 5,000 |
| **Assists** | Wingman — 30 | Support Act — 125 | Team Player — 600 | Playmaker — 1,250 | Puppetmaster — 3,000 | The Enabler — 6,000 | The Architect — 12,500 |
| **Damage dealt** \* | Scrapper — 75k | Bruiser — 250k | Heavy Hitter — 1.25M | Wrecking Ball — 2.5M | Demolisher — 6M | Annihilator — 12.5M | Cataclysm — 25M |
| **Damage taken** \* | Punching Bag — 75k | Tough Skin — 275k | Thick Hide — 1.25M | Iron Wall — 2.75M | Juggernaut — 7M | Unbreakable — 12.5M | Immovable Object — 30M |
| **Healing** \* | Band-Aid — 20k | Medic — 60k | Field Surgeon — 300k | Lifeline — 600k | Miracle Worker — 1.5M | Saint — 3M | Fountain of Life — 6.5M |

\* since Link only.

### Kill style (since Link only)

Thresholds use the average over 144 players across 12 matches: 0.38 headshot, 0.83 melee and 3.4 ability kills per match.

| Family | 1 Bronze | 2 Silver | 3 Gold | 4 Platinum | 5 Diamond | 6 Master | 7 Eternal |
|---|---|---|---|---|---|---|---|
| **Headshot kills** | Lucky Shot — 1 | Crack Shot — 4 | Marksman — 20 | Deadeye — 40 | Skull Splitter — 100 | Sniper Elite — 200 | One Tap — 400 |
| **Melee kills** | Scuffle — 2 | Brawler — 8 | Knuckle Sandwich — 40 | Pugilist — 80 | Heavyweight — 200 | Fist of Fury — 400 | Knockout King — 800 |
| **Ability kills** | Cantrip — 10 | Spellslinger — 35 | Hexer — 175 | Evoker — 350 | Warlock — 850 | Grand Warlock — 1,750 | Arcane Executioner — 3,500 |

### Economy

| Family | 1 Bronze | 2 Silver | 3 Gold | 4 Platinum | 5 Diamond | 6 Master | 7 Eternal |
|---|---|---|---|---|---|---|---|
| **Souls earned** | Pocket Change — 100k | Soul Collector — 350k | Soul Hoarder — 1.75M | Soul Baron — 3.5M | Soul Tycoon — 9M | Soul Mogul — 17.5M | Soul Emperor — 35M |

### Results

| Family | 1 Bronze | 2 Silver | 3 Gold | 4 Platinum | 5 Diamond | 6 Master | 7 Eternal |
|---|---|---|---|---|---|---|---|
| **Matches played** | Rookie — 3 | Regular — 10 | Veteran — 50 | Lifer — 100 | Die-Hard — 250 | Institution — 500 | The Pitboss — 1,000 |
| **Time played** | Warm-Up — 1.5h | Dedicated — 5h | Grinder — 25h | Committed — 50h | No-Lifer — 150h | Living in the Pit — 300h | One with the Pit — 600h |
| **Total wins** | First Win — 1 | Contender — 5 | Victor — 25 | Champion — 50 | Conqueror — 125 | Warlord — 250 | Legend — 500 |
| **Total losses** | Learning Experience — 1 | Hard Knocks — 5 | Glutton for Punishment — 25 | Still Here — 50 | Iron Will — 125 | Never Gives Up — 250 | Eternal Optimist — 500 |

Streaks aren't totals, so they keep their own 5 tiers:

| Family | Bronze | Silver | Gold | Platinum | Diamond |
|---|---|---|---|---|---|
| **Win streak** (best ever) | On a Roll — 3 | Hot Streak — 5 | Unstoppable — 7 | Dominating — 10 | Godlike — 12 |
| **Lose streak** (worst ever) | Rough Patch — 3 | Tilted — 5 | Cursed — 7 | Rock Bottom — 10 | Uninstall? — 12 |

**MVP** (since Link only): matches where the Player was the match MVP (`mvp_rank` 1). Each match has one MVP, so an average player gets one about every 12 matches. Tiers 3–7 follow the matches-to-reach rule. Tiers 1–2 can't, because they would need less than 1 MVP.

| 1 Bronze | 2 Silver | 3 Gold | 4 Platinum | 5 Diamond | 6 Master | 7 Eternal |
|---|---|---|---|---|---|---|
| Standout — 1 | Star Player — 3 | MVP — 5 | Clutch — 10 | Franchise Player — 20 | Hall of Famer — 40 | GOAT — 80 |

**Daily Grind**: most days in a row with at least one match (best ever, full history). A day runs midnight to midnight in the server's timezone.

| Tier 1 | Tier 2 | Tier 3 | Tier 4 | Tier 5 | Tier 6 |
|---|---|---|---|---|---|
| Back for More — 2 days | Hooked — 4 days | Week-Long Grind — 7 days | Can't Stop — 10 days | Two-Week Grind — 14 days | Month in the Pit — 30 days |

### Items (since Link only)

The shop has 3 item types: **Weapon**, **Vitality** and **Spirit**. Melee items are spread across all three (e.g. Melee Charge is Weapon, Melee Lifesteal is Vitality, Spirit Strike is Spirit). Counts are purchases of that type, including items later sold.

| Family | 1 Bronze — 15 | 2 Silver — 50 | 3 Gold — 250 | 4 Platinum — 500 | 5 Diamond — 1,250 | 6 Master — 2,500 | 7 Eternal — 5,000 |
|---|---|---|---|---|---|---|---|
| **Weapon** | Armed | Gunslinger | Sharpshooter | Arms Dealer | Arsenal | Walking Armory | God of War |
| **Vitality** | Healthy | Hardy | Sturdy | Fortified | Bulwark | Immortal | Living Fortress |
| **Spirit** | Spark | Mystic | Sorcerer | Arcanist | Archmage | Spirit Lord | Ascended |

Extra (optional): **Collector**, for the number of *different* items ever bought: 10 Window Shopper, 30 Bargain Hunter, 60 Collector, 90 Hoarder, every item The Whole Shop.

### Heroes

**Hero mastery**: one family per hero, counting matches on that hero. It shows as "Haze Expert".

| 1 Bronze | 2 Silver | 3 Gold | 4 Platinum | 5 Diamond | 6 Master | 7 Eternal |
|---|---|---|---|---|---|---|
| Tryout — 3 | Regular — 10 | Specialist — 50 | Expert — 100 | Master — 250 | Grandmaster — 500 | Legend — 1,000 |

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
| **Match length** (win or lose) | Long Haul — 45 min | Endurance — 55 min | Marathon — 65 min | Ultramarathon — 75 min | Forever War — 90 min |
| **Multi-kill** \* (≤10s between kills) | Triple Kill — 3 | Quad Kill — 4 | Penta Kill — 5 | Wipeout — 6 (whole team) | — |
| **Untouchable** (win with 0 deaths) | Clean Sheet — any win | Untouchable — 10+ K+A | Flawless — 20+ K+A | Perfection — 25+ K+A | — |
| **Feeder** (deaths in one match) | Feeder — 12 | Soul Donor — 15 | Open Buffet — 18 | All-You-Can-Eat — 22 | — |
| **Stomp** (win in under) | Quick Win — 25 min | Stomp — 22 min | Steamroll — 20 min | Blowout — 17 min | Speedrun — 15 min |
| **Accuracy** \* (200+ shots fired) | Steady Hand — 60% | Precise — 65% | Laser — 70% | Aimbot? — 75% | — |

\* since Link only.

Sample: about 1 in 10 wins took under 25 min, 1 in 20 under 20 min. Accuracy across 144 players: average 50%, top 10% at 64%+, best 73%.

---

## Build notes (for later)

- **Storage**: `player_totals(account_id, stat, value)` for since-Link sums. `trophies(account_id, trophy, tier, earned_at, match_id)` for earned trophies, so "newest" and rarity are one query each.
- **Metadata fields (checked)**: final `stats[-1]` has `player_damage`, `player_damage_taken` and `player_healing`. `items[]` lists every purchase with `item_id` and `sold_time_s`; keep only assets with `type == "upgrade"` and group by `item_slot_type`. Kill times for multi-kills come from each enemy's `death_details[]` (`game_time_s`, `killer_player_slot`). Kill style uses `headshot_kills`, `melee_kills` and `ability_kills`; accuracy is `shots_hit / (shots_hit + shots_missed)`. MVP is the player's `mvp_rank` (1, 2 or 3 for the top three players, missing for the rest).
- **Calibration**: before building, compute the median per match for each stat across all Linked Members and re-check the tier table above.

## Open questions

1. Melee items: these are spread across all 3 shop categories, so no single category trophy covers a melee build:

   | Item | Category |
   |---|---|
   | Melee Charge, Crushing Fists | Weapon |
   | Melee Lifesteal, Lifestrike | Vitality |
   | Spirit Strike, Spirit Snatch | Spirit |

   - **Option A (recommended): no melee item trophy.** Melee kills already rewards melee players and needs no upkeep.
   - **Option B: a "Melee items bought" family** from a hand-picked item list in the code. When a patch adds a melee item, it has to be added to the list or it won't count.

   The list above was picked from the shop by name and description, so it may be incomplete.
2. Daily Grind: which timezone counts as "a day"?
