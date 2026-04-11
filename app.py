1) Add helpers:
- def looks_like_fragrance_product_from_fields(title: str, product_type: str, tags, description: str) -> bool: (detect perfume keywords incl. عطر)
- def ensure_fragrance_fields(data: dict) -> dict: ensure scent_family, fragrance_notes{top/heart/base}, scent_evolution, projection, longevity, best_season, best_occasions, emotional_triggers, luxury_description exist with correct types
- def optimize_product_with_ai_router(product: dict, lang: str = 'en') -> tuple[dict,bool]: if fragrance then call analyze_product_with_ai(idea_string) else build_title_and_description_with_ai(product, lang)

2) In build_title_and_description_with_ai(), convert bullets before validation:
- after candidate_long_description extracted, do candidate_long_description = _convert_bullets_to_html(candidate_long_description)
- validate converted version (do not validate raw bullet form)
- remove redundant conversion

3) Update /api/optimize-product to route via optimize_product_with_ai_router and include fragrance fields when fragrance.

4) Update /optimize-all-products: inside loop route via optimize_product_with_ai_router; if fragrance, include the fragrance fields in results.append.

Use the existing code as base and make the smallest safe patch; do not remove existing endpoints.