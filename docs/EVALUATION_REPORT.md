# Evaluation replay — last 28 days

Generated 2026-11-04 14:12 UTC by `scripts/replay_evaluation.py` from the synthetic dataset (profile `full`, seed 42). Origins: 2026-10-06, 2026-10-13, 2026-10-20, 2026-10-27. Every number below is computed by the script.

> The data is synthetic (our own demand generator). These figures show how well the planning logic fits
> those demand patterns; they are not a measure of real-world accuracy.

## Forecast error and reorder decisions

| Variant | Store-SKU windows | Forecast WMAPE | Bias | Need accuracy | Precision | Recall | Need-qty WMAPE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 2,862 | 17.7% | 0.2% | 89.6% | 55.9% | 21.2% | 99.2% |
| Model Selection | 2,862 | 18.5% | 1.1% | 89.1% | 49.0% | 16.1% | 101.8% |

Windows excluded because they contain a stockout day (censored sales): 138.

## Forecast WMAPE by category

| Category | Windows | Baseline | Model selection |
|---|---:|---:|---:|
| bakery | 117 | 10.5% | 11.1% |
| beverages | 405 | 18.7% | 19.6% |
| biscuits | 509 | 17.0% | 18.5% |
| dairy | 257 | 12.1% | 12.2% |
| household | 369 | 25.2% | 24.9% |
| personal_care | 514 | 28.1% | 28.1% |
| staples | 691 | 18.7% | 19.7% |

## Methods chosen by model selection (all origins)

| Method | Store-SKU forecasts | Share |
|---|---:|---:|
| BASELINE | 1,961 | 54.5% |
| ETS | 930 | 25.8% |
| CROSTON | 479 | 13.3% |
| TSB | 230 | 6.4% |

## Definitions

- **Forecast WMAPE** = Σ|forecast × window − actual| / Σ actual over store-SKU demand windows (window = supplier lead time for that store + review period). **Bias** = Σ(forecast − actual) / Σ actual.
- **Need** = own requirement > available (closing stock before the origin + receipts arriving in the window). Accuracy / precision / recall compare the need flag from the forecast with the flag from actual demand; **need-qty WMAPE** compares the quantities.
- Model selection: ETS (smooth demand) or Croston-SBA / TSB (intermittent demand) replaces the baseline only when a rolling-origin backtest on the training history shows a > 5% lower WMAPE (D-45).
