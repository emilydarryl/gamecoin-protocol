# Consensus test suite

Run the mainnet-candidate consensus tests with:

```bash
python -m unittest discover -s tests -v
```

The suite must remain deterministic and must not depend on the public seed, wall-clock timing without an injected test time, or mutable network state.
