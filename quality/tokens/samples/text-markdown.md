## Commands

| Task | Command | Notes |
|---|---|---|
| Run the tests | `make test` | uses `pytest -q` with coverage |
| Build the docs | `make docs` | output in `site/` |
| Release | `./scripts/release.sh v1.4.2` | needs a clean tree and a signed tag |
| Check types | `mypy --strict src/tides` | runs in CI on 3.11 and 3.13 |

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q --maxfail=1 tests/test_tides.py::test_spring_tide
```

### Configuration

- `TIDES_DATA_DIR` (default `./data`): folder with the harmonic constants.
  - Files are named `<station-id>.json`, for example `DE-0042.json` or `NL-0117.json`.
  - Each file has `amplitude_m`, `phase_deg` and `speed_deg_per_h` for every constituent.
- `TIDES_CACHE_TTL=3600`: seconds a computed table stays in memory.
- `TIDES_LOG_LEVEL` is one of `debug`, `info`, `warning`; never log positions.

See [the station list](docs/stations.md#north-sea) and **never** commit files from `data/private/`.

> Note: version 1.4 changed the JSON schema (`speed` → `speed_deg_per_h`); run `tides migrate --from 1.3` once.

```json
{"station": "DE-0042", "constituents": [{"name": "M2", "amplitude_m": 1.42, "phase_deg": 318.7}]}
```
