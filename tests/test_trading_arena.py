"""Paper-trading arena: bots that die if they don't make money (no real money, no broker)."""
import math
import random
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from forgemind import trading_arena as ta


def series(prices, start=date(2026, 1, 1)):
    return [{"date": (start + timedelta(days=i)).isoformat(), "close": p, "high": p * 1.01, "low": p * 0.99}
            for i, p in enumerate(prices)]


UP = series([100 * (1.004 ** i) + 3 * math.sin(i / 3) for i in range(300)])
DOWN = series([100 * (0.997 ** i) + 3 * math.sin(i / 3) for i in range(300)])


class ArenaTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data = {s: UP for s in ta.SYMBOLS}
        self.clock = [1_800_000_000.0]
        self.arena = ta.TradingArena(Path(self.dir.name) / "arena.json", fetch=lambda s: self.data[s],
                                     clock=lambda: self.clock[0], rng=random.Random(3))

    def tearDown(self):
        self.dir.cleanup()

    def test_only_bots_that_made_money_in_a_backtest_are_born_and_they_start_on_new_bars(self):
        self.arena.step()
        alive = self.arena.alive()
        self.assertEqual(len(alive), ta.MAX_ALIVE)
        self.assertTrue(all(b["audition"] > 0 for b in alive))
        self.assertTrue(all(b["days"] == 0 and b["equity"] == ta.START_CASH for b in alive))  # no trades on old bars
        self.assertTrue(all(sum(x["symbol"] == b["symbol"] for x in alive) <= 2 for b in alive))
        keys = [(b["strategy"], str(b["params"]), b["symbol"]) for b in alive]
        self.assertEqual(len(keys), len(set(keys)))
        # nothing new to trade on: running again changes nothing
        self.arena.step()
        self.assertTrue(all(b["days"] == 0 for b in self.arena.alive()))

    def test_losers_die_and_are_replaced(self):
        self.arena.step()
        names = {b["name"] for b in self.arena.alive()}
        crash = [dict(b) for b in UP] + series([UP[-1]["close"] * (0.97 ** (i + 1)) for i in range(15)],
                                               start=date.fromisoformat(UP[-1]["date"]) + timedelta(days=1))
        for b in crash:
            b["high"], b["low"] = b["close"] * 1.001, b["close"] * 0.999
        self.data = {s: crash for s in ta.SYMBOLS}
        self.arena.fetch = lambda s: self.data[s]
        self.arena.step()
        dead = [b for b in self.arena.data["bots"] if b["status"] == "dead"]
        holders = [b for b in dead if b["name"] in names]
        for bot in holders:
            self.assertTrue("lost" in bot["reason"] or "no profit" in bot["reason"], bot["reason"])
        view = self.arena.view()
        self.assertEqual(view["died"], len(dead))
        self.assertIn("Paper only", view["rules"])

    def test_no_profit_after_the_trial_means_death(self):
        bot = {"name": "Flat", "strategy": "momentum", "params": {"fast": 5, "slow": 30}, "symbol": "SPY",
               "cash": ta.START_CASH, "shares": 0.0, "equity": ta.START_CASH, "days": 0, "trades": [], "history": [],
               "status": "alive", "start_day": "2026-01-01"}
        flat = series([100.0] * 40)
        self.arena.data["bots"] = [bot]
        self.arena.fetch = lambda s: flat
        with unittest.mock.patch.object(self.arena, "_spawn"):
            self.arena.step()
        self.assertEqual(bot["status"], "dead")
        self.assertIn(f"no profit after {ta.TRIAL_DAYS} trading days", bot["reason"])

    def test_signals_use_only_the_past(self):
        holding = False
        for i in range(60, len(UP)):
            side = ta.signal("breakout", {"enter": 20, "exit": 10}, UP[:i + 1], holding)
            holding = holding if side == "hold" else side == "buy"
        self.assertEqual(ta.signal("meanrev", {"n": 14, "low": 30, "high": 70}, UP[:5], False), "hold")
        self.assertGreater(ta.backtest("momentum", {"fast": 10, "slow": 50}, UP), 0)
        self.assertLess(ta.backtest("momentum", {"fast": 10, "slow": 50}, DOWN), 0.05)

    def test_runs_once_a_day_after_the_close_and_survives_a_restart(self):
        from datetime import datetime
        morning = datetime(2026, 11, 10, 9, 0).timestamp()
        self.arena.clock = lambda: morning
        self.assertFalse(self.arena.due())
        afternoon = datetime(2026, 11, 10, 15, 0).timestamp()
        self.arena.clock = lambda: afternoon
        self.assertTrue(self.arena.due())
        self.arena.tick()
        self.assertFalse(self.arena.due())
        again = ta.TradingArena(self.arena.path, fetch=lambda s: UP)
        self.assertEqual(len(again.alive()), ta.MAX_ALIVE)


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
