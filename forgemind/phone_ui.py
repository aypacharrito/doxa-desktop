"""Phone access panel: turn it on, connect Cloudflare, get your private phone link."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from forgemind import jarvis_ui as ui
from forgemind.phone_bridge import Tunnel, find_cloudflared, phone_link, tunnel_token_get, tunnel_token_set


def qr_image(text: str, size: int = 200):
    """A QR code for the phone link (segno, pure Python), or None if it can't be drawn."""
    try:
        import io

        import segno
        from PIL import Image, ImageTk
        out = io.BytesIO()
        segno.make(text, error="m").save(out, kind="png", scale=8, border=2)
        out.seek(0)
        return ImageTk.PhotoImage(Image.open(out).convert("RGB").resize((size, size), Image.NEAREST))
    except Exception:
        return None


def open_phone_panel(app):
    existing = getattr(app, "_phone_panel", None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        return existing
    access, server = app.phone_access, app.phone_server
    window = tk.Toplevel(app)
    ui.pop_in(window)
    app._phone_panel = window
    window.title("Doxa · Phone access")
    window.geometry("600x820")
    window.minsize(540, 640)
    window.configure(bg=ui.BG)
    frame = ttk.Frame(window, padding=14)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Doxa on your phone", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, wraplength=530, text=(
        "Your phone reaches this PC through a Cloudflare Tunnel: an encrypted outbound connection, with no "
        "router or firewall changes. Doxa answers with your local model, so this PC must be on and Doxa open. "
        "Anyone with your phone link can use Doxa, so keep it private; Create new link revokes old ones."
    )).pack(fill="x", pady=8)

    enabled = tk.BooleanVar(value=bool(access.data.get("enabled")))
    status = tk.StringVar()
    link_var = tk.StringVar(value="")
    url_var = tk.StringVar(value=access.data.get("public_url", ""))
    token_var = tk.StringVar(value="")

    def refresh():
        if not window.winfo_exists():
            return
        parts = [f"Phone server: {'on' if server.running else 'off'}"]
        tunnel = app.phone_tunnel
        if tunnel and tunnel.running:
            label = 'connected' if tunnel.ready else 'connecting/recovering'
            parts.append(f"Cloudflare: {label} · {tunnel.url or 'starting…'}")
            parts.append(f'Automatic reconnects: {tunnel.restarts}')
        elif tunnel and tunnel.error:
            parts.append("Cloudflare: " + tunnel.error)
        else:
            parts.append("Cloudflare: not connected")
        if not find_cloudflared():
            parts.append("cloudflared not installed: run SETUP_PHONE_ACCESS.bat")
        status.set("\n".join(parts))
        window.after(1000, refresh)

    def toggle():
        access.data["enabled"] = enabled.get()
        access.save()
        try:
            if enabled.get():
                server.start()
            else:
                stop_tunnel()
                server.stop()
        except OSError as exc:
            enabled.set(False)
            messagebox.showerror("Phone access", f"Could not start the phone server on port {access.port}: {exc}", parent=window)

    ttk.Checkbutton(frame, text="Turn on phone access", variable=enabled, command=toggle).pack(anchor="w")
    ttk.Label(frame, textvariable=status, wraplength=530, justify="left").pack(fill="x", pady=8)

    def need_server():
        if not server.running:
            enabled.set(True)
            toggle()
        return server.running

    def start_tunnel(kind):
        if not need_server():
            return
        if app.phone_tunnel:
            app.phone_tunnel.stop()
        app.phone_tunnel = Tunnel(access.port)
        try:
            if kind == "quick":
                app.phone_tunnel.start_quick()
                access.data["use_named_tunnel"] = False
            else:
                token = token_var.get().strip() or tunnel_token_get()
                if not url_var.get().strip().startswith("https://"):
                    raise RuntimeError("Enter your public address, e.g. https://doxa.yourdomain.com")
                if token_var.get().strip():
                    tunnel_token_set(token_var.get())
                    token_var.set("")
                app.phone_tunnel.start_named(token, url_var.get())
                access.data.update(use_named_tunnel=True, public_url=url_var.get().strip().rstrip("/"))
            access.save()
        except RuntimeError as exc:
            messagebox.showerror("Cloudflare", str(exc), parent=window)
            return
        if kind == "quick":
            def wait():
                url = app.phone_tunnel.wait_for_url()
                window.after(0, lambda: url and make_link(ask=False))  # new address: the old link no longer works
            threading.Thread(target=wait, daemon=True).start()

    def stop_tunnel():
        if app.phone_tunnel:
            app.phone_tunnel.stop()

    linkbox = ttk.LabelFrame(frame, text="Open Doxa on your phone", padding=10)
    linkbox.pack(fill="x", pady=6)
    top = ttk.Frame(linkbox)
    top.pack(fill="x")
    qr_label = tk.Label(top, bg=ui.BG)
    qr_label.pack(side="left", padx=(0, 12))
    side = ttk.Frame(top)
    side.pack(side="left", fill="both", expand=True)
    hint_var = tk.StringVar(value="Connect Cloudflare below, then your link appears here.")
    ttk.Label(side, textvariable=hint_var, wraplength=300).pack(anchor="w")
    link_entry = ttk.Entry(side, textvariable=link_var, state="readonly")
    link_entry.pack(fill="x", pady=6)

    def show_qr():
        image = qr_image(link_var.get()) if link_var.get() else None
        qr_label.configure(image=image or "")
        qr_label.image = image
        hint_var.set("Doxa app: tap Scan QR code (or Scan new link) and point it here. No app? Scan with your "
                     "camera to open Doxa in the browser, then use the menu → Add to Home screen." if link_var.get() else
                     "Your link was made earlier and isn't stored (only a fingerprint is). Press Create new link "
                     "to show a new one; the old one stops working." if access.data.get("key_hash") else
                     "Connect Cloudflare below, then your link appears here.")

    def make_link(ask=True):
        tunnel = app.phone_tunnel
        base = (tunnel.url if tunnel and tunnel.running and tunnel.url else "") or (
            access.data.get("public_url", "") if access.data.get("use_named_tunnel") else "")
        if not base:  # nothing connected (quick links end when Doxa restarts): connect, then the link appears
            hint_var.set("Connecting to Cloudflare… your link and QR code appear here in a few seconds.")
            start_tunnel("quick")
            return
        if ask and access.data.get("key_hash") and not messagebox.askyesno(
                "New phone link", "Create a new link? Phones using the old link will need the new one.", parent=window):
            return
        link_var.set(phone_link(base, access.new_key()))
        show_qr()

    def copy():
        if link_var.get():
            window.clipboard_clear()
            window.clipboard_append(link_var.get())
            messagebox.showinfo("Copied", "Link copied. Send it to yourself (e.g. a note or email to your phone), open it "
                                "on your phone, then use the browser menu → Add to Home screen.", parent=window)

    row2 = ttk.Frame(side)
    row2.pack(fill="x")
    ttk.Button(row2, text="Create new link", command=make_link, style="Accent.TButton").pack(side="left")
    ttk.Button(row2, text="Copy link", command=copy).pack(side="left", padx=6)
    ttk.Label(linkbox, wraplength=520, text="The link contains your private key, so keep it to yourself. Doxa stores only "
              "a fingerprint of it, which is why it's shown just once.", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
    show_qr()

    def first_link():
        """First time Cloudflare is connected and no link exists yet: make one right away."""
        if not window.winfo_exists():
            return
        tunnel = app.phone_tunnel
        if not access.data.get("key_hash") and not link_var.get() and tunnel and tunnel.url:
            make_link(ask=False)
        elif not link_var.get():
            window.after(1500, first_link)
    first_link()

    quick = ttk.LabelFrame(frame, text="Connect", padding=10)
    quick.pack(fill="x", pady=6)
    ttk.Label(quick, wraplength=500, text="Quick link: free and instant, no Cloudflare account needed. The address changes each "
              "time Doxa restarts, so it's best for trying it out.").pack(anchor="w")
    row = ttk.Frame(quick)
    row.pack(fill="x", pady=6)
    ttk.Button(row, text="Start quick link", command=lambda: start_tunnel("quick"), style="Accent.TButton").pack(side="left")
    ttk.Button(row, text="Disconnect", command=stop_tunnel).pack(side="left", padx=6)
    ttk.Label(quick, wraplength=500, text="Permanent address (your Cloudflare account): in the Cloudflare dashboard open "
              "Zero Trust → Networks → Tunnels → Create a tunnel (Cloudflared). Copy its token. Add a public hostname "
              f"such as doxa.yourdomain.com with service http://localhost:{access.port}. Recommended: add a "
              "Cloudflare Access policy so only your email can open it.").pack(anchor="w", pady=(8, 0))
    named = ttk.Frame(quick)
    named.pack(fill="x", pady=6)
    ttk.Label(named, text="Public address").grid(row=0, column=0, sticky="w")
    ttk.Entry(named, textvariable=url_var, width=40).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Label(named, text="Tunnel token").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(named, textvariable=token_var, width=40, show="•").grid(row=1, column=1, sticky="ew", padx=6)
    named.columnconfigure(1, weight=1)
    ttk.Label(quick, text="The token is saved in Windows Credential Manager, not in a file. Leave it blank to reuse the saved one.",
              wraplength=500).pack(anchor="w")
    ttk.Button(quick, text="Connect my Cloudflare tunnel", command=lambda: start_tunnel("named")).pack(anchor="w", pady=6)

    def close():
        app._phone_panel = None
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    refresh()
    return window
