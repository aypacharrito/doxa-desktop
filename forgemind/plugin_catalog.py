"""Ready-to-add plugins: official remote MCP servers that support one-click browser sign-in.

Every address here was probed on 2026-11-10 (ForgeMind\\checks\\mcp_probe.py): "oauth" ones answered 401 with
standard OAuth metadata, PKCE S256 and dynamic client registration; "open" ones answered without an account.
Apps that only offer developer-app sign-in (GitHub, Asana, Box, HubSpot) are left out: use Add by link + a token.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plugin:
    id: str
    name: str
    by: str
    blurb: str
    url: str
    group: str
    color: str
    auth: str = "oauth"   # "oauth" = browser sign-in, "open" = no account
    money: bool = False   # can touch payments: sign in to a test/sandbox account first
    popular: bool = False

    @property
    def letter(self) -> str:
        return self.name[0].upper()


GROUPS = ["Money", "Sites & stores", "Work", "Create", "Automate", "Build"]

CATALOG = [
    Plugin("zapier", "Zapier", "Zapier", "Gmail, Google Sheets, Drive, Slack and 8,000 more apps in one connection",
           "https://mcp.zapier.com/api/mcp/mcp", "Automate", "#ff4f00", popular=True),
    Plugin("make", "Make", "Make", "Run your Make scenarios and automations from chat",
           "https://mcp.make.com", "Automate", "#6d00cc"),
    Plugin("stripe", "Stripe", "Stripe", "Products, prices, payment links, customers and payments",
           "https://mcp.stripe.com", "Money", "#635bff", money=True, popular=True),
    Plugin("paypal", "PayPal", "PayPal", "Invoices, orders, products and transactions",
           "https://mcp.paypal.com/mcp", "Money", "#003087", money=True),
    Plugin("square", "Square", "Square", "Payments, catalog, orders and customers",
           "https://mcp.squareup.com/mcp", "Money", "#3e4348", money=True),
    Plugin("wix", "Wix", "Wix", "Build and edit Wix sites and stores",
           "https://mcp.wix.com/mcp", "Sites & stores", "#116dff"),
    Plugin("webflow", "Webflow", "Webflow", "Edit Webflow sites, pages and CMS content",
           "https://mcp.webflow.com/mcp", "Sites & stores", "#4353ff"),
    Plugin("vercel", "Vercel", "Vercel", "Deployments, projects, domains and logs",
           "https://mcp.vercel.com", "Sites & stores", "#000000", popular=True),
    Plugin("supabase", "Supabase", "Supabase", "Databases, tables and projects (restore paused ones too)",
           "https://mcp.supabase.com/mcp", "Sites & stores", "#3ecf8e", popular=True),
    Plugin("cloudflare", "Cloudflare", "Cloudflare", "Workers, domains, DNS and your Cloudflare account",
           "https://mcp.cloudflare.com/mcp", "Sites & stores", "#f38020", popular=True),
    Plugin("notion", "Notion", "Notion", "Search, read and write your Notion pages",
           "https://mcp.notion.com/mcp", "Work", "#191919", popular=True),
    Plugin("airtable", "Airtable", "Airtable", "Read and update your Airtable bases",
           "https://mcp.airtable.com/mcp", "Work", "#18bfff"),
    Plugin("monday", "monday.com", "monday.com", "Boards, items and updates",
           "https://mcp.monday.com/mcp", "Work", "#ff3d57"),
    Plugin("linear", "Linear", "Linear", "Issues, projects and cycles",
           "https://mcp.linear.app/mcp", "Work", "#5e6ad2"),
    Plugin("atlassian", "Atlassian", "Atlassian", "Jira and Confluence",
           "https://mcp.atlassian.com/v1/mcp", "Work", "#0052cc"),
    Plugin("intercom", "Intercom", "Intercom", "Customer conversations and contacts",
           "https://mcp.intercom.com/mcp", "Work", "#1f8ded"),
    Plugin("canva", "Canva", "Canva", "Search, create, autofill and export designs",
           "https://mcp.canva.com/mcp", "Create", "#00c4cc", popular=True),
    Plugin("higgsfield", "Higgsfield", "Higgsfield", "Generate images and videos with your Higgsfield plan",
           "https://mcp.higgsfield.ai/mcp", "Create", "#c8ff00", popular=True),
    Plugin("figma", "Figma", "Figma", "Read designs and turn them into code",
           "https://mcp.figma.com/mcp", "Create", "#a259ff"),
    Plugin("huggingface", "Hugging Face", "Hugging Face", "Search models, datasets and Spaces",
           "https://huggingface.co/mcp", "Build", "#ffbd2e", auth="open"),
    Plugin("expo", "Expo", "Expo", "Your Expo app builds and updates",
           "https://mcp.expo.dev/mcp", "Build", "#4630eb"),
    Plugin("sentry", "Sentry", "Sentry", "Errors and issues from your apps",
           "https://mcp.sentry.dev/mcp", "Build", "#362d59"),
    Plugin("deepwiki", "DeepWiki", "Cognition", "Ask questions about any public GitHub repo",
           "https://mcp.deepwiki.com/mcp", "Build", "#2b6cb0", auth="open"),
]

BY_ID = {plugin.id: plugin for plugin in CATALOG}


def find(query: str = "", group: str = "") -> list[Plugin]:
    words = (query or "").lower().split()
    out = []
    for plugin in CATALOG:
        if group and plugin.group != group:
            continue
        haystack = f"{plugin.name} {plugin.by} {plugin.blurb} {plugin.group}".lower()
        if all(word in haystack for word in words):
            out.append(plugin)
    return out


def match_url(url: str) -> Plugin | None:
    clean = (url or "").strip().rstrip("/").lower()
    for plugin in CATALOG:
        if plugin.url.rstrip("/").lower() == clean:
            return plugin
    return None
