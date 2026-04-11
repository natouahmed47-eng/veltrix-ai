def _looks_like_fragrance_product(title, product_type, tags, description):
    keywords = ['perfume', 'parfum', 'eau de parfum', 'eau de toilette', 'fragrance', 'cologne', 'attar', 'oud', 'musk']
    title_lower = title.lower()
    type_lower = product_type.lower()
    tags_lower = [tag.lower() for tag in tags]
    description_lower = description.lower()
    return any(keyword in title_lower or keyword in type_lower or keyword in description_lower or keyword in tags_lower for keyword in keywords)


def _ensure_fragrance_fields(data):
    fields = {
        'scent_family': '',
        'fragrance_notes': {'top': [], 'heart': [], 'base': []},
        'scent_evolution': '',
        'projection': '',
        'longevity': '',
        'best_season': '',
        'best_occasions': '',
        'emotional_triggers': '',
        'luxury_description': ''
    }
    for key, default in fields.items():
        if key not in data:
            data[key] = default


def optimize_shopify_product(product, lang='en'):
    if _looks_like_fragrance_product(product['title'], product['product_type'], product['tags'], product['description']):
        idea = f"{product['title']} {product['vendor']} {product['product_type']} {' '.join(product['tags'])} {product['description'].strip()}"
        result = analyze_product_with_ai(idea)
        return {
            **result,
            'new_description': result.get('long_description', ''),
            'source_used': 'ai_fragrance_analyzer',
            **_ensure_fragrance_fields({})
        }
    else:
        return build_title_and_description_with_ai(product, lang=lang)


def build_title_and_description_with_ai(product, lang):
    ai_result = some_ai_function(product, lang)
    candidate_long_description = ai_result['long_description']
    candidate_long_description = _convert_bullets_to_html(candidate_long_description)
    if _is_valid_ai_description(candidate_long_description):
        # Continue processing if valid
        pass


def _is_valid_ai_description(description):
    if '<ul>' in description and '<li>' in description:
        return True  # Accept if already has HTML
    # Add other validation checks if necessary
    return False


@app.route('/optimize-all-products', methods=['POST'])
def optimize_all_products():
    products = request.json['products']
    results = [optimize_shopify_product(product) for product in products]
    return jsonify(results)