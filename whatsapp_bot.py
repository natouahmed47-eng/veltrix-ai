"""
whatsapp_bot.py — Generic WhatsApp automation handler.

No hardcoded catalog, no domain-specific keywords.
All product/service data comes from the database at runtime.
Business logic is handled by the AI brain.
"""

import json
import re
import requests

# ── UltraMsg API ──────────────────────────────────────────────────────────────

_ULTRAMSG_API_BASE = "https://api.ultramsg.com"

# ── Confirmation triggers (multilingual) ─────────────────────────────────────

_CONFIRM_RE = re.compile(
    r"\b(yes|yeah|yep|sure|ok|okay|confirm|place|order|proceed"
    r"|نعم|اوكي|اوك|موافق|اطلب|اكد|تأكيد)\b",
    re.IGNORECASE,
)

_CANCEL_RE = re.compile(
    r"\b(no|nope|cancel|stop|back|لا|الغ|إلغاء|رجوع)\b",
    re.IGNORECASE,
)

# ── Catalog loading ───────────────────────────────────────────────────────────


def load_catalog_items(db_session, CatalogModel):
    """
    Load all active catalog items from the database.

    Parameters
    ----------
    db_session   : SQLAlchemy session (db.session)
    CatalogModel : The WACatalogItem model class

    Returns
    -------
    list of WACatalogItem instances
    """
    return db_session.query(CatalogModel).filter_by(is_active=True).all()


def _format_catalog_for_prompt(items):
    """Render catalog items as a numbered list for the AI system prompt."""
    if not items:
        return "(no catalog items available)"
    lines = []
    for i, item in enumerate(items, 1):
        parts = [f"{i}. {item.name}"]
        if item.price:
            parts.append(f"({item.price})")
        if item.description:
            parts.append(f"— {item.description}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


# ── AI prompt builder ─────────────────────────────────────────────────────────


def build_ai_prompt(phone, message, catalog_items, conversation):
    """
    Build the messages list to send to the OpenAI chat completions API.

    Parameters
    ----------
    phone          : str  — customer's phone number (for context only)
    message        : str  — current inbound message text
    catalog_items  : list — WACatalogItem ORM objects
    conversation   : WAConversation ORM object or None

    Returns
    -------
    list of {"role": ..., "content": ...} dicts
    """
    catalog_text = _format_catalog_for_prompt(catalog_items)

    state = conversation.state if conversation else "idle"
    selected = conversation.selected_item_name if conversation else None

    context_note = ""
    if state == "awaiting_order_confirm" and selected:
        context_note = (
            f"\n\nThe customer has already selected: \"{selected}\". "
            "Wait for their confirmation or cancellation before proceeding."
        )

    system_content = (
        "You are a helpful business assistant operating on WhatsApp. "
        "Your role is to answer customer inquiries, present available catalog items, "
        "and guide customers through placing an order — all in a friendly, concise style "
        "appropriate for a WhatsApp conversation (short messages, no markdown).\n\n"
        f"Current catalog:\n{catalog_text}"
        f"{context_note}\n\n"
        "Guidelines:\n"
        "- Keep replies short and conversational.\n"
        "- If the customer asks what you offer, list the catalog items briefly.\n"
        "- If the customer selects or shows interest in a specific item, confirm it "
        "and ask whether they want to place an order.\n"
        "- When the customer confirms an order, reply with exactly this token on its own line: "
        "ORDER_CONFIRM:<item_name> (replace <item_name> with the exact item name from the catalog).\n"
        "- If the customer cancels or says no, acknowledge it and offer to help with something else.\n"
        "- Never invent products, prices, or details that are not in the catalog.\n"
        "- Respond in the same language the customer uses."
    )

    messages = [{"role": "system", "content": system_content}]

    # Append recent conversation history (last 6 turns = 12 messages to stay within token budget)
    if conversation and conversation.history_json:
        try:
            history = json.loads(conversation.history_json)
            for turn in history[-12:]:
                if turn.get("role") in ("user", "assistant") and turn.get("content"):
                    messages.append({"role": turn["role"], "content": turn["content"]})
        except (json.JSONDecodeError, TypeError):
            pass

    messages.append({"role": "user", "content": message})
    return messages


# ── AI response generation ────────────────────────────────────────────────────


def generate_ai_response(openai_client, model, messages):
    """
    Call the OpenAI chat completions API and return the reply text.

    Parameters
    ----------
    openai_client : openai.OpenAI instance
    model         : str — model name (e.g. "gpt-4.1-mini")
    messages      : list — as returned by build_ai_prompt()

    Returns
    -------
    str — the assistant reply text
    """
    completion = openai_client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=400,
        temperature=0.4,
    )
    return completion.choices[0].message.content.strip()


# ── UltraMsg message sender ───────────────────────────────────────────────────


def send_whatsapp_message(instance_id, token, to, body):
    """
    Send a WhatsApp message via the UltraMsg REST API.

    Parameters
    ----------
    instance_id : str — UltraMsg instance ID
    token       : str — UltraMsg API token
    to          : str — recipient phone in international format (e.g. "971501234567")
    body        : str — message text

    Returns
    -------
    dict — parsed API response JSON

    Raises
    ------
    requests.HTTPError on non-2xx responses
    """
    url = f"{_ULTRAMSG_API_BASE}/{instance_id}/messages/chat"
    payload = {"token": token, "to": to, "body": body}
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ── Conversation history helpers ──────────────────────────────────────────────


def append_to_history(conversation, user_msg, assistant_msg):
    """
    Append a user/assistant exchange to the conversation's history_json.
    Keeps at most the most recent 20 turns (40 messages) to bound DB storage.
    """
    try:
        history = json.loads(conversation.history_json or "[]")
    except (json.JSONDecodeError, TypeError):
        history = []

    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": assistant_msg})

    # Trim to last 20 turns (40 messages)
    if len(history) > 40:
        history = history[-40:]

    conversation.history_json = json.dumps(history, ensure_ascii=False)


# ── Order token extraction ────────────────────────────────────────────────────


def extract_order_item(ai_reply):
    """
    If the AI reply contains the ORDER_CONFIRM token, extract the item name.

    Returns
    -------
    str | None — item name if found, else None
    """
    match = re.search(r"ORDER_CONFIRM:(.+)", ai_reply, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None
