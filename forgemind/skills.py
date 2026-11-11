"""Skills: one-click workflows, mostly for earning money with content and stores.

Built 2026-11-04 from the owner's saved reels:
- "5 Instagram settings for small accounts"  -> Instagram growth checklist, reel scripts, weekly plan
- Shopify "start with just an idea"          -> product listing + store launch checklist
- ForgeGUI "make a Roblox game in 60 s"      -> game concept + ForgeGUI-ready prompts
- "Build your own Jarvis in 9 steps"         -> interview me, evening wrap-up
The chat's paper_trading tool supports a simulated journal with observed quote sources,
fees and pre-trade reasoning. It is separate from real brokerage execution.

Two kinds of skill:
- "answer": a fixed checklist Doxa posts instantly (no model, no waiting).
- "prompt": fills the message box with a ready instruction; the owner adds details and presses Send.
  Prompts are short because the local model's prompt is capped at ~1500 tokens.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    key: str
    title: str
    subtitle: str
    kind: str  # "answer" or "prompt"
    text: str
    group: str = "Content & money"


INSTAGRAM_CHECKLIST = """Instagram growth checklist (from the "5 settings for small accounts" reel, with what's actually true)

1. Account status: Settings → Account Status. All checks should be green. If anything is flagged, your posts
   aren't recommended to non-followers (what people call a "shadowban"). Fix or appeal it first.
2. Let people share you: Settings → Sharing and reuse. Turn on Posts and reels to stories, Reposts, and
   Reels remixes. Every share is free reach.
3. Upload quality: Settings → Media quality → Upload at highest quality ON. Blurry reels lose watch time.
4. Account suggestions: on a computer, Edit profile → "Show account suggestions on profiles" ON. People who
   follow similar accounts get suggested yours (it works both ways: you'll be suggested on theirs too).
5. Strategy beats settings: post 3–5 reels a week, hook in the first 2 seconds, one idea per reel, end with
   one clear ask (DM me "QUOTE", follow for part 2).

For your insurance agency: keep it compliant. No guaranteed-savings claims, no carrier logos without
permission, and say quotes depend on eligibility. Try the "Reel scripts for my business" skill next."""

SHOPIFY_CHECKLIST = """Shopify launch checklist (the reel's "just an idea" is the start, not the whole job)

1. Validate first: who buys it, what they pay now, and 3 competitors' prices. Ask Doxa to research them.
2. Sign up yourself at shopify.com (free trial). Doxa doesn't create accounts or enter payment details.
3. Product page: use the "Shopify product listing" skill for title, description, bullets and SEO text.
4. Photos: 4–6 clean photos on a plain background, one in use. Shopify's AI can tidy one photo,
   but real photos sell better.
5. Legal and money: business license/seller's permit for your city, sales tax settings, refund policy,
   shipping rates. For food (like the reel's pickles), check California cottage-food rules first.
6. Launch: one product, one ad-free traffic source to start (your Instagram reels), then measure.
   Payments, ad spend and anything that charges money are yours to approve."""

SKILLS: tuple[Skill, ...] = (
    Skill("reel_breakdown", "Break down a reel", "Paste a reel link first. Why it works and how to copy the format.",
          "prompt", "Break down the reel transcript above: the hook in the first 2 seconds, the structure, why it "
                    "keeps people watching, and how I could make my own version for my insurance agency. "
                    "Keep it to 8 bullet points."),
    Skill("reel_scripts", "Reel scripts for my business", "3 short scripts with hooks, captions and hashtags.",
          "prompt", "Write 3 Instagram reel scripts (20–30 seconds each) for my insurance agency in Los Angeles "
                    "about: [topic, e.g. how to lower your car insurance]. For each: a 2-second hook, 3 quick "
                    "beats, a call to action (DM me \"QUOTE\"), a caption and 5 hashtags. No guaranteed-savings "
                    "claims."),
    Skill("instagram_checklist", "Instagram growth checklist", "The settings from your reel, checked against reality.",
          "answer", INSTAGRAM_CHECKLIST),
    Skill("content_week", "Plan my content week", "7 days of posts from one goal.",
          "prompt", "Plan 7 days of Instagram content for my insurance agency. Goal: [more quote requests / "
                    "followers / reviews]. For each day: format (reel, carousel or story), the idea in one "
                    "line, and the hook. Mix education, a client story (no real names) and one offer."),
    Skill("site_pitch", "Pitch a website to a local business", "A 30-second walk-in script and follow-up text.",
          "prompt", "Write a 30-second walk-in pitch, in English and Spanish, for offering a new website to [business "
                    "name and type] in [city]. I film the storefront and the room, then show the owner a preview on my "
                    "laptop. Keep it friendly and honest, ask permission to film, and end with a follow-up text I can "
                    "send that day. No guarantees about traffic or sales.", "Websites"),
    Skill("shopify_listing", "Shopify product listing", "Title, description, bullets and SEO text for a product.",
          "prompt", "Write a Shopify product listing for: [product, who it's for, price]. Give a product title "
                    "(under 70 characters), a 3-sentence description, 5 benefit bullets, an SEO title and "
                    "meta description, and 3 questions I should answer before I list it.", "Stores"),
    Skill("shopify_launch", "Shopify launch checklist", "From idea to first sale, with the legal bits.",
          "answer", SHOPIFY_CHECKLIST, "Stores"),
    Skill("roblox_game", "Roblox game idea + ForgeGUI prompts", "A game concept and the prompts to build it.",
          "prompt", "Give me a Roblox game concept that could earn Robux through game passes: [theme, e.g. a "
                    "superhero speed game]. Include the core loop in 3 steps, 3 game-pass ideas with prices in "
                    "Robux, and 5 short prompts I can paste into ForgeGUI one at a time to build it.", "Games"),
    Skill("interview_me", "Interview me", "Doxa asks about your business and goals, one question at a time.",
          "prompt", "Interview me so you can help me better. Ask one short question at a time about my "
                    "business, my goals for the next 90 days, my week, and what I hate doing. Wait for my "
                    "answer before the next question. After 8 questions, summarize what you learned in "
                    "5 bullets I can save to memory.", "Doxa"),
    Skill("evening_wrap", "Evening wrap-up", "What got done today and what's first tomorrow.",
          "prompt", "Evening wrap-up. Here's what I did today: [list]. Tell me what moved my goals forward, "
                    "what slipped, and the first 3 things I should do tomorrow morning. Keep it short.", "Doxa"),
)

SUGGESTIONS = ("reel_breakdown", "reel_scripts", "shopify_listing", "instagram_checklist")
CHIP_LABELS = {"reel_scripts": "Reel scripts", "shopify_listing": "Shopify listing",
               "instagram_checklist": "Instagram checklist"}


def get(key: str) -> Skill:
    for skill in SKILLS:
        if skill.key == key:
            return skill
    raise KeyError(key)


def groups() -> list[tuple[str, list[Skill]]]:
    order: list[str] = []
    for skill in SKILLS:
        if skill.group not in order:
            order.append(skill.group)
    return [(name, [s for s in SKILLS if s.group == name]) for name in order]
