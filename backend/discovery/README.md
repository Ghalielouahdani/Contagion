# backend/discovery/ — owner: P1 (Data & Dependency Discovery)

The service that turns the portfolio into the two "facts" files the rest of the team uses:

```
portfolio.json  ──►  discovery  ──►  dependency_graph.json  +  market_snapshot.json
                       │
                       └── calls one adapter per position (backend/adapters/)
```

Read: blueprint sections 6, 11.1–11.3, 16 P1.

## What to do, step by step

1. **Start in fixture mode on day one.** The entry point (e.g. `discover(portfolio, mode)`) returns the section 11 fixtures when `mode="fixture"`. That unblocks P2, P3 and P4 immediately.
2. **Build the live mode:** for each position, call the right adapter and merge the results:
   - deduplicate shared nodes (USDe and sUSDe appear in several positions; keep one node each, with a stable ID);
   - create one `venue:<id>` node per exit route, with an `exits_via` edge from each position. **Positions that share a venue must point to the same node.** P2 needs this for the joint-exit calculation.
3. **Build the market snapshot:** prices, the sUSDe exchange rate, `markets` (keyed by position_id), `yields` (keyed by position_id), and `exit_venues` (keyed by venue id, with depth, fee and gas). Record `as_of`, `block_number` and `chain_id`.
4. **Add a snapshot cache.** Save each live run to disk with its timestamp, so the demo can replay a frozen snapshot offline.
5. **Validate the output** against the shared schema models before returning it.

## Definition of done

- Fixture mode and live mode return the same JSON shape.
- Every critical edge has evidence; anything unverified is visibly flagged (`to_verify` / `assumed`).
- A frozen demo snapshot is saved and reloads without network access.

## Notes

- Exit depth: use a quote or pool reserves when you can get them. Otherwise keep the proxy `effective_depth_usd`, with `quote_method: "proxy"` and `source_type: "assumed"`.
