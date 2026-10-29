# Plan: click a day on "Server matches per day"

Status: not built.

## What the user gets

Click any bar on the Overview's "Server matches per day" chart. The Matches page opens with only that day's matches in the list. The first one is open in the detail pane. The list header reads e.g. "14 Oct · 6 matches", with a "Show all 30 days" link that clears the filter.

## Scope: one file

Only `pages/dashboard.html` changes. The page already has everything it needs: `D.SM` holds every match in the 30 days with its start time (`m.t`), and the server's per-day count (`D.days`) uses the same matches. No new API call, no change to `web.py` or `core/dashboard.py`.

## Steps

1. **Day key.** Use the bucket the server already uses: `day = Math.floor((D.T - m.t) / 86400)` (0 = today). Using the same formula means a bar's count always matches the number of matches the list shows.
2. **Route.** Add `#matches/day-N` (N = days ago). In `matches(a,b)`, if `a` starts with `day-`, keep only matches with that day key and select the first one. A match link inside the filtered list becomes `#matches/day-N/<match id>`, so opening a match keeps the filter.
3. **Clickable bars.** `bars()` is shared with the player souls chart. Give it an optional link-per-bar argument and use it only on the Overview chart. Each bar gets an invisible full-height hit area, so days with 1 match are still easy to click and tap, plus `cursor:pointer`.
4. **Empty days.** A bar with 0 matches has nothing to show, so it isn't clickable. If someone opens `#matches/day-N` for an empty day directly, show "No matches on this day" with the "Show all 30 days" link.
5. **Check.** Click the tallest bar: the list count matches the bar's tooltip. Click a 1-match day on a phone-width window. Open a match from the filtered list, press Back, and confirm the filter is still there.

## Known limit

Days are rolling 24-hour blocks counted back from when the dashboard was built, not calendar days. The bar tooltips already show calendar dates, so a match from late last night can land under "today". Keep it as is (matches the chart) unless that confuses people. If it does, the fix is to bucket by local midnight on both the server (`server_matches`) and the page.

## Size

About 15 to 25 lines of JS. Roughly 45 minutes including checking on desktop and phone width.
