# Gallery

`index.json` lists the six programs under `examples/`. `playgroundUrl` is a
path on `pythsol serve` (`GET /examples/<id>`); the hosted playground at
`https://www.pythsol.com/playground` serves the same examples from its
template list.

`tests` is `passing` because the repo suite compiles every example and runs
the ones that move lamports or write state in LiteSVM
(`tests/test_examples.py`, `tests/test_examples_litesvm.py`). This file is
not a claim that a weekly gallery job exists, and it is not a list of twenty
examples.
