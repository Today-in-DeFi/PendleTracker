# USDe fixed-term market evidence — 2026-11-18

Four Ethereum USDe markets are present in Pendle’s V2 directory and readable through existing public detail, data and SDK token readers. All are absent from the checked PT export, generated November 4 before the reported launch. This is evidence of stale export coverage, not a need for a new reader. These are USDe markets, not sUSDe. Economic structure and redemption controls remain unreviewed.

Current public API observations (retrieved November 18 around 07:01 UTC; individual source timestamps below). Implied APY is an indicative annualized market rate, not an executable quote. Liquidity is the API’s pool USD metric, not deposit capacity or guaranteed exit depth.

| Maturity | Implied APY | Pool liquidity USD | Source time UTC | Official market |
|---|---:|---:|---|---|
| 2027-02-28 | 5.2716% | 39,908.60 | 2026-11-18T06:00:00.000Z | [Market](https://app.pendle.finance/trade/markets/0xf1f53912c156a8c06927746cb20ba11ecec526ce/swap) |
| 2027-05-31 | 5.5000% | 50,842.85 | 2026-11-18T07:00:00.000Z | [Market](https://app.pendle.finance/trade/markets/0x00b0d4645233b74fd84f39ea3df52bd0202a1448/swap) |
| 2027-08-31 | 6.3005% | 36,312.51 | 2026-11-18T06:00:00.000Z | [Market](https://app.pendle.finance/trade/markets/0x1abe622fb6876b98f3aa1cf2ed86a32af954b3f9/swap) |
| 2027-11-30 | 6.0600% | 67,215.19 | 2026-11-18T07:00:00.000Z | [Market](https://app.pendle.finance/trade/markets/0x3f714e7623c33cd9bf1f30c6f1326a4ea933d45b/swap) |

Underlying and accounting asset: Ethereum USDe `0x4c9edd5852cd905f086c759e8383e09bff1e68b3`. SDK mint/redeem token lists identify USDe. Generic aggregator input/output lists do not certify investor eligibility or executable routes. Exact market, PT, YT and SY identities and raw source references are in `return.json`.

Underlying APY and underlying reward APY are zero in these observations. PENDLE-related LP incentives are separately nonzero; “zero Ethena incentives” must not be broadened to zero incentives of every kind.

Gaps: current deposit caps/headroom and holder eligibility were not established by these readers. The reported November 10 announcement, original 5.24–6% launch rates, initial caps and fee-sharing terms were not independently verified from a directly retrieved official announcement in this pass. Do not treat announcement terms as current quotes. No source/controller audit, execution, integration, scheduled job, watchlist change or trade was performed.

`collect.py` reuses the earlier full-directory cache under the sibling srUSDat research folder; matched directory records are embedded in `return.json`. This bundle preserves the 12 current HTTP responses independently.
