"""Local product economics and optional OpenAI creative brief. No checkout or orders."""
import argparse
import html
import json
import math
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path


def estimate(offer):
    def amount(key):
        val = D(str(offer[key]))
        if not val.is_finite() or val < 0:
            raise ValueError(f"{key} must be a finite nonnegative number")
        return val
    price = amount('price')
    if price <= 0 or amount('fee_percent') >= 100:
        raise ValueError("Enter a positive price and a valid processing rate.")
    cents = D('.01')
    fee = (price*amount('fee_percent')/100 + amount('fixed_fee')).quantize(cents, rounding=ROUND_HALF_UP)
    margin = price-fee-sum(amount(k) for k in ('product_cost','shipping','returns_allowance','acquisition'))
    return fee, margin, math.ceil((amount('monthly_target')+amount('monthly_overhead'))/margin) if margin>0 else None


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('offer',type=Path)
    ap.add_argument('report',type=Path)
    ap.add_argument('--ai',action='store_true',help='Draft original test content using your existing Doxa OpenAI budget.')
    args=ap.parse_args()
    offer=json.loads(args.offer.read_text(encoding='utf-8-sig'))
    fee,margin,orders=estimate(offer)
    text='No AI request made.'
    if args.ai and margin>0:
        from forgemind.cloud_brain import CloudBrain
        from forgemind.config import app_data_dir
        public={k:str(offer[k])[:500] for k in ('product','audience')}
        prompt=('Design a no-spend validation experiment for the proposed product below. '
                'Write three distinct filmable 15-second scripts with a visual opening, punchline, and honest interest CTA. '
                'Supply a tagged link name per script and metrics. This is a concept, not a live store: '
                'no checkout, fabricated endorsements, sales claims, supplier promises, trending claims or lifting other creators’ footage. '
                'Keep it under 450 words. Public concept: '+json.dumps(public,ensure_ascii=False))
        text=''.join(CloudBrain(app_data_dir()).stream([],prompt,None,[],[]))
    def esc(x):return html.escape(str(x))
    args.report.write_text(f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Product test brief</title>
<style>body{{background:#101719;color:#efede7;max-width:760px;margin:5vh auto;padding:24px;font:17px/1.6 system-ui}}h1,h2{{line-height:1.2}}small{{color:#bbd6c9}}pre{{white-space:pre-wrap;font:inherit}}li{{margin:.4em 0}}</style>
<small>DOXA / VYRA · EXPERIMENT 01</small><h1>{esc(offer['product'])}</h1><p>{esc(offer['audience'])}</p>
<h2>Economics before launch</h2><p>Illustrative inputs; replace with a supplier quote. USD. Price ${esc(offer['price'])}; production ${esc(offer['product_cost'])}; shipping ${esc(offer['shipping'])}; processing ${fee:.2f}; return allowance ${esc(offer['returns_allowance'])}; acquisition ${esc(offer['acquisition'])}.</p>
<p><b>${margin:.2f} contribution per order.</b> Orders/month for ${esc(offer['monthly_target'])} before owner labor and taxes, including ${esc(offer['monthly_overhead'])} fixed overhead: <b>{orders if orders is not None else 'unreachable at this margin'}</b>.</p>
<h2>Creative test</h2><pre>{esc(text)}</pre><h2>Decision log</h2><ol><li>Label it a concept and show your own design. Ask whether someone would buy it at the stated price.</li><li>Record creative ID, reach, unique product clicks, and distinct price-aware purchase inquiries. Likes alone do not validate demand.</li><li>Before accepting money: verify a sample, delivered cost, shipping time, and returns. Once live, record fulfilled orders, refunds, and contribution by creative.</li></ol></html>''',encoding='utf-8')
    print(f'{args.report}: fee={fee}, contribution={margin}, orders/month={orders}')

if __name__=='__main__':main()
