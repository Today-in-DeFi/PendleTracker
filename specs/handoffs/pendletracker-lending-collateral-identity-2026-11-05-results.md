# Morpho PT collateral identity handback — 2026-11-05

All 13 requested chain/PT identities are linked below. Existing cross-chain inventory and six matching prior route-export identities were reused. Live Pendle metadata and chain identity reads were added; no quote routes or full route diligence were repeated.

Machine evidence: `data/research/pt-collateral-identity-2026-11-05/identities.json`.
Collection completed UTC: 2026-11-05T03:25:01.384453+00:00
Original Morpho allocation source snapshot: 2026-11-05T03:06:19.191456+00:00
Inventory snapshot: 2026-11-04T10:08:00.101771+00:00; immutable identities were selectively rechecked, without treating old quote clocks as fresh quotes.

RiskAnalyst owns assessment scope and grades. This handback assigns no score, transfers no Ethereum grade to Monad, and treats PT, SY wrapper, accounting asset and underlying asset as separate identities. It adds no execution-route gate to FarmAnalyst screening.

## Exact deployment links

| Chain | PT | PT contract | Pendle market | SY | Underlying | Maturity UTC | Verification |
|---|---|---|---|---|---|---|---|
| 1 | PT-reUSD-10DEC2026 | `0xecfafdc7741323a945a163ed068b5a3c43483957` | `0x13285bcbc27f92b47b4edb99d744c07b48c977c0` | `0x9487bd5a3b16ecb5f3184453e3ee75b800141648` | reUSD `0x5086bf358635b81d8c47c66d1c8b9e567db70c72` | 2026-12-10T00:00:00+00:00  | api_and_onchain_identity_verified |
| 1 | PT-USD3-17DEC2026 | `0x7f47c3e6b2c00fc4eb4d5ae50d0ab0ab6888eb4d` | `0x4a5067c3ff1abb7449244025b0e37feaf77d8e3e` | `0xea3bc608f32847b97965c5e1648bdfcd4c2c40d0` | USD3 `0x056b269eb1f75477a8666ae8c7fe01b64dd55ecc` | 2026-12-17T00:00:00+00:00  | api_and_onchain_identity_verified |
| 1 | PT-USDat-14JAN2027 | `0xba96292ee7673e3b546cc90db6d97111cd9a314f` | `0x4ccf6deb3d1895373f604b418ff55d8adae8b846` | `0x7a7de491e1be5287874904e2b7c8488249a4d0a9` | USDat `0x23238f20b894f29041f48d88ee91131c395aaa71` | 2027-01-14T00:00:00+00:00  | api_and_onchain_identity_verified |
| 143 | PT-reUSD-10DEC2026 | `0xbb0dcdd5f0159c3d51d8bce7d84f1b9fa390ef09` | `0xea492a66e98a46426f03f5c3505ee89d96520813` | `0x8c0ee449b8babc933047541249952d5084a7d99d` | reUSD `0xd25f563e12ff616262f8c947fec108db934f8059` | 2026-12-10T00:00:00+00:00  | api_and_onchain_identity_verified |
| 143 | PT-USDat-14JAN2027 | `0xa08a69ab9dd3b04d0992bc7afb2c0b907bbdc147` | `0x88c5d8a908834e44b421cb67aec9a931782f9538` | `0x0898c3346275e79db4892feb1c18875ec154f274` | USDat `0x0bb150dfa86ea5d7742f07fefcd8e8eda81d64ef` | 2027-01-14T00:00:00+00:00  | api_and_onchain_identity_verified |
| 1 | PT-siUSD-7JAN2027 | `0x76543ac61ba84c6feeee76c6a918127bf0ca5fd1` | `0xd44f2630260ff3805d7cb317d4f6740b0044c408` | `0x9f30507c264cc6eb5be35b18ff9ad7b4539aa920` | siUSD `0xdbdc1ef57537e34680b898e1febd3d68c7389bcb` | 2027-01-07T00:00:00+00:00  | api_and_onchain_identity_verified |
| 1 | PT-strUSD-26NOV2026 | `0x74299580811e1c3c1a2831db079ba0a8f513998f` | `0xac028348c46d3455899a2b9b50077c11960eaddb` | `0x7e8a16e87fa6b0f2e657db47f3dbfe2e981ef211` | strUSD `0x280839980a7ed0d7717f64125fe241012e5f5815` | 2026-11-26T00:00:00+00:00  | api_and_onchain_identity_verified |
| 1 | PT-cUSD-23JUL2026 | `0x928fb6ed39100a92b2480f5cbb93453f98d9f4ce` | `0x9eaaeda23177b7168c55a3a0f937f67919733449` | `0x3eaf6c8425b40c554099beed4dcb9f4601942fcb` | cUSD `0xcccc62962d17b8914c62d74ffb843d73b2a3cccc` | 2026-07-23T00:00:00+00:00 EXPIRED | api_and_onchain_identity_verified |
| 1 | PT-trUSD-26NOV2026 | `0x7191878f1fe834b28f4d0cead0e4375b814c4abb` | `0xfcf009cb3135da12a6eb1f73f3ee05392a7bc947` | `0xa09482f2f6cb5f2177b05144bc276d06b8b818eb` | trUSD `0xd0580192e98ea6ceb9c7b6191ed2e27560911697` | 2026-11-26T00:00:00+00:00  | api_and_onchain_identity_verified |
| 1 | PT-fxSAVE-29OCT2026 | `0x079c3469143804af5d0d645a878c371dbe8d038e` | `0x8308e53f584a7e5f0c581059d9ba971c0bec9454` | `0x13945b761b2ed3219a497a46d15a8923f418d2ab` | fxSAVE `0x7743e50f534a7f9f1791dde7dcd89f7783eefc39` | 2026-10-29T00:00:00+00:00 EXPIRED | api_and_onchain_identity_verified |
| 1 | PT-fxSAVE-29APR2027 | `0xc1ea9419dd1dab4dd54aa13b13a766e4de22ebc3` | `0x9df10b8c99dc1a48dd7048a9a524bff9b54a0a30` | `0x7ca334286e9519de99703ab49d4eff6e5559499f` | fxSAVE `0x7743e50f534a7f9f1791dde7dcd89f7783eefc39` | 2027-04-29T00:00:00+00:00  | api_and_onchain_identity_verified |
| 999 | PT-kHYPE-19MAR2026 | `0xea84ca9849d9e76a78b91f221f84e9ca065fc9f5` | `0x31104779b2a07a273d6c662419377773083d0b2e` | `0x57fc55dff8ceca86ee94a6bf255af2f0ed90eb9e` | kHYPE `0xfd739d4e423301ce9385c1fb8850539d657c296d` | 2026-03-19T00:00:00+00:00 EXPIRED | api_and_onchain_identity_verified |
| 999 | PT-kHYPE-24SEP2026 | `0x50fc4edc6346f36993bb30fe60e932504ed17391` | `0xb48b0c95b2ddc464484305b7363fad5bd5b7a683` | `0x57fc55dff8ceca86ee94a6bf255af2f0ed90eb9e` | kHYPE `0xfd739d4e423301ce9385c1fb8850539d657c296d` | 2026-09-24T00:00:00+00:00 EXPIRED | api_and_onchain_identity_verified |

## Accounting and observation boundaries

Ethereum USD3 and Ethereum/Monad reUSD use USDC accounting references; this does not turn the PT or its underlying into USDC. siUSD uses iUSD accounting, strUSD uses trUSD, and fxSAVE uses its separate base-pool accounting asset. HyperEVM kHYPE uses the native HYPE accounting reference at the zero address; zero here is not a missing contract.
Each machine record includes the official market URL, HTTP observation times, cached inventory timestamps, exact PT/SY/YT linkage reads, PT expiry and SY yieldToken/assetInfo observations. Market-detail price-update clocks are recorded separately and are not required to treat an immutable identity as a live price quote.
Ethereum and Monad chain calls use explicit block numbers. HyperEVM default RPC only supports latest state; its before/after headers bound the observation window, and the evidence explicitly does not claim block-pinned calls.

## Expired PTs still reported in targeted live vault allocations

Values below are the vault's lender supply position in a Morpho market labelled with this collateral PT. They are not borrower collateral balances or bad-debt measurements. Dust is preserved without rounding it away.

| Chain | Expired PT | Vault | Morpho market ID | Reported lender supply USD | Position scope | Live HTTP observation UTC |
|---|---|---|---|---|---|---|
| 1 | PT-cUSD-23JUL2026 | Hyperithm USDC Apex `0x093272c07700d3ca5301c3bf9b3a392624179e2f` | `0x702b7ec7628de2622e51e1bb34a7e6ad9e95f3a25a2ed361e4ce621f23f5e642` | 9.99829076e-07 | direct V2 market-adapter lender position | 2026-11-05T03:24:49.118870+00:00 |
| 1 | PT-cUSD-23JUL2026 | Yearn OG USDC `0xb885f6d448da7e2c642ec31190b629e40e87b069` | `0x702b7ec7628de2622e51e1bb34a7e6ad9e95f3a25a2ed361e4ce621f23f5e642` | 9.99829076e-07 | direct V2 market-adapter lender position | 2026-11-05T03:24:51.810890+00:00 |
| 1 | PT-cUSD-23JUL2026 | KPK USDC Yield `0xd5cce260e7a755ddf0fb9cdf06443d593aaeaa13` | `0x702b7ec7628de2622e51e1bb34a7e6ad9e95f3a25a2ed361e4ce621f23f5e642` | 9.99829076e-07 | direct V2 market-adapter lender position | 2026-11-05T03:24:53.961866+00:00 |
| 1 | PT-fxSAVE-29OCT2026 | RockawayX f(x) Protocol Ecosystem USDC `0x2ca22cb25558fa2018ecb1ce4ed8af92ee7ea423` | `0xae992849c5f544a32dfdfcc74c0695b73b8732f449727827af6ce3768e968382` | 30888.778245896745 | direct V2 market-adapter lender position | 2026-11-05T03:24:59.690077+00:00 |
| 1 | PT-fxSAVE-29OCT2026 | Clearstar USDC Core `0x69a238ae7ebeb3c53ff3b544e48b96a2142fc284` | `0xae992849c5f544a32dfdfcc74c0695b73b8732f449727827af6ce3768e968382` | 1500.4466018219682 | direct V2 market-adapter lender position | 2026-11-05T03:25:01.370329+00:00 |
| 999 | PT-kHYPE-19MAR2026 | Felix USDC `0x8a862fd6c12f9ad34c9c2ff45ab2b6712e8cea27` | `0xcd9898604b9b658fc3295f86d4cd7f02fa3a6b0a573879f1db9b83369f4951fb` | 8613.564944337017 | direct V1 vault lender position | 2026-11-05T03:23:12.671023+00:00 |
| 999 | PT-kHYPE-19MAR2026 | Felix HYPE `0x2900abd73631b2f60747e687095537b673c06a76` | `0x6243736b94609da57ca7cb399df512cfae8a112fa5a325d08fd5f4234f5ccd2c` | 0 | direct V1 vault lender position | 2026-11-05T03:23:15.401361+00:00 |
| 999 | PT-kHYPE-24SEP2026 | Felix USDC `0x8a862fd6c12f9ad34c9c2ff45ab2b6712e8cea27` | `0xbdceb93661a9efbd67f97ff2842d159a493f792e71f762c8ba426b586dc1c565` | 7170.703765101632 | direct V1 vault lender position | 2026-11-05T03:23:12.671023+00:00 |
| 999 | PT-kHYPE-24SEP2026 | Felix HYPE `0x2900abd73631b2f60747e687095537b673c06a76` | `0xa13b394993cb7006f2202338fe8a02e88156dd145c1582b5cc466d8ca3a33854` | 2058.9306231969535 | direct V1 vault lender position | 2026-11-05T03:23:15.401361+00:00 |

V2 nested MetaMorpho rows, if present, are labelled as the nested vault's lender supply; they are not a pro-rata valuation of the parent vault's exposure. No overlapping allocation totals are summed.
All original snapshot allocations remain in the machine handback, including any row absent from a later targeted response. Maturity is a review condition, not proof of closure, forfeiture, unrecoverable exposure or bad debt. No producer allocations or positions were edited.

## Verification summary

{"pt_identities": 13, "api_and_onchain_verified": 13, "expired_identities": 4, "reused_route_identities": 6, "live_vault_checks": 7, "positive_expired_allocation_rows": 8}
Evidence hashes and exact unique chain/PT coverage verified; live market/SY/PT/expiry checks retained per record. Read-only request audit confirms no SDK route calls or transaction submission. Exact-chain and ambiguous-mapping rejection checks passed.

## Source references

- Pendle official API overview: https://docs.pendle.finance/pendle-v2-dev/Backend/ApiOverview
- Per-deployment official detail endpoint: `https://api-v2.pendle.finance/core/v1/{chain}/markets/{market}` (actual URL and raw evidence in every record).
- Morpho official allocation API: https://api.morpho.org/graphql (saved query, variables, raw response, source JSON pointers and observation times).
- HyperEVM RPC limitations: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/json-rpc
- FarmAnalyst source queue and discovery snapshot paths plus SHA-256 hashes are in `input_evidence`.

No changes to trades, schedules, assessments, the inventory producer or live monitoring configuration.
