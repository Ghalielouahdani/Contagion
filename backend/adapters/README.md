# backend/adapters/ — owner: P1 (Data & Dependency Discovery)

One adapter per protocol or token family. Each answers "what does this entity depend on?" by
reading contracts at the pinned block (and protocol APIs as a second source), writing typed nodes
and evidence-backed edges into the shared graph, and returning the entities to explore next. The
explorer in `backend/discovery/` runs them; see that README for how to run discovery.

```python
class Adapter(Protocol):                       # base.py
    name: str
    def accepts(self, entity: Entity, ctx: Ctx) -> bool: ...
    def discover(self, entity: Entity, ctx: Ctx) -> list[Entity]: ...   # follow-ups
```

`Entity(kind, key)`: `token`, `pendle_market`, `morpho_market`, `aave_market`, `collateral_scan`.
`Ctx` carries the clients, the registry, the graph builder, the pinned block and the shared outputs
(market parameters and yields per position, facts, unresolved items, warnings). Any asset an adapter
touches is queued for exploration, so an oracle reading USDT leads to USDT's issuer.

| file | handles | reads |
|------|---------|-------|
| `ethena.py` | USDe, sUSDe | `minter()` vs Ethena's published minting contract, `asset()`, `convertToAssets`, cooldown, rewards vesting; backing from docs (documented) |
| `pendle.py` | Pendle market, PT, SY | `readTokens`, `readState` (implied rate, reserves, scalar root, fee), `SY()`, `yieldToken()`, `exchangeRate()`, `assetInfo()`; Pendle API to cross-check ids, expiry, implied APY and read liquidity |
| `morpho.py` | Morpho Blue market | `idToMarketParams`, `market`, IRM `borrowRateView`; Morpho API to cross-check and to list markets accepting a collateral |
| `aave.py` | Aave v3 collateral/debt pair | provider → Pool/DataProvider/Oracle, reserve config and rates, eMode bitmaps (v3.2+), `getSourceOfAsset` |
| `oracles.py` | any oracle address | recursive introspection (meta-oracle, Morpho ChainlinkOracleV2, Aave capped/ratio adapters, Pendle linear discount, Chainlink feeds, EIP-1167 proxies) → drivers → USDe pass-through |
| `collateral.py` | layer-5 scan for PTs | Morpho markets with this exact collateral, Aave reserve lists (negative results recorded) |
| `venues.py` | exit venues | joint and standalone executable quotes (Pendle router for PTs, KyberSwap otherwise) → depth for the proxy |
| `tokens.py` | any ERC-4626 / ERC-20 | vault → underlying (verified); issuer only from the registry, otherwise unresolved |
| `sources.py` | — | read-only JSON-RPC client (block pinning, Multicall3, retries, endpoint fallback) and HTTP client, both recorded/replayed through a cassette |
| `registry/ethereum.json` | — | protocol entry points and canonical token addresses with their source URL (the only hand-entered addresses) |

`market_id` per protocol: Pendle = market address, Morpho = market id (bytes32), Aave =
`<PoolAddressesProvider>` or `<PoolAddressesProvider>#emode=<id>` (without it, the eligible eMode with
the highest LT is chosen and flagged as inferred).

## Evidence and confidence

Every edge carries `method` (onchain_call, protocol_api, protocol_documentation, third_party_api,
fixture), `reference` (contract address or URL), `observed_at`, `block_number` for on-chain reads,
`call` (e.g. `PT.SY()`), `note` (why the edge exists) and a `confidence`:

- `verified`: read on-chain at the pinned block, or two sources agree (e.g. on-chain minter = documented minter);
- `documented`: published by the protocol, not observable on-chain (Ethena custody/backing);
- `inferred`: derived by a stated rule (feed description → asset by symbol, chosen eMode, exit route);
- `assumed`: team assumption (only the venue fallback in `backend/discovery/assumptions.json`).

## Rules kept

- A missing field becomes a warning or an `unresolved` entry, never an invented value.
- Two tokens are never merged on their symbol; identity is `(chain_id, address)`.
- An oracle price is not the spot price: each market records which oracle it consumes and what that oracle reads.
- TVL is not exposure; RPCs are read-only; no keys or secrets in outputs (`ETH_RPC_URL` is recorded as `env:ETH_RPC_URL`).

## Adding a protocol

1. Add its entry points to `registry/ethereum.json` (with the source URL).
2. Write `<protocol>.py` with `accepts` / `discover`, writing nodes, edges with evidence, and (for a
   position's market) `ctx.market_params[position_id]` in the matching `contracts/schemas/v1/markets/` shape.
3. Register it in `default_adapters()` (`__init__.py`), record a cassette for an example, add a replay test.
