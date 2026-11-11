"""Daily business experiments, sourcing references and standalone concept sites."""
from datetime import date
from html import escape
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
import webbrowser

from .config import app_data_dir


TESTS = (
    "Compare two Alibaba listings for the same product. Ask for sample cost, customization, minimum quantity, and delivery to California.",
    "Build a one-page concept for a nearby business. Use its own approved footage and time how quickly a visitor can find the offer.",
    "Film two original hooks for the same product. Keep the price and audience identical and compare purchase inquiries.",
    "Write one page answering a real buyer question. Record whether it attracts qualified visitors.",
    "Outline three original explainer episodes. Produce the first and compare completion against your usual clips.",
    "Compare bulk purchase and single-unit fulfillment. Include shipping, packaging, fees and return allowance.",
    "Review the week's evidence. Repeat the experiment with the strongest purchase intent and change one variable.",
)


def daily_test(day):
    return TESTS[(day - date(2026, 11, 5)).days % len(TESTS)]


def search_url(product):
    return "https://www.alibaba.com/trade/search?" + urlencode({"SearchText": product.strip()})


def quote_check(unit_price, shipping_per_unit, duty_percent, sell_price, ad_cost_per_order,
                monthly_target=10000, fee_percent=2.9, fixed_fee=0.30, returns_percent=5.0):
    """Turn a supplier quote into per-order profit. All money in USD. Raises ValueError on bad input.

    landed = unit + shipping + duty on the unit price; fees = card processing; returns = allowance on the
    selling price. Orders are what it takes to clear `monthly_target` of profit (before your time and taxes)."""
    values = [float(v) for v in (unit_price, shipping_per_unit, duty_percent, sell_price, ad_cost_per_order,
                                 monthly_target, fee_percent, fixed_fee, returns_percent)]
    if any(v != v or v < 0 for v in values) or values[3] <= 0:
        raise ValueError("Use numbers of zero or more, and a selling price above zero.")
    unit, ship, duty, price, ads, target, fee_pct, fixed, returns_pct = values
    landed = unit + ship + unit * duty / 100
    fees = price * fee_pct / 100 + fixed
    returns = price * returns_pct / 100
    profit = price - landed - fees - returns - ads
    orders = None if profit <= 0 else -(-target // profit)
    return {"landed": round(landed, 2), "fees": round(fees, 2), "returns": round(returns, 2),
            "profit": round(profit, 2), "margin_percent": round(100 * profit / price, 1),
            "orders_per_month": int(orders) if orders else None,
            "orders_per_day": round(orders / 30, 1) if orders else None,
            "break_even_ad_cost": round(max(0.0, profit + ads), 2)}


def quote_summary(result):
    if result["profit"] <= 0:
        return (f"Loses ${-result['profit']:.2f} per order (landed ${result['landed']:.2f}). Don't order yet: "
                f"negotiate the price down, raise yours, or cut ad cost below ${result['break_even_ad_cost']:.2f}.")
    return (f"${result['profit']:.2f} profit per order ({result['margin_percent']}%), landed cost "
            f"${result['landed']:.2f}. About {result['orders_per_month']:,} orders/month "
            f"({result['orders_per_day']}/day) for your goal. Ads stop paying above ${result['break_even_ad_cost']:.2f} "
            "per order. Order one sample before any bulk order.")


def concept_page(title, audience, price, tagline):
    title, audience, price, tagline = map(escape, (title, audience, price, tagline))
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>*{{box-sizing:border-box}}body{{margin:0;color:#eee9dc;background:#101917;font:17px/1.5 system-ui}}main{{min-height:100svh;display:grid;grid-template-columns:1fr 1fr;align-items:center;gap:5vw;padding:7vw}}small{{color:#c3d69b;letter-spacing:.14em}}h1{{font:clamp(44px,6vw,98px)/.98 Georgia,serif;max-width:13ch;margin:28px 0}}p{{max-width:38ch}}article{{background:radial-gradient(ellipse at 50% 25%,#405344,#1d2a24 65%);min-height:350px;display:grid;place-items:center;padding:7%;border-radius:8px}}.sign{{width:100%;padding:12% 5%;text-align:center;color:#203129;background:#e5e0c3;border-bottom:9px solid #88876e;font:600 clamp(22px,3vw,45px)/1.08 system-ui;transform:perspective(850px) rotateY(-13deg) rotateX(6deg);box-shadow:0 20px 28px #0b1812;transition:transform .25s}}article:hover .sign,article:focus .sign{{transform:none}}footer{{color:#b5c1b7;margin-top:30px}}@media(max-width:700px){{main{{grid-template-columns:1fr}}article{{min-height:240px}}}}@media(prefers-reduced-motion:reduce){{.sign{{transition:none;transform:none}}}}</style>
<main><section><small>PRODUCT CONCEPT</small><h1>{title}</h1><p>{audience}</p><footer>Proposed price · {price}<br>Concept preview · orders closed</footer></section>
<article tabindex="0" aria-label="Design preview"><div class="sign">{tagline}</div></article></main></html>"""


def open_studio(app):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from .workspace_ui import window

    win, body = window(app, "Business experiments", "750x650")
    tabs = ttk.Notebook(body)
    tabs.pack(fill="both", expand=True)

    def tab(name):
        frame = ttk.Frame(tabs, padding=16)
        tabs.add(frame, text=name)
        return frame

    def field(frame, label, initial):
        ttk.Label(frame, text=label).pack(anchor="w", pady=(8, 2))
        value = tk.StringVar(value=initial)
        ttk.Entry(frame, textvariable=value).pack(fill="x")
        return value

    sourcing = tab("Alibaba sourcing")
    query = field(sourcing, "Product to source", "custom printed acrylic desk sign")
    ttk.Button(sourcing, text="Find suppliers on Alibaba", command=lambda: webbrowser.open(search_url(query.get()))).pack(anchor="w", pady=12)
    ttk.Button(sourcing, text="Open Alibaba request for quotes", command=lambda: webbrowser.open("https://sourcing.alibaba.com/")).pack(anchor="w")
    ttk.Label(sourcing, text="Buyer workspace opens in your browser. Review terms with the supplier before ordering.", wraplength=540).pack(anchor="w", pady=14)

    def copy_request():
        win.clipboard_clear()
        win.clipboard_append(f"I am comparing suppliers for {query.get().strip()}. Please quote one customized sample and your minimum order, including setup, packaging, and delivery to California. Can you fulfill individual US customer orders? Please specify production time, transit time, replacement terms and how long the quote is valid.")

    ttk.Button(sourcing, text="Copy supplier inquiry", command=copy_request).pack(anchor="w")
    check = tab("Quote check")
    ttk.Label(check, text="Paste the numbers from a supplier's quote (USD). Nothing is ordered or sent.",
              wraplength=540).pack(anchor="w")
    inputs = {key: field(check, label, default) for key, label, default in [
        ("unit_price", "Unit price from the supplier", "6.50"), ("shipping_per_unit", "Shipping per unit to you", "2.00"),
        ("duty_percent", "Import duty % (check the HTS code)", "0"), ("sell_price", "Your selling price", "24"),
        ("ad_cost_per_order", "Ad cost per order (0 if organic)", "0"), ("monthly_target", "Monthly profit goal", "10000")]}
    verdict = tk.StringVar()
    ttk.Label(check, textvariable=verdict, wraplength=540).pack(anchor="w", pady=12)

    def run_check():
        try:
            verdict.set(quote_summary(quote_check(**{k: v.get() for k, v in inputs.items()})))
        except ValueError as error:
            verdict.set(str(error) if "Use numbers" in str(error) else "Use plain numbers, like 6.50.")
    ttk.Button(check, text="Check this quote", command=run_check).pack(anchor="w")
    page = tab("Site preview")
    title = field(page, "Product name", "Family Tech Support")
    audience = field(page, "Who it's for", "For the one person everyone calls when the Wi-Fi goes out.")
    price = field(page, "Proposed price", "$24")
    tagline = field(page, "Design text", "Soporte técnico · fuera de horario")

    def export():
        if not all(v.get().strip() for v in (title,audience,price,tagline)):
            messagebox.showerror("Site preview", "Fill in all four fields.", parent=win)
            return
        filename = filedialog.asksaveasfilename(parent=win, defaultextension=".html", initialfile="product-concept.html")
        if filename:
            try:
                path=Path(filename)
                path.write_text(concept_page(title.get(),audience.get(),price.get(),tagline.get()), encoding="utf-8")
                webbrowser.open(path.resolve().as_uri())
            except OSError as error:
                messagebox.showerror("Site preview", str(error), parent=win)
    ttk.Button(page, text="Export and preview site", command=export).pack(anchor="w", pady=14)
    journal = tab("Daily experiment")
    today = date.today()
    ttk.Label(journal, text=f"{today:%A, %B %d}", font=("Segoe UI Semibold",14)).pack(anchor="w")
    ttk.Label(journal, text=daily_test(today), wraplength=550).pack(anchor="w", pady=10)
    ttk.Label(journal, text="What did you try, and what happened?").pack(anchor="w")
    result=tk.Text(journal,height=6,wrap="word")
    result.pack(fill="x",pady=6)
    dbpath=app_data_dir() / "business-experiments.sqlite3"
    from contextlib import closing
    with closing(sqlite3.connect(dbpath)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS experiments(day TEXT PRIMARY KEY, result TEXT NOT NULL)")
        previous=db.execute("SELECT day,result FROM experiments ORDER BY day DESC").fetchall()
    history=tk.StringVar()
    def render(rows):
        history.set("\n".join(f"{d} · {r[:130]}" for d,r in rows[:5]))
    render(previous)
    if previous and previous[0][0]==today.isoformat():
        result.insert("1.0",previous[0][1])
    def save():
        value=result.get("1.0","end-1c").strip()
        if not value:return
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute("INSERT OR REPLACE INTO experiments VALUES (?,?)",(today.isoformat(),value))
            render(db.execute("SELECT day,result FROM experiments ORDER BY day DESC LIMIT 5").fetchall())
    ttk.Button(journal,text="Save result",command=save).pack(anchor="w",pady=8)
    ttk.Label(journal,textvariable=history,wraplength=550).pack(anchor="w")
    return win
