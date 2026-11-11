"""Trading arena: paper-trading bots that die if they don't make money (the owner 2026-11-09: "I liked that idea where we
have one bot that dies if it doesn't make money, specifically the AI trading bot, we can test it out with that one").

PAPER ONLY: fake $1,000 per bot, real daily closing prices (Yahoo's public chart feed, once a day), fees + slippage
counted. No broker, no real orders.

- Birth: a new bot (strategy + parameters + one symbol) must first make money in a backtest on the last ~6 months;
  only then does it go live (trades from the NEXT new daily bar on, never on bars it has already seen).
- Life: once per new trading day each live bot reads its signal from past prices only and trades all-in / all-out at
  that day's close.
- Death: after TRIAL_DAYS live days with equity below its start, or as soon as it's down MAX_DRAWDOWN, it dies (kept in
  the graveyard with the reason). Replacements are mutated from the best live bot (or random), so the arena keeps
  MAX_ALIVE bots and the strategies that make money survive.
"""
from __future__ import annotations

import json
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

START_CASH = 1000.0
TRIAL_DAYS = 10
MAX_DRAWDOWN = 0.10
MAX_ALIVE = 6
FEE = 0.0005                 # 5 bps per trade for fees + slippage
SYMBOLS = ["SPY", "QQQ", "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "META", "AMZN", "GOOGL"]
STRATEGIES = {
    "momentum": {"fast": [5, 10, 20], "slow": [30, 50, 100]},
    "meanrev": {"n": [7, 14], "low": [25, 30, 35], "high": [55, 60, 70]},
    "breakout": {"enter": [10, 20, 55], "exit": [5, 10, 20]},
}
NAMES = ["Ace", "Blitz", "Cobra", "Dash", "Echo", "Flux", "Ghost", "Hex", "Ion", "Jinx", "Kilo", "Lynx", "Moxie",
         "Nitro", "Onyx", "Pike", "Quark", "Rook", "Sable", "Tango", "Umbra", "Vex", "Wolf", "Xeno", "Yuki", "Zed"]


def fetch_yahoo(symbol: str) -> list[dict]:
    """~1 year of daily bars from Yahoo's public chart endpoint: [{date, close, high, low}] oldest first."""
    import requests
    response = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                            params={"range": "1y", "interval": "1d"}, headers={"User-Agent": "Mozilla/5.0 Doxa"},
                            timeout=(5, 20))
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    bars = []
    for ts, close, high, low in zip(result.get("timestamp") or [], quote.get("close") or [], quote.get("high") or [],
                                    quote.get("low") or []):
        if close is None or high is None or low is None:
            continue
        bars.append({"date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"), "close": float(close),
                     "high": float(high), "low": float(low)})
    return bars


# --- signals (each uses only bars up to and including the current one) -------------------------------------------
def _sma(values, n):
    return sum(values[-n:]) / n if len(values) >= n else None


def _rsi(values, n):
    if len(values) <= n:
        return None
    gains = losses = 0.0
    for a, b in zip(values[-n - 1:-1], values[-n:]):
        change = b - a
        gains += max(change, 0)
        losses += max(-change, 0)
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def signal(strategy: str, params: dict, bars: list[dict], holding: bool) -> str:
    """'buy', 'sell' or 'hold' at the last bar."""
    closes = [b["close"] for b in bars]
    if strategy == "momentum":
        fast, slow = _sma(closes, params["fast"]), _sma(closes, params["slow"])
        if fast is None or slow is None:
            return "hold"
        if not holding and closes[-1] > fast > slow:
            return "buy"
        if holding and closes[-1] < fast:
            return "sell"
    elif strategy == "meanrev":
        rsi = _rsi(closes, params["n"])
        if rsi is None:
            return "hold"
        if not holding and rsi < params["low"]:
            return "buy"
        if holding and rsi > params["high"]:
            return "sell"
    elif strategy == "breakout":
        enter, leave = params["enter"], params["exit"]
        if len(bars) <= max(enter, leave):
            return "hold"
        if not holding and closes[-1] > max(b["high"] for b in bars[-enter - 1:-1]):
            return "buy"
        if holding and closes[-1] < min(b["low"] for b in bars[-leave - 1:-1]):
            return "sell"
    return "hold"


def _trade(bot, side, bar):
    price = bar["close"]
    if side == "buy" and bot["cash"] > 0:
        qty = bot["cash"] * (1 - FEE) / price
        bot.update(shares=qty, cash=0.0)
        bot["trades"].append({"date": bar["date"], "side": "buy", "price": round(price, 4), "qty": round(qty, 6)})
    elif side == "sell" and bot["shares"] > 0:
        bot["cash"] = bot["shares"] * price * (1 - FEE)
        bot["trades"].append({"date": bar["date"], "side": "sell", "price": round(price, 4),
                              "qty": round(bot["shares"], 6)})
        bot["shares"] = 0.0
    bot["trades"] = bot["trades"][-60:]


def equity(bot, price) -> float:
    return bot["cash"] + bot["shares"] * price


def backtest(strategy, params, bars, days=126) -> float:
    """Return of the strategy over the last `days` bars (paper, with fees). 0.0 when there isn't enough history."""
    if len(bars) < days + 120:
        return 0.0
    bot = {"cash": START_CASH, "shares": 0.0, "trades": []}
    for i in range(len(bars) - days, len(bars)):
        side = signal(strategy, params, bars[:i + 1], bot["shares"] > 0)
        if side != "hold":
            _trade(bot, side, bars[i])
    return equity(bot, bars[-1]["close"]) / START_CASH - 1


class TradingArena:
    def __init__(self, path: Path, fetch=fetch_yahoo, clock=time.time, rng=None, notify=None):
        self.path = Path(path)
        self.fetch, self.clock = fetch, clock
        self.rng = rng or random.Random()
        self.notify = notify or (lambda text: None)
        self.lock = threading.RLock()
        self.running = False
        try:
            self.data = json.loads(self.path.read_text("utf-8"))
            if not isinstance(self.data.get("bots"), list):
                raise ValueError
        except (OSError, ValueError, AttributeError):
            self.data = {"bots": [], "last_day": "", "status": "", "born": 0, "died": 0}

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1), "utf-8")
            tmp.replace(self.path)

    def alive(self):
        return [b for b in self.data["bots"] if b["status"] == "alive"]

    # --- birth ----------------------------------------------------------------------------------------------------
    def _candidate(self):
        alive = self.alive()
        best = max(alive, key=lambda b: b["equity"], default=None)
        if best and best["equity"] > START_CASH and self.rng.random() < 0.6:  # mutate a winner
            strategy, params, symbol = best["strategy"], dict(best["params"]), best["symbol"]
            key = self.rng.choice(list(STRATEGIES[strategy]))
            params[key] = self.rng.choice(STRATEGIES[strategy][key])
            if self.rng.random() < 0.4:
                symbol = self.rng.choice(SYMBOLS)
            parent = best["name"]
        else:
            strategy = self.rng.choice(list(STRATEGIES))
            params = {k: self.rng.choice(v) for k, v in STRATEGIES[strategy].items()}
            symbol, parent = self.rng.choice(SYMBOLS), ""
        if strategy == "momentum" and params["fast"] >= params["slow"]:
            params["fast"] = min(STRATEGIES["momentum"]["fast"])
        return strategy, params, symbol, parent

    def _spawn(self, bars_for, today):
        tries = 0
        while len(self.alive()) < MAX_ALIVE and tries < 40:
            tries += 1
            strategy, params, symbol, parent = self._candidate()
            alive = self.alive()
            if any((b["strategy"], b["params"], b["symbol"]) == (strategy, params, symbol) for b in alive) or \
                    sum(b["symbol"] == symbol for b in alive) >= 2:
                continue  # no twins, at most two bots per stock: spread the bets
            bars = bars_for(symbol)
            if not bars:
                continue
            audition = backtest(strategy, params, bars)
            if audition <= 0:
                continue  # only strategies that made money on the last ~6 months go live
            self.data["born"] = self.data.get("born", 0) + 1
            name = f"{NAMES[(self.data['born'] - 1) % len(NAMES)]}-{self.data['born']}"
            self.data["bots"].append({
                "id": f"b{self.data['born']}", "name": name, "strategy": strategy, "params": params, "symbol": symbol,
                "parent": parent, "audition": round(audition * 100, 2), "born": today, "start_day": bars[-1]["date"],
                "cash": START_CASH, "shares": 0.0, "equity": START_CASH, "days": 0, "trades": [], "history": [],
                "status": "alive", "died": "", "reason": ""})
            self.notify(f"Trading arena: {name} is born ({strategy} on {symbol}, +{audition * 100:.1f}% in its backtest).")

    # --- a trading day -------------------------------------------------------------------------------------------
    def step(self) -> str:
        """Fetch prices once, trade every live bot on the newest bar it hasn't seen, bury losers, spawn new bots."""
        cache = {}

        def bars_for(symbol):
            if symbol not in cache:
                try:
                    cache[symbol] = self.fetch(symbol)
                except Exception:
                    cache[symbol] = []
            return cache[symbol]

        today = datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d")
        with self.lock:
            for bot in self.alive():
                bars = bars_for(bot["symbol"])
                new = [b for b in bars if b["date"] > (bot["history"][-1]["date"] if bot["history"] else bot["start_day"])]
                for bar in new:
                    seen = [b for b in bars if b["date"] <= bar["date"]]
                    side = signal(bot["strategy"], bot["params"], seen, bot["shares"] > 0)
                    if side != "hold":
                        _trade(bot, side, bar)
                    bot["equity"] = round(equity(bot, bar["close"]), 2)
                    bot["days"] += 1
                    bot["history"] = (bot["history"] + [{"date": bar["date"], "equity": bot["equity"]}])[-120:]
                    if bot["equity"] < START_CASH * (1 - MAX_DRAWDOWN):
                        reason = f"lost {100 - bot['equity'] / START_CASH * 100:.1f}% (limit {MAX_DRAWDOWN:.0%})"
                    elif bot["days"] >= TRIAL_DAYS and bot["equity"] <= START_CASH:
                        reason = f"no profit after {bot['days']} trading days"
                    else:
                        continue
                    bot.update(status="dead", died=bar["date"], reason=reason)
                    self.data["died"] = self.data.get("died", 0) + 1
                    self.notify(f"Trading arena: {bot['name']} died: {reason}.")
                    break
            self._spawn(bars_for, today)
            self.data["bots"] = self.alive() + [b for b in self.data["bots"] if b["status"] == "dead"][-30:]
            live = self.alive()
            total = sum(b["equity"] for b in live)
            self.data.update(last_day=today, status=f"{len(live)} bots alive, ${total:,.0f} paper equity "
                             f"(started with ${START_CASH * len(live):,.0f}).")
            self.save()
        return self.data["status"]

    def due(self) -> bool:
        """Once a day, after the US close (4:30 PM New York ≈ 1:30 PM in California)."""
        now = datetime.fromtimestamp(self.clock())
        return self.data.get("last_day") != now.strftime("%Y-%m-%d") and now.hour >= 14 and not self.running

    def tick(self):
        if not self.due():
            return None
        self.running = True
        try:
            return self.step()
        finally:
            self.running = False

    def view(self) -> dict:
        def row(b):
            return {k: b.get(k) for k in ("name", "strategy", "symbol", "params", "equity", "days", "audition",
                                          "status", "reason", "born", "died", "parent")} | {
                "trades": len(b["trades"]), "last": b["trades"][-1] if b["trades"] else None}
        live = self.alive()
        return {"alive": [row(b) for b in sorted(live, key=lambda b: -b["equity"])],
                "dead": [row(b) for b in self.data["bots"] if b["status"] == "dead"][-8:][::-1],
                "born": self.data.get("born", 0), "died": self.data.get("died", 0), "status": self.data.get("status", ""),
                "last_day": self.data.get("last_day", ""), "rules": f"Paper only. ${START_CASH:,.0f} each. Dies after "
                f"{TRIAL_DAYS} trading days without profit or at -{MAX_DRAWDOWN:.0%}."}
