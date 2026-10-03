# Run order for real data: make stamp (after committing), then make real
# make real = market, kalshi, market-935, build, analyze, report
PY ?= python3

.PHONY: keygen airdrop stamp-test stamp verify-stamp test synth access kalshi-probe market kalshi-smoke kalshi market-935 build analyze report power real

test:
	$(PY) test_offline.py

synth:
	$(PY) make_synthetic.py --out data_synth --ratio 2.5
	$(PY) build_dataset.py --data data_synth --out results_synth
	$(PY) sensitivity_test.py --table results_synth/event_table.csv --out results_synth
	$(PY) report.py --results results_synth --data data_synth

access:
	$(PY) massive_fetch.py check-access

kalshi-probe:
	$(PY) kalshi_fetch.py --probe KXCPI
	$(PY) kalshi_fetch.py --probe KXCPICORE
	$(PY) kalshi_fetch.py --probe KXFED
	$(PY) kalshi_fetch.py --list-series

market:
	$(PY) massive_fetch.py market --since 2021-11-01 --out data --releases data/releases.csv

kalshi-smoke:
	$(PY) kalshi_fetch.py --out data --since 2021-12-01 --spx data/spx_daily.csv --max-releases 3

kalshi:
	$(PY) kalshi_fetch.py --out data --since 2021-12-01 --spx data/spx_daily.csv --resume

market-935:
	$(PY) massive_fetch.py market --since 2021-11-01 --out data --releases data/releases.csv

build:
	$(PY) build_dataset.py --data data --out results

analyze:
	$(PY) sensitivity_test.py --table results/event_table.csv --out results

report:
	$(PY) report.py --results results --data data

power:
	$(PY) power_sim.py --calibrate results/event_table.csv

keygen:
	$(PY) timestamp_solana.py keygen

airdrop:
	$(PY) timestamp_solana.py airdrop

stamp-test:
	$(PY) timestamp_solana.py stamp --network devnet

stamp:
	$(PY) timestamp_solana.py stamp --network mainnet

verify-stamp:
	$(PY) timestamp_solana.py verify

real: market kalshi market-935 build analyze report
