"""
Locale-aware crisis-support context for the chat system prompt (Phase K).

Three rules this module exists to enforce. All three are load-bearing; none of
them is a style preference.

1.  It NEVER decides whether the user is in crisis. There is no detector here
    and there must not be one — this module only ever renders text; whether
    that text gets used is entirely the caller's call. Originally (Phase K)
    that meant unconditional, every turn, because no classifier here could be
    trusted not to be narrower than the model's own judgment.

    Phase U changed the caller, not this module: chat_prompt_service.py now
    gates inclusion on chat_router.classify_message's real `crisis` field —
    but only after building a validated, code-level fail-safe (any classify
    failure, or a turn the router never even ran on, defaults to crisis=True
    unconditionally, never left to the model to reason its way there) plus a
    several-turn carry-forward after a real crisis turn. The narrower-signal
    risk this rule originally guarded against is the failure path, and that
    path is now hard-coded to the safe side, not the classifier's call to
    make. See chat_service.py's `_CRISIS_WINDOW_TURNS` and the crisis_active
    computation just above build_messages() for the actual mechanism. The one
    residual gap: a classify call that *succeeds* but is simply wrong (a real
    signal, confidently misread as crisis=false) — that risk is real and not
    fully closed by this phase; it is the trade this module's caller now makes
    in exchange for not showing crisis text, with its format override, on
    every single ordinary turn.

2.  It NEVER contains a phone number. Numbers differ per country, go stale, and
    a wrong one during a crisis is worse than none at all. The only resource
    emitted is a URL into findahelpline.com — a directory run by ThroughLine in
    partnership with IASP, with a page per country. Verified live for this
    phase: /countries/in, /countries/us and /countries/gb all return 200, /in
    redirects to /countries/in, and an invalid code returns 404 (which is why
    country codes here can only ever come from the tzdb table below, never from
    client input).

3.  It NEVER performs a lookup. No IP geolocation, no third-party call, no
    network access of any kind — least of all one triggered by the content of a
    sensitive message. The only locale signal is the IANA timezone the browser
    already volunteers, resolved against a table built at import time from data
    already vendored inside the `tzdata` package.

Real state of the world before this module existed: the app had no locale
signal anywhere (users holds user_id/email/name/hashed_pw/created_at/
feed_version, register_user takes email/name/password, ChatRequest carried no
locale field, and nothing read Accept-Language), and no crisis instruction
anywhere in the prompt architecture — the resource lists users were seeing came
purely from the underlying model's own training.
"""

from __future__ import annotations

from importlib.resources import files

# The directory root — used verbatim when we don't know the country. Real and
# current; per-country pages hang off /countries/<iso2>.
HELPLINE_DIRECTORY = "https://findahelpline.com"


def _read_tzdata(name: str) -> str:
    return files("tzdata.zoneinfo").joinpath(name).read_text(encoding="utf-8")


def _parse_tab(name: str, key_col: int, val_col: int) -> dict[str, str]:
    """Parse one of the tab-separated tables tzdata ships. Comments start with #."""
    out: dict[str, str] = {}
    for line in _read_tzdata(name).splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("	")
        if len(parts) > max(key_col, val_col):
            out[parts[key_col].strip()] = parts[val_col].strip()
    return out


# IANA timezone -> ISO 3166-1 alpha-2, and that code -> the country's English
# name. Both come straight out of the `tzdata` package (requiremnts.txt:99,
# already a dependency — this adds none), which ships the tzdb reference tables
# `zone.tab` and `iso3166.tab` as package data. 418 zones and 249 countries as
# of tzdata 2026.2, and they update whenever tzdata does.
#
# zone.tab rather than zone1970.tab specifically because zone.tab guarantees
# exactly one country code per row, so there is no shared-zone ambiguity to
# resolve — and resolving it by guessing is the one thing this module must not do.
#
# Deliberately NO fallback for an unmapped zone (a deprecated alias like
# Asia/Calcutta, or "UTC"): not knowing where someone is is a real state, and the
# honest-uncertainty branch below is the correct answer to it, not a guess.
_ZONE_TO_COUNTRY: dict[str, str] = _parse_tab("zone.tab", key_col=2, val_col=0)
_COUNTRY_NAMES:   dict[str, str] = _parse_tab("iso3166.tab", key_col=0, val_col=1)


def resolve_country(client_timezone: str | None) -> tuple[str, str] | None:
    """
    Resolve a browser-reported IANA timezone to (iso2, display_name).

    Returns None when the timezone is missing, blank, or not a real IANA zone
    with a country — i.e. when we do not know where this person is.

    This is also the trust boundary for `client_timezone`, which is arbitrary
    client input that ends up inside a system prompt. It is never echoed: only
    an exact key of _ZONE_TO_COUNTRY resolves, and what gets rendered is that
    key plus tzdb's own country name, so there is no path from arbitrary client
    text into the prompt.
    """
    cc = _ZONE_TO_COUNTRY.get((client_timezone or "").strip())
    if not cc:
        return None
    return cc, _COUNTRY_NAMES.get(cc, cc)


def country_helpline_url(iso2: str) -> str:
    """Per-country directory page. Codes come from _ZONE_TO_COUNTRY only."""
    return f"{HELPLINE_DIRECTORY}/countries/{iso2.lower()}"


def _locale_block(client_timezone: str | None) -> str:
    resolved = resolve_country(client_timezone)

    if resolved is None:
        return (
            "WHERE THIS PERSON IS: unknown.\n"
            "Their device did not report a timezone you can place, so you do not know what\n"
            "country they are in. Be honest about that instead of assuming — and do NOT fall\n"
            "back to a US number, or to any hotline number you happen to remember. Most\n"
            "people on earth are not in the US, and a number that doesn't connect where they\n"
            "actually are is worse than no number at all, because they will try it at the\n"
            "worst possible moment and get nothing.\n"
            f"Give them the international directory instead: {HELPLINE_DIRECTORY}\n"
            "It asks where they are and returns the real line for that country. Asking them\n"
            "yourself is fine too — but give the link first. Help doesn't wait for an answer."
        )

    iso2, name = resolved
    return (
        f"WHERE THIS PERSON IS: {name} — their device reports the timezone "
        f"{(client_timezone or '').strip()}.\n"
        f"Crisis and mental-health lines for {name}: {country_helpline_url(iso2)}\n"
        f"That page is maintained and specific to {name}. Point them there.\n"
        "Do not recite a phone number from memory — not for this country, not for any other.\n"
        "Yours may be out of date, misremembered, or belong somewhere else entirely. The link\n"
        "is the accurate answer; a half-remembered number is a dangerous one."
    )


# The standing behavioural instruction. Constant, not built per-turn — only the
# locale block above varies.
_CRISIS_CONDUCT = """\
CRISIS AND DISTRESS SUPPORT — ALWAYS IN FORCE:
This section applies on every turn of every conversation and nothing elsewhere in
this prompt overrides it.

- If someone signals they are thinking about suicide, self-harm, or not wanting to
  be alive — plainly, sideways, hypothetically, bitterly, as a threat, as a joke,
  or as leverage in an argument they're losing — treat it as real and respond to it.
  Offer help every single time. Do not try to judge whether they meant it. You
  cannot tell, responding to someone who didn't mean it costs nothing, and not
  responding to someone who did costs everything.
- Offer the resource outright. Never ask for permission first ("would you like some
  resources?") and never make it conditional on them explaining themselves.
- Lead like a person, not a pamphlet. Say the human thing first — that you're glad
  they told you, that you don't want them sitting with this on their own — and then
  give them somewhere real to go. Don't open with a bulleted list of services.
- Stay short and steady. This is the one moment where more words are not more care.
  Don't reflect their phrasing back at them, don't interpret what they "really"
  mean, don't stack up questions, don't dramatise it. Be calm, be present, name one
  concrete next step.
- You are not their only option and you should not act like it. Warmth, then a real
  human on the other end of a real line — that's the shape of a good answer here.
- This overrides output formatting. If a turn calls for this, answer in plain,
  direct prose. Do not wrap it in JSON, headings, or any response schema, whatever
  the format rules elsewhere in this prompt say.

AFTER A DISTRESS TURN — HOW THE NEXT MESSAGES GO:
- Anger, swearing, sarcasm, "I was joking", or a hard swerve into another topic
  right after you offered help is NOT a signal that you got it wrong. It is one of
  the most ordinary ways real distress comes back out. RESPONSE PRINCIPLES tells you
  that pushback means change your approach — that rule is suspended here. Do not
  apply it to this.
- Do not apologise for having offered help, and do not walk it back. "Sorry if I
  upset you" reads as agreeing it was a mistake to care.
- Do not re-paste the same resource block word for word. Repeating yourself reads as
  not listening. Say it shorter, differently, and leave it standing.
- Do not quietly slide back into ordinary assistant mode as though the earlier
  message never happened. Answer whatever they've now asked — genuinely, not
  grudgingly — while still being someone who remembers what they said.
- If they insist they're fine, don't argue and don't interrogate. Take them at their
  word out loud, and still leave one short line open — that you're around, and that
  the line you gave them is worth using even on an ordinary day.
- Never treat their reluctance to reach out as settled. Encourage it again, lightly,
  without nagging."""


def build_crisis_support_section(client_timezone: str | None = None) -> str:
    """
    The full crisis-support prompt section. Never empty, never gated.

    `client_timezone` is the browser's IANA zone for this turn (chat context key
    "client_timezone"); anything unrecognised degrades to the honest-uncertainty
    branch rather than to a guess.
    """
    return f"{_CRISIS_CONDUCT}\n\n{_locale_block(client_timezone)}"
