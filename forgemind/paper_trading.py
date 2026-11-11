"""Append-only simulated, cash-only trading journal. No broker or order API."""
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class PaperBook:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS fills (id TEXT PRIMARY KEY, at TEXT, payload TEXT)')

    def _state(self, db):
        cash, realized, positions = 10000.0, 0.0, {}
        rows = db.execute('SELECT id,at,payload FROM fills ORDER BY rowid').fetchall()
        for _, _, raw in rows:
            f = json.loads(raw)
            p = positions.setdefault(f['symbol'], {'quantity': 0.0, 'cost': 0.0})
            q, price, fee = f['quantity'], f['price'], f['fee']
            if f['side'] == 'buy':
                cash -= q * price + fee
                p['quantity'] += q
                p['cost'] += q * price + fee
            else:
                basis = p['cost'] * q / p['quantity']
                cash += q * price - fee
                realized += q * price - fee - basis
                p['quantity'] -= q
                p['cost'] -= basis
        return {'mode': 'simulation', 'starting_cash': 10000, 'cash': cash, 'realized_pnl': realized,
                'positions': positions, 'fills': [{'id': i, 'at': at, **json.loads(raw)} for i, at, raw in rows],
                'note': 'Prices are supplied observations, not a live feed. No broker connected. '
                        'Unrealized P&L requires fresh quotes; simulated fills do not prove live returns.'}

    def report(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            return self._state(db)

    def fill(self, *, request_id, symbol, side, quantity, price, source, observed_at, thesis, fee=0):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', request_id):
            raise ValueError('Use a stable unique request_id (8–100 letters/numbers/dashes).')
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Za-z0-9.^/_-]{1,24}', symbol):
            raise ValueError('Invalid symbol.')
        if side not in ('buy', 'sell'):
            raise ValueError('Side must be buy or sell.')
        for n in (quantity, price, fee):
            if isinstance(n, bool) or not isinstance(n, (float, int)) or not math.isfinite(n):
                raise ValueError('Quantity, price and fee must be finite numbers.')
        if quantity <= 0 or price <= 0 or fee < 0 or not math.isfinite(quantity * price):
            raise ValueError('Use positive quantity/price and a nonnegative fee.')
        if not all(isinstance(s, str) and s.strip() and len(s) <= 2000 for s in (source, observed_at, thesis)):
            raise ValueError('Provide a quote source, observation time and pre-trade thesis.')
        stamp = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
            raise ValueError('Observation time must include a timezone and cannot be in the future.')
        f = dict(symbol=symbol.upper(), side=side, quantity=quantity, price=price, fee=fee,
                 source=source, observed_at=observed_at, thesis=thesis)
        raw = json.dumps(f, sort_keys=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload FROM fills WHERE id=?', (request_id,)).fetchone()
            if existing:
                if existing[0] != raw:
                    raise ValueError('This request_id already identifies a different fill.')
                return self._state(db)
            state = self._state(db)
            if side == 'buy' and quantity * price + fee > state['cash']:
                raise ValueError('Insufficient simulated cash.')
            if side == 'sell' and quantity > state['positions'].get(symbol.upper(), {}).get('quantity', 0):
                raise ValueError('Cannot sell more than the simulated holding.')
            db.execute('INSERT INTO fills VALUES (?,?,?)',
                       (request_id, datetime.now(timezone.utc).isoformat(), raw))
            return self._state(db)
