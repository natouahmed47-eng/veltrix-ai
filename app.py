# app.py

# Main application logic for product optimization.

def _looks_like_fragrance_product(tags):
    """Check if the product looks like a fragrance based on tags."""
    # Ensure tags can be string or list
    if isinstance(tags, str):
        tags = [tags]
    # Include Arabic keyword
    return any(tag in tags or tag == 'عطر' for tag in tags)


def _ensure_fragrance_fields(data):
    """Ensure mandatory fields exist for fragrance products."""
    mandatory_keys = ['fragrance_name', 'fragrance_type', 'brand']
    for key in mandatory_keys:
        if key not in data:
            data[key] = ''
    # Returning the updated dict now
    return data


def optimize_product_with_ai(payload, lang='en'):
    """Unified helper to route product optimization tasks."""
    if _looks_like_fragrance_product(payload.get('tags')):
        return analyze_product_with_ai(payload)
    else:
        return build_title_and_description_with_ai(payload, lang)


def optimize_shopify_product(payload):
    """Optimize the Shopify product using AI optimization helper."""
    optimized_data = optimize_product_with_ai(payload)
    # Correct usage of keys
    optimized_data['body_html'] = payload.get('description')
    optimized_data['tags'] = normalize_tags(payload.get('tags'))
    return _ensure_fragrance_fields(optimized_data)


from flask import Flask, request

app = Flask(__name__)

@app.route('/api/optimize-product', methods=['POST'])
def optimize_product_route():
    """Route for optimizing fragrance products."""
    payload = request.json
    if _looks_like_fragrance_product(payload.get('tags')):
        return analyze_product_with_ai(payload)
    return 'Invalid Product', 400


def build_title_and_description_with_ai(payload, lang):
    """Build title and description using AI."""
    # Ensure bullet conversion happens
    bullet_content = _convert_bullets_to_html(payload.get('bullets', ''))
    if not _is_valid_ai_description(bullet_content):
        return 'Invalid description', 400
    return {'title': 'Generated Title', 'description': bullet_content}


def _convert_bullets_to_html(bullets):
    """Convert bullet points to HTML."""
    return '<ul>' + ''.join(f'<li>{bullet}</li>' for bullet in bullets.split(',')) + '</ul>'


def _is_valid_ai_description(description):
    """Check if generated AI description is valid."""
    return len(description) > 0
