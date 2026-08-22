# console-contracts

The only public-domain contract source for Console V2. DTOs serialize with
camelCase names, normalized positions use `0.0..=1.0`, and raw sidecar vectors
are explicit `raw*` fields. Generate the checked-in UI projection with:

```powershell
pnpm generate:contracts
pnpm check:contracts
```
