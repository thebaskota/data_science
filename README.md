# Fraud Detection Assignment

Seminar project: detect **suspicion** (not proof) of market manipulation, collusion, and spoofing on synthetic Polymarket-style data.

## Setup

```bash
cd data_science
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run analysis

```bash
python fraud_analysis.py
```

Outputs:

| Path | Contents |
|------|----------|
| `output/figures/` | 4 plots (Tasks 2–4) |
| `output/tables/` | QC reports, top markets/accounts/clusters, score weights |
| `report/management_summary.md` | One-page summary with counter-hypotheses |

## Jupyter notebook

```bash
jupyter notebook notebook/fraud_analysis.ipynb
```

Or open in Google Colab: upload CSVs from `polymarket_fraud_seminar_student/` and set `ROOT` to your Drive path.

## Data

CSV files live in `polymarket_fraud_seminar_student/` (8 tables + `data_dictionary.csv`).

## Tasks

1. Data quality & join model  
2. Suspicious markets (top 10)  
3. Account clusters (top 3)  
4. Transparent weighted fraud score  
5. Management summary + counter-hypotheses  
