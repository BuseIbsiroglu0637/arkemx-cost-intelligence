# Data rights policy — M1

## Data categories
1. **Synthetic test data:** internally authored demonstration descriptions and quantities; allowed in repository.
2. **Client-owned quantity takeoff:** permitted only where that client has authority to share/process the material; no public redistribution.
3. **Official/government position and unit-price data:** rights must be reviewed **per source / year / release / usage purpose** before commercial ingestion, copying, storage, indexing, public redistribution or AI inference.

## State machine
`pending` -> `verified` (organization-admin assertion with written evidence and permitted scope) or `rejected` (future moderation workflow). `verified` in M1 is NOT independent external permission verification. No bulk catalog imports exist in M1.

## Planned gate before M2/M3
- Source identity, source address, year/period and SHA256.
- A dated and attributable permission/licence or legal basis for the intended commercial use (not just site availability).
- Legal scope: cache/index AI processing; any republication, sublicensing, sharing and redistribution rights separately.
- Approval by product operator/lawyer before making source usable to tenants.
- Audit of approval, revocation, expiry, corrections and dataset deletion/retention.

Never scrape/copy public price catalogs just because a site allows browsing. Read current source terms and obtain permission if required. This repository includes **no government price schedules**.
