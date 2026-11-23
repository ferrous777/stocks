---
name: trade-suggestions
description: Daily investment review over the stocks MCP server — scheduled (daily or hourly) or on request. Reads the outlook, real and paper accounts, research and data quality; gives a real broad-allocation preference, any validated real tactical recommendation, and operates the AI-agent PAPER experiment (submits qualified paper orders). Use for "run trade suggestions", "daily investment review", scheduled review tasks, or "what should I buy/short today".
---

# Daily investment review (trade suggestions)

Workflow version **2.0.0**. User policy baseline **`2026-11-21-paper-v2`**. MCP `prompt_version`:
**`trade-suggestions-v2`** (bump it with every change to this skill).

Repo rules in `AGENTS.md` apply to everything here: no fabricated values; unknown stays unknown, never
zero; missing data fails explicitly.

## Read first: authority

1. Read [references/operating-contract.md](references/operating-contract.md) in full. It is the user's
   standing instruction snapshot. Newer explicit user instructions win over it. Older memories and reports
   are dated evidence; they never restore superseded prohibitions or annual return hurdles.
2. Read [references/execution-guide.md](references/execution-guide.md) for the tool map, the evidence
   schema and the persistence layout.
3. Before finishing, read [references/improvement-loop.md](references/improvement-loop.md).
4. Read [references/continuity.md](references/continuity.md) only to bootstrap missing pointers or to
   investigate a known failure. Its observations are dated and are never current facts.

Keep three decisions independent:

| Decision | Required authority and evidence |
|---|---|
| Real broad allocation | A supported ITOT/IVV/alternative versus cash preference, a suitable allocation, and verified account and funds for any size. It needs no tactical Grade A, no 15% forecast and no short bracket. |
| Validated real tactical recommendation | Grade A (validated), a fresh complete live plan and appropriate account evidence. The objective is 15% net per trade within six calendar months, never a guarantee. Recommendations only. |
| AI-agent paper experiment | Only the existing authorized AI-agent PAPER account (`paper-agent`). Grades A/B/C are allowed with an explicit contemporary hypothesis, a defensible complete server plan, costs, a time exit and risk checks. **Actually submit when qualified.** Label unvalidated experiments, and never advise copying them into real accounts. |

**Never:** place real orders; buy options or futures; enroll in margin; operate baseline, strategy or
autonomous accounts (`paper-baseline`, `paper-<strategy>-v<n>`); create a paper account or service; loosen
an existing stop; force a trade; confirm a watch-list change on the user's behalf. The standing paper
authorization applies to this user, this workflow and `paper-agent` only. It does not need daily
reconfirmation.

## Run sequence

Each step's tool calls, fields and fallbacks are listed in the execution guide. Record actual retrieval
start and end times (UTC) around every source call. If one connector fails, keep doing the work it
doesn't block, and record the failure verbatim.

1. **Time and state.** Get the current UTC time, the Pacific date, and the XNYS last completed and next
   session (local `stocks_service.sessions`). Read the latest pointers in `reports/trade-suggestions/`
   (portfolio, entry, six-month, paper, usefulness). Read holdings and activity for every account, and
   every watch list, all pages. Build the instrument union: holdings + saved watch lists + QQQM, GOOGL,
   META, ITOT, IVV + cash. Mark comparator-only rows and unsupported instruments. Never remove an
   instrument. Ask the user to add a missing one (watch-list adds need their yes).
2. **Read Stocks comprehensively.** Read the MCP tool list and server instructions. Then read:
   - the outlook, both sides, every grade including insufficient (`min_grade="insufficient"`), with no
     return filter;
   - `paper-agent`'s account, orders, transactions and performance, plus the matching baseline comparison;
   - predictions for the strongest long and short, every proposed order and every material rejection.

   Check that `last_session_executed` has reached the outlook `asof` and that the account isn't stalled.
   The native horizon is **126 sessions**; never relabel it as six months.
3. **Reconcile and sync.** Only if a complete holdings source (e.g. a Plaid extraction) is available in
   this run:
   - read the destination real account first;
   - upload the complete snapshot under `upload_holdings` rules (omit unknown core cash and unknown
     institution timestamps; Plaid `available` goes to `available_to_withdraw` only);
   - read it back and keep these apart: accepted snapshot, reported positions, ledger positions and
     pending breaks.

   Never invent a transaction to make a readback match. A missing source is "sync skipped: no source",
   not an outage.
4. **Validate data; score due work first.** Check that each price's `asof` is the last completed session,
   and that coverage is complete with no duplicates. Compare historical closes with the previous evidence
   file. Quarantine any material revision until a split or dividend explains it. Score frozen forecasts
   only when they are due, and keep the original versions. A closed-market day creates no new
   independent outcome. Never reuse yesterday's conclusion by default.
5. **Research and compare.** For each instrument, cover:
   - the case for and against;
   - combined trend/MACD/Bollinger evidence;
   - valuation and catalysts;
   - concentration and industry drivers;
   - research quality and account readiness.

   Compare broad allocation, the strongest tactical candidate and cash on matching dates, and state a
   supported preference even if sizing is unresolved. Read applicable rejected-rule tests and event
   audits, including pre-event and through-event windows.
6. **Algorithm work.** Discover the research capabilities in this run (QuanterLab if connected, and the
   service's research endpoints). First retrieve completed jobs and saved results, and don't relaunch
   duplicates. Write down the exact hypothesis, rule, data cutoff, cost model, baseline and evaluation
   window. Test longs and shorts separately, including:
   - gaps, dividends and borrow costs;
   - nearby parameters;
   - out-of-sample periods.

   Queued is not completed. A different model does not test the server bracket. If one candidate fails,
   assess the next credible alternative.
7. **Paper decision.** Apply *Paper sizing and submission* below. Submit when qualified. If nothing
   qualifies, finish the next available discriminating test or data request **in this run**, and record
   its result or real job ID.
8. **Forecasts and measured results.** For every saved instrument, keep:
   - dated next-session research;
   - both-direction six-calendar-month comparisons against cash and QQQM, keeping unavailable, negative
     and below-15% rows;
   - a ranking by supported central net estimate, never by optimistic upside;
   - a separate table of the native 126-session per-position estimates.

   Report `paper-agent`'s actual orders, fills, P&L, costs, equity and drawdown against its paired
   baseline. Keep strategy accounts and historical tests separate.
9. **Persist and check.** Write the readable report and machine-readable evidence. Update **only** the
   pointers whose sections were fully covered, and only after the save is confirmed. Run the checks in
   the execution guide. Do the improvement loop.
10. **Deliver.** See *Delivery*.

## Paper sizing and submission

`scripts/paper_limits.py` is an arithmetic helper, not a signal and not a substitute for server
validation. Read its docstring. Feed it only verified inputs, keep the source of each input in the
evidence, and run it with
`venv/bin/python -I .claude/skills/trade-suggestions/scripts/paper_limits.py <input.json>`. It enforces
the smallest whole-share limit across:

- $1,000 initial notional and 1% of current paper equity per position;
- 0.25% of equity for the planned entry-to-stop loss plus modeled round-trip costs (and full-horizon
  borrow for shorts);
- 10% aggregate experiment gross exposure, including open and reserved orders;
- verified free cash or collateral (short proceeds are not free cash) and every stricter server limit;
- an enforceable time exit within six calendar months of the fill;
- at most **two** new positions per completed-session decision, across reruns.

It rejects the order when even one share doesn't fit. Long returns use cash deployed including entry
costs; short returns use initial short notional. The round-trip cost reserve is separate from the
denominator, and target profit is not expected return. Never round a target return to claim a pass.
Planned stop loss is not maximum loss.

A candidate qualifies only with:
- grade A, B or C (insufficient fails);
- a current written hypothesis;
- a complete server plan;
- a fresh `placeable_until`;
- the correct target session;
- liquidity and event checks;
- known costs;
- no failed adopted policy.

Read numeric policy and cost values from the server (documented defaults count). Unknown stays unknown
after checking.

**Submission:**
1. Re-read the account and its orders.
2. Use the key `paper-agent:<SYMBOL>:<side>:<outlook run_id>:<target session>`. Never use wall-clock
   time.
3. Check for an existing order with that key or symbol.
4. Call `place_paper_order` with the current schema.
5. Verify the returned ID and status through `list_orders`. Accepted is not filled.
6. If the result is ambiguous, inspect orders and transactions before retrying with the **same** key.
7. A server risk rejection may be retried once at the server's stated *smaller* quantity. Never retry
   with weaker risk.

## Delivery

At most **120 words**, in three items:
1. the next real purchase or preference, or the named candidate and the exact missing gate;
2. the actual paper actions and results, and both directional verdicts;
3. concrete progress or blocker, plus the full-details link (the report path).

Label every experiment: **"PAPER EXPERIMENT — unvalidated; not a real-money recommendation."** Only a
genuine market-data outage (no outlook and no prices) gets the operational outage message from the
contract. Promise a retry only once one is actually scheduled. A missing optional connector, one ticker
or a paper credential is not an outage.

## Improve this skill during use

The user authorizes ongoing maintenance. Follow [references/improvement-loop.md](references/improvement-loop.md):
fix demonstrated procedural errors, add a regression test, validate, and save through the repo's PR
workflow. Never silently expand authority, relax caps, turn research into orders, change schedules,
replace frozen forecasts, adopt a failed strategy, or tune numeric policy after seeing outcomes. Keep
accounts, raw daily evidence and credentials out of skill files.
