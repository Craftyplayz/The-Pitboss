# The Pitboss

A Discord bot for one Deadlock community server that shows game stats and insights about the server's players and the wider game.

## Language

### People

**Member**:
A person in the Discord server.
_Avoid_: User, account

**Player**:
A Deadlock account, identified by its Steam account.
_Avoid_: Account, profile, user

**Link**:
A Member's self-declared claim that a Player is theirs. Unverified. A Member has at most one Link, and a Player belongs to at most one Member.
_Avoid_: Connection, registration, verification

**Linked Member**:
A Member who has a Link. Every Linked Member gets Match Recaps.

### Stats

**Profile**:
A summary of one Player's stats: rank, win rate and most-played heroes.
_Avoid_: Player card, stats page

**Match**:
One finished game of Deadlock.
_Avoid_: Game, round

**Meta**:
Game-wide stats about heroes and items across all Players, not tied to this server.
_Avoid_: Tier list, global stats

**Leaderboard**:
A ranking of this server's Linked Members against each other by one metric: rank, win rate, KDA, Matches played, souls per minute or Rank Climb. It covers all heroes or one hero.
_Avoid_: Ranking, top list

**Rank Climb**:
The MMR a Player gained or lost over the Leaderboard Window.
_Avoid_: Progress, gains

**Leaderboard Window**:
The last 30 days of Matches. A Linked Member needs at least 10 Matches in the window to appear on a window-based Leaderboard.
_Avoid_: Period, season

**Insight**:
A rule-based comparison computed from stats, such as a hero win rate against the Player's own average.
_Avoid_: Analysis, tip

**Match Recap**:
A message the bot posts on its own after a Linked Member finishes a Match. On linking, every Match from the 30 days before the Link gets one (the Backfill). After that, a Match missed for more than 24 hours gets none.
_Avoid_: Notification, alert, match post

**Scrim**:
A custom Match between Members, set up with /scrim: Members sign up in its own category (a sign-up channel plus a voice channel per team), get split into two teams and play in a custom lobby the bot makes. Its scoreboard is saved once the Match is over.
_Avoid_: Custom game, inhouse, private match

**Recap Thread**:
The forum post, one per Member, where that Member's Match Recaps are posted. It is created with the first Match Recap and archived when the Link ends.
_Avoid_: Feed, log

**Patch Notes**:
Valve's changelog for one Deadlock update, taken from Steam. Picking the patch notes channel with /setup posts every past one there, oldest first, as a log; after that each new one is posted as it comes out. Long ones continue in a thread under the post.
_Avoid_: Changelog, update post
