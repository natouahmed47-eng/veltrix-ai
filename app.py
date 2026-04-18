import html
import os
import re
import json
import secrets
import statistics
import traceback
import requests
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlencode

from flask import Flask, jsonify, make_response, redirect, request, render_template_string, send_file, session
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI, OpenAIError
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# ── CORS — restrict to the app's own origin(s) ──
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
if _allowed_origins:
    CORS(app, origins=[o.strip() for o in _allowed_origins.split(",") if o.strip()])
else:
    # Same-origin only: no cross-origin requests allowed when env var is unset.
    CORS(app, origins=[])

# ── Rate limiting ──
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],            # no blanket limit; applied per-route
    storage_uri="memory://",
)

# ── Session / cookie security ──
_flask_secret = os.environ.get("FLASK_SECRET_KEY")
if not _flask_secret:
    raise RuntimeError("FLASK_SECRET_KEY environment variable is required")
app.secret_key = _flask_secret
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing")

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")
SHOPIFY_REDIRECT_URI = os.environ.get("SHOPIFY_REDIRECT_URI")
SHOPIFY_SCOPES = os.environ.get("SHOPIFY_SCOPES", "read_products,write_products")

PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")
PAYPAL_API_BASE = os.environ.get("PAYPAL_API_BASE", "https://api-m.paypal.com")
PAYPAL_PLAN_ID = os.environ.get("PAYPAL_PLAN_ID", "")
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID", "")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

# ── Deploy verification marker — change this string on every deploy ──
_CODE_VERSION = "version-2026-04-fix-check"

# ── Log level — ensure INFO-level logs are visible in production ──
import logging as _logging
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
_logging.basicConfig(level=getattr(_logging, _log_level, _logging.INFO))
app.logger.setLevel(getattr(_logging, _log_level, _logging.INFO))

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

MAX_AI_GENERATION_RETRIES = 3
FREE_ANALYSIS_LIMIT = 5


# ── Secure browser headers ──
@app.after_request
def _set_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Strict-Transport-Security"] = (
        "max-age=63072000; includeSubDomains; preload"
    )
    response.headers["Referrer-Policy"] = "same-origin"
    return response


# ── CSRF protection helpers ──
def _generate_csrf_token():
    """Create a new CSRF token and store it in the session."""
    token = secrets.token_hex(32)
    session["csrf_token"] = token
    return token


def csrf_protected(f):
    """Decorator that enforces CSRF token on session-authenticated admin POSTs.

    Bearer-token requests (API tools) are exempt because they carry a secret
    that already proves intent.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # If the caller authenticated via Bearer token, skip CSRF check.
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            provided = auth_header.replace("Bearer ", "").strip()
            if ADMIN_SECRET and secrets.compare_digest(provided, ADMIN_SECRET):
                return f(*args, **kwargs)

        # Session-based callers must present a valid CSRF token.
        token_in_session = session.get("csrf_token", "")
        token_in_header = request.headers.get("X-CSRF-Token", "")
        if (
            not token_in_session
            or not token_in_header
            or not secrets.compare_digest(token_in_session, token_in_header)
        ):
            return jsonify({"error": "CSRF token missing or invalid"}), 403
        return f(*args, **kwargs)
    return decorated

# Category-specific fields that may be present in AI analysis results.
# Used by API endpoints to dynamically pass through category data.
CATEGORY_SPECIFIC_FIELDS = [
    # Universal fields present in every response
    "use_cases", "performance", "specifications",
    # Nested category-specific object
    "category_specific",
    # Legacy flat fields kept for backward compatibility
    "scent_family", "fragrance_notes", "scent_evolution", "projection",
    "longevity", "best_season", "best_occasions", "emotional_triggers",
    "luxury_description",
    "specs", "battery", "pros", "cons",
    "style", "materials", "fit", "occasions", "care_instructions",
    "platform", "features", "integrations", "pricing_model",
    "problem", "solution", "monetization", "competitive_advantage", "market_size",
]

# Supported product categories
SUPPORTED_CATEGORIES = ["fragrance", "electronics", "fashion", "beauty", "home", "general"]

# Minimum character length for a reason/action to be considered specific (not generic).
MIN_SPECIFIC_REASON_LENGTH = 25

# Pre-compiled regex for detecting negative signals in verdict reasoning/top_reasons.
# Used by post-processing to override BUILD → DON'T BUILD when reasoning contradicts verdict.
_negative_signals_re = re.compile(
    r"\b(no demand|no market|insufficient|cannot|unfeasible|infeasible"
    r"|unclear|lack of|not viable|no viable|not feasible"
    r"|no evidence|no verifiable|oversaturated|saturated"
    r"|no competitive|no differentiation|no moat|no clear"
    r"|no proven|weak demand|low demand|no search volume"
    r"|no social proof|no traction|high risk|too risky"
    r"|high competition|does not justify|does not meet|not recommended"
    r"|no realistic|no sustainable|negative margin|no margin)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Smart validation helpers for reasoning preservation
# ---------------------------------------------------------------------------
# Detects real analytical signals that indicate the AI produced specific,
# useful reasoning — not generic filler.  Used to decide whether to keep
# AI-generated content vs. falling back.

_real_signal_re = re.compile(
    r"(?:"
    # Market condition language
    r"(?:saturat|fragment|open market|niche market|blue ocean|red ocean"
    r"|market share|market size|TAM|SAM|SOM|addressable market)"
    # Demand quality language
    r"|(?:high demand|low demand|unproven demand|proven demand|validated demand"
    r"|search volume|trend(?:ing)?|growing|declining|customer base)"
    # Monetization / pricing / margins
    r"|(?:margin|COGS|unit cost|retail price|wholesale|pricing|revenue"
    r"|profit|CAC|LTV|AOV|subscription|monetiz|MRR|ARR)"
    # Retention / churn
    r"|(?:churn|retention|repeat purchase|customer lifetime)"
    # Legal / IP / licensing
    r"|(?:trademark|patent|licens|copyright|IP |intellectual property"
    r"|regulat|FDA|FTC|compliance|cease.and.desist|authorized)"
    # Differentiation / moat
    r"|(?:moat|switching cost|differentiat|unique value|proprietary"
    r"|barrier.to.entry|first.mover|network effect)"
    # Quantitative clues (numbers, percentages, dollar values, timeframes)
    r"|(?:\d+\s*%|\$\s*[\d,.]+|\d+[\d,]*\s*(?:unit|user|customer|subscriber)"
    r"|\d+\s*(?:hour|day|week|month|year|minute)|\d+\s?(?:usd|دولار))"
    # Supply chain specifics
    r"|(?:MOQ|minimum order|supplier|sourcing|Alibaba|manufacturer|landed cost"
    r"|shipping cost|fulfillment|warehouse)"
    # SaaS metrics
    r"|(?:cac|churn|ltv|pricing|subscription|mrr|arr|arpu|payback period)"
    # Shopify ecosystem / known competitors
    r"|(?:shopify|narvar|returnly|loop\s?returns?)"
    r")",
    re.IGNORECASE,
)

# Case-sensitive pattern for named entities (proper nouns, domain names).
# Kept separate so IGNORECASE doesn't make it match common words like "good idea".
_named_entity_re = re.compile(
    # Multi-word proper nouns (e.g. "Tom Ford", "Louis Vuitton", "Flight Club")
    r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)+"
    # Domain-style names (e.g. "Monday.com", "StockX.io")
    r"|[A-Z][a-zA-Z]+\.(?:com|io|co|org|net)"
)

# Known fallback / placeholder reason phrases.  These contain signal words
# like "demand", "saturated", "margin" which would trick ``has_real_signal``
# into treating them as real analysis.  They must be recognised as generic
# *before* the signal-word check runs.
# Uses substring matching (re.search) so that any variation of these phrases
# is caught regardless of extra punctuation, suffixes, or wording tweaks.
_KNOWN_FALLBACK_PATTERN = re.compile(
    r"("
    # Match progressively more of the known fallback phrases so that
    # the *remainder* (checked for real signal) is truly what the AI added.
    r"no verifiable demand(?:\s+signals)?(?:\s+or\s+market\s+data(?:\s+available)?)?"
    r"|competitive landscape(?:\s+(?:is\s+)?unclear)?(?:\s*[-—–]+\s*risk\s+of\s+entering\s+a\s+saturated\s+space)?"
    r"|unit economics(?:\s+and\s+margin\s+potential)?\s*(?:cannot|can(?:'|')t)\s+be\s+assessed"
    r"|لا توجد إشارات طلب"
    r"|المشهد التنافسي غير واضح"
    r"|لا يمكن تقييم اقتصاديات"
    r")",
    re.IGNORECASE,
)

# Phrases that are clearly generic filler — only these warrant replacement.
_clearly_generic_re = re.compile(
    r"^\s{0,5}("
    r"addresses a market need|addresses a real need|addresses an unmet need"
    r"|feasible to build|technically feasible|can be built"
    r"|shows potential|has potential|strong potential"
    r"|worth exploring|could be promising|interesting concept"
    r"|validate demand|do more research|research competitors"
    r"|test the market|explore partnerships|gather feedback"
    r"|conduct market research|seek feedback|get feedback"
    r"|product addresses a market need"
    r")\.?\s{0,5}$",
    re.IGNORECASE,
)


def has_real_signal(text: str) -> bool:
    """Return True if the text contains at least one concrete analytical signal.

    This is the primary guard against over-replacement: if the AI output
    references real data (competitors, numbers, market conditions, margins,
    legal constraints, etc.), it should be preserved.
    """
    if not text or not text.strip():
        return False
    # Check analytical-term signals (case-insensitive)
    if _real_signal_re.search(text):
        return True
    # Check named entities (case-sensitive — proper nouns, domain names)
    if _named_entity_re.search(text):
        return True
    return False


def is_reason_generic(text: str) -> bool:
    """Return True only if a reason is clearly generic filler with no real signal.

    A reason is generic if:
    - it matches a known fallback/placeholder phrase AND the remaining text
      (beyond the fallback substring) does not contain real analytical signal, OR
    - it matches a known filler pattern entirely, OR
    - it is very short AND contains no quantitative or analytical signals.
    """
    if not text or not text.strip():
        return True
    stripped = text.strip()
    # ---- Known fallback phrases ----
    # These contain signal words like "demand" / "saturated" / "margin" but are
    # still placeholder text, not real analysis.  Substring matching ensures
    # variations (extra punctuation, suffixes, ellipsis) are still caught.
    #
    # HOWEVER, the AI sometimes expands a fallback phrase with real specifics
    # (named competitors, dollar amounts, concrete data).  In that case the
    # reason should be preserved.  We detect this by removing the matched
    # fallback substring and checking whether the *remainder* contains real
    # analytical signal.  This avoids false positives from signal words that
    # are part of the fallback phrase itself (e.g. "saturated", "margin").
    m = _KNOWN_FALLBACK_PATTERN.search(stripped)
    if m:
        # Remove the matched fallback substring and check the remainder.
        remainder = (stripped[:m.start()] + stripped[m.end():]).strip()
        if not remainder or not has_real_signal(remainder):
            return True
        # The reason contains the fallback substring but the surrounding text
        # has real analytical signal — preserve it.
    # Entirely a known generic phrase
    if _clearly_generic_re.match(stripped):
        return True
    # If the text has any real analytical signal, keep it
    if has_real_signal(stripped):
        return False
    # Very short text with no signal is likely generic
    if len(stripped) < MIN_SPECIFIC_REASON_LENGTH:
        return True
    return False


def is_action_generic(text: str) -> bool:
    """Return True only if a next-action is clearly generic filler.

    Same logic as is_reason_generic — actions that reference specific
    numbers, companies, or concrete steps are preserved.
    """
    return is_reason_generic(text)


# ---------------------------------------------------------------------------
# Derive top_reasons from analysis text (heuristic extraction)
# ---------------------------------------------------------------------------
# Category keyword maps — each maps a reason "dimension" to trigger keywords
# and a sentence-building template.
_REASON_CATEGORIES = {
    "demand": {
        "keywords": re.compile(
            r"\b(demand|adoption|ROI|churn|users|growth|search volume|trend"
            r"|customer base|retention|repeat purchase|subscriber|traction"
            r"|validated demand|proven demand|unproven demand)\b",
            re.IGNORECASE,
        ),
        "label": "Demand",
    },
    "competition": {
        "keywords": re.compile(
            r"\b(competitor|competitors|competes|compete|competing"
            r"|saturated|market share|incumbent"
            r"|incumbents|CAC|customer acquisition|fragmented|red ocean"
            r"|blue ocean|market leader|dominant|dominate"
            r"|narvar|returnly|loop\s?returns?)\b",
            re.IGNORECASE,
        ),
        "label": "Competition",
    },
    "monetization": {
        "keywords": re.compile(
            r"(?:"
            r"\b(?:pricing|margin|cost|revenue|CAC|LTV|COGS|unit cost"
            r"|retail price|wholesale|profit|MRR|ARR|monetiz"
            r"|subscription|AOV|churn|ltv)\b"
            r"|\$\d+|\d+%|\d+\s?(?:usd|دولار)"
            r")",
            re.IGNORECASE,
        ),
        "label": "Monetization",
    },
    "differentiation": {
        "keywords": re.compile(
            r"\b(differentiat\w*|undifferentiated|moat|unique|switching cost"
            r"|barrier to entry|first mover|network effect|proprietary"
            r"|IP\b|patent|trademark|licens\w*|weak|similar|copycat"
            r"|overlap\w*|commodit\w*|no\s+(?:clear\s+)?moat)\b",
            re.IGNORECASE,
        ),
        "label": "Differentiation",
    },
    "saas_metrics": {
        "keywords": re.compile(
            r"\b(cac|churn|ltv|pricing|subscription|mrr|arr|arpu|payback period)\b",
            re.IGNORECASE,
        ),
        "label": "SaaS Metrics",
    },
    "shopify_ecosystem": {
        "keywords": re.compile(
            r"\b(shopify|returns|narvar|returnly|loop\s?returns?"
            r"|shopify app|shopify ecosystem|e-?commerce)\b",
            re.IGNORECASE,
        ),
        "label": "Shopify Ecosystem",
    },
}


def derive_top_reasons_from_text(text: str) -> list[str]:
    """Extract up to 3 specific reasons from analysis text using heuristic rules.

    Scans *text* (typically verdict_reasoning + long analysis sections) for
    keyword signals in six categories: demand, competition, monetization,
    differentiation, saas_metrics, shopify_ecosystem.  For each matched
    category, it picks the most signal-dense sentence and condenses it into
    a punchy reason.

    Returns a list of up to 3 derived reasons (may be fewer if the text
    only touches fewer categories).
    """
    if not text or not text.strip():
        return []

    app.logger.debug("FULL ANALYSIS TEXT: %s", text)

    # Split into sentences
    sentences = re.split(r'[.!?]\s+|\n+', text)
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) >= 12]

    app.logger.debug("SPLIT SENTENCES: %s", sentences)

    derived: list[str] = []
    used_categories: set[str] = set()

    # --- Broad signal regex for sentences with quantitative / specific data ---
    _broad_signal_re = re.compile(
        r"(?:\$\s*[\d,.]+|\d+\s*%|\d{2,})"  # dollar amounts, percentages, numbers
        r"|(?:\bCAC\b|\bchurn\b|\bLTV\b|\bARR\b|\bMRR\b|\bpric\w+)"  # SaaS metrics
        r"|(?:\breturnly\b|\bnarvar\b|\bloop\s?returns?\b)"  # named competitors
        r"|(?:\bweak\b|\bno moat\b|\bsimilar\b|\bundifferentiated\b|\boverlap)",  # differentiation
        re.IGNORECASE,
    )

    # Score each sentence by category and pick the best sentence per category
    category_best: dict[str, tuple[str, int]] = {}
    for sent in sentences:
        for cat_key, cat_info in _REASON_CATEGORIES.items():
            matches = cat_info["keywords"].findall(sent)
            if matches:
                score = len(matches)
                # Bonus for sentences that also contain broad quantitative signals
                if _broad_signal_re.search(sent):
                    score += 1
                if cat_key not in category_best or score > category_best[cat_key][1]:
                    category_best[cat_key] = (sent, score)

    # Build reasons from best-matching sentences, ordered by score
    ranked = sorted(category_best.items(), key=lambda x: x[1][1], reverse=True)
    for cat_key, (best_sent, _score) in ranked:
        if len(derived) >= 3:
            break
        if cat_key in used_categories:
            continue
        used_categories.add(cat_key)
        # Trim the sentence to a reasonable length for a "reason" line
        reason = best_sent.strip()
        # Remove leading bullet markers if present
        reason = re.sub(r"^[-•–]\s*", "", reason)
        # Remove HTML tags if present
        reason = re.sub(r"<[^>]+>", "", reason)
        # Cap length — keep the first natural clause if very long
        if len(reason) > 180:
            # Try to break at a clause boundary (comma, semicolon, dash)
            for sep in [" — ", " – ", "; ", ", "]:
                idx = reason.find(sep, 60)
                if 60 < idx < 160:
                    reason = reason[:idx]
                    break
            else:
                reason = reason[:175].rsplit(" ", 1)[0] + "…"
        if reason and len(reason) >= MIN_SPECIFIC_REASON_LENGTH:
            derived.append(reason)

    app.logger.debug("DERIVED REASONS: %s", derived)

    if not derived:
        app.logger.debug("DERIVATION FAILED — no reasons extracted")

    return derived


# Verdict-field names that should NOT be aggressively scrubbed by regex.
_VERDICT_FIELDS = frozenset(["verdict_reasoning", "top_reasons", "next_actions"])


# ---------------------------------------------------------------------------
# Lightweight brand/product spelling corrections
# Keys are lowercase misspellings; values are the canonical form.
# ---------------------------------------------------------------------------
BRAND_CORRECTIONS = {
    "doir": "Dior",
    "dior perfume": "Dior fragrance",
    "nik": "Nike",
    "nikee": "Nike",
    "nkie": "Nike",
    "aple": "Apple",
    "appel": "Apple",
    "aplle": "Apple",
    "cerve": "CeraVe",
    "ikea kalax": "IKEA Kallax",
    "ikea callax": "IKEA Kallax",
    "addidas": "Adidas",
    "adiddas": "Adidas",
    "samung": "Samsung",
    "samsng": "Samsung",
    "samsumg": "Samsung",
    "gucchi": "Gucci",
    "guuci": "Gucci",
    "chanle": "Chanel",
    "chnal": "Chanel",
    "versache": "Versace",
    "versac": "Versace",
    "dolce gabana": "Dolce & Gabbana",
    "dolce gabanna": "Dolce & Gabbana",
    "ysl": "Yves Saint Laurent",
    "lous vuitton": "Louis Vuitton",
    "luis vuitton": "Louis Vuitton",
    "loui vuitton": "Louis Vuitton",
    "zarra": "Zara",
    "h and m": "H&M",
    "gogle": "Google",
    "googel": "Google",
    "soney": "Sony",
    "sonny": "Sony",
    "lenevo": "Lenovo",
    "lenvoo": "Lenovo",
    "micrsoft": "Microsoft",
    "microsft": "Microsoft",
}

# ---------------------------------------------------------------------------
# Brand → category mapping (applied AFTER preprocessing, BEFORE final response)
# Keys are canonical brand names (title-case); values are SUPPORTED_CATEGORIES.
# ---------------------------------------------------------------------------
BRAND_CATEGORY_MAP = {
    "Dior": "fashion",
    "Nike": "fashion",
    "Apple": "electronics",
    "IKEA": "home",
    "CeraVe": "beauty",
    "Samsung": "electronics",
    "Gucci": "fashion",
    "Chanel": "fashion",
    "Louis Vuitton": "fashion",
    "Adidas": "fashion",
    "Versace": "fashion",
    "Dolce & Gabbana": "fashion",
    "Yves Saint Laurent": "fashion",
    "Zara": "fashion",
    "H&M": "fashion",
    "Google": "electronics",
    "Sony": "electronics",
    "Lenovo": "electronics",
    "Microsoft": "electronics",
}

# Pre-sorted brand list (longest first) for deterministic matching
_SORTED_BRANDS = sorted(BRAND_CATEGORY_MAP, key=len, reverse=True)


def get_brand_category(interpreted_input: str) -> str:
    """Return the mapped category for a known brand found in *interpreted_input*.

    Checks whether any key in BRAND_CATEGORY_MAP appears (case-insensitive,
    word-boundary match) in the interpreted input.  Longer brand names are
    checked first so that "Louis Vuitton" matches before a single-word entry.

    Returns the mapped category string, or an empty string if no brand matches.
    """
    text_lower = interpreted_input.lower()
    for brand in _SORTED_BRANDS:
        # Use word-boundary regex to avoid false positives
        if re.search(r"(?<!\w)" + re.escape(brand.lower()) + r"(?!\w)", text_lower):
            return BRAND_CATEGORY_MAP[brand]
    return ""


def preprocess_product_input(raw_input: str):
    """Normalize and correct common brand/product misspellings.

    Returns a tuple of (corrected_input, original_input).
    The corrected_input has dictionary-based fixes applied.
    The original_input is the trimmed but otherwise unchanged value.
    """
    original = raw_input.strip()
    if not original:
        return original, original

    normalized = original.lower()

    # Try full-string match first, then token-level replacements
    if normalized in BRAND_CORRECTIONS:
        corrected = BRAND_CORRECTIONS[normalized]
        return corrected, original

    # Token-level: replace any token (or bigram) that matches a known typo
    tokens = normalized.split()
    corrected_tokens = original.split()  # keep original casing for non-matched tokens
    changed = False
    i = 0
    while i < len(tokens):
        # Try bigram first (e.g. "ikea kalax")
        if i + 1 < len(tokens):
            bigram = f"{tokens[i]} {tokens[i + 1]}"
            if bigram in BRAND_CORRECTIONS:
                replacement = BRAND_CORRECTIONS[bigram]
                corrected_tokens[i] = replacement
                corrected_tokens[i + 1] = ""
                changed = True
                i += 2
                continue
        # Single token
        if tokens[i] in BRAND_CORRECTIONS:
            corrected_tokens[i] = BRAND_CORRECTIONS[tokens[i]]
            changed = True
        i += 1

    if changed:
        corrected = " ".join(t for t in corrected_tokens if t).strip()
        return corrected, original

    return original, original


class ShopifyStore(db.Model):
    __tablename__ = "shopify_stores"

    id = db.Column(db.Integer, primary_key=True)
    shop = db.Column(db.String(255), unique=True, nullable=False, index=True)
    access_token = db.Column(db.Text, nullable=False)
    scope = db.Column(db.Text, nullable=True)
    default_language = db.Column(db.String(10), default="en")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.Text, nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    is_pro = db.Column(db.Boolean, default=False, nullable=False)
    paypal_order_id = db.Column(db.String(255), nullable=True)
    paypal_subscription_id = db.Column(db.String(255), nullable=True)
    paypal_plan_id = db.Column(db.String(255), nullable=True)
    subscription_status = db.Column(db.String(50), nullable=True)
    paypal_last_event_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    analyses = db.relationship("SavedAnalysis", backref="user", lazy=True)


class SavedAnalysis(db.Model):
    __tablename__ = "saved_analyses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    idea = db.Column(db.Text, nullable=False)
    result_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TrackingEvent(db.Model):
    __tablename__ = "tracking_events"

    id = db.Column(db.Integer, primary_key=True)
    event_name = db.Column(db.String(100), nullable=False, index=True)
    source = db.Column(db.String(100), nullable=True)
    plan = db.Column(db.String(50), nullable=True)
    user_state = db.Column(db.String(50), nullable=True)
    username = db.Column(db.String(80), nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


# Allowed event names for the tracking endpoint
_ALLOWED_TRACKING_EVENTS = frozenset({
    "pricing_view",
    "upgrade_click",
    "paypal_button_rendered",
    "paypal_subscription_approved",
    "payment_success_page_view",
    "payment_cancel_page_view",
    "experiment_view",
    "experiment_conversion",
    "cta_primary_click",
})

# Maximum request body size for the tracking endpoint (2 KB)
_TRACK_EVENT_MAX_BYTES = 2048


def get_current_user():
    """Extract user from Authorization header (Bearer token)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    if not token:
        return None
    return User.query.filter_by(token=token).first()


def login_required(f):
    """Decorator that requires a valid auth token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if user is None:
            return jsonify({"error": "Authentication required"}), 401
        return f(user, *args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator that requires admin auth via Bearer token OR session cookie."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check session cookie first (set by POST /api/admin/login)
        if session.get("admin_authenticated"):
            return f(*args, **kwargs)
        # Fall back to Authorization header for backward compat / API tools
        auth_header = request.headers.get("Authorization", "")
        provided = auth_header.replace("Bearer ", "").strip()
        if not ADMIN_SECRET or not secrets.compare_digest(provided, ADMIN_SECRET):
            return jsonify({"error": "Unauthorized"}), 403
        return f(*args, **kwargs)
    return decorated


def get_paypal_access_token():
    """Obtain an OAuth2 access token from PayPal."""
    resp = requests.post(
        f"{PAYPAL_API_BASE}/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def sanitize_plain_text(text_value: str) -> str:
    if not text_value:
        return ""
    return (
        str(text_value)
        .replace("#", "")
        .replace("*", "")
        .replace("`", "")
        .strip()
    )


def is_valid_html_description(html: str) -> bool:
    if not html or not isinstance(html, str):
        return False

    text = html.strip().lower()

    if "<ul>" not in text or "</ul>" not in text:
        return False

    li_count = text.count("<li>")
    if li_count < 5 or li_count > 7:
        return False

    if "<p>" not in text or "</p>" not in text:
        return False

    return True


def build_fallback_description(product_title: str = "", brand: str = "", angle: str = "general") -> str:
    name = (product_title or "this product").strip()
    brand_text = f" from {brand.strip()}" if brand and brand.strip() else ""

    fallback_map = {
        "grooming": (
            f"<p>Upgrade your grooming routine with {name}{brand_text} and enjoy a cleaner, more confident result.</p>"
            "<p>Designed for comfort and convenience, this product helps make your routine feel easier and more effective.</p>"
            "<ul>"
            "<li>Enjoy a smoother grooming experience with practical everyday performance.</li>"
            "<li>Save time with a solution built for convenience and reliability.</li>"
            "<li>Feel more confident with cleaner, more polished results.</li>"
            "<li>Use a product designed to make your routine feel easier.</li>"
            "<li>Choose a dependable option that supports daily grooming needs.</li>"
            "</ul>"
            "<p>Make the switch today and enjoy the difference a better grooming essential can make.</p>"
        ),
        "beauty": (
            f"<p>Elevate your beauty routine with {name}{brand_text} and enjoy a more polished, confident look.</p>"
            "<p>This solution is designed to help your daily self-care feel smoother, easier, and more rewarding.</p>"
            "<ul>"
            "<li>Support a more radiant and put-together everyday appearance.</li>"
            "<li>Enjoy a routine that feels easier, smoother, and more effective.</li>"
            "<li>Save time while upgrading your self-care experience.</li>"
            "<li>Add comfort and convenience to your daily beauty routine.</li>"
            "<li>Choose a beauty essential that helps you feel more confident.</li>"
            "</ul>"
            "<p>Refresh your routine today with a beauty upgrade you will actually enjoy using.</p>"
        ),
        "home": (
            f"<p>Make everyday living easier with {name}{brand_text} and enjoy a more practical home routine.</p>"
            "<p>Built to simplify daily tasks, this product helps reduce hassle and improve comfort at home.</p>"
            "<ul>"
            "<li>Bring more ease and convenience into your daily routine.</li>"
            "<li>Save time with a solution built around real household needs.</li>"
            "<li>Enjoy a more organized and stress-free experience.</li>"
            "<li>Improve comfort and usability in the moments that matter most.</li>"
            "<li>Choose a dependable addition that supports everyday living.</li>"
            "</ul>"
            "<p>Simplify your routine with a home essential built for real life.</p>"
        ),
        "tech": (
            f"<p>Upgrade your setup with {name}{brand_text} and enjoy a smarter everyday experience.</p>"
            "<p>This product is designed to bring convenience, performance, and modern functionality into your routine.</p>"
            "<ul>"
            "<li>Enjoy a smoother and more efficient daily experience.</li>"
            "<li>Save time with practical functionality that fits your routine.</li>"
            "<li>Get dependable performance where it matters most.</li>"
            "<li>Add convenience and flexibility to your everyday setup.</li>"
            "<li>Choose a modern essential built to keep up with your lifestyle.</li>"
            "</ul>"
            "<p>Make the smarter choice for a more seamless everyday routine.</p>"
        ),
        "fashion": (
            f"<p>Refine your look with {name}{brand_text} and add more confidence to your style.</p>"
            "<p>Designed to feel versatile and polished, this piece helps elevate your everyday wardrobe.</p>"
            "<ul>"
            "<li>Enhance your personal style with a more elevated finish.</li>"
            "<li>Enjoy a versatile piece that works across different occasions.</li>"
            "<li>Feel more confident with a polished and put-together look.</li>"
            "<li>Bring comfort and style together in one smart choice.</li>"
            "<li>Choose an item that adds value to your everyday wardrobe.</li>"
            "</ul>"
            "<p>Step into a sharper, more confident version of your style today.</p>"
        ),
        "fitness": (
            f"<p>Support your performance with {name}{brand_text} and make your fitness routine feel more effective.</p>"
            "<p>Built for comfort and consistency, this solution helps support your training goals with less friction.</p>"
            "<ul>"
            "<li>Make your routine feel more effective and easier to maintain.</li>"
            "<li>Stay more comfortable and focused during training.</li>"
            "<li>Support better performance with a smarter fitness choice.</li>"
            "<li>Reduce friction in your routine and improve consistency.</li>"
            "<li>Choose a solution built around real performance needs.</li>"
            "</ul>"
            "<p>Upgrade your training experience with a smarter fitness essential.</p>"
        ),
        "pet": (
            f"<p>Make pet care easier with {name}{brand_text} and enjoy a calmer daily routine.</p>"
            "<p>Designed for comfort and convenience, this product helps simplify the care you provide every day.</p>"
            "<ul>"
            "<li>Enjoy a smoother and less stressful care routine.</li>"
            "<li>Save time while improving your pet care experience.</li>"
            "<li>Support better comfort for both you and your pet.</li>"
            "<li>Make daily care feel easier, cleaner, and more efficient.</li>"
            "<li>Choose a dependable pet essential built for real use.</li>"
            "</ul>"
            "<p>Simplify your routine with a pet care upgrade that makes daily life easier.</p>"
        ),
        "general": (
            f"<p>Upgrade your routine with {name}{brand_text} and enjoy a smarter, more effective experience.</p>"
            "<p>This product is designed to deliver comfort, convenience, and practical value from the start.</p>"
            "<ul>"
            "<li>Enjoy a smoother and more reliable experience every time.</li>"
            "<li>Save time with practical performance built for daily use.</li>"
            "<li>Feel more confident with cleaner and more polished results.</li>"
            "<li>Experience comfort and control designed around real needs.</li>"
            "<li>Choose a product that combines function, convenience, and value.</li>"
            "</ul>"
            "<p>Make the switch today and experience the difference for yourself.</p>"
        ),
    }

    return fallback_map.get(angle, fallback_map["general"])


def detect_product_angle(title: str, product_type: str, tags: str, description: str) -> str:
    text_blob = " ".join([
        (title or "").lower(),
        (product_type or "").lower(),
        (tags or "").lower(),
        (description or "").lower(),
    ])

    angle_map = {
        "grooming": [
            "shaver", "shave", "razor", "clipper", "beard", "groom",
            "hair trimmer", "grooming", "barber"
        ],
        "beauty": [
            "beauty", "skincare", "skin", "face", "cosmetic", "serum",
            "makeup", "cleanser", "cream", "beauty tool"
        ],
        "home": [
            "home", "kitchen", "household", "organizer", "cleaning",
            "storage", "cook", "appliance", "room"
        ],
        "tech": [
            "tech", "electronic", "device", "smart", "charger", "wireless",
            "usb", "gadget", "bluetooth"
        ],
        "fashion": [
            "fashion", "wear", "shirt", "dress", "watch", "bag", "shoe",
            "jewelry", "accessory"
        ],
        "fitness": [
            "fitness", "gym", "workout", "exercise", "training", "sport",
            "sports", "recovery", "muscle"
        ],
        "pet": [
            "pet", "dog", "cat", "animal", "pet care", "pet grooming"
        ],
    }

    for angle, keywords in angle_map.items():
        if any(keyword in text_blob for keyword in keywords):
            return angle

    return "general"


def _is_valid_ai_description(description: str) -> bool:
    if not description or not isinstance(description, str):
        return False

    text = description.strip().lower()

    if "<ul>" not in text or "</ul>" not in text:
        return False

    if "<p>" not in text or "</p>" not in text:
        return False

    li_tags = re.findall(r"<li\b[^>]*>.*?</li>", description, re.DOTALL | re.IGNORECASE)
    if len(li_tags) < 5 or len(li_tags) > 7:
        return False

    return True


def get_store(shop: str):
    return ShopifyStore.query.filter_by(shop=shop).first()


def get_latest_store():
    return ShopifyStore.query.order_by(ShopifyStore.updated_at.desc()).first()


def save_shop_token(
    shop: str,
    access_token: str,
    scope: str | None = None,
    default_language: str = "en",
):
    store = get_store(shop)

    if store:
        store.access_token = access_token
        store.scope = scope
        if not store.default_language:
            store.default_language = default_language
        store.updated_at = datetime.utcnow()
    else:
        store = ShopifyStore(
            shop=shop,
            access_token=access_token,
            scope=scope,
            default_language=default_language,
        )
        db.session.add(store)

    db.session.commit()
    return store


def _convert_bullets_to_html(text: str) -> str:
    """Convert plain-text bullet lines (• or -) to <ul><li> HTML if no <ul> is present."""
    if "<ul>" in text.lower():
        return text

    lines = text.splitlines()
    bullet_pattern = re.compile(r"^\s*[-•*]\s+(\S[^\r\n]*)$")
    result = []
    ul_items = []

    def flush_ul():
        if ul_items:
            result.append("<ul>")
            for item in ul_items:
                # Bold the label before the first colon, if present
                if ":" in item:
                    label, _, rest = item.partition(":")
                    result.append(
                        f"<li><strong>{html.escape(label.strip())}:</strong>{html.escape(rest)}</li>"
                    )
                else:
                    result.append(f"<li>{html.escape(item.strip())}</li>")
            result.append("</ul>")
            ul_items.clear()

    for line in lines:
        m = bullet_pattern.match(line)
        if m:
            ul_items.append(m.group(1))
        else:
            flush_ul()
            if line.strip():
                result.append(line)

    flush_ul()
    return "\n".join(result)


def build_title_and_description_with_ai(product: dict, lang: str = "en") -> dict:
    if not client:
        raise RuntimeError("OpenAI is not configured")

    title = (product.get("title") or "").strip()
    description = (product.get("body_html") or "").strip()
    vendor = (product.get("vendor") or "").strip()
    product_type = (product.get("product_type") or "").strip()
    tags = (product.get("tags") or "").strip()

    language_map = {
        "ar": "Arabic",
        "en": "English",
        "fr": "French",
        "es": "Spanish",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "tr": "Turkish",
    }
    language_name = language_map.get(lang, "English")

    prompt = f"""
You are a senior ecommerce product strategist, technical product analyst, and conversion copywriter.
You write expert-level, highly specific, conversion-focused product content — NOT generic marketing text.

---
STEP 1 — IDENTIFY PRODUCT CATEGORY
Classify the product into exactly one of these categories:
- perfume / fragrance
- skincare / beauty
- grooming
- electronics
- fashion
- home product
- supplement
- general ecommerce product

---
STEP 2 — DEEP PRODUCT ANALYSIS (based on category)

For "perfume / fragrance":
- Identify the scent family (floral, oriental, woody, fresh, citrus, gourmand, etc.)
- Infer top notes, heart notes, and base notes when the input supports it
- Describe mood, occasion, season, and target audience
- Highlight luxury selling angles that drive conversion

For "skincare / beauty":
- Identify likely active ingredients when the input supports it
- Describe skin type fit, benefits, usage instructions, and concerns addressed
- Avoid unsafe medical claims — use phrases like "may help", "formulated to", "designed to"

For "grooming" or "electronics":
- Explain function, use case, target customer, pain points solved, and key differentiators

For "supplement":
- Describe the intended benefit, key ingredients or compounds (if supported), usage, and target user
- Avoid guaranteed health claims — use "formulated to support", "may aid", etc.

For "fashion":
- Describe style, material hints, fit, occasions, and target buyer persona

For "home product":
- Explain practical function, daily use case, convenience benefits, and who it is for

For any category:
- If ingredients, notes, or components are NOT in the input, infer carefully and prefix uncertain details with "Likely:"
- Never present inferred details as guaranteed facts

---
STEP 3 — OUTPUT
Return ONLY valid JSON. No markdown. No code fences. No extra text.

The JSON must have EXACTLY these fields:

{{
  "category": "detected category from the list above",
  "title": "optimized SEO title — must be compelling, benefit-driven, and different from the original",
  "short_summary": "2–3 sentence persuasive hook for the product",
  "technical_analysis": "expert-level analysis of what makes this product distinctive — ingredients, mechanism, design, or sensory profile",
  "target_audience": "specific description of who this product is for and why it fits their needs",
  "ingredients_or_notes": "ingredients, fragrance notes, or key components — infer carefully when not in the input and prefix uncertain items with Likely:",
  "key_benefits": ["benefit 1", "benefit 2", "benefit 3", "benefit 4", "benefit 5"],
  "selling_points": ["conversion angle 1", "conversion angle 2", "conversion angle 3"],
  "long_description": "<valid HTML — see structure below>",
  "meta_description": "under 155 characters, buyer-intent focused",
  "keywords": "comma-separated buyer-intent keywords"
}}

long_description HTML structure (STRICT):
<p>Opening hook paragraph that grabs attention and highlights the primary benefit or sensory appeal.</p>
<p>Second paragraph that addresses the buyer's pain point or desire and positions this product as the ideal solution.</p>
<ul>
<li><strong>Benefit 1:</strong> Specific, outcome-focused explanation.</li>
<li><strong>Benefit 2:</strong> Specific, outcome-focused explanation.</li>
<li><strong>Benefit 3:</strong> Specific, outcome-focused explanation.</li>
<li><strong>Benefit 4:</strong> Specific, outcome-focused explanation.</li>
<li><strong>Benefit 5:</strong> Specific, outcome-focused explanation.</li>
</ul>
<p>Closing persuasive call to action that creates urgency or desire.</p>

STRICT RULES for long_description:
- Use ONLY <p>, <ul>, <li>, <strong> tags
- MUST have exactly 5 <li> items
- Each <li> MUST follow the format <li><strong>Label:</strong> explanation</li>
- DO NOT use "•" or "-" or "*" or plain text bullets
- DO NOT escape HTML characters
- DO NOT break the HTML structure

GLOBAL RULES:
- DO NOT use vague words like "ultimate", "premium", "our product", "amazing"
- Use real, specific search keywords naturally throughout
- All text content must be written entirely in {language_name}
- key_benefits and selling_points must be JSON arrays
- meta_description must be under 155 characters
- DO NOT wrap output in markdown or code fences

---
PRODUCT DATA
Title: {title}
Brand: {vendor}
Category: {product_type}
Tags: {tags}
Description: {description}
"""

    fallback_description = build_fallback_description(
        product_title=title,
        brand=vendor,
        angle=detect_product_angle(title, product_type, tags, description),
    )

    new_title = title or "Optimized Product"
    new_long_description = ""
    new_meta_description = ""
    new_keywords = f"{title}, {vendor}, {product_type}" if product_type else f"{title}, {vendor}"
    new_category = ""
    new_short_summary = ""
    new_technical_analysis = ""
    new_target_audience = ""
    new_ingredients_or_notes = ""
    new_key_benefits = []
    new_selling_points = []
    source_used = "initial_fallback"

    for _ in range(MAX_AI_GENERATION_RETRIES):
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior ecommerce product strategist and conversion copywriter. "
                        "You return clean, structured JSON only — no markdown, no code fences, no extra text."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.7,
        )

        raw_text = response.choices[0].message.content if response.choices else ""
        if not raw_text:
            continue

        cleaned = raw_text.strip().replace("\u200b", "").replace("\ufeff", "")

        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]

        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        cleaned = cleaned.strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]

        try:
            ai_result = json.loads(cleaned)
        except Exception:
            continue

        candidate_title = str(ai_result.get("title") or title).strip() or title
        candidate_long_description = str(ai_result.get("long_description") or "").strip()
        candidate_meta = str(ai_result.get("meta_description") or "").strip()
        candidate_keywords = str(ai_result.get("keywords") or "").strip()
        candidate_category = str(ai_result.get("category") or "").strip()
        candidate_short_summary = str(ai_result.get("short_summary") or "").strip()
        candidate_technical_analysis = str(ai_result.get("technical_analysis") or "").strip()
        candidate_target_audience = str(ai_result.get("target_audience") or "").strip()
        candidate_ingredients_or_notes = str(ai_result.get("ingredients_or_notes") or "").strip()

        raw_benefits = ai_result.get("key_benefits") or []
        candidate_key_benefits = (
            list(raw_benefits) if isinstance(raw_benefits, list)
            else [str(raw_benefits)]
        )

        raw_selling = ai_result.get("selling_points") or []
        candidate_selling_points = (
            list(raw_selling) if isinstance(raw_selling, list)
            else [str(raw_selling)]
        )

        candidate_long_description = _convert_bullets_to_html(candidate_long_description)

        if not _is_valid_ai_description(candidate_long_description):
            continue

        new_title = candidate_title
        new_long_description = candidate_long_description
        if "<ul>" not in new_long_description:
            new_long_description = _convert_bullets_to_html(new_long_description)
        new_meta_description = candidate_meta
        new_keywords = candidate_keywords or new_keywords
        new_category = candidate_category
        new_short_summary = candidate_short_summary
        new_technical_analysis = candidate_technical_analysis
        new_target_audience = candidate_target_audience
        new_ingredients_or_notes = candidate_ingredients_or_notes
        new_key_benefits = candidate_key_benefits
        new_selling_points = candidate_selling_points
        source_used = "ai"
        break

    if not new_long_description or not _is_valid_ai_description(new_long_description):
        new_long_description = fallback_description
        new_title = title or "Optimized Product"
        new_meta_description = sanitize_plain_text(new_long_description)
        new_keywords = f"{title}, {vendor}, {product_type}" if product_type else f"{title}, {vendor}"
        source_used = "generated_fallback"

    if not new_meta_description:
        fallback_meta = sanitize_plain_text(new_long_description or fallback_description or new_title)
        if len(fallback_meta) > 155:
            fallback_meta = fallback_meta[:152].rstrip() + "..."
        new_meta_description = fallback_meta

    if len(new_meta_description) > 155:
        new_meta_description = new_meta_description[:152].rstrip() + "..."

    if not new_keywords:
        fallback_keywords_parts = [title, vendor, product_type]
        fallback_keywords_parts = [k.strip() for k in fallback_keywords_parts if k and k.strip()]
        new_keywords = ", ".join(fallback_keywords_parts[:6])

    if "<ul>" not in new_long_description:
        new_long_description = _convert_bullets_to_html(new_long_description)

    return {
        "category": new_category,
        "title": new_title,
        "short_summary": new_short_summary,
        "technical_analysis": new_technical_analysis,
        "target_audience": new_target_audience,
        "ingredients_or_notes": new_ingredients_or_notes,
        "key_benefits": new_key_benefits,
        "selling_points": new_selling_points,
        "long_description": new_long_description,
        "description": new_long_description,
        "meta_description": new_meta_description,
        "keywords": new_keywords,
        "source_used": source_used,
        "has_ul": "<ul>" in new_long_description.lower(),
        "li_count": new_long_description.lower().count("<li>"),
        "contains_bullet_symbol": "•" in new_long_description,
    }


def enforce_no_empty_fields(data: dict, idea: str = "") -> dict:
    """Fill any missing or empty values with concrete, category-aware defaults.

    Ensures zero empty strings, zero empty arrays, and zero forbidden/vague
    phrases in the final output.  All defaults are concrete data — never
    prefixed with 'Likely' or wrapped in hedging language.
    """
    idea_lower = idea.lower()
    category = (data.get("category") or "").lower()

    # --- Detect whether this is a fragrance product ---
    fragrance_keywords = ["perfume", "parfum", "fragrance", "cologne", "oud", "eau de"]
    is_fragrance = category == "fragrance" or any(k in idea_lower for k in fragrance_keywords)

    # --- Always-required string fields (universal) ---
    string_defaults = {
        "short_summary": f"Product analysis: {idea[:80]}",
        "technical_analysis": f"Structured product assessment for: {idea[:80]}",
        "target_audience": "Quality-conscious consumers in the 25-45 age range",
        "meta_description": idea[:150] if idea else "Product analysis and specifications",
        "keywords": idea[:100] if idea else "product, analysis, specifications",
        "category": category or ("fragrance" if is_fragrance else "general"),
    }

    for field, fallback in string_defaults.items():
        val = data.get(field)
        if not val or (isinstance(val, str) and not val.strip()):
            data[field] = fallback

    # --- Always-required list fields (universal) ---
    list_defaults = {
        "key_benefits": ["High build quality", "Functional design", "Competitive value"],
        "selling_points": ["Verified product specifications", "Clear use-case fit", "Strong category positioning"],
        "use_cases": ["Everyday use", "Gift option", "Personal upgrade"],
    }

    for field, fallback in list_defaults.items():
        val = data.get(field)
        if not val or (isinstance(val, list) and len(val) == 0):
            data[field] = fallback

    # --- Universal dict fields ---
    if not data.get("performance") or not isinstance(data.get("performance"), dict):
        data["performance"] = {}
    if not data.get("specifications") or not isinstance(data.get("specifications"), dict):
        data["specifications"] = {}
    if not data.get("category_specific") or not isinstance(data.get("category_specific"), dict):
        data["category_specific"] = {}

    # --- Category-specific defaults (fill category_specific sub-fields) ---
    cs = data.get("category_specific", {})

    if is_fragrance:
        has_oud = "oud" in idea_lower
        has_spicy = "spicy" in idea_lower or "spice" in idea_lower
        has_parfum = "parfum" in idea_lower
        luxury_brands = [
            "tom ford", "dior", "chanel", "creed", "maison francis kurkdjian",
            "byredo", "le labo", "amouage", "xerjoff", "roja", "clive christian",
            "initio", "parfums de marly", "nishane", "tiziana terenzi",
        ]
        is_luxury = any(b in idea_lower for b in luxury_brands)

        if has_oud:
            default_family = "Woody-oriental"
            default_top = ["Saffron", "Bergamot"]
            default_heart = ["Oud", "Rose"]
            default_base = ["Sandalwood", "Musk", "Amber"]
            default_projection = "Strong"
            default_longevity = "8-12 hours"
        elif has_spicy:
            default_family = "Warm spicy"
            default_top = ["Black pepper", "Cardamom"]
            default_heart = ["Cinnamon", "Nutmeg"]
            default_base = ["Vanilla", "Tonka bean", "Amber"]
            default_projection = "Moderate to strong"
            default_longevity = "6-10 hours"
        elif has_parfum:
            default_family = "Concentrated aromatic"
            default_top = ["Citrus accord", "Aromatic herbs"]
            default_heart = ["Floral-woody blend"]
            default_base = ["Musk", "Amber", "Woods"]
            default_projection = "Strong (parfum concentration)"
            default_longevity = "10+ hours (parfum concentration)"
        elif is_luxury:
            default_family = "Complex artisan blend"
            default_top = ["Refined citrus", "Spice opening"]
            default_heart = ["Rare florals", "Precious woods"]
            default_base = ["Ambergris", "Musk", "Precious woods"]
            default_projection = "Moderate to strong"
            default_longevity = "8+ hours"
        else:
            default_family = "Balanced aromatic"
            default_top = ["Fresh citrus", "Aromatic herbs"]
            default_heart = ["Floral accord", "Woody heart"]
            default_base = ["Musk", "Cedarwood"]
            default_projection = "Moderate"
            default_longevity = "4-6 hours"

        frag_defaults = {
            "scent_family": default_family,
            "projection": default_projection,
            "longevity": default_longevity,
            "best_season": "Spring, Fall",
            "best_occasions": ["Evening events", "Special occasions"],
        }
        for field, fallback in frag_defaults.items():
            val = cs.get(field) or data.get(field)
            if not val or (isinstance(val, str) and not val.strip()):
                cs[field] = fallback
            elif field not in cs:
                cs[field] = val

        notes = cs.get("fragrance_notes") or data.get("fragrance_notes")
        if not isinstance(notes, dict):
            notes = {"top": [], "heart": [], "base": []}
        if not notes.get("top"):
            notes["top"] = default_top
        if not notes.get("heart"):
            notes["heart"] = default_heart
        if not notes.get("base"):
            notes["base"] = default_base
        cs["fragrance_notes"] = notes

        data["category_specific"] = cs

        # Backward-compat: sync flat fields
        data["scent_family"] = cs.get("scent_family", "")
        data["fragrance_notes"] = cs.get("fragrance_notes", {"top": [], "heart": [], "base": []})
        data["projection"] = cs.get("projection", "")
        data["longevity"] = cs.get("longevity", "")
        data["best_season"] = cs.get("best_season", "")
        data["best_occasions"] = cs.get("best_occasions", [])

    elif category == "electronics":
        elec_defaults = {
            "battery": "Standard capacity for category",
            "connectivity": "Standard connectivity options",
            "compatibility": "Cross-platform compatible",
            "build_quality": "Standard build quality",
            "performance_level": "Mid-range",
        }
        for field, fallback in elec_defaults.items():
            val = cs.get(field)
            if not val or (isinstance(val, str) and not val.strip()):
                cs[field] = fallback
        data["category_specific"] = cs

    elif category == "fashion":
        fashion_defaults = {
            "style": "Contemporary",
            "material": "Standard fabric blend",
            "fit": "Regular fit",
            "occasion": ["Casual", "Everyday"],
            "season": "All seasons",
        }
        for field, fallback in fashion_defaults.items():
            val = cs.get(field)
            if not val or (isinstance(val, str) and not val.strip()) or (isinstance(val, list) and len(val) == 0):
                cs[field] = fallback
        data["category_specific"] = cs

    elif category == "beauty":
        beauty_defaults = {
            "skin_type": "All skin types",
            "key_ingredients": ["Active formula"],
            "texture": "Smooth application",
            "routine_fit": "Daily skincare routine",
        }
        for field, fallback in beauty_defaults.items():
            val = cs.get(field)
            if not val or (isinstance(val, str) and not val.strip()) or (isinstance(val, list) and len(val) == 0):
                cs[field] = fallback
        data["category_specific"] = cs

    elif category == "home":
        home_defaults = {
            "room_fit": "Living room, bedroom",
            "material": "Durable construction",
            "practicality": "Functional design",
            "maintenance": "Easy to maintain",
        }
        for field, fallback in home_defaults.items():
            val = cs.get(field)
            if not val or (isinstance(val, str) and not val.strip()):
                cs[field] = fallback
        data["category_specific"] = cs

    # --- Ensure long_description is non-empty ---
    if not data.get("long_description") or not data["long_description"].strip():
        data["long_description"] = f"<p>{idea}</p>"

    # --- Ensure title is non-empty ---
    if not data.get("title") or not data["title"].strip():
        data["title"] = idea

    # --- Final pass: strip forbidden/vague phrases from all values ---
    _final_banned_re = re.compile(
        r"\b(not specified|not provided|unavailable|cannot be determined|no data"
        r"|based on context|based on product context|inferred from product positioning"
        r"|inferred from product context"
        r"|addresses a market need|addresses a real need|addresses an unmet need"
        r"|feasible to build|technically feasible|can be built"
        r"|shows potential|has potential|strong potential)\b",
        re.IGNORECASE,
    )
    _likely_re = re.compile(r"\bLikely:?\s*", re.IGNORECASE)
    _marketing_re = re.compile(
        r"\b(luxurious|elegant|sophisticated|exquisite|opulent|sumptuous)\b",
        re.IGNORECASE,
    )

    def _final_scrub(value, field_name=""):
        """Strip vague/marketing filler — but preserve verdict fields that
        contain real analytical signals."""
        if isinstance(value, str):
            cleaned = value
            # Remove "Likely" / "Likely:" prefixes
            cleaned = _likely_re.sub("", cleaned)
            # Only apply aggressive regex to non-verdict fields
            if field_name not in _VERDICT_FIELDS:
                cleaned = _final_banned_re.sub("", cleaned)
                cleaned = _marketing_re.sub("", cleaned)
            # Collapse whitespace
            while "  " in cleaned:
                cleaned = cleaned.replace("  ", " ")
            cleaned = cleaned.strip(" .,;:-–—")
            return cleaned if cleaned else value
        if isinstance(value, list):
            result = []
            for v in value:
                scrubbed = _final_scrub(v, field_name)
                if scrubbed:
                    result.append(scrubbed)
            return result if result else ["General-purpose product benefit"]
        if isinstance(value, dict):
            return {k: _final_scrub(v, k) for k, v in value.items()}
        return value

    data = _final_scrub(data)

    return data


def analyze_product_with_ai(idea: str):
    # --- STEP 0: Pre-detect category from input keywords ---
    idea_lower = idea.lower()

    if any(k in idea_lower for k in ["perfume", "parfum", "fragrance", "cologne", "oud", "eau de"]):
        detected_category = "fragrance"
    elif any(k in idea_lower for k in ["phone", "laptop", "tablet", "headphone", "speaker", "camera", "tv", "monitor", "processor", "gpu", "charger", "keyboard", "mouse", "smartwatch", "earbuds"]):
        detected_category = "electronics"
    elif any(k in idea_lower for k in ["watch", "shirt", "dress", "jacket", "sneaker", "shoe", "handbag", "sunglasses", "clothing", "hoodie", "jeans", "pants", "skirt", "coat"]):
        detected_category = "fashion"
    elif any(k in idea_lower for k in ["skincare", "moisturizer", "serum", "cleanser", "makeup", "foundation", "lipstick", "mascara", "sunscreen", "cream", "lotion", "shampoo", "conditioner"]):
        detected_category = "beauty"
    elif any(k in idea_lower for k in ["lamp", "chair", "table", "sofa", "couch", "pillow", "blanket", "rug", "candle", "vase", "shelf", "curtain", "mattress", "desk", "organizer"]):
        detected_category = "home"
    else:
        detected_category = "general"

    # --- STEP 0b: Brand-to-category mapping override ---
    # If the (possibly corrected) input contains a known brand, use its
    # mapped category instead of the keyword-based detection above.
    brand_cat = get_brand_category(idea)
    if brand_cat:
        detected_category = brand_cat

    # --- Build category-specific prompt sections ---
    if detected_category == "fragrance":
        category_instructions = """
CATEGORY-SPECIFIC FIELDS (fragrance) — return inside "category_specific" object:
- scent_family: exact fragrance family (e.g. "woody-oriental", "fresh citrus", "floral-musk")
- fragrance_notes: { "top": [...], "heart": [...], "base": [...] } — each array must have 2-4 specific ingredient names
- projection: one of "weak", "moderate", "strong"
- longevity: concrete hour range (e.g. "6-8 hours")
- best_season: specific seasons (e.g. "Fall, Winter")
- best_occasions: array of 2-3 specific occasions

FRAGRANCE ANALYSIS RULES:
- Use actual perfumery terminology (top/heart/base notes, sillage, dry-down)
- Identify real ingredients, not vague descriptors
- Derive scent family from note composition
- Estimate longevity and projection from concentration type and base note weight
"""
    elif detected_category == "electronics":
        category_instructions = """
CATEGORY-SPECIFIC FIELDS (electronics) — return inside "category_specific" object:
- battery: battery life estimate with usage scenario (e.g. "8 hours mixed use")
- connectivity: connectivity options (e.g. "Bluetooth 5.3, Wi-Fi 6E, USB-C")
- compatibility: compatible systems/devices (e.g. "Windows, macOS, Android, iOS")
- build_quality: build quality assessment (e.g. "aluminum unibody, IP68 rated")
- performance_level: performance tier (e.g. "mid-range", "flagship", "entry-level")

ELECTRONICS ANALYSIS RULES:
- Use real spec numbers and units (GHz, GB, mAh, nits)
- Compare against category benchmarks where possible
- Identify target user segment based on specs and price positioning
"""
    elif detected_category == "fashion":
        category_instructions = """
CATEGORY-SPECIFIC FIELDS (fashion) — return inside "category_specific" object:
- style: specific style category (e.g. "minimalist streetwear", "business casual")
- material: primary materials/fabrics used (e.g. "100% organic cotton", "Italian leather")
- fit: fit description (e.g. "slim fit", "relaxed", "true to size")
- occasion: array of suitable occasions (e.g. ["casual", "office", "evening"])
- season: best seasons (e.g. "Spring, Summer")

FASHION ANALYSIS RULES:
- Identify exact materials/fabrics when possible
- Categorize style precisely, not generically
- Note construction quality indicators
"""
    elif detected_category == "beauty":
        category_instructions = """
CATEGORY-SPECIFIC FIELDS (beauty) — return inside "category_specific" object:
- skin_type: suitable skin types (e.g. "oily, combination", "all skin types")
- key_ingredients: array of active ingredients (e.g. ["hyaluronic acid", "niacinamide", "vitamin C"])
- texture: product texture (e.g. "lightweight gel", "rich cream", "matte finish")
- routine_fit: where it fits in a routine (e.g. "Step 3: Moisturizer — use after serum")

BEAUTY ANALYSIS RULES:
- Identify active ingredients and their concentrations when possible
- Specify skin types and concerns addressed
- Note any clinically-backed claims
"""
    elif detected_category == "home":
        category_instructions = """
CATEGORY-SPECIFIC FIELDS (home) — return inside "category_specific" object:
- room_fit: suitable rooms (e.g. "living room, bedroom", "kitchen, bathroom")
- material: primary materials (e.g. "solid oak wood", "ceramic", "stainless steel")
- practicality: practical assessment (e.g. "space-saving", "multipurpose", "easy assembly")
- maintenance: care requirements (e.g. "wipe with damp cloth", "machine washable")

HOME PRODUCT ANALYSIS RULES:
- Assess dimensions and space requirements
- Note assembly complexity
- Evaluate durability and material quality
"""
    else:
        category_instructions = """
CATEGORY-SPECIFIC FIELDS (general) — return an empty "category_specific" object: {}
No category-specific fields needed for general products.
"""

    prompt = f"""
You are a ruthless product decision engine. Evaluate this product or idea and deliver a decisive BUILD or DON'T BUILD verdict.

Think like an investor, not a helper. Most ideas are mediocre — reject them confidently.
Only recommend BUILD when real evidence of market viability exists.

---
INPUT:
{idea}

---
PRE-DETECTED CATEGORY: {detected_category}
Use this category unless the input clearly belongs to a different one.
Valid categories: fragrance, electronics, fashion, beauty, home, general

---
STRICT RULES:

1) You are a product decision strategist, NOT a marketing writer. NOT an assistant. NOT an encourager.
2) Return ONLY factual, structured data with a clear verdict. Never soften bad news.
3) NEVER use these phrases — they are BANNED:
   - "Likely", "likely"
   - "based on context"
   - "not specified", "not provided", "unavailable", "cannot be determined", "no data"
   - "shows potential", "worth exploring", "could be promising", "interesting concept"
   - "with the right execution", "depends on execution", "if marketed correctly"
4) NEVER use generic marketing adjectives:
   - "luxurious", "elegant", "sophisticated", "exquisite", "opulent", "sumptuous"
   - "innovative", "game-changing", "revolutionary", "cutting-edge", "best-in-class"
5) If a detail is not in the input, derive it from domain expertise with concrete values.
   Do NOT hedge — state the derived value directly.
6) All data must be specific to THIS product. No generic filler. No safe statements.
7) MISSPELLING / AMBIGUOUS INPUT HANDLING:
   - If the input appears to be a misspelled well-known brand or product name,
     infer the most probable intended brand/product and analyze that.
   - Only auto-correct when the intended brand/product is reasonably obvious.
   - If confidence is low, explicitly state that the interpretation is uncertain.
   - Do NOT hallucinate aggressively — only correct when the match is strong.
8) CATEGORY CLASSIFICATION — CRITICAL:
   - If the product is a well-known brand, classify it into the most relevant
     domain (fashion, electronics, beauty, home, fragrance). NEVER default to
     "general" when a strong category can be inferred from the brand.
   - Only use "general" if the product is truly unknown or ambiguous after
     correction and no specific category can reasonably be determined.
9) INVESTOR MINDSET — CRITICAL:
   - Evaluate competitive landscape: who already owns this space and why?
   - Assess unit economics: can this realistically generate margin?
   - Identify demand signals: is there proven demand or just an assumption?
   - Be brutally honest about weaknesses. A DON'T BUILD with clear reasoning is more valuable than a soft BUILD.
10) VERDICT-REASONING ALIGNMENT — CRITICAL:
   - If your reasoning is negative, your verdict MUST be DON'T BUILD. Never return BUILD with negative signals.
   - No hedging language. No mixed signals. The verdict must strictly align with the reasoning.
   - If top_reasons contain negative facts (no demand, saturated market, weak margins), the verdict MUST be DON'T BUILD.
   - A BUILD verdict requires ALL of: proven demand, viable margins, and a defensible market position.

11) CONTEXT-AWARE REASONING — CRITICAL:
   Your top_reasons and next_actions MUST be specific to the exact scenario described in the input.
   Generic advice is NOT allowed. Every reason and action must directly reference the specific
   product, brand, market, or constraint relevant to THIS idea — not boilerplate startup advice.

   REASONING-FIRST RULE:
   - First: perform deep analysis (market landscape, competition mapping, unit economics, demand signals)
   - Then: derive your reasoning from that analysis
   - Then: generate top_reasons FROM your reasoning
   DO NOT generate reasons before completing your analysis. Each reason must be a CONCLUSION from analysis, not an assumption.

   FACTOR-ANCHORING RULE — each top_reason MUST explicitly reference at least one of:
   - Demand level: state if demand is high, low, proven, or unproven — with evidence (search volume, market size, growth rate)
   - Competition intensity: state if the market is saturated, fragmented, or open — name competitors and their share
   - Differentiation: state if differentiation is clear, weak, or nonexistent — explain the moat (or lack of it)
   - Monetization viability: state if margins are strong, unclear, or weak — include unit economics or pricing data

12) SCENARIO DETECTION — CRITICAL:
   You MUST identify the type of idea and tailor your reasoning and actions accordingly:

   a) KNOWN BRAND (Nike, Dior, Apple, Louis Vuitton, Chanel, Gucci, etc.):
      → Your reasoning MUST address: licensing requirements, legal restrictions,
        trademark/IP ownership, brand-controlled distribution, authorized reseller
        barriers, and cease-and-desist risk. These are the PRIMARY constraints.
      → next_actions MUST include steps like "Contact [Brand] wholesale division
        for authorized reseller application" or "Consult an IP attorney about
        trademark licensing in your jurisdiction — budget $500-1,500".

   b) SATURATED MARKET (food delivery, social media, generic t-shirts, dropshipping, etc.):
      → Your reasoning MUST address: competition density with named incumbents
        and their market share, specific differentiation gaps (or lack thereof),
        customer acquisition costs in that vertical, and switching costs.
      → next_actions MUST include concrete differentiation steps with measurable
        targets, not "research competitors".

   c) SaaS / SOFTWARE IDEA:
      → Your reasoning MUST address: customer acquisition cost (CAC) estimates,
        expected churn rate for the vertical, retention benchmarks, distribution
        channel viability, and build-vs-buy alternatives already on the market.
      → next_actions MUST include steps like "Build an MVP landing page and run
        $200 in Google Ads targeting [specific keyword] to measure signup rate"
        or "Interview 15 [specific role] at [company size] to confirm willingness
        to pay $X/month".

   d) PHYSICAL PRODUCT:
      → Your reasoning MUST address: sourcing complexity, landed cost per unit,
        logistics and fulfillment costs, margin analysis at realistic retail
        price points, supply chain risks, and MOQ (minimum order quantity)
        requirements from manufacturers.
      → next_actions MUST include steps like "Request quotes from 3 manufacturers
        on Alibaba for MOQ of 500 units — target unit cost under $X" or "Calculate
        total landed cost including shipping, duties, and packaging".

   e) REGULATED INDUSTRY (health, finance, cannabis, alcohol, firearms, etc.):
      → Your reasoning MUST address: regulatory compliance requirements, licensing
        costs and timelines, legal barriers to entry, and liability exposure.

   If the idea spans multiple types, address ALL relevant constraints.

13) BANNED GENERIC OUTPUTS — CRITICAL:
   The following phrases are FORBIDDEN in top_reasons and next_actions:
   - "Validate demand" / "Validate the market" / "Validate the idea"
   - "Do more research" / "Research competitors" / "Research the market"
   - "Test the market" / "Test your idea" / "Test the concept"
   - "Build an MVP" (without specific scope, timeline, and budget)
   - "Talk to potential customers" (without specifying how many, which segment, and what to ask)
   - "Explore partnerships" (without naming specific partner types or companies)
   - "Addresses a market need" / "Addresses a real need" / "Addresses an unmet need"
   - "Feasible to build" / "Technically feasible" / "Can be built"
   - "Shows potential" / "Has potential" / "Strong potential"

   Every output MUST instead include:
   - Specific numbers (dollar amounts, percentages, unit counts, timeframes)
   - Concrete actions that can be executed immediately
   - Real constraints tied to THIS specific idea

   EXAMPLES OF REQUIRED TRANSFORMATION:
   ❌ "Validate demand" → ✅ "Survey 30+ sneaker collectors in the $150-300 price range and confirm at least 40% would purchase within 30 days"
   ❌ "Research competitors" → ✅ "Map the top 5 competitors (StockX, GOAT, Flight Club, Stadium Goods, eBay) — document their fees, seller experience, and gaps in authentication"
   ❌ "Test the market" → ✅ "Run a $100 Instagram ad campaign targeting 18-34 streetwear enthusiasts in 3 metro areas — measure click-through rate against 2% benchmark"
   ❌ "Explore partnerships" → ✅ "Contact 5 independent sneaker boutiques in your metro area and propose a consignment pilot — 30-day trial, 15% commission"

---
VERDICT (required):
- verdict: exactly "BUILD" or "DON'T BUILD" — your clear recommendation on whether to pursue, stock, or invest in this product. Default to DON'T BUILD unless there is compelling evidence otherwise.
- verdict_reasoning: 2-3 sentences explaining the core reason behind your verdict. Be brutally direct — reference specific market data, named competitors, demand signals, margin potential, or concrete product weaknesses. NEVER use phrases like "shows potential" or "worth exploring".
- confidence: integer 60-97 representing how confident you are in this verdict (based on data richness and market clarity)
- top_reasons: array of exactly 3 short, punchy sentences — the top 3 reasons driving this verdict. REASONING-FIRST RULE: You MUST first complete your deep analysis (market research, competition mapping, unit economics), THEN derive reasoning, THEN generate top_reasons FROM that reasoning. Do NOT generate reasons before thinking. Each reason MUST explicitly reference at least one of these four factors: (1) demand level — state whether demand is high, low, proven, or unproven with evidence; (2) competition intensity — state whether the market is saturated, fragmented, or open and name competitors; (3) differentiation — state whether differentiation is clear, weak, or nonexistent and explain why; (4) monetization viability — state whether margins are strong, unclear, or weak with numbers. Reference specific facts: market size, competitor names, pricing data, demand trends, legal barriers, licensing issues, or supply chain realities. For known brands, ALWAYS mention IP/licensing/trademark constraints. For saturated markets, ALWAYS name incumbent competitors and their market share. (e.g. "Demand is unproven — zero search volume for this niche and no existing customer base to validate against", "Market is saturated with 20+ similar tools — Notion, Asana, Monday.com control 68% of project management spend", "Differentiation is weak — feature set overlaps 90% with free-tier Trello and no unique moat exists", "Unit cost ~$8 with $25-35 retail price gives healthy 65%+ margins — monetization is strong"). These must read like an investor's bullet points, not marketing copy. NEVER output generic reasons like "addresses a market need", "feasible to build", "shows potential", "validate demand", or "research competitors".
- next_actions: array of exactly 3 concrete, tactical next steps the user should execute based on this verdict. Each action MUST be: (1) executable immediately without further research, (2) include specific numbers, dollar amounts, or measurable targets, (3) directly address the specific constraints identified in top_reasons. For known brands: include legal/licensing steps with cost estimates. For physical products: include sourcing steps with MOQ and unit cost targets. For SaaS: include CAC testing steps with ad budget amounts. (e.g. "Contact Dior's authorized wholesale division and apply for reseller status — expect $50K minimum buy-in and brand compliance audit", "Source 3 suppliers from Alibaba for MOQ of 500 units — target unit cost under $8 to maintain 60%+ margins at $22 retail", "Run a $150 Google Ads campaign targeting 'project management for agencies' — measure cost-per-signup against $25 CAC target"). FORBIDDEN: "validate demand", "do more research", "test the market", "explore partnerships" without specifics.

---
UNIVERSAL FIELDS (always required):
- title: product name
- category: "{detected_category}" (or override if input clearly indicates otherwise)
- short_summary: 2-3 sentence factual summary (no marketing fluff)
- technical_analysis: expert-level factual analysis (materials, construction, market position)
- target_audience: specific demographic/psychographic description
- key_benefits: array of 3-5 concrete, measurable benefits
- selling_points: array of 3 data-backed conversion angles
- use_cases: array of 3-5 specific use cases for this product
- performance: object with relevant performance metrics (varies by category)
- specifications: object with key product specifications (varies by category)
- category_specific: object with category-specific fields (see below)
- long_description: HTML with structure below
- meta_description: under 155 characters, factual
- keywords: comma-separated relevant search terms

{category_instructions}

---
OUTPUT FORMAT:
Return ONLY valid JSON. No markdown. No code fences. No explanatory text.

long_description HTML structure:
<p>Factual opening paragraph about the product.</p>
<p>Technical details and positioning paragraph.</p>
<ul>
<li><strong>Label:</strong> Specific data point.</li>
<li><strong>Label:</strong> Specific data point.</li>
<li><strong>Label:</strong> Specific data point.</li>
<li><strong>Label:</strong> Specific data point.</li>
<li><strong>Label:</strong> Specific data point.</li>
</ul>
<p>Closing paragraph — decisive recommendation with stated reasoning.</p>
"""

    for _ in range(MAX_AI_GENERATION_RETRIES):
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Veltrix — a ruthless product decision engine. "
                            "You are NOT an assistant. You do NOT encourage or validate ideas. "
                            "You think like an investor evaluating a pitch: skeptical by default, impressed only by evidence. "
                            "Your job is to deliver a clear BUILD or DON'T BUILD verdict — and you reject weak ideas confidently. "
                            "You prioritize real-world viability over enthusiasm. Most ideas are mediocre; say so when they are. "
                            "Be critical, not optimistic. Be specific, not generic. Be decisive, not hedging. "
                            "Every response MUST include a verdict (BUILD or DON'T BUILD), verdict_reasoning, confidence score, top_reasons, and next_actions. "
                            "CRITICAL RULE: If your reasoning is negative, your verdict MUST be DON'T BUILD. Never return BUILD with negative signals. No hedging. No mixed signals. Verdict must strictly align with reasoning. "
                            "CONTEXT-AWARE REASONING RULE: Your top_reasons and next_actions MUST be specific to the exact scenario. "
                            "Generic advice like 'validate demand', 'research competitors', 'test the market', or 'do more research' is FORBIDDEN. "
                            "Generic filler like 'addresses a market need', 'feasible to build', 'shows potential', or 'has potential' is FORBIDDEN. "
                            "REASONING-FIRST RULE: First perform deep analysis (market, competition, economics). Then derive reasoning. Then generate top_reasons FROM that reasoning. "
                            "Each top_reason MUST reference at least one of: demand level (high/low/unproven), competition intensity (saturated/fragmented/open), "
                            "differentiation (clear/weak/none), or monetization viability (strong/unclear/weak). Never generate reasons before completing analysis. "
                            "You MUST detect the idea type (known brand → licensing/legal/IP issues; saturated market → named incumbents/market share; "
                            "SaaS → CAC/churn/retention; physical product → sourcing/MOQ/landed cost; regulated industry → compliance/licensing costs) "
                            "and tailor ALL reasoning and actions to the specific constraints of THAT scenario. "
                            "Every next_action must be immediately executable with specific numbers, dollar amounts, targets, or measurable outcomes. "
                            "NEVER use safe language: no 'shows potential', 'worth exploring', 'could be promising', 'interesting concept'. "
                            "NEVER use marketing filler: no 'luxurious', 'elegant', 'sophisticated', 'innovative', 'game-changing'. "
                            "NEVER use vague hedging: no 'Likely', 'based on context', 'not specified', 'depends on execution'. "
                            "If the product is weak, say exactly why — name the competitors that crush it, the market gap that doesn't exist, or the unit economics that don't work. "
                            "If the product is strong, justify it with market size, demand signals, competitive moats, or margin potential — not adjectives. "
                            "If information is missing from the input, derive it using domain expertise and state it directly. "
                            "If the input looks like a misspelled well-known brand or product, infer the correct name and analyze it. "
                            "Only auto-correct when the match is reasonably obvious; if unsure, state the uncertainty. "
                            "IMPORTANT: If the product belongs to a well-known brand, always classify it into the correct domain "
                            "(fashion, electronics, beauty, home, fragrance). Never default to 'general' when the brand clearly belongs to a specific category. "
                            "For known brands, ALWAYS address licensing, trademark, and authorized distribution as primary constraints — "
                            "these are the REAL barriers, not generic market advice. "
                            "You return clean, valid JSON only — no markdown, no code fences, no extra text."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.4,
            )
        except (OpenAIError, ConnectionError, TimeoutError) as exc:
            app.logger.warning("analyze_product_with_ai: API call failed, retrying: %s", exc)
            continue

        content = response.choices[0].message.content
        if not content:
            continue

        cleaned = content.strip()

        # Remove code block markers if present
        cleaned = re.sub(r"^```json", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except Exception as e:
            app.logger.warning("JSON parse error: %s", e)
            app.logger.info("TOP_REASONS PIPELINE — BRANCH: JSON parse error fallback triggered (static fallback assigned)")
            app.logger.debug("Raw AI output: %s", content)

            # fallback structure — defaults to DON'T BUILD (ruthless by default)
            data = {
                "title": idea,
                "short_summary": cleaned[:200],
                "category": detected_category,
                "verdict": "DON'T BUILD",
                "verdict_reasoning": "Insufficient structured data to form a verdict. Without clear market positioning, competitive differentiation, or demand evidence, this does not meet the threshold for a BUILD recommendation.",
                "confidence": 62,
                "top_reasons": [
                    "No verifiable demand signals or market data available",
                    "Competitive landscape unclear — risk of entering a saturated space",
                    "Unit economics and margin potential cannot be assessed",
                ],
                "next_actions": [
                    "Define the exact target customer and validate demand with 30+ survey responses",
                    "Identify the top 3 direct competitors and document how this product is concretely different",
                    "Calculate landed cost per unit and target retail price to confirm 50%+ margins",
                ],
                "key_benefits": [],
                "selling_points": [],
                "target_audience": "",
                "technical_analysis": "",
                "long_description": cleaned,
                "meta_description": cleaned[:150],
                "keywords": idea,
            }

        if not isinstance(data, dict):
            continue

        # --- Process the parsed dict and build the structured output --------
        try:
            # --- Bullet handling: convert dash/bullet lines in
            # long_description to proper <ul><li> HTML. ---
            ld = data.get("long_description", "")
            if ld:
                def _bullets_to_html(text: str) -> str:
                    _bullet_re = re.compile(r"^[-•–]\s+")
                    lines = text.split("\n")
                    result: list[str] = []
                    in_list = False
                    for line in lines:
                        stripped = line.strip()
                        is_bullet = bool(
                            _bullet_re.match(stripped)
                        ) and "<li>" not in stripped
                        if is_bullet:
                            if not in_list:
                                result.append("<ul>")
                                in_list = True
                            content = _bullet_re.sub("", stripped)
                            result.append(f"<li>{content}</li>")
                        else:
                            if in_list:
                                result.append("</ul>")
                                in_list = False
                            result.append(line)
                    if in_list:
                        result.append("</ul>")
                    return "\n".join(result)

                data["long_description"] = _bullets_to_html(ld)

            # --- Strip banned/vague/marketing phrases from ALL values ------
            _banned_re = re.compile(
                r"\b(not specified|not provided|unavailable|cannot be determined|no data"
                r"|shows potential|worth exploring|could be promising|interesting concept"
                r"|has potential|strong potential"
                r"|addresses a market need|addresses a real need|addresses an unmet need"
                r"|feasible to build|technically feasible|can be built"
                r"|with the right execution|depends on execution|if marketed correctly)\b",
                re.IGNORECASE,
            )
            _likely_re = re.compile(r"\bLikely:?\s*", re.IGNORECASE)
            _marketing_re = re.compile(
                r"\b(luxurious|elegant|sophisticated|exquisite|opulent|sumptuous"
                r"|innovative|game-changing|revolutionary|cutting-edge|best-in-class)\b",
                re.IGNORECASE,
            )

            def _scrub(value, field_name=""):
                """Recursively clean banned phrases, 'Likely' prefixes, and marketing filler.

                Verdict fields (verdict_reasoning, top_reasons, next_actions) are
                only lightly cleaned — 'Likely' prefix removal only — to preserve
                AI-generated analytical reasoning.  Aggressive regex replacement is
                reserved for non-verdict fields (descriptions, summaries, etc.).
                """
                if isinstance(value, str):
                    cleaned = value
                    # Always remove "Likely" prefixes
                    cleaned = _likely_re.sub("", cleaned)
                    # Only apply aggressive banned/marketing regex to non-verdict fields
                    if field_name not in _VERDICT_FIELDS:
                        cleaned = _banned_re.sub("", cleaned)
                        cleaned = _marketing_re.sub("", cleaned)
                    while "  " in cleaned:
                        cleaned = cleaned.replace("  ", " ")
                    cleaned = cleaned.strip()
                    return cleaned if cleaned else value
                if isinstance(value, list):
                    return [_scrub(v, field_name) for v in value]
                if isinstance(value, dict):
                    return {k: _scrub(v, k) for k, v in value.items()}
                return value

            data = _scrub(data)

            # Flatten nested AI response fields that may have been returned
            # under alternate keys.
            insights = data.pop("extracted_insights", None) or {}
            frag = data.pop("fragrance_analysis", None) or {}

            # clean_summary → short_summary
            if "clean_summary" in data and "short_summary" not in data:
                data["short_summary"] = data.pop("clean_summary")

            # luxury_upgrade_text → luxury_description
            if "luxury_upgrade_text" in data and "luxury_description" not in data:
                data["luxury_description"] = data.pop("luxury_upgrade_text")

            # extracted_insights → flat fields
            data.setdefault("key_benefits", insights.get("benefits", []))
            data.setdefault("selling_points", insights.get("key_features", []))
            data.setdefault("target_audience", insights.get("positioning", ""))

            # fragrance_analysis → flat fields (only if present)
            if frag:
                data.setdefault("scent_family", frag.get("scent_family", ""))
                data.setdefault("fragrance_notes", {
                    "top": frag.get("top_notes", []),
                    "heart": frag.get("heart_notes", []),
                    "base": frag.get("base_notes", []),
                })
                data.setdefault("projection", frag.get("projection", ""))
                data.setdefault("longevity", frag.get("longevity", ""))

            # --- Normalize category early ---
            category = (data.get("category") or detected_category or "general").lower()
            if category not in SUPPORTED_CATEGORIES:
                category = "general"
            data["category"] = category

            # --- Build the unified output dict ---
            output = {
                "title": data.get("title", idea),
                "category": category,
                "verdict": data.get("verdict", "DON'T BUILD"),
                "verdict_reasoning": data.get("verdict_reasoning", ""),
                "confidence": min(max(int(data.get("confidence", 80)), 60), 97),
                "top_reasons": data.get("top_reasons", [])[:3],
                "next_actions": data.get("next_actions", [])[:3],
                "short_summary": data.get("short_summary", ""),
                "technical_analysis": data.get("technical_analysis", ""),
                "target_audience": data.get("target_audience", ""),
                "key_benefits": data.get("key_benefits", []),
                "selling_points": data.get("selling_points", []),
                "use_cases": data.get("use_cases", []),
                "performance": data.get("performance", {}),
                "specifications": data.get("specifications", data.get("specs", {})),
                "category_specific": {},
                "long_description": data.get("long_description", ""),
                "meta_description": data.get("meta_description", ""),
                "keywords": data.get("keywords", ""),
            }

            # Normalize verdict to exactly "BUILD" or "DON'T BUILD"
            raw_verdict = str(output.get("verdict", "DON'T BUILD")).strip().upper()
            output["verdict"] = "DON'T BUILD" if "DON" in raw_verdict else "BUILD"

            # ---- Stage A: Log raw incoming fields ----
            app.logger.info("TOP_REASONS DEBUG MARKER: %s", _CODE_VERSION)
            app.logger.info("TOP_REASONS PIPELINE [Stage A] — raw top_reasons: %s", output.get("top_reasons"))
            app.logger.info("TOP_REASONS PIPELINE [Stage A] — verdict_reasoning (first 200): %.200s", output.get("verdict_reasoning", ""))
            app.logger.debug("TOP_REASONS PIPELINE [Stage A] — technical_analysis (first 200): %.200s", output.get("technical_analysis", ""))
            app.logger.debug("TOP_REASONS PIPELINE [Stage A] — target_audience: %s", output.get("target_audience", ""))
            app.logger.debug("TOP_REASONS PIPELINE [Stage A] — long_description (first 200): %.200s", output.get("long_description", ""))
            app.logger.debug("TOP_REASONS PIPELINE [Stage A] — short_summary: %s", output.get("short_summary", ""))

            # Ensure verdict section always has content — fallback ONLY when
            # the field is truly empty or entirely generic filler.
            # Preserve AI-generated reasoning that contains real signal.
            vr = output.get("verdict_reasoning", "")
            if not vr or not vr.strip() or is_reason_generic(vr):
                output["verdict_reasoning"] = "Insufficient data to justify a BUILD. No clear competitive moat, demand validation, or margin evidence was found."

            # ---- Stage B: Generic classification ----
            str_reasons = [r for r in output.get("top_reasons", []) if isinstance(r, str) and r.strip()]
            generic_flags = []
            for r in str_reasons:
                r_stripped = r.strip()
                fallback_match = _KNOWN_FALLBACK_PATTERN.search(r_stripped)
                signal = has_real_signal(r_stripped)
                generic = is_reason_generic(r)
                generic_flags.append((r, generic))
                app.logger.debug(
                    "TOP_REASONS PIPELINE [Stage B] — reason: '%.100s' | fallback_match=%s | has_real_signal=%s | is_generic=%s",
                    r, bool(fallback_match), signal, generic,
                )
            all_generic = not str_reasons or all(g for _, g in generic_flags)
            app.logger.info("TOP_REASONS PIPELINE [Stage B] — all_generic: %s | reason_count: %d", all_generic, len(str_reasons))
            _reasons_from_derivation = False
            if all_generic:
                # Attempt to derive reasons from the actual analysis text
                # before falling back to generic placeholders.

                # ---- Stage C: Derivation input ----
                full_analysis_text = " ".join(filter(None, [
                    output.get("verdict_reasoning", ""),
                    output.get("technical_analysis", ""),
                    output.get("target_audience", ""),
                    output.get("long_description", ""),
                    output.get("short_summary", ""),
                ]))
                app.logger.debug("TOP_REASONS PIPELINE [Stage C] — full_analysis_text length: %d", len(full_analysis_text))
                app.logger.debug("TOP_REASONS PIPELINE [Stage C] — full_analysis_text (first 500 chars): %.500s", full_analysis_text)

                # ---- Stage D: Derivation result ----
                derived = derive_top_reasons_from_text(full_analysis_text)
                app.logger.info("TOP_REASONS PIPELINE [Stage D] — derivation returned %d reasons: %s", len(derived), derived)
                if derived and len(derived) >= 1:
                    output["top_reasons"] = derived
                    _reasons_from_derivation = True
                    app.logger.info("TOP_REASONS PIPELINE [Stage D] — BRANCH: assigned derived reasons")
                else:
                    # Only use fallback when derivation truly failed
                    output["top_reasons"] = [
                        "No verifiable demand signals or market data available",
                        "Competitive landscape unclear — risk of entering a saturated space",
                        "Unit economics and margin potential cannot be assessed",
                    ]
                    app.logger.info("TOP_REASONS PIPELINE [Stage D] — BRANCH: derivation empty → static fallback assigned")
                app.logger.info("TOP_REASONS PIPELINE — after first pass: %s", output["top_reasons"])
            str_actions = [a for a in output.get("next_actions", []) if isinstance(a, str) and a.strip()]
            if not str_actions or all(is_action_generic(a) for a in str_actions):
                output["next_actions"] = [
                    "Define the exact target customer and validate demand with 30+ survey responses",
                    "Identify the top 3 direct competitors and document how this product is concretely different",
                    "Calculate landed cost per unit and target retail price to confirm 50%+ margins",
                ]

            # --- Post-processing: enforce verdict consistency ---
            # If reasoning or top_reasons contain negative signals but verdict
            # is BUILD, override to DON'T BUILD.  This prevents contradictions
            # where negative analysis is paired with a positive verdict.
            if output["verdict"] == "BUILD":
                reasoning_text = output.get("verdict_reasoning", "")
                reasons_text = " ".join(output.get("top_reasons", []))
                combined_text = f"{reasoning_text} {reasons_text}"
                if _negative_signals_re.search(combined_text):
                    output["verdict"] = "DON'T BUILD"

            # --- Post-processing: selective validation of top_reasons
            # and next_actions using smart validators ---
            # Only replace items that are clearly generic filler.
            # Preserve any reason/action that contains real analytical signal.
            # For generic reasons, attempt to derive from analysis before falling back.
            # SKIP re-validation if reasons were already derived from analysis text.
            # ---- Stage E: Post-derivation overwrite ----
            app.logger.info("TOP_REASONS PIPELINE [Stage E] — _reasons_from_derivation: %s", _reasons_from_derivation)
            if _reasons_from_derivation:
                app.logger.info("TOP_REASONS PIPELINE [Stage E] — BRANCH: skipping second-pass (reasons from derivation)")
            else:
                _fallback_reasons = [
                    "No verifiable demand signals or market data available",
                    "Competitive landscape unclear — risk of entering a saturated space",
                    "Unit economics and margin potential cannot be assessed",
                ]

                # Build the analysis text pool once for derivation
                _analysis_pool = " ".join(filter(None, [
                    output.get("verdict_reasoning", ""),
                    output.get("technical_analysis", ""),
                    output.get("target_audience", ""),
                    output.get("long_description", ""),
                    output.get("short_summary", ""),
                ]))
                _derived_reasons_pool = derive_top_reasons_from_text(_analysis_pool) if _analysis_pool.strip() else []
                app.logger.info("TOP_REASONS PIPELINE [Stage E] — second-pass derived pool (%d): %s", len(_derived_reasons_pool), _derived_reasons_pool)

                # Validate each top_reason individually — keep strong, derive or replace weak
                raw_reasons = output.get("top_reasons", [])
                app.logger.info("TOP_REASONS PIPELINE [Stage E] — raw_reasons before validation: %s", raw_reasons)
                validated_reasons = []
                derived_idx = 0
                fallback_idx = 0
                for r in raw_reasons:
                    if isinstance(r, str) and not is_reason_generic(r):
                        validated_reasons.append(r)
                    else:
                        app.logger.info("TOP_REASONS PIPELINE [Stage E] — reason marked generic, replacing: '%.100s'", r)
                        # Try to use a derived reason from analysis first
                        if derived_idx < len(_derived_reasons_pool):
                            validated_reasons.append(_derived_reasons_pool[derived_idx])
                            derived_idx += 1
                        elif fallback_idx < len(_fallback_reasons):
                            validated_reasons.append(_fallback_reasons[fallback_idx])
                            fallback_idx += 1
                # Pad to 3 if some were dropped
                while len(validated_reasons) < 3:
                    if derived_idx < len(_derived_reasons_pool):
                        validated_reasons.append(_derived_reasons_pool[derived_idx])
                        derived_idx += 1
                    elif fallback_idx < len(_fallback_reasons):
                        validated_reasons.append(_fallback_reasons[fallback_idx])
                        fallback_idx += 1
                    else:
                        break
                output["top_reasons"] = validated_reasons[:3]
            app.logger.info("TOP_REASONS PIPELINE [FINAL] — output[top_reasons]: %s", output["top_reasons"])

            # Validate each next_action individually — keep strong, replace weak
            _fallback_actions = [
                "Define the exact target customer and validate demand with 30+ survey responses",
                "Identify the top 3 direct competitors and document how this product is concretely different",
                "Calculate landed cost per unit and target retail price to confirm 50%+ margins",
            ]
            raw_actions = output.get("next_actions", [])
            validated_actions = []
            fallback_idx = 0
            for a in raw_actions:
                if isinstance(a, str) and not is_action_generic(a):
                    validated_actions.append(a)
                else:
                    if fallback_idx < len(_fallback_actions):
                        validated_actions.append(_fallback_actions[fallback_idx])
                        fallback_idx += 1
            while len(validated_actions) < 3 and fallback_idx < len(_fallback_actions):
                validated_actions.append(_fallback_actions[fallback_idx])
                fallback_idx += 1
            output["next_actions"] = validated_actions[:3]

            # --- Post-processing: enforce verdict consistency AFTER validation ---
            # Re-check verdict alignment now that reasons are finalized.
            if output["verdict"] == "BUILD":
                final_reasoning = output.get("verdict_reasoning", "")
                final_reasons = " ".join(output.get("top_reasons", []))
                if _negative_signals_re.search(f"{final_reasoning} {final_reasons}"):
                    output["verdict"] = "DON'T BUILD"

            # Ensure performance and specifications are dicts
            if isinstance(output["performance"], str):
                output["performance"] = {"summary": output["performance"]}
            if not isinstance(output["performance"], dict):
                output["performance"] = {}
            if not isinstance(output["specifications"], dict):
                output["specifications"] = {}

            # Build category_specific from AI response
            cs = data.get("category_specific", {})
            if not isinstance(cs, dict):
                cs = {}

            if category == "fragrance":
                output["category_specific"] = {
                    "scent_family": cs.get("scent_family") or data.get("scent_family", ""),
                    "fragrance_notes": cs.get("fragrance_notes") or data.get("fragrance_notes", {"top": [], "heart": [], "base": []}),
                    "projection": cs.get("projection") or data.get("projection", ""),
                    "longevity": cs.get("longevity") or data.get("longevity", ""),
                    "best_season": cs.get("best_season") or data.get("best_season", ""),
                    "best_occasions": cs.get("best_occasions") or data.get("best_occasions", []),
                }
                # Backward-compat: also set flat fields
                output["scent_family"] = output["category_specific"]["scent_family"]
                output["fragrance_notes"] = output["category_specific"]["fragrance_notes"]
                output["projection"] = output["category_specific"]["projection"]
                output["longevity"] = output["category_specific"]["longevity"]
                output["best_season"] = output["category_specific"]["best_season"]
                output["best_occasions"] = output["category_specific"]["best_occasions"]
            elif category == "electronics":
                output["category_specific"] = {
                    "battery": cs.get("battery") or data.get("battery", ""),
                    "connectivity": cs.get("connectivity") or data.get("connectivity", ""),
                    "compatibility": cs.get("compatibility") or data.get("compatibility", ""),
                    "build_quality": cs.get("build_quality") or data.get("build_quality", ""),
                    "performance_level": cs.get("performance_level") or data.get("performance_level", ""),
                }
            elif category == "fashion":
                output["category_specific"] = {
                    "style": cs.get("style") or data.get("style", ""),
                    "material": cs.get("material") or data.get("material") or data.get("materials", ""),
                    "fit": cs.get("fit") or data.get("fit", ""),
                    "occasion": cs.get("occasion") or data.get("occasion") or data.get("occasions", []),
                    "season": cs.get("season") or data.get("season", ""),
                }
                # Normalize material: if it's a list, join it
                mat = output["category_specific"]["material"]
                if isinstance(mat, list):
                    output["category_specific"]["material"] = ", ".join(mat)
                # Normalize occasion: ensure it's an array
                occ = output["category_specific"]["occasion"]
                if isinstance(occ, str):
                    output["category_specific"]["occasion"] = [occ] if occ else []
            elif category == "beauty":
                output["category_specific"] = {
                    "skin_type": cs.get("skin_type") or data.get("skin_type", ""),
                    "key_ingredients": cs.get("key_ingredients") or data.get("key_ingredients", []),
                    "texture": cs.get("texture") or data.get("texture", ""),
                    "routine_fit": cs.get("routine_fit") or data.get("routine_fit", ""),
                }
            elif category == "home":
                output["category_specific"] = {
                    "room_fit": cs.get("room_fit") or data.get("room_fit", ""),
                    "material": cs.get("material") or data.get("material", ""),
                    "practicality": cs.get("practicality") or data.get("practicality", ""),
                    "maintenance": cs.get("maintenance") or data.get("maintenance", ""),
                }
                # Normalize material: if it's a list, join it
                mat = output["category_specific"]["material"]
                if isinstance(mat, list):
                    output["category_specific"]["material"] = ", ".join(mat)

            return enforce_no_empty_fields(output, idea)
        except Exception as exc:
            app.logger.warning("analyze_product_with_ai: post-processing error: %s", exc)
            continue

    app.logger.warning("TOP_REASONS PIPELINE — BRANCH: all %d retries exhausted → function-level static fallback", MAX_AI_GENERATION_RETRIES)
    fallback = {
        "title": idea,
        "category": detected_category if detected_category in SUPPORTED_CATEGORIES else "general",
        "verdict": "DON'T BUILD",
        "verdict_reasoning": "Insufficient data to justify a BUILD. No clear competitive moat, demand validation, or margin evidence was found.",
        "confidence": 62,
        "top_reasons": [
            "No verifiable demand signals or market data available",
            "Competitive landscape unclear — risk of entering a saturated space",
            "Unit economics and margin potential cannot be assessed",
        ],
        "next_actions": [
            "Define the exact target customer and validate demand with 30+ survey responses",
            "Identify the top 3 direct competitors and document how this product is concretely different",
            "Calculate landed cost per unit and target retail price to confirm 50%+ margins",
        ],
        "short_summary": "",
        "technical_analysis": "",
        "target_audience": "",
        "key_benefits": [],
        "selling_points": [],
        "use_cases": [],
        "performance": {},
        "specifications": {},
        "category_specific": {},
        "long_description": f"<p>{idea}</p>",
        "meta_description": "",
        "keywords": idea,
    }
    try:
        return enforce_no_empty_fields(fallback, idea)
    except Exception as e:
        app.logger.warning("analyze_product_with_ai: fallback enforce_no_empty_fields error: %s", e)
        return fallback


def looks_like_fragrance(product):
    text = " ".join([
        str(product.get("title", "")).lower(),
        str(product.get("product_type", "")).lower(),
        str(product.get("tags", "")).lower(),
        str(product.get("body_html", "")).lower(),
    ])

    keywords = [
        "perfume", "parfum", "fragrance", "cologne",
        "eau de parfum", "eau de toilette",
        "oud", "tom ford", "dior", "chanel",
        "\u0639\u0637\u0631", "\u0628\u0627\u0631\u0641\u0627\u0646"
    ]

    return any(k in text for k in keywords)


def looks_like_fragrance_product(product: dict) -> bool:
    text = " ".join([
        (product.get("title") or "").lower(),
        (product.get("product_type") or "").lower(),
        (product.get("tags") or "").lower(),
        (product.get("body_html") or "").lower(),
    ])

    keywords = [
        "perfume", "parfum", "fragrance", "cologne",
        "oud", "eau de parfum", "eau de toilette",
        "tom ford", "dior", "chanel",
        "\u0639\u0637\u0631", "\u0628\u0627\u0631\u0641\u0627\u0646",
    ]

    matched = [k for k in keywords if k in text]
    is_frag = len(matched) > 0
    return is_frag


def optimize_product_router(product, lang="en"):
    """Route any product through the Veltrix product decision engine.

    Builds a rich input string from the product's fields and sends it through
    analyze_product_with_ai() which auto-detects the category and returns
    a verdict (BUILD / DON'T BUILD) with category-specific structured data.
    """
    title = product.get("title", "")
    brand = product.get("vendor", "")
    product_type = product.get("product_type", "")
    tags = product.get("tags", "")
    body_html = product.get("body_html", "")

    idea = (
        f"[PRODUCT TO ANALYZE]\n"
        f"This is a real product currently listed for sale. "
        f"Analyze it as a specific, existing product — do NOT generate generic content.\n"
        f"\n"
        f"Full Product Title: {title}\n"
        f"Brand / Vendor: {brand}\n"
        f"Product Type: {product_type}\n"
        f"Tags: {tags}\n"
        f"Product Description / Body HTML:\n{body_html}"
    ).strip()

    # Preprocess: normalize and correct misspellings in the idea string
    idea, _ = preprocess_product_input(idea)

    result = analyze_product_with_ai(idea)
    app.logger.info("Product router result: category=%s title=%s", result.get("category"), result.get("title"))

    result.setdefault("title", product.get("title", ""))
    result.setdefault("category", "general")
    result.setdefault("short_summary", "")
    result.setdefault("technical_analysis", "")
    result.setdefault("target_audience", "")
    result.setdefault("key_benefits", [])
    result.setdefault("selling_points", [])
    result.setdefault("long_description", "")
    result.setdefault("meta_description", "")
    result.setdefault("keywords", "")

    # Backward compatibility: set is_fragrance flag
    result["is_fragrance"] = (result.get("category", "").lower() == "fragrance")

    return result


@app.route("/")
def home():
    return send_file("index.html")


@app.route("/script.js")
def serve_script():
    return send_file("script.js")


@app.route("/upsell.js")
def serve_upsell():
    return send_file("upsell.js")


@app.route("/style.css")
def serve_style():
    return send_file("style.css")


@app.route("/dashboard")
def dashboard():
    return send_file("dashboard.html")


@app.route("/success")
def payment_success():
    return send_file("success.html")


@app.route("/cancel")
def payment_cancel():
    return send_file("cancel.html")


@app.route("/admin")
def admin_page():
    """Serve admin dashboard only if a valid admin session cookie exists."""
    if not session.get("admin_authenticated"):
        return render_template_string(ADMIN_LOGIN_HTML, error=False)
    return send_file("admin.html")


@app.route("/api/admin/login", methods=["POST"])
@limiter.limit("5 per minute")
def admin_login():
    """Verify the admin secret and set a secure session cookie."""
    data = request.get_json(silent=True) or {}
    provided = (data.get("secret") or "").strip()
    if not ADMIN_SECRET or not provided or not secrets.compare_digest(provided, ADMIN_SECRET):
        return render_template_string(ADMIN_LOGIN_HTML, error=True), 403
    session.permanent = True
    session["admin_authenticated"] = True
    _generate_csrf_token()
    return redirect("/admin")


@app.route("/api/admin/csrf-token", methods=["GET"])
def admin_csrf_token():
    """Return the current CSRF token for session-authenticated admins."""
    if not session.get("admin_authenticated"):
        return jsonify({"error": "Unauthorized"}), 403
    token = session.get("csrf_token") or _generate_csrf_token()
    return jsonify({"csrf_token": token})


@app.route("/api/admin/logout", methods=["POST"])
@csrf_protected
def admin_logout():
    """Clear the admin session and redirect to the login page."""
    session.pop("admin_authenticated", None)
    session.pop("csrf_token", None)
    return redirect("/admin")


# Minimal login page served when admin session is absent / invalid.
ADMIN_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Admin Login — Veltrix AI</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#0f172a;margin:0;display:flex;
align-items:center;justify-content:center;min-height:100vh;color:#e2e8f0}
.box{background:#1e293b;border-radius:16px;padding:40px;width:100%;max-width:400px;
text-align:center;border:1px solid #334155}
h1{font-size:22px;font-weight:800;margin:0 0 8px}
h1 span{color:#818cf8}
p{font-size:13px;color:#94a3b8;margin:0 0 24px}
input{width:100%;padding:12px 16px;border-radius:10px;border:1px solid #475569;
background:#0f172a;color:#e2e8f0;font-size:14px;font-family:inherit;margin-bottom:16px;outline:none}
input:focus{border-color:#818cf8}
button{width:100%;padding:12px;border-radius:10px;border:none;background:#818cf8;
color:#fff;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit}
button:hover{background:#6366f1}
.err{color:#f87171;font-size:13px;margin-top:12px;display:none}
</style>
</head>
<body>
<div class="box">
<h1>Veltrix<span>AI</span></h1>
<p>Admin Dashboard &mdash; Enter your admin secret to continue</p>
<form id="adminLoginForm" autocomplete="off">
<input type="password" id="secretField" placeholder="Admin Secret" required autofocus/>
<button type="submit">Authenticate</button>
</form>
{% if error %}<div class="err" style="display:block">Invalid admin secret. Access denied.</div>{% endif %}
</div>
<script>
document.getElementById("adminLoginForm").addEventListener("submit", function(e) {
    e.preventDefault();
    var secret = document.getElementById("secretField").value;
    fetch("/api/admin/login", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "same-origin",
        body: JSON.stringify({secret: secret})
    }).then(function(resp) {
        if (resp.ok || resp.redirected) {
            window.location.href = "/admin";
            return;
        }
        document.querySelector(".err").style.display = "block";
    }).catch(function() {
        document.querySelector(".err").style.display = "block";
    });
});
</script>
</body>
</html>"""


# ── Auth & SaaS Endpoints ──

@app.route("/api/register", methods=["POST"])
def api_register():
    try:
        data = request.get_json() or {}
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()

        if not username or not password:
            return jsonify({"error": "Missing username or password"}), 400

        existing = User.query.filter_by(username=username).first()
        if existing:
            return jsonify({"error": "Username already taken"}), 409

        token = secrets.token_hex(32)
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            token=token,
            is_pro=False,
        )

        db.session.add(user)
        db.session.commit()

        return jsonify({"token": token, "username": user.username}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid username or password"}), 401

    token = secrets.token_hex(32)
    user.token = token
    db.session.commit()

    return jsonify({"token": token, "username": user.username})


@app.route("/api/me", methods=["GET"])
@login_required
def api_me(user):
    analysis_count = SavedAnalysis.query.filter_by(user_id=user.id).count()
    limit = "unlimited" if user.is_pro else FREE_ANALYSIS_LIMIT

    # Derive a clean plan label for the frontend
    sub_status = user.subscription_status or ""
    if user.is_pro:
        plan = "pro"
    elif sub_status.upper() in ("CANCELLED", "SUSPENDED", "EXPIRED"):
        plan = "free"
    else:
        plan = "free"

    return jsonify({
        "username": user.username,
        "analysis_count": analysis_count,
        "analysis_limit": limit,
        "is_pro": user.is_pro,
        "plan": plan,
        "subscription_status": sub_status or None,
        "paypal_subscription_id": user.paypal_subscription_id or None,
    })


@app.route("/api/paypal/create-order", methods=["POST"])
@login_required
def paypal_create_order(user):
    try:
        access_token = get_paypal_access_token()
    except Exception as exc:
        app.logger.error("PayPal auth failed: %s", exc)
        return jsonify({"error": "PayPal authentication failed"}), 502

    order_payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "amount": {
                    "currency_code": "USD",
                    "value": "10.00",
                },
            }
        ],
    }

    resp = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders",
        json=order_payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        app.logger.error("PayPal create-order failed: %s %s", resp.status_code, resp.text)
        return jsonify({"error": "Failed to create PayPal order"}), 502

    order_data = resp.json()
    return jsonify({"id": order_data["id"]})


@app.route("/api/paypal/capture-order", methods=["POST"])
@login_required
def paypal_capture_order(user):
    body = request.get_json(force=True, silent=True) or {}
    order_id = (body.get("orderID") or "").strip()
    if not order_id:
        return jsonify({"error": "orderID is required"}), 400

    # Idempotency: if this order was already processed, return success
    if user.is_pro and user.paypal_order_id == order_id:
        return jsonify({"message": "Payment already processed.", "is_pro": True})

    try:
        access_token = get_paypal_access_token()
    except Exception as exc:
        app.logger.error("PayPal auth failed: %s", exc)
        return jsonify({"error": "PayPal authentication failed"}), 502

    resp = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        app.logger.error("PayPal capture failed: %s %s", resp.status_code, resp.text)
        return jsonify({"error": "Failed to capture PayPal order"}), 502

    capture_data = resp.json()
    if capture_data.get("status") != "COMPLETED":
        return jsonify({"error": "Payment was not completed"}), 400

    user.is_pro = True
    user.paypal_order_id = order_id
    db.session.commit()

    return jsonify({"message": "Payment successful. Pro activated!", "is_pro": True})


@app.route("/api/config", methods=["GET"])
def api_config():
    """Return safe public configuration. Never expose secrets."""
    return jsonify({
        "paypal_client_id": PAYPAL_CLIENT_ID,
        "paypal_plan_id": PAYPAL_PLAN_ID,
    })


@app.route("/api/debug/version", methods=["GET"])
def debug_version():
    """Return code version marker to verify deployed code is up to date."""
    return jsonify({
        "code_version": _CODE_VERSION,
        "log_level": app.logger.getEffectiveLevel(),
        "model": OPENAI_MODEL,
    })


@app.route("/api/admin/reset-db", methods=["POST"])
@admin_required
@csrf_protected
def admin_reset_db():
    """One-time admin helper: drop and recreate all database tables.

    Requires ``Authorization: Bearer <ADMIN_SECRET>`` header.
    WARNING: This is destructive and deletes all data. Use only for
    development/testing recovery when the schema is out of sync.
    """
    try:
        db.drop_all()
        db.create_all()
        return jsonify({"success": True, "message": "Database tables reset successfully"}), 200
    except Exception as e:
        app.logger.error("Database reset failed: %s", e)
        return jsonify({"error": "Database reset failed"}), 500


@app.route("/api/admin/migrate-db", methods=["POST"])
@admin_required
@csrf_protected
def admin_migrate_db():
    """One-time admin helper: add any missing columns to existing tables.

    Requires ``Authorization: Bearer <ADMIN_SECRET>`` header.
    Safe to run multiple times — skips columns that already exist.
    Uses ALTER TABLE ADD COLUMN for each missing column.
    """
    from sqlalchemy import inspect as sa_inspect, text as sa_text

    added = []
    skipped = []
    try:
        inspector = sa_inspect(db.engine)
        for model in (User, ShopifyStore, SavedAnalysis):
            table = model.__tablename__
            existing = {c["name"] for c in inspector.get_columns(table)}
            for col in model.__table__.columns:
                if col.name not in existing:
                    col_type = col.type.compile(db.engine.dialect)
                    stmt = f'ALTER TABLE "{table}" ADD COLUMN "{col.name}" {col_type}'
                    try:
                        db.session.execute(sa_text(stmt))
                        db.session.commit()
                        added.append(f"{table}.{col.name}")
                    except Exception as col_exc:
                        db.session.rollback()
                        skipped.append({"column": f"{table}.{col.name}"})
    except Exception as e:
        app.logger.error("Migration failed: %s", e)
        return jsonify({"error": "Migration failed"}), 500

    return jsonify({
        "success": True,
        "added": added,
        "skipped": skipped,
        "message": f"Migration complete. {len(added)} column(s) added.",
    })


# ── Admin Dashboard API Endpoints ──

@app.route("/api/admin/overview", methods=["GET"])
@admin_required
def admin_overview():
    """Return high-level dashboard statistics and recent activity."""
    try:
        total_users = User.query.count()
        total_pro = User.query.filter_by(is_pro=True).count()
        total_analyses = SavedAnalysis.query.count()

        recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
        recent_analyses = (
            SavedAnalysis.query
            .order_by(SavedAnalysis.created_at.desc())
            .limit(10)
            .all()
        )

        # Recent PayPal subscriptions (users with a paypal_subscription_id)
        recent_subscriptions = (
            User.query
            .filter(User.paypal_subscription_id.isnot(None))
            .order_by(User.created_at.desc())
            .limit(10)
            .all()
        )

        latest_store = get_latest_store()

        return jsonify({
            "stats": {
                "total_users": total_users,
                "total_pro_users": total_pro,
                "total_analyses": total_analyses,
            },
            "recent_users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "is_pro": u.is_pro,
                    "subscription_status": u.subscription_status,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in recent_users
            ],
            "recent_analyses": [
                {
                    "id": a.id,
                    "user_id": a.user_id,
                    "idea": (a.idea[:120] + "...") if len(a.idea) > 120 else a.idea,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in recent_analyses
            ],
            "recent_subscriptions": [
                {
                    "id": u.id,
                    "username": u.username,
                    "paypal_subscription_id": u.paypal_subscription_id,
                    "subscription_status": u.subscription_status,
                    "is_pro": u.is_pro,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in recent_subscriptions
            ],
            "system_health": {
                "database": "connected",
                "openai_ready": bool(OPENAI_API_KEY),
                "shopify_configured": bool(SHOPIFY_API_KEY and SHOPIFY_API_SECRET),
                "shopify_store": latest_store.shop if latest_store else None,
                "paypal_configured": bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET),
            },
        })
    except Exception as e:
        app.logger.error("Admin overview failed: %s", e)
        return jsonify({"error": "Failed to load overview"}), 500


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def admin_users():
    """Return paginated list of all users."""
    try:
        page = max(request.args.get("page", 1, type=int), 1)
        per_page = max(min(request.args.get("per_page", 50, type=int), 100), 1)
        pagination = (
            User.query
            .order_by(User.created_at.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        return jsonify({
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "is_pro": u.is_pro,
                    "paypal_subscription_id": u.paypal_subscription_id,
                    "subscription_status": u.subscription_status,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in pagination.items
            ],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
        })
    except Exception as e:
        app.logger.error("Admin users failed: %s", e)
        return jsonify({"error": "Failed to load users"}), 500


@app.route("/api/admin/analyses", methods=["GET"])
@admin_required
def admin_analyses():
    """Return paginated list of all saved analyses."""
    try:
        page = max(request.args.get("page", 1, type=int), 1)
        per_page = max(min(request.args.get("per_page", 50, type=int), 100), 1)
        pagination = (
            SavedAnalysis.query
            .order_by(SavedAnalysis.created_at.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        return jsonify({
            "analyses": [
                {
                    "id": a.id,
                    "user_id": a.user_id,
                    "idea": (a.idea[:200] + "...") if len(a.idea) > 200 else a.idea,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in pagination.items
            ],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
        })
    except Exception as e:
        app.logger.error("Admin analyses failed: %s", e)
        return jsonify({"error": "Failed to load analyses"}), 500


# ── Shared funnel analytics helpers ──
_FUNNEL_EVENTS = [
    "pricing_view",
    "upgrade_click",
    "paypal_button_rendered",
    "paypal_subscription_approved",
    "payment_success_page_view",
    "payment_cancel_page_view",
]


def _funnel_rate(numerator, denominator):
    """Return percentage rate rounded to 2 decimals, or 0.0 if denominator is zero."""
    if denominator == 0:
        return 0.0
    return round(numerator / denominator * 100, 2)


def _parse_funnel_date_filter():
    """Build a SQLAlchemy filter clause from request query params (range, start_date, end_date).

    Returns None when no time constraint should be applied ("all" range).
    Raises a (message, status_code) tuple on invalid input.
    """
    start_date_param = request.args.get("start_date")
    end_date_param = request.args.get("end_date")
    range_param = request.args.get("range", "all")

    now = datetime.utcnow()

    if start_date_param and end_date_param:
        try:
            start_dt = datetime.fromisoformat(start_date_param.replace("Z", "+00:00")).replace(tzinfo=None)
            end_dt = datetime.fromisoformat(end_date_param.replace("Z", "+00:00")).replace(tzinfo=None)
            return TrackingEvent.created_at.between(start_dt, end_dt)
        except (ValueError, TypeError):
            raise ValueError("Invalid start_date or end_date format")
    elif range_param == "today":
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return TrackingEvent.created_at >= midnight
    elif range_param == "7d":
        return TrackingEvent.created_at >= (now - timedelta(days=7))
    elif range_param == "30d":
        return TrackingEvent.created_at >= (now - timedelta(days=30))
    # "all" or unrecognised → no filter
    return None


@app.route("/api/admin/analytics/funnel", methods=["GET"])
@admin_required
def admin_analytics_funnel():
    """Return conversion funnel counts, derived rates, and recent tracking events."""
    try:
        try:
            date_filter = _parse_funnel_date_filter()
        except ValueError:
            return jsonify({"error": "Invalid start_date or end_date format"}), 400

        counts = {}
        for evt in _FUNNEL_EVENTS:
            q = TrackingEvent.query.filter_by(event_name=evt)
            if date_filter is not None:
                q = q.filter(date_filter)
            counts[evt] = q.count()

        pricing = counts["pricing_view"] or 0
        clicks = counts["upgrade_click"] or 0
        approvals = counts["paypal_subscription_approved"] or 0
        successes = counts["payment_success_page_view"] or 0
        cancels = counts["payment_cancel_page_view"] or 0

        derived = {
            "pricing_to_click_rate": _funnel_rate(clicks, pricing),
            "click_to_approval_rate": _funnel_rate(approvals, clicks),
            "pricing_to_success_rate": _funnel_rate(successes, pricing),
            "cancel_rate": _funnel_rate(cancels, pricing),
        }

        recent_q = TrackingEvent.query
        if date_filter is not None:
            recent_q = recent_q.filter(date_filter)
        recent_events = (
            recent_q
            .order_by(TrackingEvent.created_at.desc())
            .limit(20)
            .all()
        )

        return jsonify({
            "funnel_counts": counts,
            "derived_metrics": derived,
            "recent_events": [
                {
                    "id": e.id,
                    "event_name": e.event_name,
                    "username": e.username,
                    "user_id": e.user_id,
                    "source": e.source,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in recent_events
            ],
        })
    except Exception as e:
        app.logger.error("Admin analytics funnel failed: %s", e)
        return jsonify({"error": "Failed to load funnel analytics"}), 500


@app.route("/api/admin/analytics/funnel-breakdown", methods=["GET"])
@admin_required
def admin_analytics_funnel_breakdown():
    """Return funnel counts and derived rates broken down by user_state and source."""
    try:
        try:
            date_filter = _parse_funnel_date_filter()
        except ValueError:
            return jsonify({"error": "Invalid start_date or end_date format"}), 400

        def _build_breakdown(group_column):
            """Build per-group funnel counts + derived metrics."""
            base_q = db.session.query(
                group_column,
                TrackingEvent.event_name,
                db.func.count(TrackingEvent.id),
            ).filter(TrackingEvent.event_name.in_(_FUNNEL_EVENTS))
            if date_filter is not None:
                base_q = base_q.filter(date_filter)
            rows = base_q.group_by(group_column, TrackingEvent.event_name).all()

            groups = {}
            for raw_group, event_name, cnt in rows:
                group = raw_group if raw_group else "unknown"
                if group not in groups:
                    groups[group] = {evt: 0 for evt in _FUNNEL_EVENTS}
                groups[group][event_name] = cnt

            result = {}
            for group, counts in groups.items():
                pricing = counts.get("pricing_view", 0)
                clicks = counts.get("upgrade_click", 0)
                approvals = counts.get("paypal_subscription_approved", 0)
                successes = counts.get("payment_success_page_view", 0)
                cancels = counts.get("payment_cancel_page_view", 0)
                result[group] = {
                    "funnel_counts": counts,
                    "derived_metrics": {
                        "pricing_to_click_rate": _funnel_rate(clicks, pricing),
                        "click_to_approval_rate": _funnel_rate(approvals, clicks),
                        "pricing_to_success_rate": _funnel_rate(successes, pricing),
                        "cancel_rate": _funnel_rate(cancels, pricing),
                    },
                }
            return result

        return jsonify({
            "by_user_state": _build_breakdown(TrackingEvent.user_state),
            "by_source": _build_breakdown(TrackingEvent.source),
        })
    except Exception as e:
        app.logger.error("Admin analytics funnel-breakdown failed: %s", e)
        return jsonify({"error": "Failed to load funnel breakdown"}), 500


_EXPERIMENT_EVENTS = ["experiment_view", "cta_primary_click", "experiment_conversion"]
MIN_EXPERIMENT_SAMPLE = 50


def _compute_time_to_conversion_stats(durations_seconds):
    """Return summary stats dict for a list of durations (in seconds). Returns None if empty."""
    if not durations_seconds:
        return None
    return {
        "average_time_to_conversion_seconds": round(statistics.mean(durations_seconds), 1),
        "median_time_to_conversion_seconds": round(statistics.median(durations_seconds), 1),
        "fastest_conversion_seconds": round(min(durations_seconds), 1),
        "slowest_conversion_seconds": round(max(durations_seconds), 1),
        "total_conversions_measured": len(durations_seconds),
    }


def _build_time_to_conversion(events, experiment_name):
    """Calculate time-to-conversion from experiment_view to experiment_conversion.

    Matches by session_id first, then user_id, then username. For each session,
    finds the earliest experiment_view and the first experiment_conversion AFTER
    that view with the same experiment+variant, calculates the time difference.

    Returns dict with 'overall' and 'by_variant' breakdowns.
    """
    # Separate views and conversions, keyed by (identity, variant)
    # Each entry: {(identity, variant): [(created_at,), ...]}
    views_by_key = {}       # (identity, variant) -> [created_at, ...]
    conversions_by_key = {} # (identity, variant) -> [created_at, ...]

    for e in events:
        meta = {}
        if e.metadata_json:
            try:
                meta = json.loads(e.metadata_json)
            except (json.JSONDecodeError, ValueError):
                pass

        if meta.get("experiment") != experiment_name:
            continue

        # Determine identity: prefer session_id, then user_id, then username
        session_id = meta.get("session_id")
        identity = None
        if session_id:
            identity = ("sid", session_id)
        elif e.user_id:
            identity = ("uid", e.user_id)
        elif e.username:
            identity = ("uname", e.username)
        else:
            continue  # Cannot match without identity

        variant = meta.get("variant", "unknown")
        key = (identity, variant)

        if e.event_name == "experiment_view":
            views_by_key.setdefault(key, []).append(e.created_at)
        elif e.event_name == "experiment_conversion":
            conversions_by_key.setdefault(key, []).append(e.created_at)

    # Calculate durations
    all_durations = []
    variant_durations = {}  # variant -> [duration_seconds]

    for key, conv_times in conversions_by_key.items():
        if key not in views_by_key:
            continue
        view_times = views_by_key[key]

        # Earliest view (first view in session for this experiment+variant)
        earliest_view_time = min(view_times)
        # First conversion AFTER the earliest view
        valid_convs = [t for t in conv_times if t > earliest_view_time]
        if not valid_convs:
            continue  # All conversions before view — skip

        first_conv_time = min(valid_convs)

        duration = (first_conv_time - earliest_view_time).total_seconds()
        all_durations.append(duration)

        # Use the variant from the key for breakdown
        variant = key[1]
        variant_durations.setdefault(variant, []).append(duration)

    result = {
        "overall": _compute_time_to_conversion_stats(all_durations),
        "by_variant": {},
    }
    for v, durations in sorted(variant_durations.items()):
        result["by_variant"][v] = _compute_time_to_conversion_stats(durations)

    return result


@app.route("/api/admin/analytics/experiments", methods=["GET"])
@admin_required
def admin_analytics_experiments():
    """Return A/B experiment results comparing variants using TrackingEvent data."""
    try:
        try:
            date_filter = _parse_funnel_date_filter()
        except ValueError:
            return jsonify({"error": "Invalid start_date or end_date format"}), 400

        experiment_name = request.args.get("experiment", "upsell_v1")

        q = TrackingEvent.query.filter(
            TrackingEvent.event_name.in_(_EXPERIMENT_EVENTS)
        )
        if date_filter is not None:
            q = q.filter(date_filter)

        events = q.all()

        # Group counts by variant (overall) and by source+variant
        variants = {}
        source_variants = {}  # {source: {variant: {event: count}}}
        for e in events:
            meta = {}
            if e.metadata_json:
                try:
                    meta = json.loads(e.metadata_json)
                except (json.JSONDecodeError, ValueError):
                    pass

            if meta.get("experiment") != experiment_name:
                continue

            variant = meta.get("variant", "unknown")
            if variant not in variants:
                variants[variant] = {evt: 0 for evt in _EXPERIMENT_EVENTS}
            variants[variant][e.event_name] += 1

            # Group by source + variant
            raw_source = (e.source or meta.get("source") or "").strip()
            source = raw_source if raw_source else "unknown"
            if source not in source_variants:
                source_variants[source] = {}
            if variant not in source_variants[source]:
                source_variants[source][variant] = {evt: 0 for evt in _EXPERIMENT_EVENTS}
            source_variants[source][variant][e.event_name] += 1

        def _build_variant_metrics(counts_map):
            """Build per-variant metrics dict from a {variant: {event: count}} map."""
            metrics = {}
            for v, counts in counts_map.items():
                views = counts.get("experiment_view", 0)
                clicks = counts.get("cta_primary_click", 0)
                conversions = counts.get("experiment_conversion", 0)
                metrics[v] = {
                    "experiment_view": views,
                    "cta_primary_click": clicks,
                    "experiment_conversion": conversions,
                    "view_to_click_rate": _funnel_rate(clicks, views),
                    "click_to_conversion_rate": _funnel_rate(conversions, clicks),
                    "view_to_conversion_rate": _funnel_rate(conversions, views),
                }
            return metrics

        def _sample_info(metrics):
            """Return sorted variant keys and their experiment_view counts."""
            sorted_keys = sorted(metrics.keys())
            sample_counts = {k: metrics[k].get("experiment_view", 0) for k in sorted_keys}
            return sorted_keys, sample_counts

        def _pick_winner(metrics):
            """Determine winner by highest view_to_conversion_rate with min-sample guard."""
            sorted_keys, sample_counts = _sample_info(metrics)
            has_multiple_variants = len(metrics) >= 2
            sample_ok = all(c >= MIN_EXPERIMENT_SAMPLE for c in sample_counts.values()) if has_multiple_variants else False

            winner = None
            if sample_ok and has_multiple_variants:
                sorted_v = sorted(
                    metrics.items(),
                    key=lambda x: x[1]["view_to_conversion_rate"],
                    reverse=True,
                )
                if sorted_v[0][1]["view_to_conversion_rate"] > sorted_v[1][1]["view_to_conversion_rate"]:
                    winner = sorted_v[0][0]

            result = {
                "winner": winner,
                "sample_size_ok": sample_ok,
                "minimum_sample_required": MIN_EXPERIMENT_SAMPLE,
            }
            # Attach current_sample_A / current_sample_B
            if len(sorted_keys) >= 1:
                result["current_sample_A"] = sample_counts[sorted_keys[0]]
            if len(sorted_keys) >= 2:
                result["current_sample_B"] = sample_counts[sorted_keys[1]]
            return result

        # Build overall per-variant metrics
        results = _build_variant_metrics(variants)
        winner_info = _pick_winner(results)

        # Build time-to-conversion analytics
        time_to_conversion = _build_time_to_conversion(events, experiment_name)

        # Build per-source breakdown
        by_source = {}
        for source, sv_map in sorted(source_variants.items()):
            src_metrics = _build_variant_metrics(sv_map)
            src_winner_info = _pick_winner(src_metrics)
            by_source[source] = {
                "variants": src_metrics,
                "winner": src_winner_info["winner"],
                "sample_size_ok": src_winner_info["sample_size_ok"],
                "minimum_sample_required": src_winner_info["minimum_sample_required"],
                "current_sample_A": src_winner_info.get("current_sample_A"),
                "current_sample_B": src_winner_info.get("current_sample_B"),
            }

        return jsonify({
            "experiment": experiment_name,
            "variants": results,
            "winner": winner_info["winner"],
            "sample_size_ok": winner_info["sample_size_ok"],
            "minimum_sample_required": winner_info["minimum_sample_required"],
            "current_sample_A": winner_info.get("current_sample_A"),
            "current_sample_B": winner_info.get("current_sample_B"),
            "by_source": by_source,
            "time_to_conversion": time_to_conversion,
            "attribution_model": "session_first",
        })
    except Exception as e:
        app.logger.error("Admin analytics experiments failed: %s", e)
        return jsonify({"error": "Failed to load experiment analytics"}), 500


@app.route("/api/admin/paypal/create-plan", methods=["POST"])
@admin_required
@csrf_protected
def admin_create_paypal_plan():
    """One-time admin helper: create PayPal Product + Billing Plan via API.

    Requires ``Authorization: Bearer <ADMIN_SECRET>`` header.
    Skips if PAYPAL_PLAN_ID is already set.
    """
    if PAYPAL_PLAN_ID:
        return jsonify({
            "message": "PAYPAL_PLAN_ID already set",
            "plan_id": PAYPAL_PLAN_ID,
        })

    # --- Step 1: PayPal OAuth ---
    try:
        access_token = get_paypal_access_token()
    except Exception as exc:
        app.logger.error("PayPal auth failed during plan creation: %s", exc)
        return jsonify({"error": "PayPal authentication failed"}), 502

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    # --- Step 2: Create Catalog Product ---
    product_payload = {
        "name": "Veltrix AI Pro",
        "description": "Monthly subscription for unlimited AI product analysis on Veltrix AI",
        "type": "SERVICE",
        "category": "SOFTWARE",
    }
    prod_resp = requests.post(
        f"{PAYPAL_API_BASE}/v1/catalogs/products",
        json=product_payload,
        headers=headers,
        timeout=30,
    )
    if prod_resp.status_code not in (200, 201):
        app.logger.error(
            "PayPal product creation failed: %s %s",
            prod_resp.status_code, prod_resp.text,
        )
        return jsonify({
            "error": "Failed to create PayPal catalog product",
            "details": prod_resp.text,
        }), 502

    product_data = prod_resp.json()
    product_id = product_data.get("id", "")

    # --- Step 3: Create Billing Plan ---
    plan_payload = {
        "product_id": product_id,
        "name": "Veltrix AI Pro Monthly",
        "description": "10 USD monthly subscription for unlimited AI product analysis",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "MONTH",
                    "interval_count": 1,
                },
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "10",
                        "currency_code": "USD",
                    }
                },
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "payment_failure_threshold": 3,
        },
        "quantity_supported": False,
    }
    plan_resp = requests.post(
        f"{PAYPAL_API_BASE}/v1/billing/plans",
        json=plan_payload,
        headers=headers,
        timeout=30,
    )
    if plan_resp.status_code not in (200, 201):
        app.logger.error(
            "PayPal plan creation failed: %s %s",
            plan_resp.status_code, plan_resp.text,
        )
        return jsonify({
            "error": "Failed to create PayPal billing plan",
            "details": plan_resp.text,
        }), 502

    plan_data = plan_resp.json()
    plan_id = plan_data.get("id", "")

    app.logger.info(
        "PayPal plan created — product_id=%s plan_id=%s. "
        "Set PAYPAL_PLAN_ID=%s in your environment.",
        product_id, plan_id, plan_id,
    )

    return jsonify({
        "product_id": product_id,
        "plan_id": plan_id,
        "message": "Plan created. Set PAYPAL_PLAN_ID env var to this plan_id.",
    }), 201


@app.route("/api/paypal/activate-subscription", methods=["POST"])
@login_required
def paypal_activate_subscription(user):
    """Activate Pro after a PayPal subscription is approved."""
    body = request.get_json(force=True, silent=True) or {}
    subscription_id = (body.get("subscriptionID") or "").strip()
    if not subscription_id:
        return jsonify({"error": "subscriptionID is required"}), 400

    # Idempotency
    if user.is_pro and user.paypal_subscription_id == subscription_id:
        return jsonify({"message": "Subscription already active.", "is_pro": True})

    # Verify subscription status with PayPal
    try:
        access_token = get_paypal_access_token()
    except Exception as exc:
        app.logger.error("PayPal auth failed: %s", exc)
        return jsonify({"error": "PayPal authentication failed"}), 502

    resp = requests.get(
        f"{PAYPAL_API_BASE}/v1/billing/subscriptions/{subscription_id}",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        app.logger.error(
            "PayPal subscription check failed: %s %s",
            resp.status_code, resp.text,
        )
        return jsonify({"error": "Failed to verify subscription"}), 502

    sub_data = resp.json()
    status = sub_data.get("status", "")
    if status not in ("ACTIVE", "APPROVED"):
        return jsonify({"error": f"Subscription status is {status}, not active"}), 400

    user.is_pro = True
    user.paypal_subscription_id = subscription_id
    user.subscription_status = "ACTIVE"
    db.session.commit()

    return jsonify({"message": "Subscription activated. Pro enabled!", "is_pro": True})


def _verify_paypal_webhook(headers, event_body):
    """Verify a PayPal webhook using the verify-webhook-signature API.

    Returns ``True`` when the signature is valid, ``False`` otherwise.
    """
    if not PAYPAL_WEBHOOK_ID:
        app.logger.error("PAYPAL_WEBHOOK_ID not configured")
        return False

    try:
        access_token = get_paypal_access_token()
    except Exception as exc:
        app.logger.error("PayPal auth failed during webhook verification: %s", exc)
        return False

    verify_payload = {
        "auth_algo": headers.get("PAYPAL-AUTH-ALGO", ""),
        "cert_url": headers.get("PAYPAL-CERT-URL", ""),
        "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID", ""),
        "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG", ""),
        "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME", ""),
        "webhook_id": PAYPAL_WEBHOOK_ID,
        "webhook_event": event_body,
    }

    resp = requests.post(
        f"{PAYPAL_API_BASE}/v1/notifications/verify-webhook-signature",
        json=verify_payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        timeout=30,
    )

    if resp.status_code != 200:
        app.logger.error(
            "PayPal webhook verification request failed: %s %s",
            resp.status_code, resp.text,
        )
        return False

    verification_status = resp.json().get("verification_status", "")
    return verification_status == "SUCCESS"


@app.route("/api/paypal/webhook", methods=["POST"])
def paypal_webhook():
    """Receive and process PayPal webhook events.

    This is the source of truth for subscription lifecycle and payments.
    """
    body_text = request.get_data(as_text=True)
    if not body_text:
        return jsonify({"error": "Empty body"}), 400

    try:
        event = json.loads(body_text)
    except (json.JSONDecodeError, ValueError):
        return jsonify({"error": "Invalid JSON body"}), 400

    # --- Verify webhook signature ---
    if not _verify_paypal_webhook(request.headers, event):
        app.logger.warning("PayPal webhook signature verification failed")
        return jsonify({"error": "Webhook verification failed"}), 403

    event_type = event.get("event_type", "")
    event_id = event.get("id", "")
    resource = event.get("resource", {})

    app.logger.info("PayPal webhook received: %s (id=%s)", event_type, event_id)

    # ---- Subscription events ----
    if event_type in (
        "BILLING.SUBSCRIPTION.ACTIVATED",
        "BILLING.SUBSCRIPTION.CANCELLED",
        "BILLING.SUBSCRIPTION.SUSPENDED",
        "BILLING.SUBSCRIPTION.EXPIRED",
    ):
        subscription_id = resource.get("id", "")
        status = resource.get("status", "")
        if not subscription_id:
            app.logger.warning("Webhook %s missing subscription id", event_type)
            return jsonify({"status": "ignored"}), 200

        user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
        if not user:
            app.logger.info(
                "No user found for subscription event %s", event_type,
            )
            return jsonify({"status": "no_user"}), 200

        # Idempotency: skip if we already processed this event
        if user.paypal_last_event_id == event_id:
            return jsonify({"status": "already_processed"}), 200

        user.subscription_status = status
        user.paypal_last_event_id = event_id

        if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
            user.is_pro = True
        elif event_type in (
            "BILLING.SUBSCRIPTION.CANCELLED",
            "BILLING.SUBSCRIPTION.SUSPENDED",
            "BILLING.SUBSCRIPTION.EXPIRED",
        ):
            user.is_pro = False

        db.session.commit()
        app.logger.info(
            "User %s updated: is_pro=%s subscription_status=%s (event %s)",
            user.username, user.is_pro, user.subscription_status, event_type,
        )
        return jsonify({"status": "ok"}), 200

    # ---- Payment events ----
    if event_type in (
        "PAYMENT.SALE.COMPLETED",
        "PAYMENT.SALE.DENIED",
        "PAYMENT.SALE.REFUNDED",
        "PAYMENT.SALE.REVERSED",
    ):
        # PayPal sale resources include billing_agreement_id for subscriptions
        subscription_id = resource.get("billing_agreement_id", "")
        if not subscription_id:
            app.logger.info(
                "Payment event %s has no billing_agreement_id; skipping", event_type,
            )
            return jsonify({"status": "ignored"}), 200

        user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
        if not user:
            app.logger.info(
                "No user found for payment event %s", event_type,
            )
            return jsonify({"status": "no_user"}), 200

        if user.paypal_last_event_id == event_id:
            return jsonify({"status": "already_processed"}), 200

        user.paypal_last_event_id = event_id

        if event_type == "PAYMENT.SALE.COMPLETED":
            user.is_pro = True
            user.subscription_status = "ACTIVE"
        elif event_type in (
            "PAYMENT.SALE.DENIED",
            "PAYMENT.SALE.REFUNDED",
            "PAYMENT.SALE.REVERSED",
        ):
            user.is_pro = False
            user.subscription_status = "SUSPENDED"

        db.session.commit()
        app.logger.info(
            "User %s payment update: is_pro=%s (event %s)",
            user.username, user.is_pro, event_type,
        )
        return jsonify({"status": "ok"}), 200

    # Unhandled event types — acknowledge receipt
    app.logger.info("Unhandled PayPal webhook event type: %s", event_type)
    return jsonify({"status": "ignored"}), 200



@app.route("/api/save-analysis", methods=["POST"])
@login_required
def api_save_analysis(user):
    analysis_count = SavedAnalysis.query.filter_by(user_id=user.id).count()
    if not user.is_pro and analysis_count >= FREE_ANALYSIS_LIMIT:
        return jsonify({
            "error": f"Free plan limit reached ({FREE_ANALYSIS_LIMIT} analyses). Upgrade to save more.",
        }), 403

    data = request.get_json(force=True, silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    idea = (data.get("idea") or "").strip()
    result = data.get("result")

    if not idea or result is None:
        return jsonify({"error": "Fields 'idea' and 'result' are required"}), 400

    saved = SavedAnalysis(
        user_id=user.id,
        idea=idea,
        result_json=json.dumps(result),
    )
    db.session.add(saved)
    db.session.commit()

    limit = "unlimited" if user.is_pro else FREE_ANALYSIS_LIMIT
    return jsonify({
        "message": "Analysis saved",
        "id": saved.id,
        "analysis_count": analysis_count + 1,
        "analysis_limit": limit,
    }), 201


@app.route("/api/my-analyses", methods=["GET"])
@login_required
def api_my_analyses(user):
    analyses = (
        SavedAnalysis.query
        .filter_by(user_id=user.id)
        .order_by(SavedAnalysis.created_at.desc())
        .all()
    )
    items = []
    for a in analyses:
        result_data = json.loads(a.result_json)
        items.append({
            "id": a.id,
            "idea": a.idea,
            "title": result_data.get("title", a.idea),
            "category": result_data.get("category", "general"),
            "short_summary": result_data.get("short_summary", ""),
            "created_at": a.created_at.isoformat() + "Z",
        })
    return jsonify({
        "analyses": items,
        "count": len(items),
        "limit": "unlimited" if user.is_pro else FREE_ANALYSIS_LIMIT,
    })


@app.route("/health")
def health():
    latest_store = get_latest_store()

    return jsonify({
        "status": "ok",
        "openai_ready": bool(OPENAI_API_KEY),
        "saved_shop": latest_store.shop if latest_store else None,
        "shopify_api_key_ready": bool(SHOPIFY_API_KEY),
        "shopify_api_secret_ready": bool(SHOPIFY_API_SECRET),
        "shopify_redirect_ready": bool(SHOPIFY_REDIRECT_URI),
        "shopify_token_ready": latest_store is not None,
    })


@app.route("/install")
def install():
    shop = (request.args.get("shop") or "").strip()

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    if not SHOPIFY_API_KEY or not SHOPIFY_REDIRECT_URI:
        return jsonify({"error": "Missing SHOPIFY_API_KEY or SHOPIFY_REDIRECT_URI"}), 500

    params = {
        "client_id": SHOPIFY_API_KEY,
        "scope": SHOPIFY_SCOPES,
        "redirect_uri": SHOPIFY_REDIRECT_URI,
    }

    install_url = f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"
    return redirect(install_url)


@app.route("/callback")
def callback():
    shop = (request.args.get("shop") or "").strip()
    code = (request.args.get("code") or "").strip()

    if not shop or not code:
        return jsonify({"error": "Missing shop or code"}), 400

    if not SHOPIFY_API_KEY or not SHOPIFY_API_SECRET:
        return jsonify({"error": "Missing SHOPIFY_API_KEY or SHOPIFY_API_SECRET"}), 500

    token_url = f"https://{shop}/admin/oauth/access_token"

    try:
        response = requests.post(
            token_url,
            json={
                "client_id": SHOPIFY_API_KEY,
                "client_secret": SHOPIFY_API_SECRET,
                "code": code,
            },
            timeout=30,
        )
        data = response.json()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    access_token = data.get("access_token")

    if not access_token:
        return jsonify({
            "error": "No access token returned",
            "shopify_response": data,
        }), 500

    save_shop_token(shop, access_token, SHOPIFY_SCOPES, default_language="en")

    return jsonify({
        "message": "App installed successfully",
        "shop": shop,
    })


@app.route("/products")
def get_products():
    shop = (request.args.get("shop") or "").strip()

    if not shop:
        latest_store = get_latest_store()
        if not latest_store:
            return jsonify({"error": "No saved Shopify token"}), 500
        shop = latest_store.shop

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    store = get_store(shop)
    if not store:
        return jsonify({"error": "No saved Shopify token"}), 500

    url = f"https://{shop}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": store.access_token,
        "Content-Type": "application/json",
    }

    response = requests.get(url, headers=headers, timeout=30)
    return jsonify(response.json()), response.status_code


@app.route("/set-store-language", methods=["GET", "POST"])
def set_store_language():
    shop = (request.args.get("shop") or "").strip()
    lang = (request.args.get("lang") or "").strip().lower()

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    allowed_languages = {"ar", "en", "fr", "es", "de", "it", "pt", "tr"}
    if lang not in allowed_languages:
        return jsonify({
            "error": "Unsupported language",
            "allowed_languages": sorted(list(allowed_languages)),
        }), 400

    store = get_store(shop)
    if not store:
        return jsonify({"error": "Store not found"}), 404

    store.default_language = lang
    db.session.commit()

    return jsonify({
        "message": "Store language updated successfully",
        "shop": shop,
        "default_language": lang,
    })


@app.route("/settings", methods=["GET"])
def settings_page():
    shop = (request.args.get("shop") or "").strip()

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    store = get_store(shop)
    if not store:
        return jsonify({"error": "Store not found"}), 404

    current_lang = store.default_language or "en"

    template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Veltrix AI Settings</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #f6f7fb;
            margin: 0;
            padding: 24px;
            color: #111827;
        }
        .container {
            max-width: 700px;
            margin: 0 auto;
            background: white;
            padding: 24px;
            border-radius: 16px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.08);
        }
        h1 {
            margin-top: 0;
            font-size: 28px;
        }
        .muted {
            color: #6b7280;
            margin-bottom: 24px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
        }
        select, button {
            width: 100%;
            padding: 14px;
            border-radius: 10px;
            border: 1px solid #d1d5db;
            font-size: 16px;
            margin-bottom: 16px;
        }
        button {
            background: #111827;
            color: white;
            border: none;
            cursor: pointer;
        }
        button:hover {
            background: #1f2937;
        }
        .secondary {
            background: #2563eb;
        }
        .secondary:hover {
            background: #1d4ed8;
        }
        .card {
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 16px;
            margin-top: 20px;
            background: #fafafa;
        }
        .success {
            color: green;
            margin-top: 12px;
        }
        .error {
            color: red;
            margin-top: 12px;
        }
        code {
            background: #f3f4f6;
            padding: 2px 6px;
            border-radius: 6px;
        }
        /* ── Result card styles ── */
        .result-card {
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: 20px;
            margin-top: 18px;
            background: #fff;
        }
        .result-card .product-title {
            font-size: 22px;
            font-weight: 700;
            margin: 6px 0 10px;
            color: #1e293b;
        }
        .result-card .badge {
            display: inline-block;
            background: #fbbf24;
            color: #000;
            padding: 3px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 6px;
            vertical-align: middle;
        }
        .result-card .summary-text {
            font-size: 15px;
            color: #374151;
            line-height: 1.6;
            margin: 8px 0 14px;
        }
        .result-card .meta-row {
            font-size: 13px;
            color: #6b7280;
            margin-bottom: 4px;
        }
        .result-card .meta-row strong {
            color: #374151;
        }
        .section-box {
            margin-top: 14px;
            padding: 14px 16px;
            border-radius: 12px;
        }
        .section-box h4 {
            margin: 0 0 10px;
            font-size: 15px;
        }
        .fragrance-box {
            background: #fdf6ec;
            border: 1px solid #f5d89a;
        }
        .fragrance-box h4 { color: #92400e; }
        .notes-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 10px;
            margin: 10px 0;
        }
        .note-card {
            background: #fff;
            border: 1px solid #fde68a;
            border-radius: 10px;
            padding: 10px 12px;
        }
        .note-card .note-label {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #92400e;
            margin-bottom: 4px;
        }
        .note-card .note-value {
            font-size: 13px;
            color: #1e293b;
        }
        .detail-row {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 8px;
        }
        .detail-chip {
            background: #fffbeb;
            border: 1px solid #fde68a;
            border-radius: 8px;
            padding: 6px 12px;
            font-size: 13px;
        }
        .detail-chip .chip-label {
            font-weight: 700;
            color: #92400e;
            font-size: 11px;
            text-transform: uppercase;
            display: block;
            margin-bottom: 2px;
        }
        .tag-list {
            list-style: none;
            padding: 0;
            margin: 6px 0 0;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .tag-list li {
            background: #fef3c7;
            border: 1px solid #fde68a;
            border-radius: 20px;
            padding: 4px 12px;
            font-size: 13px;
            color: #78350f;
        }
        .scent-family-value {
            font-size: 16px;
            font-weight: 600;
            color: #78350f;
        }
        .description-box {
            background: #f9fafb;
            border: 1px solid #e5e7eb;
        }
        .description-box h4 { color: #1e293b; }
        .description-html {
            font-size: 14px;
            line-height: 1.7;
            color: #374151;
        }
        .description-html ul {
            padding-left: 20px;
            margin: 10px 0;
        }
        .description-html li {
            margin-bottom: 6px;
        }
        .diagnostics-row {
            margin-top: 10px;
            font-size: 11px;
            color: #9ca3af;
            background: #f9fafb;
            padding: 6px 10px;
            border-radius: 6px;
        }
        .seo-box {
            background: #f0fdf4;
            border: 1px solid #bbf7d0;
        }
        .seo-box h4 { color: #166534; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Veltrix AI Language Settings</h1>
        <div class="muted">Store: <strong>{{ shop }}</strong></div>

        <div class="card">
            <label for="language">Choose your default content language</label>
            <select id="language">
                <option value="en" {% if current_lang == "en" %}selected{% endif %}>English</option>
                <option value="fr" {% if current_lang == "fr" %}selected{% endif %}>French</option>
                <option value="es" {% if current_lang == "es" %}selected{% endif %}>Spanish</option>
                <option value="ar" {% if current_lang == "ar" %}selected{% endif %}>Arabic</option>
                <option value="de" {% if current_lang == "de" %}selected{% endif %}>German</option>
                <option value="it" {% if current_lang == "it" %}selected{% endif %}>Italian</option>
                <option value="pt" {% if current_lang == "pt" %}selected{% endif %}>Portuguese</option>
                <option value="tr" {% if current_lang == "tr" %}selected{% endif %}>Turkish</option>
            </select>

            <button onclick="saveLanguage()">Save Language</button>
            <button class="secondary" onclick="optimizeProducts()">Optimize Products</button>

            <div id="message"></div>
            <div id="results" style="margin-top:20px;"></div>
        </div>

        <div class="card">
            <strong>How it works:</strong>
            <p>1. Select the language you want.</p>
            <p>2. Click <code>Save Language</code>.</p>
            <p>3. Click <code>Optimize Products</code>.</p>
        </div>
    </div>

    <script>
        const shop = {{ shop|tojson }};

        async function saveLanguage() {
            const lang = document.getElementById("language").value;
            const message = document.getElementById("message");
            message.innerHTML = "Saving...";

            try {
                const response = await fetch(`/set-store-language?shop=${encodeURIComponent(shop)}&lang=${encodeURIComponent(lang)}`);
                const data = await response.json();

                if (response.ok) {
                    message.innerHTML = `<div class="success">Language saved successfully: ${data.default_language}</div>`;
                } else {
                    message.innerHTML = `<div class="error">${data.error || "Failed to save language"}</div>`;
                }
            } catch (error) {
                message.innerHTML = `<div class="error">${error.message}</div>`;
            }
        }

        async function optimizeProducts() {
            const message = document.getElementById("message");
            const resultsBox = document.getElementById("results");
            const lang = document.getElementById("language").value;

            message.innerHTML = "Optimizing products...";
            resultsBox.innerHTML = "";

            try {
                const response = await fetch(`/optimize-all-products?shop=${encodeURIComponent(shop)}&lang=${encodeURIComponent(lang)}`);
                const data = await response.json();

                if (!response.ok) {
                    message.innerHTML = `<div class="error">${data.error || "Optimization failed"}</div>`;
                    return;
                }

                message.innerHTML = `<div class="success">Optimization completed successfully. Language used: ${data.language_used}</div>`;

                if (!data.results || !data.results.length) {
                    resultsBox.innerHTML = `<div class="card"><p>No products were processed.</p></div>`;
                    return;
                }

                let html = `<div class="card"><h3>Optimization Results</h3>`;

                data.results.forEach((item, index) => {
                    const benefits = Array.isArray(item.key_benefits) ? item.key_benefits.map(b => `<li>${b}</li>`).join("") : "";
                    const sellingPts = Array.isArray(item.selling_points) ? item.selling_points.map(s => `<li>${s}</li>`).join("") : "";
                    const category = (item.category || "").toLowerCase();

                    /* ── Category badge ── */
                    const categoryBadgeColors = {
                        fragrance: { bg: "#fbbf24", icon: "🌸" },
                        electronics: { bg: "#60a5fa", icon: "💻" },
                        fashion: { bg: "#f472b6", icon: "👗" },
                        beauty: { bg: "#c084fc", icon: "✨" },
                        home: { bg: "#34d399", icon: "🏠" },
                        general: { bg: "#9ca3af", icon: "📦" },
                    };
                    const badgeInfo = categoryBadgeColors[category] || categoryBadgeColors.general;
                    const categoryBadge = `<span class="badge" style="background:${badgeInfo.bg};">${badgeInfo.icon} ${item.category || "Product"}</span>`;

                    /* ── FRAGRANCE sections (only if category is fragrance) ── */
                    let scentFamilyHtml = "";
                    if (item.scent_family) {
                        scentFamilyHtml = `
                            <div class="section-box fragrance-box">
                                <h4>🌿 Scent Family</h4>
                                <div class="scent-family-value">${item.scent_family}</div>
                            </div>
                        `;
                    }

                    let fragranceNotesHtml = "";
                    const notes = item.fragrance_notes || {};
                    const hasNotes = (Array.isArray(notes.top) && notes.top.length) ||
                                     (Array.isArray(notes.heart) && notes.heart.length) ||
                                     (Array.isArray(notes.base) && notes.base.length);
                    if (hasNotes) {
                        const topNotes = Array.isArray(notes.top) ? notes.top.join(", ") : "";
                        const heartNotes = Array.isArray(notes.heart) ? notes.heart.join(", ") : "";
                        const baseNotes = Array.isArray(notes.base) ? notes.base.join(", ") : "";
                        fragranceNotesHtml = `
                            <div class="section-box fragrance-box">
                                <h4>🎵 Fragrance Notes</h4>
                                <div class="notes-grid">
                                    ${topNotes ? `<div class="note-card"><div class="note-label">Top Notes</div><div class="note-value">${topNotes}</div></div>` : ""}
                                    ${heartNotes ? `<div class="note-card"><div class="note-label">Heart Notes</div><div class="note-value">${heartNotes}</div></div>` : ""}
                                    ${baseNotes ? `<div class="note-card"><div class="note-label">Base Notes</div><div class="note-value">${baseNotes}</div></div>` : ""}
                                </div>
                                ${item.scent_evolution ? `<div style="margin-top:10px;font-size:13px;"><strong style="color:#92400e;">Scent Evolution:</strong> ${item.scent_evolution}</div>` : ""}
                            </div>
                        `;
                    }

                    let fragrancePerformanceHtml = "";
                    if (item.projection || item.longevity) {
                        fragrancePerformanceHtml = `
                            <div class="section-box fragrance-box">
                                <h4>📊 Performance</h4>
                                <div class="detail-row">
                                    ${item.projection ? `<div class="detail-chip"><span class="chip-label">Projection</span>${item.projection}</div>` : ""}
                                    ${item.longevity ? `<div class="detail-chip"><span class="chip-label">Longevity</span>${item.longevity}</div>` : ""}
                                </div>
                            </div>
                        `;
                    }

                    let usageHtml = "";
                    if (item.best_season || (Array.isArray(item.best_occasions) && item.best_occasions.length)) {
                        usageHtml = `
                            <div class="section-box fragrance-box">
                                <h4>🗓️ Usage</h4>
                                ${item.best_season ? `<div style="margin-bottom:8px;"><strong style="font-size:13px;color:#92400e;">Best Season:</strong> <span style="font-size:13px;">${item.best_season}</span></div>` : ""}
                                ${Array.isArray(item.best_occasions) && item.best_occasions.length ? `<div><strong style="font-size:13px;color:#92400e;">Best Occasions</strong><ul class="tag-list">${item.best_occasions.map(o => `<li>${o}</li>`).join("")}</ul></div>` : ""}
                            </div>
                        `;
                    }

                    let emotionalHtml = "";
                    if (Array.isArray(item.emotional_triggers) && item.emotional_triggers.length) {
                        emotionalHtml = `
                            <div class="section-box fragrance-box">
                                <h4>💫 Emotional Profile</h4>
                                <ul class="tag-list">${item.emotional_triggers.map(e => `<li>${e}</li>`).join("")}</ul>
                            </div>
                        `;
                    }

                    let luxuryHtml = "";
                    if (item.luxury_description) {
                        luxuryHtml = `<div style="margin-top:10px;font-size:13px;font-style:italic;color:#78350f;padding:10px 14px;background:#fffbeb;border-radius:8px;border:1px solid #fde68a;">${item.luxury_description}</div>`;
                    }

                    /* ── ELECTRONICS sections ── */
                    let specsHtml = "";
                    if (item.specs && typeof item.specs === "object" && Object.keys(item.specs).length) {
                        const specRows = Object.entries(item.specs).map(([k, v]) => `<div class="detail-chip"><span class="chip-label">${k}</span>${v}</div>`).join("");
                        specsHtml = `
                            <div class="section-box" style="background:#eff6ff;border:1px solid #bfdbfe;">
                                <h4 style="color:#1e40af;">⚙️ Specifications</h4>
                                <div class="detail-row">${specRows}</div>
                            </div>
                        `;
                    }

                    let electronicsPerformanceHtml = "";
                    if (item.performance && category === "electronics") {
                        electronicsPerformanceHtml = `<div class="meta-row"><strong>Performance:</strong> ${item.performance}</div>`;
                    }

                    let prosHtml = "";
                    if (Array.isArray(item.pros) && item.pros.length) {
                        prosHtml = `<div style="margin-top:8px;"><strong style="font-size:13px;color:#166534;">✅ Pros</strong><ul style="margin:4px 0 0;padding-left:20px;">${item.pros.map(p => `<li>${p}</li>`).join("")}</ul></div>`;
                    }

                    let consHtml = "";
                    if (Array.isArray(item.cons) && item.cons.length) {
                        consHtml = `<div style="margin-top:8px;"><strong style="font-size:13px;color:#991b1b;">⚠️ Cons</strong><ul style="margin:4px 0 0;padding-left:20px;">${item.cons.map(c => `<li>${c}</li>`).join("")}</ul></div>`;
                    }

                    /* ── FASHION sections ── */
                    let fashionHtml = "";
                    if (item.style || item.fit || (Array.isArray(item.materials) && item.materials.length)) {
                        fashionHtml = `
                            <div class="section-box" style="background:#fdf2f8;border:1px solid #fbcfe8;">
                                <h4 style="color:#9d174d;">👗 Fashion Details</h4>
                                ${item.style ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Style:</strong> ${item.style}</div>` : ""}
                                ${item.fit ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Fit:</strong> ${item.fit}</div>` : ""}
                                ${Array.isArray(item.materials) && item.materials.length ? `<div style="font-size:13px;"><strong>Materials:</strong> ${item.materials.join(", ")}</div>` : ""}
                            </div>
                        `;
                    }

                    let fashionOccasionsHtml = "";
                    if (Array.isArray(item.occasions) && item.occasions.length) {
                        fashionOccasionsHtml = `<div style="margin-top:8px;"><strong style="font-size:13px;">Occasions</strong><ul class="tag-list">${item.occasions.map(o => `<li>${o}</li>`).join("")}</ul></div>`;
                    }

                    let careHtml = "";
                    if (item.care_instructions) {
                        careHtml = `<div class="meta-row"><strong>Care:</strong> ${item.care_instructions}</div>`;
                    }

                    /* ── SOFTWARE sections ── */
                    let softwareHtml = "";
                    if (item.platform || (Array.isArray(item.features) && item.features.length)) {
                        softwareHtml = `
                            <div class="section-box" style="background:#f5f3ff;border:1px solid #ddd6fe;">
                                <h4 style="color:#5b21b6;">🖥️ Software Details</h4>
                                ${item.platform ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Platform:</strong> ${item.platform}</div>` : ""}
                                ${item.pricing_model ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Pricing:</strong> ${item.pricing_model}</div>` : ""}
                                ${Array.isArray(item.features) && item.features.length ? `<div style="font-size:13px;"><strong>Features:</strong><ul style="margin:4px 0 0;padding-left:20px;">${item.features.map(f => `<li>${f}</li>`).join("")}</ul></div>` : ""}
                            </div>
                        `;
                    }

                    let integrationsHtml = "";
                    if (Array.isArray(item.integrations) && item.integrations.length) {
                        integrationsHtml = `<div style="margin-top:8px;"><strong style="font-size:13px;">Integrations</strong><ul class="tag-list">${item.integrations.map(i => `<li>${i}</li>`).join("")}</ul></div>`;
                    }

                    /* ── BUSINESS IDEA sections ── */
                    let businessHtml = "";
                    if (item.problem || item.solution || item.monetization) {
                        businessHtml = `
                            <div class="section-box" style="background:#ecfdf5;border:1px solid #a7f3d0;">
                                <h4 style="color:#065f46;">💡 Business Analysis</h4>
                                ${item.problem ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Problem:</strong> ${item.problem}</div>` : ""}
                                ${item.solution ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Solution:</strong> ${item.solution}</div>` : ""}
                                ${item.monetization ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Monetization:</strong> ${item.monetization}</div>` : ""}
                                ${item.competitive_advantage ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Competitive Advantage:</strong> ${item.competitive_advantage}</div>` : ""}
                                ${item.market_size ? `<div style="font-size:13px;"><strong>Market Size:</strong> ${item.market_size}</div>` : ""}
                            </div>
                        `;
                    }

                    /* ── GENERIC PRODUCT specifications ── */
                    let genericSpecsHtml = "";
                    if (item.specifications && typeof item.specifications === "object" && Object.keys(item.specifications).length) {
                        const rows = Object.entries(item.specifications).map(([k, v]) => `<div class="detail-chip"><span class="chip-label">${k}</span>${v}</div>`).join("");
                        genericSpecsHtml = `
                            <div class="section-box" style="background:#f9fafb;border:1px solid #e5e7eb;">
                                <h4 style="color:#374151;">📋 Specifications</h4>
                                <div class="detail-row">${rows}</div>
                            </div>
                        `;
                    }

                    /* ── USE CASES (shared by electronics, software, generic) ── */
                    let useCasesHtml = "";
                    if (Array.isArray(item.use_cases) && item.use_cases.length) {
                        useCasesHtml = `<div style="margin-top:8px;"><strong style="font-size:13px;">Use Cases</strong><ul class="tag-list">${item.use_cases.map(u => `<li>${u}</li>`).join("")}</ul></div>`;
                    }

                    /* ── DESCRIPTION section (rendered as HTML) ── */
                    let descriptionHtml = "";
                    if (item.new_description) {
                        descriptionHtml = `
                            <div class="section-box description-box">
                                <h4>📝 Description</h4>
                                <div class="description-html">${item.new_description}</div>
                            </div>
                        `;
                    }

                    /* ── SEO section ── */
                    let seoHtml = "";
                    if (item.meta_description_preview || item.keywords) {
                        seoHtml = `
                            <div class="section-box seo-box">
                                <h4>🔎 SEO</h4>
                                ${item.meta_description_preview ? `<div style="font-size:13px;margin-bottom:6px;"><strong>Meta Description:</strong> ${item.meta_description_preview}</div>` : ""}
                                ${item.keywords ? `<div style="font-size:13px;"><strong>Keywords:</strong> ${item.keywords}</div>` : ""}
                            </div>
                        `;
                    }

                    html += `
                        <div class="result-card">
                            <div class="meta-row">
                                <strong>#${index + 1}</strong>
                                ${categoryBadge}
                                &nbsp;·&nbsp; Product ID: ${item.product_id ?? ""}
                                &nbsp;·&nbsp; ${item.success ? "✅ Success" : "❌ Failed"}
                            </div>

                            ${item.old_title ? `<div class="meta-row">Previously: ${item.old_title}</div>` : ""}

                            <div class="product-title">${item.new_title ?? ""}</div>

                            ${item.short_summary ? `<p class="summary-text">${item.short_summary}</p>` : ""}

                            ${item.technical_analysis ? `<div class="meta-row"><strong>Technical Analysis:</strong> ${item.technical_analysis}</div>` : ""}
                            ${item.target_audience ? `<div class="meta-row"><strong>Target Audience:</strong> ${item.target_audience}</div>` : ""}

                            ${benefits ? `<div style="margin-top:8px;"><strong style="font-size:13px;">Key Benefits</strong><ul style="margin:4px 0 0;padding-left:20px;">${benefits}</ul></div>` : ""}
                            ${sellingPts ? `<div style="margin-top:8px;"><strong style="font-size:13px;">Selling Points</strong><ul style="margin:4px 0 0;padding-left:20px;">${sellingPts}</ul></div>` : ""}

                            ${scentFamilyHtml}
                            ${fragranceNotesHtml}
                            ${fragrancePerformanceHtml}
                            ${usageHtml}
                            ${emotionalHtml}
                            ${luxuryHtml}
                            ${specsHtml}
                            ${electronicsPerformanceHtml}
                            ${prosHtml}
                            ${consHtml}
                            ${fashionHtml}
                            ${fashionOccasionsHtml}
                            ${careHtml}
                            ${softwareHtml}
                            ${integrationsHtml}
                            ${businessHtml}
                            ${genericSpecsHtml}
                            ${useCasesHtml}
                            ${descriptionHtml}
                            ${seoHtml}

                            <div class="diagnostics-row">
                                🔍 category=${item.category ?? "unknown"} | is_fragrance=${item.is_fragrance ?? false} | has_ul=${item.has_ul} | li_count=${item.li_count} | bullet_symbol=${item.contains_bullet_symbol} | source=${item.source_used ?? ""} | lang=${item.language_used ?? ""}
                            </div>
                            ${item.error ? `<div style="color:red;margin-top:8px;"><strong>Error:</strong> ${item.error}</div>` : ""}
                        </div>
                    `;
                });

                html += `</div>`;
                resultsBox.innerHTML = html;
            } catch (error) {
                message.innerHTML = `<div class="error">${error.message}</div>`;
            }
        }
    </script>
</body>
</html>
"""

    return render_template_string(template, shop=shop, current_lang=current_lang)


@app.route("/api/optimize-product", methods=["POST"])
def optimize_product():
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    data = request.get_json(force=True, silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    vendor = (data.get("vendor") or "").strip()
    product_type = (data.get("product_type") or "").strip()

    if not any([title, description, vendor, product_type]):
        return jsonify({"error": "At least one of title, description, vendor, or product_type is required"}), 400

    product = {
        "title": title,
        "body_html": description,
        "vendor": vendor,
        "product_type": product_type,
        "tags": "",
    }

    result = optimize_product_router(product, lang="en")

    long_desc = result.get("long_description") or result.get("description", "")

    # Build response with universal fields
    response_data = {
        "category": result.get("category", ""),
        "title": result.get("title"),
        "short_summary": result.get("short_summary", ""),
        "technical_analysis": result.get("technical_analysis", ""),
        "target_audience": result.get("target_audience", ""),
        "key_benefits": result.get("key_benefits", []),
        "selling_points": result.get("selling_points", []),
        "long_description": long_desc,
        "description": long_desc,
        "meta_description": result.get("meta_description"),
        "keywords": result.get("keywords"),
        "source_used": result.get("source_used"),
        "is_fragrance": result.get("is_fragrance", False),
        "has_ul": "<ul>" in long_desc.lower(),
        "li_count": long_desc.lower().count("<li>"),
        "contains_bullet_symbol": "•" in long_desc,
    }

    # Include all category-specific fields dynamically
    for field in CATEGORY_SPECIFIC_FIELDS:
        if field in result:
            response_data[field] = result[field]

    return jsonify(response_data)


@app.route("/api/analyze-product", methods=["POST"])
@limiter.limit("30 per minute")
def analyze_product():
    try:
        data = request.get_json(force=True, silent=True)
        if data is None:
            return jsonify({"error": "Invalid or missing JSON body"}), 400

        idea = (data.get("idea") or "").strip()
        if not idea:
            return jsonify({"error": "Field 'idea' is required"}), 400

        # Usage limit for logged-in users
        current_user = get_current_user()
        if current_user:
            analysis_count = SavedAnalysis.query.filter_by(user_id=current_user.id).count()
            if not current_user.is_pro and analysis_count >= FREE_ANALYSIS_LIMIT:
                return jsonify({
                    "error": f"Free plan limit reached ({FREE_ANALYSIS_LIMIT} analyses). Upgrade for unlimited access.",
                    "limit_reached": True,
                }), 403

        if not client:
            # Fallback: return static demo data when OpenAI is not configured
            response_data = {
                "title": idea,
                "category": "fragrance",
                "short_summary": f"AI analysis for \"{idea}\" is not available because OpenAI is not configured. This is a demo response.",
                "technical_analysis": "",
                "target_audience": "Fragrance enthusiasts",
                "key_benefits": ["Premium quality", "Long-lasting scent", "Unique composition"],
                "selling_points": ["Luxury positioning", "Distinctive character"],
                "use_cases": ["Evening wear", "Special occasions", "Signature scent"],
                "performance": {"longevity": "6-8 hours", "projection": "Moderate to strong"},
                "specifications": {"concentration": "Eau de Parfum", "volume": "100ml"},
                "category_specific": {
                    "scent_family": "Oriental",
                    "fragrance_notes": {"top": ["Bergamot"], "heart": ["Rose"], "base": ["Sandalwood"]},
                    "projection": "Moderate to strong",
                    "longevity": "6-8 hours",
                    "best_season": "Fall / Winter",
                    "best_occasions": ["Evening events", "Date night"],
                },
                "long_description": f"<p><strong>{html.escape(idea)}</strong> — demo analysis (OpenAI not configured).</p>",
                "meta_description": f"Discover {html.escape(idea)} — a premium fragrance experience.",
                "keywords": idea.lower(),
                # Backward-compat flat fields
                "scent_family": "Oriental",
                "fragrance_notes": {"top": ["Bergamot"], "heart": ["Rose"], "base": ["Sandalwood"]},
                "projection": "Moderate to strong",
                "longevity": "6-8 hours",
                "best_season": "Fall / Winter",
                "best_occasions": ["Evening events", "Date night"],
            }
            return jsonify(response_data)

        # Preprocess: normalize and correct misspellings
        interpreted, original_raw = preprocess_product_input(idea)
        idea = interpreted  # use corrected input for AI analysis

        result = analyze_product_with_ai(idea)

        # --- Brand-category safety net ---
        # If the AI still returned "general" but the interpreted input
        # contains a known brand, override the category deterministically.
        ai_category = result.get("category", "general")
        if ai_category == "general":
            brand_override = get_brand_category(interpreted)
            if brand_override:
                result["category"] = brand_override

        long_desc = result.get("long_description", "")

        # Build response with unified fields
        response_data = {
            "original_input": original_raw,
            "interpreted_input": interpreted,
            "title": result.get("title", idea),
            "category": result.get("category", "general"),
            "short_summary": result.get("short_summary", ""),
            "technical_analysis": result.get("technical_analysis", ""),
            "target_audience": result.get("target_audience", ""),
            "key_benefits": result.get("key_benefits", []),
            "selling_points": result.get("selling_points", []),
            "use_cases": result.get("use_cases", []),
            "performance": result.get("performance", {}),
            "specifications": result.get("specifications", {}),
            "category_specific": result.get("category_specific", {}),
            "long_description": long_desc,
            "meta_description": result.get("meta_description", ""),
            "keywords": result.get("keywords", ""),
            "has_ul": "<ul>" in long_desc.lower(),
            "li_count": long_desc.lower().count("<li>"),
        }

        # Include all category-specific fields dynamically (backward compat)
        for field in CATEGORY_SPECIFIC_FIELDS:
            if field in result and field not in response_data:
                response_data[field] = result[field]

        return jsonify(response_data)
    except Exception as e:
        tb = traceback.format_exc()
        app.logger.error("[ANALYZE ERROR] Exception in /api/analyze-product: %s\n%s", e, tb)
        return jsonify({
            "error": "Internal Server Error",
        }), 500


@app.route("/optimize-all-products", methods=["GET", "POST"])
def optimize_all_products():
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    shop = (request.args.get("shop") or "").strip()
    requested_lang = (request.args.get("lang") or "").strip().lower()

    if not shop:
        latest_store = get_latest_store()
        if not latest_store:
            return jsonify({"error": "No saved Shopify token"}), 500
        shop = latest_store.shop

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    store = get_store(shop)
    if not store:
        return jsonify({"error": "No saved Shopify token"}), 500

    lang = requested_lang or (store.default_language or "en")

    products_response = requests.get(
        f"https://{shop}/admin/api/2024-01/products.json",
        headers={
            "X-Shopify-Access-Token": store.access_token,
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    try:
        products_data = products_response.json()
    except Exception:
        return jsonify({"error": "Failed to parse Shopify products response"}), 500

    products = products_data.get("products", [])
    results = []

    for product in products[:5]:
        try:
            product_title = product.get("title", "")

            optimized = optimize_product_router(product, lang)

            long_desc = optimized.get("long_description") or optimized.get("description", "")

            result_item = {
                "product_id": product.get("id"),
                "old_title": product_title,
                "new_title": optimized.get("title", ""),
                "category": optimized.get("category", ""),
                "short_summary": optimized.get("short_summary", ""),
                "technical_analysis": optimized.get("technical_analysis", ""),
                "target_audience": optimized.get("target_audience", ""),
                "key_benefits": optimized.get("key_benefits", []),
                "selling_points": optimized.get("selling_points", []),
                "new_description": long_desc,
                "meta_description_preview": optimized.get("meta_description", ""),
                "keywords": optimized.get("keywords", ""),
                "source_used": optimized.get("source_used", "unknown"),
                "success": True,
                "status_code": 200,
                "language_used": lang,
                "error": "",
                "title_variants": [],
                "is_fragrance": optimized.get("is_fragrance", False),
                "has_ul": optimized.get("has_ul"),
                "li_count": optimized.get("li_count"),
                "contains_bullet_symbol": optimized.get("contains_bullet_symbol"),
            }

            # Include all category-specific fields dynamically
            for field in CATEGORY_SPECIFIC_FIELDS:
                if field in optimized:
                    result_item[field] = optimized[field]

            results.append(result_item)
        except Exception as e:
            results.append({
                "product_id": product.get("id"),
                "old_title": product.get("title", ""),
                "new_title": product.get("title", ""),
                "new_description": "",
                "meta_description_preview": "",
                "keywords": "",
                "source_used": "error",
                "success": False,
                "status_code": 500,
                "language_used": lang,
                "error": str(e),
                "title_variants": [],
            })

    return jsonify({
        "message": "Optimization completed",
        "language_used": lang,
        "results": results,
    })


@app.route("/api/track-event", methods=["POST"])
@limiter.limit("30/minute")
def track_event():
    """Store a frontend conversion event in the database."""
    # ── Cap payload size ──
    content_length = request.content_length or 0
    if content_length > _TRACK_EVENT_MAX_BYTES:
        return jsonify({"error": "Payload too large"}), 413

    body = request.get_data(as_text=True)
    if len(body) > _TRACK_EVENT_MAX_BYTES:
        return jsonify({"error": "Payload too large"}), 413

    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return jsonify({"error": "Invalid JSON"}), 400

    if not isinstance(data, dict):
        return jsonify({"error": "Invalid payload"}), 400

    event_name = data.get("event", "").strip()
    if event_name not in _ALLOWED_TRACKING_EVENTS:
        return jsonify({"error": "Unknown event name"}), 400

    # ── Resolve user identity server-side (do not trust frontend) ──
    user = get_current_user()
    username = user.username if user else None
    uid = user.id if user else None

    # ── Build optional metadata (exclude known top-level keys) ──
    known_keys = {"event", "source", "plan", "user_state", "timestamp"}
    extra = {k: v for k, v in data.items() if k not in known_keys}
    metadata = json.dumps(extra) if extra else None

    evt = TrackingEvent(
        event_name=event_name,
        source=data.get("source", "")[:100] if data.get("source") else None,
        plan=data.get("plan", "")[:50] if data.get("plan") else None,
        user_state=data.get("user_state", "")[:50] if data.get("user_state") else None,
        username=username,
        user_id=uid,
        metadata_json=metadata,
    )
    db.session.add(evt)
    db.session.commit()

    return jsonify({"ok": True}), 201


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({"error": "Internal server error"}), 500


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.logger.info("=== VELTRIX STARTUP — code_version: %s ===", _CODE_VERSION)
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
            
