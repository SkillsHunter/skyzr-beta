# Where the build depends on something the team hasn't approved

Every item here is a Proposal (design doc) or a plan v2 Fix. If the team says no on Sunday, this list shows what to change.

| Item | Source | Where it lives | If the team says no |
|---|---|---|---|
| Hurricane Kestrel scenario: track Wilmington → Southern Pines → Greensboro, 50 km band, 29 hit counties, 72 hours | Design doc Proposal; v2 §3 | Generator (TRACK, BAND_M), held by Sai outside the repo | Sai edits the track, reruns the generator and its checks |
| Silence = 12 simulated hours with no contact; purple runs from last contact + 12 h to next contact | Design doc Proposal | `SILENT` in the generator; engine rule (to build) | Change the threshold in one constant |
| Feeds count as contact for silence (silent counties lose feeds too) | v2 Fix 1 | `feeds.csv` drops feeds inside silent windows | Without Fix 1, almost every hit county goes purple, because reports alone leave gaps far over 12 h |
| Pender "silent from hour 20 to 36" read as *purple* 20 to 36, so last contact is hour 8. Then at hour 22 Pender's last report is 14 hours old, the same figure as the design doc's chat example ("No report for 14 hours"; the doc doesn't name an hour) | v2 demo path | `SILENT["Pender"] = (8, 36)` | If the team meant last contact at 20, Pender isn't purple at hour 22 and demo step 2 has to move to hour 32 |
| Shelter is cots and shelter kits that can be shipped | Design doc open item (p. 13) | 9th resource column in `stock.csv` and `answer_key.csv` | Show shelter capacity as read-only and block it in Direct supplies |
| Units for the 9 resources | Design doc Proposal | `RESOURCES` in the generator | Rename units; Sai reruns |
| True need formulas (e.g. water red → 2 + 3 × intensity tankers) are invented for the beta | Plan v2 §3 | `needs()` in the generator | Change the formulas; Sai reruns |
| True, reported and known need kept apart; no request shows "No request received, need unknown" | v2 Fix 4 | `answer_key.csv` holds true need only; reports hold reported need | Show true need in the panel (answer-key mode only) |
| Delivery confirmations aren't in `reports.csv`. The engine writes them at runtime from a fixed template after transit time, and they go through AI intake like any report | Design doc p. 8 | Engine (to build) | n/a |
| Transit 6 h, or 12 h if the receiver's Roads lifeline is red | Design doc Proposal | Engine (to build) | One constant |
| Hit counties start with zero or a small stock; grey counties hold enough for the peak total need | Plan v2 §3 | `build_stock()` in the generator | Sai reruns with other ranges |
| `answer_key.csv` `overall_before_silence` is the most urgent of the 5 lifelines. Purple is applied by the engine on top | Design doc | Engine (to build) | n/a |
| Feeds arrive every 3 h; the answer key is hourly. Feed readings always match the answer key's power and comms colors at feed hours, but between feeds AI mode shows the last reading, so power or comms differs from the answer key in 195 of 2,117 county-hours (9.2%, silent windows included) | Plan v2 §3 | `feeds.csv` | For the blind map check, Kyle picks hours that are multiples of 3, or scores power and comms against the latest feed |
| `reports.csv` has `county` and `fips` columns. The design doc's report file lists no county | Plan v2 Fix 1 needs report contact per county in answer-key mode | `reports.csv` | Drop the columns; answer-key mode then parses the county from `source` (3 social posts name it only in the text) |
| Per-lifeline report ages and "the report behind" each lifeline color need extracted facts, so in answer-key mode they show "AI mode only" | Plan v2 Fix 1; design doc panel section 2 | Engine and panel (to build) | n/a |
| The contradiction rule also covers resource requests: same county and resource, within 6 h, different source, values more than 20% apart | Design doc says "lifeline and metric"; requests can conflict too | Engine (to build) | Without it, the contradiction check can't reach 5/5 |
| A delivery confirmation lowers known need (and the gap) and adds stock. It does not change a lifeline color: only a status report does. In demo step 7, Robeson's gap shrinks and it stays red because its water systems are still out. Robeson needs 4 tankers at hour 22 and holds 0, so 2 from Wake leave a gap of 2; sending 4 closes it | Design doc p. 8 says "its color is recalculated"; plan v2 §7 step 7 | Engine (to build); demo script | Team to confirm the wording of demo step 7 |
| In answer-key mode, need after deliveries = true need minus confirmed deliveries | Plan v2 Phase 2 test "its need drops" | Engine (to build) | n/a |
| Wake's nearest edge is 0.25 km outside the 50 km band. The generator fails loudly if the hit set changes, and the data check confirms Wake stays grey | Plan v2 §3 | Generator and its checks | Pick another grey sender if the track moves |
| For the stranger test's "biggest water gap" question, give the tester a mode and an hour: in answer-key mode several counties tie | Plan v2 §6 stranger test | Test script for Kyle | n/a |


## Added in Phase 1 (answer-key mode)

| Item | Source | Where it lives | If the team says no |
|---|---|---|---|
| Purple runs for hours *last contact + 12 ≤ h < next contact*. At the next contact hour the county is back to its color, so Pender is purple 20 to 35 and back at 36 | Design doc silence rule (Proposal); data README "Purple 20 to 36" | `engine.state_at`, `SILENCE_HOURS` | If 36 should still be purple, change `>=` handling in `state_at` and the tests' `_purple_hours` |
| Contact = any report or any feed reading for the county (Fix 1) | Plan v2 Fix 1 | `engine.build_scenario` (`contacts`) | Reports only: almost every hit county goes purple (see Fix 1 row above) |
| While a county is purple, its panel shows lifelines and need *as last known at last contact*, labelled with that hour, not the answer key's current values | Design doc: silent = "Status unknown"; SKYZR doesn't guess | `engine.state_at` (`lifelines_as_of`) | Show the answer key's current values in the panel (the map stays purple either way) |
| In answer-key mode a non-silent county's lifeline colors and need follow the answer key every hour, not only at report hours | Design doc: "Until the AI reading step works, test mode colors the map straight from the answer key" | `engine.state_at` | n/a |
| Status words: Urgent need, Moderate need, Needs met or minimal, Silent: no contact, Not hit | Design doc color table (wording shortened) | `engine.STATUS_WORD` | Change the strings |
| "Last report" counts reports only; "last contact" counts reports and feeds | Design doc panel header; Fix 1 | `engine.state_at` | n/a |
| Playback: the cursor follows the live head only when it is at the live head; while reviewing an earlier hour during play, the live head keeps moving and the view stays put. "Back to live" jumps the view to the live head without starting play | Plan v2 Fix 2 (doesn't say what play does to a cursor held back) | `engine.tick`, app "Back to live" button | Make any slider move pause playback |
| Dragging the slider past the live head snaps it back to the live head with a one-line note | Plan v2 Fix 2 | `engine.move_cursor`, `app.on_slider` | n/a |
| Grey counties show stock to send; their need is blank, not zero | Design doc panel section 3; Fix 4 | `engine.state_at` (`need: None`) | n/a |

## Added in Phase 2A (engine only; confirmation waits for the 9:00 call)

| Item | Source | Where it lives | If the team says no |
|---|---|---|---|
| Transit time is fixed at dispatch from the receiver's Roads color then (for a silent receiver, its last known Roads color). A later Roads change doesn't shorten or lengthen a shipment already sent | Design doc Proposal "6, or 12 if Roads is red"; doesn't say when Roads is read | `engine.direct_supplies` (`transit_hours`) | Recompute arrival from Roads at each hour |
| Until delivery confirmation is decided, a shipment past its transit time shows "Arrived, not confirmed" and stays counted as in transit at the receiver. It never reaches the receiver's on-hand stock, need or color. This keeps total stock conserved | Design doc p. 8: on-hand rises only on an accepted confirmation; confirmation itself is out of scope tonight | `engine.shipment_status`, `engine.apply_events` | Phase 2B decides what an accepted confirmation does |
| Receivers must be in the storm path; senders can be any county with stock, hit or grey | Design doc: "From a hit county's panel, click Direct supplies"; sending list is every county with stock | `engine.direct_supplies` | Allow grey receivers by deleting one check |
| A county can't send to itself; quantity must be a whole number above zero; role and reason must be non-blank | Design doc: reason required; role stamped on every action | `engine.direct_supplies` | n/a |
| The log is a tuple of frozen entries; adding returns a new tuple. Nothing in the engine edits or deletes an entry | Design doc: no one can edit or delete a log entry | `engine.DirectSupplies`, `engine.direct_supplies` | n/a |
| A refused action raises `ActionRefused` and logs nothing | Design doc: Confirm stays disabled until valid | `engine.ActionRefused` | n/a |
| Reviewing an hour before a dispatch shows the stock as it was then (the log is replayed up to the cursor) | Plan v2 Fix 2: everything recomputed from the log up to the cursor | `engine.apply_events` | n/a |

## Added in Phase 2B-safe (branch phase-2)

| Item | Source | Where it lives | If the team says no |
|---|---|---|---|
| Role picker: a label at the top of the page (Situation analyst, Logistics, Operations chief, Other), no password, stamped on every action. Starts empty; Direct supplies asks for a role first | Design doc p. 3, **Proposal** | `engine.ROLES`; `app.py` role selectbox | Remove the picker and stamp a fixed role, e.g. "Other" |
| Every sent shipment reads "In transit" on screen and in the CSV, including after its transit time, until delivery confirmation is decided | Team instruction for Phase 2B-safe; design doc p. 8 | `engine.display_status` | Phase 2B shows arrival and confirmation |
| Sending list: every other county (hit or grey), alphabetical by name only, each with its on-hand stock of the chosen resource. Counties with 0 are listed too, so the list is never filtered by stock | Design doc p. 7 | `engine.sender_options` | Hide counties with 0 stock (a filter, still alphabetical) |
| Nothing is preselected: resource, quantity, sender and reason all start empty, and the form clears after each send | Design doc: SKYZR never suggests a sender or quantity | `app.direct_supplies_form` | n/a |
| The log panel shows entries made at or before the hour on screen; the CSV exports the whole log as of the live hour | Plan v2 Fix 2 (screen recomputed up to the cursor); Fix 3 (CSV is the lasting copy) | `engine.log_rows`, `engine.log_csv` | Export only what's on screen |
| Details read "2 water tankers, Wake to Robeson" using a fixed noun per resource | Design doc p. 4 example | `engine.DETAIL_NOUN` | Change the nouns |
| Streamlit's table toolbar (with its own download) is hidden, so the log's button is the only CSV export | Team instruction | `ui.CSS` | n/a |
