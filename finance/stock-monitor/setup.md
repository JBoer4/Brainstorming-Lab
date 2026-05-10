# Stock Monitor — Setup

Checks your watchlist daily against the 200-week moving average and emails you when a stock touches it.

## Prerequisites

- Python 3.10+
- A Gmail account with 2-Step Verification enabled

## 1. Gmail App Password

You need an App Password — not your regular Gmail password.

1. Go to [myaccount.google.com](https://myaccount.google.com) → **Security**
2. Under "How you sign in to Google", open **2-Step Verification**
3. Scroll to the bottom → **App passwords**
4. Create one named "Stock Monitor" — copy the 16-character password

## 2. GitHub Secrets

In the GitHub repo, go to **Settings → Secrets and variables → Actions → New repository secret**.

Add two secrets:

| Name | Value |
|------|-------|
| `GMAIL_ADDRESS` | your Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-character app password from step 1 |

## 3. GitHub Actions

The workflow in `.github/workflows/stock-monitor.yml` runs automatically on weekdays at ~9am ET.

To trigger a manual run: go to **Actions → Stock Monitor → Run workflow**.

## 4. Local Testing

```bash
cd finance/stock-monitor
pip install -r requirements.txt

# Run without email (no env vars set — will print results and exit with an error on send)
python monitor.py

# Run with email
GMAIL_ADDRESS=you@gmail.com GMAIL_APP_PASSWORD=yourapppassword python monitor.py
```

To force a triggered alert (useful for testing email delivery), temporarily set `threshold_pct: 100` in `config.yaml` — every stock on the watchlist will trigger.

## 5. Customizing Your Watchlist

Edit `config.yaml`:

```yaml
threshold_pct: 5   # within 5% above the 200-week MA

watchlist:
  - AAPL
  - AMZN
  - GOOGL   # add or remove tickers here
```

Use standard ticker symbols (e.g. `GOOGL` not `GOOG`, `BRK-B` not `BRK.B`).
