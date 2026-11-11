import tempfile
import unittest
from pathlib import Path
from forgemind.paper_trading import PaperBook


class PaperTests(unittest.TestCase):
    def test_fees_basis_persistence_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'book.sqlite3'
            book = PaperBook(path)
            args = dict(request_id='example-001', symbol='TEST', side='buy', quantity=2,
                        price=100, fee=1, source='test fixture', observed_at='2026-01-01T12:00:00Z',
                        thesis='Test accounting only')
            self.assertEqual(book.fill(**args)['cash'], 9799)
            self.assertEqual(len(book.fill(**args)['fills']), 1)
            args.update(request_id='example-002', side='sell', quantity=1, price=110)
            state = PaperBook(path).fill(**args)
            self.assertEqual(state['realized_pnl'], 8.5)
            self.assertEqual(state['positions']['TEST']['cost'], 100.5)
            args['price'] = 111
            with self.assertRaises(ValueError):
                book.fill(**args)

    def test_invalid_fills_cannot_change_balance(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = PaperBook(Path(tmp) / 'book.sqlite3')
            args = dict(request_id='example-001', symbol='TEST', side='buy', quantity=1,
                        price=100, source='fixture', observed_at='2026-01-01T12:00:00Z', thesis='test')
            for field, value in [('price', float('nan')), ('quantity', -1), ('fee', -1),
                                 ('quantity', 1000), ('side', 'sell'), ('source', ''),
                                 ('observed_at', '2099-01-01T00:00:00Z')]:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        book.fill(**{**args, field: value})
            self.assertEqual(book.report()['cash'], 10000)
            self.assertEqual(book.report()['fills'], [])
