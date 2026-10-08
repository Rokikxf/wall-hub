# Contracts

The hub's own copies of the wall-\* output contracts. Each tool's repo has the
original `schema.json`. These copies record what the hub's code understands.

```
<tool>/v<major>.json    schema for every <major>.x version of the tool's output
<tool>/examples/*.json  valid example documents, used as test fixtures
```

`inventory/contracts.py` validates each tool document against the copy matching
the major number in its `schema_version`. A minor version (new optional fields)
validates against the existing copy, so a tool can be upgraded without changing
the hub. A new major version is rejected until a `v<major>.json` and the code to
handle it are added here.

`tests/test_contracts.py` checks three things:
- every example follows its contract;
- deliberately broken documents are rejected;
- the shared envelope is identical in all contracts.

The rules themselves are in `CONTRACT.md` in the tool template repository.
