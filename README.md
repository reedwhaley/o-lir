# O-Lir

O-Lir is the tournament control system for Metroid Prime events.

It handles tournament creation, entrant signup, team registration, SpeedGaming identity storage, async seeding workflows, seeding review, seed calculation, standings, pairing generation, scheduling thread creation, result approval, bracket progression, and internal API support for Lightbringer integration.

Lightbringer handles live match operations. O-Lir handles the tournament brain.

## What O-Lir is for

Use O-Lir when you need to:

- create a tournament and define its rules
- collect singles or team signups
- store each player's SpeedGaming identity data
- distribute async seeding race files
- accept seeding submissions with proof and VODs
- review and approve seeding submissions
- compute official seeds using a chosen seeding method
- apply a drop-lowest seeding rule
- use a selected standings tiebreak rule
- generate swiss rounds
- generate top cut
- open Discord scheduling threads for pairings
- link Lightbringer matches back to pairing records
- approve or correct results before advancing the bracket

## Core command groups

O-Lir is organized into these main groups in `tournament_commands.py`: `/tournament setup`, `/tournament entry`, `/tournament seeding`, `/tournament bracket`, and `/tournament admin`. fileciteturn73file0

---

# Tournament creation options

Tournament creation now includes seeding and tiebreak configuration in addition to the normal format settings.

## Required tournament creation fields

The admin create command currently takes the normal tournament fields such as name, category, entrant type, seeding race count, swiss round count, and top cut size, and is intended to be expanded to include the seeding method, seeding drop count, and standings tiebreak method as required configuration. The tournament model and service now support storing `seeding_method`, `seeding_drop_count`, and `standings_tiebreak_method`. fileciteturn73file0turn74file0turn75file0

## Seeding method

This controls how approved seeding race submissions are turned into final entrant seeds.

Supported methods in the seeding service are:

- `baja_special`
- `average_score`
- `sum_of_placements`
- `percent_max`
- `percent_difference`
- `z_sum`
- `z_percentile`
- `zipfs_law` fileciteturn75file0

## Seeding drop count

This controls how many of an entrant's worst seeding race contributions are removed before the final seed calculation is made.

Typical values are:

- `0`
- `1`

The patched seeding logic applies `tournament.seeding_drop_count` through a shared `_drop_lowest(...)` helper before final aggregation. fileciteturn75file0

## Standings tiebreak method

This controls how standings ties are resolved after matches are played. This is separate from seeding math.

Recommended supported values are:

- `buchholz`
- `sonneborn_berger`
- `buchholz_then_sonneborn_berger`

The tournament model and service were prepared for this field so standings logic can use it instead of assuming one fixed rule forever. fileciteturn74file0

---

# Seeding method explanations

These methods are implemented over O-Lir's current data model, which stores approved race submissions as times per entrant per race. That means these are time-based adaptations of common tournament seeding approaches, not scorecard-style multi-map judge systems. The implementation lives in `SeedingService.compute_seeds()` and its helper methods. fileciteturn75file0

## Baja Special

This is O-Lir's custom original method and should remain available as a named first-class option.

How it works:

1. Group approved submissions by race.
2. For each race, sort entrants by time from fastest to slowest.
3. Build a par pool using the fastest `ceil(field_size / 6)` runs.
4. Sum those top times into a par value.
5. Convert each entrant's race into a score using `(2 - entrant_time / par_sum) * 100`.
6. Clamp the score to a minimum positive floor for completed runs.
7. Drop the configured number of worst race contributions.
8. Sum the best remaining scores, currently preserving the existing behavior of using the top two remaining contributions. fileciteturn75file0

Use Baja Special when:

- you want to preserve the existing O-Lir seeding culture
- you want a custom house formula instead of a generic rank average
- you want a method that rewards stronger runs against a race-based par benchmark

## Average Score

In O-Lir's current implementation, this uses placement-normalized scoring for each race.

How it works:

1. Rank each race by finish time.
2. Convert placement into a percent-like value based on field size.
3. Higher placement means a higher contribution.
4. Drop the configured number of lowest contributions.
5. Average the remaining contributions. fileciteturn75file0

Use it when:

- you want steady consistency rewarded across all seeding races
- you want easier explanation to players
- you prefer average performance over spike performance

## Sum of Placements

This uses per-race placement totals.

How it works:

1. Rank each race by finish time.
2. Assign placement numbers.
3. Lower placements are better, so the implementation stores them as negative values so better placements still sort higher in the final score system.
4. Drop the configured number of worst placements.
5. Sum the remaining placement contributions. fileciteturn75file0

Use it when:

- you want relative race finish rank to matter more than raw time margins
- you want each race to count as a placement event
- you want a method that is easy to explain in competitive terms

## Percent Max

This compares each entrant to the fastest run in each race.

How it works:

1. Find the fastest time in the race.
2. Convert each entrant's result into `fastest / entrant_time * 100`.
3. Faster runs produce higher percentages.
4. Drop the configured number of worst race contributions.
5. Average the remaining percentages. fileciteturn75file0

Use it when:

- you want performance measured relative to the best run each race
- you want raw closeness to first place to matter
- you want a normalized percent-style method without standings math

## Percent Difference

This measures how far behind the fastest run each entrant is.

How it works:

1. Find the fastest time in the race.
2. Compute each entrant's percent behind first.
3. Convert that into a higher-is-better contribution by subtracting from 100.
4. Drop the configured number of worst contributions.
5. Average the remaining contributions. fileciteturn75file0

Use it when:

- you want to penalize being far behind the best run
- you want percent-based normalization
- you want a more intuitive "distance from first" framing

## Z-Sum

This uses standard score normalization across race times.

How it works:

1. Convert times so faster runs become larger transformed values.
2. Compute the mean and standard deviation for the race.
3. Convert each entrant's transformed value into a z-score.
4. Missing runs get a score worse than the worst present value.
5. Drop the configured number of worst contributions.
6. Sum the remaining z-scores. fileciteturn75file0

Use it when:

- you want field-relative normalization
- you want to account for race-by-race variance
- you prefer a method that measures how far above or below the field average someone performed

## Z-Percentile

This converts placement percentile into a z-score.

How it works:

1. Rank each race by finish time.
2. Convert placement into a percentile.
3. Transform that percentile using the inverse normal distribution.
4. Missing runs get a very low fallback percentile.
5. Drop the configured number of worst contributions.
6. Sum the remaining z-percentile contributions. fileciteturn75file0

Use it when:

- you want percentile ranking with normal-distribution smoothing
- you want a method less sensitive to raw time gaps
- you still want field-relative normalization

## Zipf's Law

This gives each placement a reciprocal value.

How it works:

1. Rank each race by finish time.
2. Convert each placement into `1 / placement`.
3. First is worth the most, second is half that, third is a third, and so on.
4. Missing runs get zero.
5. Drop the configured number of worst contributions.
6. Sum the remaining contributions. fileciteturn75file0

Use it when:

- you want a strongly placement-driven method
- you want first place to be rewarded sharply
- you want a simple diminishing-return rank model

---

# Tiebreaker explanations

These apply to standings after actual matches, not to qualifier seed submissions.

## Buchholz

Buchholz is a strength-of-schedule tiebreaker.

How it works:

- take the match point totals of a player's opponents
- sum them
- higher total means the player faced stronger opposition

Use it when:

- you want standings to reward a harder schedule
- you run swiss and need a common competitive tiebreak

The current standings display in `TournamentBracketGroup.standings` already shows Buchholz as part of standings output. fileciteturn73file0

## Sonneborn-Berger

Sonneborn-Berger is an opponent-result-weighted tiebreaker.

How it works in principle:

- wins count the final value of beaten opponents
- draws, if your game supports them, count partial value
- losses do not contribute

Use it when:

- you want to reward wins over stronger opponents
- you want a secondary tiebreak after match points

The current standings display also exposes Sonneborn-Berger in the output list. fileciteturn73file0

## Buchholz then Sonneborn-Berger

This is a chained tiebreak system.

How it works:

1. compare Buchholz first
2. if still tied, compare Sonneborn-Berger next

Use it when:

- you want a clear default ordering
- you want schedule strength first and opponent-quality wins second
- you want fewer unresolved ties in standings

---

# Commands and use cases

## `/tournament setup`

This group is for player self-service profile setup. It is implemented in `TournamentSetupGroup`. fileciteturn73file0

### `/tournament setup speedgaming`

Creates or updates the caller's stored SpeedGaming profile.

Stores:

- Discord username snapshot
- SpeedGaming display name
- SpeedGaming Twitch name

Use it when:

- a player wants to sign up for a tournament
- a player needs their SG identity available for Lightbringer handoff
- a staff member tells entrants to get their profile on file before registration

### `/tournament setup speedgaming_view`

Shows the caller's current stored SpeedGaming profile.

Use it when:

- a player wants to verify what O-Lir has on file
- a player wants to confirm their SG display name or Twitch name before signup

### `/tournament setup speedgaming_clear`

Deletes the caller's stored SpeedGaming profile.

Use it when:

- a player wants to remove stale SG data
- a player is correcting a bad setup from scratch

## `/tournament entry`

This group is for entrant registration and self-management. It is implemented in `TournamentEntryGroup`. fileciteturn73file0

### `/tournament entry signup`

Signs the caller up as a singles entrant.

Use it when:

- the tournament is a singles event
- the player already completed SpeedGaming setup
- registration is open

Checks include:

- tournament exists
- tournament allows singles
- player is not already entered
- player has a SpeedGaming profile on file fileciteturn73file0turn74file0

### `/tournament entry signup_team`

Signs up a two-player team.

Use it when:

- the event is team-based
- both players have finished SpeedGaming setup
- registration is open

It also stores per-member identity rows for downstream Lightbringer use. fileciteturn73file0

### `/tournament entry withdraw`

Withdraws the caller's active entry while signup remains open.

Use it when:

- a player or team member needs to drop before registration closes

### `/tournament entry my_entry`

Shows the caller's current active entry in a tournament.

Use it when:

- a player wants to verify they are registered
- a team member wants to verify the team entry was created correctly

### `/tournament entry entrants`

Lists active entrants in the tournament.

Use it when:

- staff want a quick entrant list
- players want to confirm bracket field population
- you want to see current seeds or unseeded status

## `/tournament seeding`

This group handles async seed distribution and submission review. It is implemented in `TournamentSeedingGroup`. fileciteturn73file0turn75file0

### `/tournament seeding upload_async_seed`

Uploads or replaces a private async seed file for a seeding race.

Staff only.

Use it when:

- staff are preparing seeding race files
- an async seed needs to be replaced or corrected

### `/tournament seeding request_async_seed`

Requests an async seed for the caller's entrant or team and sends it by DM.

Use it when:

- a player is ready to run a seeding race
- staff want O-Lir to log the request and lock it to the requesting entrant composition

### `/tournament seeding list_async_seed_requests`

Lists logged async seed requests for a tournament.

Use it when:

- staff want to audit which entrants requested which async seed
- staff need to see whether a race was already issued

### `/tournament seeding clear_async_seed_request`

Clears a logged async seed request so it can be reissued.

Use it when:

- delivery failed
- staff need to reset issuance state
- an entrant needs a clean retry

### `/tournament seeding submit_seed`

Submits a seeding race result with:

- race number
- time value
- VOD URL
- proof image attachment

Use it when:

- a player or team finishes an async seeding race
- staff want proof-backed seeding submission records

### `/tournament seeding submissions`

Lists seeding submissions, optionally filtered by entrant or status.

Use it when:

- staff want to review pending work
- staff want to audit approved and rejected submissions

### `/tournament seeding show_submission`

DMs a proof image to authorized staff.

Use it when:

- staff need to inspect proof privately
- you do not want to expose proof images in public channels

### `/tournament seeding approve_submission`

Marks a seeding submission approved.

Use it when:

- proof and VOD check out
- staff are ready for the run to count toward seeding

### `/tournament seeding reject_submission`

Marks a seeding submission rejected.

Use it when:

- proof is invalid
- VOD is missing or incorrect
- the run does not meet requirements

### `/tournament seeding clear_submission`

Deletes a seeding submission so it can be resubmitted.

Use it when:

- a bad upload needs to be replaced entirely
- staff want a clean resubmission instead of a reject note

### `/tournament seeding compute_seeds`

Calculates official seeds for the tournament using approved submissions and the selected seeding method. The command currently calls `SeedingService.compute_seeds(tournament_id)` and then writes seeds back to entrants. fileciteturn73file0turn75file0

Use it when:

- all seeding races are reviewed
- staff are ready to lock in ordering
- you want to verify how the selected seeding math impacts final seeds

## `/tournament bracket`

This group handles standings, pairing visibility, result management, and advancement. It is implemented in `TournamentBracketGroup`. fileciteturn73file0

### `/tournament bracket matches`

Lists pairings for a tournament.

Use it when:

- staff want to see all pairings
- staff want to filter by round
- staff want only unresolved matches

### `/tournament bracket match_details`

Shows full details for a specific pairing.

Use it when:

- staff want winner, status, thread, or recorded result details
- staff need a quick diagnostic view for one match

### `/tournament bracket record_match_result`

Manually records a match result.

Use it when:

- Lightbringer import is unavailable
- staff must key in winner and times manually

### `/tournament bracket approve_match_result`

Approves a recorded result for progression.

Use it when:

- staff have reviewed a manual or imported result
- the match should now count toward advancing the bracket

### `/tournament bracket clear_match_result`

Clears a recorded result.

Use it when:

- a result was entered incorrectly
- staff need to reset a match before re-recording it

### `/tournament bracket generate_swiss_round`

Creates the next swiss round and opens scheduling threads for ready pairings.

Use it when:

- seeding is done
- previous swiss round is complete
- staff are ready to generate the next wave of matches

### `/tournament bracket advance_to_next_round`

Advances the tournament after validating the current round.

Use it when:

- all current round matches are completed and approved
- staff want O-Lir to either start the next swiss round or move into top cut

### `/tournament bracket standings`

Displays standings including match points, Buchholz, Sonneborn-Berger, and seed data in the current implementation. fileciteturn73file0

Use it when:

- staff want a current ranking table
- players want to see where they stand
- you need to inspect tiebreak ordering

### `/tournament bracket generate_top_cut`

Creates top cut pairings and opens scheduling threads.

Use it when:

- swiss is complete
- staff are ready to start elimination phase

### `/tournament bracket open_match_thread`

Opens a Discord scheduling thread for an existing pairing. The implementation now uses `ThreadService.build_pairing_thread_body(...)`, stores thread context, and stores the starter message ID for later refresh. fileciteturn73file0turn61file0

Use it when:

- a pairing exists but no scheduling thread was created yet
- staff need to manually open the thread for coordination

## `/tournament admin`

This group covers tournament setup and staff overrides. It is implemented in `TournamentAdminGroup`. fileciteturn73file0

### `/tournament admin create`

Creates a tournament.

Use it when:

- a new event is being set up
- staff need to define format and seeding behavior before signups open

Recommended fields now include:

- name
- category slug
- entrant type
- seeding race count
- seeding method
- seeding drop count
- standings tiebreak method
- swiss round count
- top cut size

### `/tournament admin add_entrant`

Adds a singles entrant directly as staff.

Use it when:

- a player cannot self-register
- staff need to repair or complete the field manually

### `/tournament admin add_team

Adds a team-based entrant directly as staff.

Use it when:

- a team cannot self-register
- staff need to repair or complete the field manually

---

# Pairing and Lightbringer integration

O-Lir owns the pairing record and scheduling thread lifecycle.

The internal pairing routes support:

- lookup by thread ID
- linking a Lightbringer match ID to a pairing
- reporting Lightbringer results back into O-Lir fileciteturn61file0

Use this integration when:

- O-Lir creates a pairing thread
- Lightbringer is used to schedule and run the live match
- final match state needs to return to the bracket system

---

# Typical workflows

## Standard tournament workflow

1. Staff create the tournament.
2. Staff choose seeding method, drop count, and standings tiebreak rule.
3. Players complete SpeedGaming setup.
4. Players sign up.
5. Staff upload async seed files if needed.
6. Players request async seeds and submit runs.
7. Staff review and approve submissions.
8. Staff run compute seeds.
9. Staff generate swiss round one.
10. O-Lir opens pairing threads.
11. Lightbringer creates live matches inside those threads.
12. Results are approved and the bracket advances.

## Team event workflow

1. Staff create a team event.
2. Both players complete SpeedGaming setup.
3. Teams register through team signup.
4. Staff run the seeding workflow.
5. O-Lir computes team seeds using the chosen method.
6. Pairings are created.
7. Lightbringer handles live match operations.

## When to choose each seeding style

Choose Baja Special when you want to preserve the existing custom house formula.

Choose Average Score when you want stable average placement-style performance rewarded.

Choose Sum of Placements when you care more about finishing order than raw time gaps.

Choose Percent Max when you want every race compared directly to the fastest run.

Choose Percent Difference when you want to reward staying close to first place.

Choose Z-Sum when you want field-relative statistical normalization.

Choose Z-Percentile when you want percentile-based normalization with smoother weighting.

Choose Zipf's Law when you want sharply placement-weighted rewards.

## When to use drop lowest

Use `seeding_drop_count = 1` when:

- you want to forgive one bad seeding race
- you expect occasional seed variance or one-off problems
- you want less punishment for a single disaster run

Use `seeding_drop_count = 0` when:

- every seeding race should count
- you want maximum consistency pressure

## When to choose each tiebreaker

Choose Buchholz when strength of schedule should be the first answer.

Choose Sonneborn-Berger when you care more about the quality of opponents beaten.

Choose Buchholz then Sonneborn-Berger when you want a practical chained default that resolves more ties cleanly.

---

# Repository purpose

O-Lir is the tournament control plane.

It owns:

- tournament definitions
- entrant and team records
- SpeedGaming identity mapping
- seeding submission review
- seed calculation
- standings and tiebreak state
- pairings
- scheduling threads
- bracket progression
- internal API for Lightbringer synchronization

If Lightbringer is the live match operations bot, O-Lir is the system that decides what the tournament actually is.
