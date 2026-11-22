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

