import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

import yfinance as yf
import yaml


def load_config():
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def check_ticker(ticker, threshold_multiplier):
    start = datetime.now() - timedelta(weeks=205)
    data = yf.Ticker(ticker).history(start=start, interval="1wk")

    if data.empty or len(data) < 200:
        print(f"WARNING: {ticker} has insufficient history ({len(data)} weeks), skipping.")
        return None

    ma_200w = float(data["Close"].tail(200).mean())
    current_price = float(data["Close"].iloc[-1])
    pct_above = (current_price / ma_200w - 1) * 100

    return {
        "ticker": ticker,
        "price": current_price,
        "ma": ma_200w,
        "pct_above": pct_above,
        "triggered": current_price <= ma_200w * threshold_multiplier,
    }


def send_email(triggered, gmail_address, gmail_password):
    lines = [f"Stock Monitor — {datetime.now().strftime('%Y-%m-%d')}", ""]
    lines.append("The following stocks are at or near their 200-week moving average:")
    lines.append("")
    for s in triggered:
        direction = "below" if s["pct_above"] < 0 else "above"
        lines.append(
            f"  {s['ticker']:<6}  Current: ${s['price']:.2f}"
            f"   200w MA: ${s['ma']:.2f}"
            f"   ({abs(s['pct_above']):.1f}% {direction} MA)"
        )
    body = "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"Buy signal: {', '.join(s['ticker'] for s in triggered)}"
    msg["From"] = gmail_address
    msg["To"] = gmail_address

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_password)
        server.send_message(msg)

    print(f"Email sent for: {', '.join(s['ticker'] for s in triggered)}")


def main():
    config = load_config()
    threshold_pct = config.get("threshold_pct", 5)
    threshold_multiplier = 1 + threshold_pct / 100
    watchlist = config["watchlist"]

    print(f"Checking {len(watchlist)} stocks | threshold: within {threshold_pct}% of 200-week MA")
    print()

    results = []
    for ticker in watchlist:
        result = check_ticker(ticker, threshold_multiplier)
        if result:
            status = "TRIGGER" if result["triggered"] else "ok"
            print(f"  {ticker:<6}  ${result['price']:.2f}  |  MA ${result['ma']:.2f}  |  [{status}]")
            results.append(result)

    triggered = [r for r in results if r["triggered"]]

    print()
    if not triggered:
        print("No signals today.")
        return

    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_address or not gmail_password:
        print("ERROR: Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD env vars to send email.")
        sys.exit(1)

    send_email(triggered, gmail_address, gmail_password)


if __name__ == "__main__":
    main()
