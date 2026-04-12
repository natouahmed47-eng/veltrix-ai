"""Shopify service module — store persistence, product fetching, and OAuth."""

from datetime import datetime
import requests

# ---------------------------------------------------------------------------
# Module-level references – set once via init_shopify_service()
# ---------------------------------------------------------------------------
_db = None
_ShopifyStore = None


def init_shopify_service(db, shopify_store_model):
    """Bind the SQLAlchemy db session and ShopifyStore model."""
    global _db, _ShopifyStore
    _db = db
    _ShopifyStore = shopify_store_model


# ---------------------------------------------------------------------------
# Store CRUD helpers
# ---------------------------------------------------------------------------

def get_store(shop: str):
    return _ShopifyStore.query.filter_by(shop=shop).first()


def get_latest_store():
    return _ShopifyStore.query.order_by(_ShopifyStore.updated_at.desc()).first()


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
        store = _ShopifyStore(
            shop=shop,
            access_token=access_token,
            scope=scope,
            default_language=default_language,
        )
        _db.session.add(store)

    _db.session.commit()
    return store


# ---------------------------------------------------------------------------
# Shopify API helpers
# ---------------------------------------------------------------------------

def fetch_shopify_products(shop: str, access_token: str):
    """Fetch products from the Shopify Admin API. Returns a requests.Response."""
    url = f"https://{shop}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    return requests.get(url, headers=headers, timeout=30)


def exchange_shopify_token(shop: str, code: str, api_key: str, api_secret: str) -> dict:
    """Exchange an OAuth code for a Shopify access token. Returns the parsed JSON response."""
    token_url = f"https://{shop}/admin/oauth/access_token"
    response = requests.post(
        token_url,
        json={
            "client_id": api_key,
            "client_secret": api_secret,
            "code": code,
        },
        timeout=30,
    )
    return response.json()
