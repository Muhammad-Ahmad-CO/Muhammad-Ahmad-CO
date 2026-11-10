#!/usr/bin/env python3
"""
Generate the animated SVG cards for Muhammad Ahmad's GitHub profile README.

Design source (read 2026-11-10):
  * Website  : https://ahmadsportfolios.lovable.app  (repo: ahmadsportfolios, src/styles.css)
               background #0C0C0C, paper #EDEFF2, hero gradient #646973 -> #BBCCD7,
               pale steel #D7E2EA / #BBCCD7. Fonts: Kanit (sans), Space Grotesk
               (headings), Inter (body).
  * Reference: Instagram reel Dfh40X-SuCr (Avi Vashishta's profile) — light
               editorial cards stacked in the README: hero with halftone
               portrait, a contribution-graph card, a monthly bar chart with
               stats, three bold tiles in a row, then repo cards.

How the cards work:
  * The README shows every card through an <img> tag, so a card can only use
    what an SVG image can do: one inline <style> block with CSS @keyframes,
    SMIL <animate> elements, and fonts subset with pyftsubset (fontTools) and
    embedded as base64 WOFF data URIs. No external requests, no JavaScript.
  * Animation delays are staggered by card position (BASE_DELAYS) so the page
    plays top to bottom.
  * Every animation is switched off under `prefers-reduced-motion`, and SMIL
    elements are hidden there too.
  * STATIC=1 renders the final frame only (no animation attributes at all),
    so the stack can be screenshotted before pushing:
        STATIC=1 OUT_DIR=preview/static python3 scripts/generate_cards.py

Data:
  * Contribution data is read from data/contributions.json, which the daily
    GitHub Action (.github/workflows/cards.yml) refreshes before running
    this script. Format = github-contributions-api.jogruber.de/v4 response:
    {"total": {"lastYear": N}, "contributions": [{"date","count","level"}]}
  * The hero portrait is the halftone artwork in
    assets/portrait-halftone.b64.txt (base64 JPEG, generated from the photo
    the owner supplied; its background is PAPER so it blends into the card).
"""

import base64
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.request
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.environ.get("STATIC") == "1"
OUT_DIR = os.path.join(ROOT, os.environ.get("OUT_DIR", "cards"))
FONT_CACHE = os.path.join(ROOT, os.environ.get("FONT_CACHE", ".font-cache"))
DATA_FILE = os.path.join(ROOT, "data", "contributions.json")
PORTRAIT_B64 = os.path.join(ROOT, "assets", "portrait-halftone.b64.txt")

# ---------------------------------------------------------------- brand ----
PAPER = "#EDEFF2"      # website light paper
INK = "#0C0C0C"        # website background / ink
MUTED = "#646973"      # hero-gradient top / muted text
BODY = "#3C4450"       # body text on paper
PALE = "#D7E2EA"       # website pale steel
STEEL = "#BBCCD7"      # website steel (hero-gradient bottom)
DEEP = "#46617A"       # deepened steel — AA-readable on paper, brand hue
MID = "#7FA0B8"        # mid steel
TS_BLUE = "#3178C6"    # TypeScript language colour
GRAPH_RAMP = ["#E2E6EA", "#B9CFDF", "#8FB0C7", "#5B84A6", "#33566F"]

USER = "Muhammad-Ahmad-CO"
NAME_1, NAME_2 = "Muhammad", "Ahmad"
EYEBROW = "AI SPECIALIST & WEB DEVELOPER"
TAGLINE = "I build intelligent systems with AI & code."
SITE = "ahmadsportfolios.lovable.app"
PUBLIC_REPOS = 31  # verified via GitHub API (get_me) on 2026-11-10

# Stagger: card index in the README stack -> base delay (seconds).
# hero, tiles x3, monthly, repos x6, graph
BASE_DELAYS = [0.0, 0.35, 0.5, 0.65, 0.9] + [1.2 + 0.15 * i for i in range(6)] + [2.2]

FEATURED = [
    dict(name="al-fjrfoods", stars=1, lang="TypeScript", lang_pct="94.2%",
         desc="A modern food-brand experience — product presentation, responsive UI and digital storytelling.",
         live=None),
    dict(name="ahmadsportfolios", stars=1, lang="TypeScript", lang_pct="96.1%",
         desc="My portfolio — AI, automation and modern web engineering, presented with polish.",
         live="https://ahmadsportfolios.lovable.app"),
    dict(name="cement-zen", stars=1, lang="TypeScript", lang_pct="95.0%",
         desc="Climate-tech concept — decarbonizing cement, told as a focused scroll narrative with proof points.",
         live="https://cement-zen.lovable.app"),
    dict(name="monolithstudio", stars=1, lang="TypeScript", lang_pct="97.4%",
         desc="Premium creative-studio concept — visual craftsmanship, strategy and modern digital presentation.",
         live="https://monolithstudio.lovable.app"),
    dict(name="hero-blossom-glow", stars=1, lang="TypeScript", lang_pct="92.3%",
         desc="Beauty & wellness experience — premium presentation, responsive layouts, visual storytelling.",
         live="https://hero-blossom-glow.lovable.app"),
    dict(name="home-hearth-store", stars=1, lang="TypeScript", lang_pct="96.6%",
         desc="Home & lifestyle storefront — product discovery and a modern, responsive retail UI.",
         live="https://home-hearth-store.lovable.app"),
]

# ---------------------------------------------------------------- fonts ----
FONT_CSS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Kanit:ital,wght@0,600;0,800;1,800"
    "&family=Space+Grotesk:wght@500;700"
    "&family=Inter:wght@400;600&display=swap"
)
OLD_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/534"


def fetch_font_urls():
    """Resolve (family, style, weight) -> TTF url from Google Fonts css2."""
    req = urllib.request.Request(FONT_CSS_URL, headers={"User-Agent": OLD_UA})
    css = urllib.request.urlopen(req, timeout=30).read().decode()
    urls = {}
    for block in css.split("@font-face"):
        fam = re.search(r"font-family:\s*'([^']+)'", block)
        sty = re.search(r"font-style:\s*(\w+)", block)
        wgt = re.search(r"font-weight:\s*(\d+)", block)
        url = re.search(r"url\((https://[^)]+\.ttf)\)", block)
        if fam and sty and wgt and url:
            urls[(fam.group(1), sty.group(1), int(wgt.group(1)))] = url.group(1)
    return urls


def subset_font_b64(family, style, weight, text):
    """Download a TTF once, subset it to `text`, return base64 WOFF."""
    from fontTools import subset
    from fontTools.ttLib import TTFont

    os.makedirs(FONT_CACHE, exist_ok=True)
    key = f"{family}-{style}-{weight}".replace(" ", "")
    cache_ttf = os.path.join(FONT_CACHE, key + ".ttf")
    if not os.path.exists(cache_ttf):
        url = fetch_font_urls()[(family, style, weight)]
        urllib.request.urlretrieve(url, cache_ttf)
    font = TTFont(cache_ttf)
    opts = subset.Options(flavor="woff", layout_features="kern,liga",
                          name_IDs=[], notdef_outline=True)
    ss = subset.Subsetter(opts)
    ss.populate(text="".join(sorted(set(text))))
    ss.subset(font)
    buf = io.BytesIO()
    font.flavor = "woff"
    font.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


def font_faces(faces, texts):
    """faces: [(family, style, weight)] -> <style> @font-face rules (b64)."""
    all_text = "".join(texts) + "0123456789 .,;:!?@%&()_-+/'→↗★·—–…"
    rules = []
    for family, style, weight in faces:
        b64 = subset_font_b64(family, style, weight, all_text)
        rules.append(
            "@font-face{font-family:'%s';font-style:%s;font-weight:%d;"
            "src:url(data:font/woff;base64,%s) format('woff')}"
            % (family, style, weight, b64))
    return "".join(rules)


# ------------------------------------------------------------ svg helpers --
KEYFRAMES = """
@keyframes rise{from{opacity:0;transform:translateY(14px)}}
@keyframes fade{from{opacity:0}}
@keyframes growY{from{transform:scaleY(0)}}
@keyframes growX{from{transform:scaleX(0)}}
.rise{animation:rise .7s cubic-bezier(.2,.7,.2,1) both}
.fade{animation:fade .8s ease both}
.growY{animation:growY .8s cubic-bezier(.2,.7,.2,1) both;transform-box:fill-box;transform-origin:50% 100%}
.growX{animation:growX .8s cubic-bezier(.2,.7,.2,1) both;transform-box:fill-box;transform-origin:0 50%}
@media (prefers-reduced-motion: reduce){
  *{animation:none!important}
  animate,animateTransform,set{display:none}
}
"""

KANIT = "Kanit, sans-serif"
GROTESK = "'Space Grotesk', sans-serif"
INTER = "Inter, sans-serif"


def style_block(faces, texts):
    if STATIC:
        return "<style>%s</style>" % font_faces(faces, texts)
    return "<style>%s%s</style>" % (font_faces(faces, texts), KEYFRAMES)


def anim(cls, delay):
    """Animation class + delay, or nothing in STATIC mode."""
    if STATIC:
        return ""
    return ' class="%s" style="animation-delay:%.2fs"' % (cls, delay)


def smil_pulse(begin, dur="2.6s"):
    """SMIL opacity pulse for small live dots (omitted in STATIC mode)."""
    if STATIC:
        return ""
    return ('<animate attributeName="opacity" values="1;.35;1" dur="%s" '
            'begin="%.2fs" repeatCount="indefinite"/>' % (dur, begin))


def svg_doc(w, h, faces, texts, body):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" role="img">%s%s</svg>\n'
        % (w, h, w, h, style_block(faces, texts), body))


def text(x, y, s, family, size, fill, weight=None, style=None, anchor=None,
         spacing=None, opacity=None, extra=""):
    a = ['x="%s"' % x, 'y="%s"' % y, 'font-family="%s"' % family,
         'font-size="%s"' % size, 'fill="%s"' % fill]
    if weight:
        a.append('font-weight="%d"' % weight)
    if style:
        a.append('font-style="%s"' % style)
    if anchor:
        a.append('text-anchor="%s"' % anchor)
    if spacing:
        a.append('letter-spacing="%s"' % spacing)
    if opacity:
        a.append('opacity="%s"' % opacity)
    return "<text %s %s>%s</text>" % (" ".join(a), extra, escape(s))


def card_bg(w, h, fill=PAPER, rx=18):
    return ('<rect x="0.5" y="0.5" width="%d" height="%d" rx="%d" fill="%s" '
            'stroke="%s" stroke-opacity="0.14"/>' % (w - 1, h - 1, rx, fill, INK))


# ------------------------------------------------------------------ data ---
def load_data():
    with open(DATA_FILE) as f:
        raw = json.load(f)
    days = [(dt.date.fromisoformat(c["date"]), int(c["count"]), int(c["level"]))
            for c in raw["contributions"]]
    days.sort()
    total = raw.get("total", {}).get("lastYear", sum(d[1] for d in days))

    monthly = {}
    for d, count, _ in days:
        monthly[(d.year, d.month)] = monthly.get((d.year, d.month), 0) + count
    months = []
    y, m = days[0][0].year, days[0][0].month
    for _ in range(12):
        months.append(((y, m), monthly.get((y, m), 0)))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    # If the window holds >12 months (partial first month), keep the last 12.
    months = months[-12:] if len(months) > 12 else months
    all_months = sorted(monthly.items())
    months = [(k, monthly[k]) for k, _ in all_months][-12:]

    active_days = sum(1 for _, c, _ in days if c > 0)
    busiest = max(days, key=lambda d: d[1])
    longest = cur = 0
    for _, c, _ in days:
        cur = cur + 1 if c > 0 else 0
        longest = max(longest, cur)
    i = len(days) - 1
    if i >= 0 and days[i][1] == 0:
        i -= 1  # today may still be in progress
    current = 0
    while i >= 0 and days[i][1] > 0:
        current += 1
        i -= 1
    return dict(days=days, total=total, months=months, active_days=active_days,
                busiest=busiest, longest=longest, current=current)


def fmt_date(d):
    return d.strftime("%b %-d")


# ----------------------------------------------------------------- cards ---
def hero_card(base):
    portrait = ""
    if os.path.exists(PORTRAIT_B64):
        b64 = open(PORTRAIT_B64).read().strip()
        portrait = ('<image x="604" y="38" width="240" height="240" '
                    'href="data:image/jpeg;base64,%s"%s/>'
                    % (b64, anim("rise", base + 0.30)))
    texts = [EYEBROW, NAME_1, NAME_2, TAGLINE, SITE + " ↗",
             "MUHAMMAD-AHMAD-CO"]
    faces = [("Kanit", "normal", 800), ("Kanit", "italic", 800),
             ("Space Grotesk", "normal", 500), ("Inter", "normal", 400),
             ("Inter", "normal", 600)]
    body = [card_bg(880, 320)]
    body.append(portrait)
    body.append('<circle cx="48" cy="50" r="4.5" fill="%s"%s>%s</circle>'
                % (DEEP, anim("fade", base), smil_pulse(base + 1.2)))
    body.append(text(64, 55, EYEBROW, GROTESK, 13, MUTED, weight=500,
                     spacing="3", extra=anim("rise", base + 0.05)))
    body.append(text(46, 140, NAME_1, KANIT, 78, INK, weight=800,
                     extra=anim("rise", base + 0.10)))
    body.append(text(46, 218, NAME_2, KANIT, 78, INK, weight=800,
                     style="italic", extra=anim("rise", base + 0.20)))
    body.append('<rect x="49" y="234" width="148" height="6" rx="3" fill="%s"%s/>'
                % (DEEP, anim("growX", base + 0.45)))
    body.append(text(48, 272, TAGLINE, INTER, 19, BODY,
                     extra=anim("rise", base + 0.35)))
    body.append(text(48, 300, SITE + " ↗", INTER, 14.5, DEEP, weight=600,
                     extra=anim("rise", base + 0.42)))
    return svg_doc(880, 320, faces, texts, "".join(body))


def tile_card(base, big, label, sub, bg, fg, sub_opacity="0.85"):
    texts = [big, label, sub, "↗"]
    faces = [("Kanit", "normal", 800), ("Space Grotesk", "normal", 500),
             ("Inter", "normal", 400)]
    body = [card_bg(284, 168, fill=bg, rx=16)]
    body.append(text(258, 40, "↗", INTER, 20, fg,
                     extra=anim("fade", base + 0.25)))
    body.append(text(24, 82, big, KANIT, 54, fg, weight=800,
                     extra=anim("rise", base)))
    body.append(text(25, 114, label, GROTESK, 12.5, fg, weight=500,
                     spacing="2", extra=anim("rise", base + 0.10)))
    body.append(text(25, 140, sub, INTER, 12.5, fg, opacity=sub_opacity,
                     extra=anim("rise", base + 0.18)))
    return svg_doc(284, 168, faces, texts, "".join(body))


def monthly_card(base, data):
    months = data["months"]
    peak = max(c for _, c in months) or 1
    texts = ["%d contributions" % data["total"], "in the last year",
             "LONGEST STREAK", "CURRENT STREAK", "ACTIVE DAYS", "BUSIEST DAY",
             "%d days" % data["longest"], "%d days" % data["current"],
             str(data["active_days"]),
             "%s · %d" % (fmt_date(data["busiest"][0]), data["busiest"][1])]
    faces = [("Kanit", "normal", 800), ("Space Grotesk", "normal", 500),
             ("Space Grotesk", "normal", 700), ("Inter", "normal", 400),
             ("Inter", "normal", 600)]
    body = [card_bg(880, 310)]
    body.append(text(48, 66, "%d contributions" % data["total"], KANIT, 40,
                     INK, weight=800, extra=anim("rise", base)))
    body.append(text(48, 94, "in the last year", INTER, 14.5, MUTED,
                     extra=anim("rise", base + 0.08)))
    stats = [("%d days" % data["longest"], "LONGEST STREAK"),
             ("%d days" % data["current"], "CURRENT STREAK"),
             (str(data["active_days"]), "ACTIVE DAYS"),
             ("%s · %d" % (fmt_date(data["busiest"][0]), data["busiest"][1]),
              "BUSIEST DAY")]
    for i, (val, lab) in enumerate(stats):
        x = 452 + i * 94
        body.append(text(x, 62, val, GROTESK, 17.5, INK, weight=700,
                         extra=anim("rise", base + 0.10 + i * 0.07)))
        body.append(text(x, 82, lab, GROTESK, 8.5, MUTED, weight=500,
                         spacing="1.2",
                         extra=anim("rise", base + 0.14 + i * 0.07)))
    body.append('<line x1="48" y1="112" x2="832" y2="112" stroke="%s" '
                'stroke-opacity="0.14"/>' % INK)
    base_y, max_h, slot, bw = 258, 118, 784 / 12.0, 38
    busiest_month = max(months, key=lambda kv: kv[1])[0]
    for i, ((y, m), count) in enumerate(months):
        cx = 48 + slot * i + slot / 2
        h = max(3, round(max_h * count / peak)) if count else 3
        fill = DEEP if (y, m) == busiest_month and count else INK
        if not count:
            fill = INK
        op = "" if count else ' opacity="0.18"'
        body.append('<rect x="%.1f" y="%d" width="%d" height="%d" rx="4" '
                    'fill="%s"%s%s/>' % (cx - bw / 2, base_y - h, bw, h, fill,
                                         op, anim("growY", base + 0.15 + i * 0.06)))
        texts.append(str(count))
        if count:
            body.append(text(cx, base_y - h - 9, str(count), INTER, 12, BODY,
                             weight=600, anchor="middle",
                             extra=anim("fade", base + 0.45 + i * 0.06)))
        lab = dt.date(y, m, 1).strftime("%b")
        body.append(text(cx, base_y + 24, lab, GROTESK, 11, MUTED, weight=500,
                         anchor="middle",
                         extra=anim("fade", base + 0.30 + i * 0.04)))
        texts.append(lab)
    body.append('<line x1="48" y1="258" x2="832" y2="258" stroke="%s" '
                'stroke-opacity="0.25"/>' % INK)
    return svg_doc(880, 310, faces, texts, "".join(body))


def repo_card(base, repo):
    name = repo["name"]
    texts = [name, repo["desc"], repo["lang"], repo["lang_pct"],
             "★ %d" % repo["stars"], "View repository →"]
    faces = [("Space Grotesk", "normal", 700), ("Inter", "normal", 400),
             ("Inter", "normal", 600)]
    body = [card_bg(880, 138)]
    body.append('<rect x="3" y="18" width="6" height="102" rx="3" fill="%s"%s/>'
                % (DEEP, anim("growY", base + 0.05)))
    body.append(text(40, 50, name, GROTESK, 23, INK, weight=700,
                     extra=anim("rise", base)))
    if repo.get("live"):
        pill_x = 44 + len(name) * 14.6
        body.append('<rect x="%.0f" y="30" width="58" height="21" rx="10.5" '
                    'fill="%s"%s/>' % (pill_x, PALE, anim("fade", base + 0.3)))
        body.append(text(pill_x + 29, 45, "LIVE ↗", INTER, 10.5, DEEP,
                         weight=600, anchor="middle",
                         extra=anim("fade", base + 0.3)))
        texts.append("LIVE ↗")
    body.append(text(40, 80, repo["desc"], INTER, 15, BODY,
                     extra=anim("rise", base + 0.10)))
    body.append('<circle cx="45" cy="108" r="5" fill="%s"/>' % TS_BLUE)
    body.append(text(58, 113, "%s %s" % (repo["lang"], repo["lang_pct"]),
                     INTER, 12.5, BODY, weight=600,
                     extra=anim("fade", base + 0.2)))
    body.append(text(196, 113, "★ %d" % repo["stars"], INTER, 12.5, BODY,
                     weight=600, extra=anim("fade", base + 0.24)))
    body.append(text(832, 113, "View repository →", INTER, 12.5, DEEP,
                     weight=600, anchor="end",
                     extra=anim("fade", base + 0.28)))
    return svg_doc(880, 138, faces, texts, "".join(body))


def graph_card(base, data):
    days = data["days"]
    # Align to GitHub's calendar: columns are weeks starting on Sunday.
    first = days[0][0]
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)
    cells = {}
    for d, count, level in days:
        cells[d] = (count, level)
    n_weeks = ((days[-1][0] - start).days // 7) + 1
    texts = ["Every day, ", "in steel blue", "REFRESHED DAILY", "Less", "More",
             "%d contributions in the last year" % data["total"]]
    faces = [("Kanit", "normal", 800), ("Kanit", "italic", 800),
             ("Space Grotesk", "normal", 500), ("Inter", "normal", 400)]
    body = [card_bg(880, 264)]
    body.append(
        '<text x="48" y="54" font-family="%s" font-weight="800" '
        'font-size="30" fill="%s"%s>Every day, <tspan font-style="italic" '
        'fill="%s">in steel blue</tspan></text>'
        % (KANIT, INK, anim("rise", base), DEEP))
    body.append('<circle cx="700" cy="46" r="3.5" fill="%s">%s</circle>'
                % (DEEP, smil_pulse(base + 1.0)))
    body.append(text(832, 50, "REFRESHED DAILY", GROTESK, 11, MUTED,
                     weight=500, anchor="end", spacing="2",
                     extra=anim("fade", base + 0.1)))
    x0, y0, pitch, cell = 48, 88, 14.4, 11
    last_month = None
    for w in range(n_weeks):
        week_start = start + dt.timedelta(days=7 * w)
        if week_start.month != last_month and week_start <= days[-1][0]:
            last_month = week_start.month
            lab = week_start.strftime("%b")
            body.append(text(x0 + w * pitch, y0 - 10, lab, INTER, 10.5,
                             MUTED, extra=anim("fade", base + 0.2 + w * 0.01)))
            texts.append(lab)
        for r in range(7):
            d = week_start + dt.timedelta(days=r)
            if d < days[0][0] or d > days[-1][0] or d not in cells:
                continue
            _, level = cells[d]
            body.append(
                '<rect x="%.1f" y="%.1f" width="%d" height="%d" rx="2.5" '
                'fill="%s"%s/>' % (x0 + w * pitch, y0 + r * pitch, cell, cell,
                                   GRAPH_RAMP[min(level, 4)],
                                   anim("fade", base + 0.15 + w * 0.02 + r * 0.004)))
    legend_y = 232
    body.append(text(48, legend_y + 4, "Less", INTER, 11, MUTED,
                     extra=anim("fade", base + 0.6)))
    for i, col in enumerate(GRAPH_RAMP):
        body.append('<rect x="%d" y="%d" width="11" height="11" rx="2.5" '
                    'fill="%s"%s/>' % (86 + i * 15, legend_y - 7, col,
                                       anim("fade", base + 0.65 + i * 0.05)))
    body.append(text(86 + 5 * 15 + 6, legend_y + 4, "More", INTER, 11, MUTED,
                     extra=anim("fade", base + 0.9)))
    body.append(text(832, legend_y + 4,
                     "%d contributions in the last year" % data["total"],
                     INTER, 12, BODY, anchor="end",
                     extra=anim("fade", base + 0.7)))
    return svg_doc(880, 264, faces, texts, "".join(body))


# ------------------------------------------------------------------ main ---
def main():
    data = load_data()
    os.makedirs(OUT_DIR, exist_ok=True)
    cards = {}
    cards["hero.svg"] = hero_card(BASE_DELAYS[0])
    cards["tile-repos.svg"] = tile_card(
        BASE_DELAYS[1], str(PUBLIC_REPOS), "PUBLIC REPOS",
        "github.com/" + USER, INK, PALE)
    cards["tile-contributions.svg"] = tile_card(
        BASE_DELAYS[2], str(data["total"]), "CONTRIBUTIONS",
        "in the last year", STEEL, INK)
    cards["tile-projects.svg"] = tile_card(
        BASE_DELAYS[3], str(len(FEATURED)), "FEATURED PROJECTS",
        SITE + " ↗", DEEP, "#FFFFFF")
    cards["monthly.svg"] = monthly_card(BASE_DELAYS[4], data)
    for i, repo in enumerate(FEATURED):
        cards["repo-%s.svg" % repo["name"]] = repo_card(BASE_DELAYS[5 + i], repo)
    cards["graph.svg"] = graph_card(BASE_DELAYS[5 + len(FEATURED)], data)
    for name, svg in cards.items():
        with open(os.path.join(OUT_DIR, name), "w") as f:
            f.write(svg)
        print("wrote %-28s %6.1f KB" % (name, len(svg.encode()) / 1024))
    print("mode:", "STATIC (final frame)" if STATIC else "animated",
          "| total:", data["total"], "| months:",
          [(k, v) for k, v in data["months"]])


if __name__ == "__main__":
    sys.exit(main())
