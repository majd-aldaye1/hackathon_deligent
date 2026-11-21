# Namesake

Namesake is our entry for Track 2 (Same Person or Not?) of the Grok Bot × Diligent London Financial Crime Hackathon. For every watchlist screening hit, it decides whether the hit is the bank's customer, gives a reason code, a short reason and the records that decided it, and explains all of it.

```bash
system/run dev output/dev.jsonl
```

- [`system/`](system/) holds the runnable system. Its [README](system/README.md) covers the architecture, how both sides are resolved, evidence, determinism and three worked cases.
- [`output/dev.jsonl`](output/dev.jsonl) holds the predictions on the development set, one line per hit.

The data room (`dev/`) is for event participants only, so it is not in this repository.
