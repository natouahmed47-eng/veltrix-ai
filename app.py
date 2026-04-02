def build_description_with_ai(product):
    if not client:
        raise RuntimeError("OpenAI not configured")

    title = (product.get("title") or "").strip()
    body_html = (product.get("body_html") or "").strip()
    vendor = (product.get("vendor") or "").strip()
    product_type = (product.get("product_type") or "").strip()
    tags = (product.get("tags") or "").strip()

    image_alt_text = ""
    images = product.get("images") or []
    if images:
        image_alt_text = (images[0].get("alt") or "").strip()

    system_prompt = """You are a professional e-commerce copywriter.

Write a high-converting product description in clear, strong, direct English.

Rules:
- No fluff
- No poetic language
- No weak words like maybe, might, possibly
- Focus on real benefits
- Be persuasive and realistic
- No markdown symbols like # or *

Structure:
- Strong product headline
- Short convincing paragraph
- Clear practical benefits
- Strong closing call to action

Output must be plain clean text only.
"""

    user_prompt = f"""Product name: {title}
Brand: {vendor}
Category: {product_type}
Tags: {tags}
Existing description: {body_html}
Image alt text: {image_alt_text}

Write a better final product description in English only.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7
    )

    raw_text = response.choices[0].message.content.strip()
    clean_text = re.sub(r"[#*]", "", raw_text)
    html_text = clean_text.replace("\n", "<br>")
    return html_text


def update_shopify_product_description(shop, token, product_id, description_html):
    url = f"https://{shop}/admin/api/2024-01/products/{product_id}.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }
    payload = {
        "product": {
            "id": int(product_id),
            "body_html": description_html
        }
    }

    response = requests.put(url, headers=headers, json=payload, timeout=30)
    return response


@app.route("/optimize-all-products", methods=["POST"])
def optimize_all_products():
    shop = (request.args.get("shop") or request.json.get("shop") if request.is_json else None) or DEFAULT_SHOP
    shop = shop.strip()
    token = get_shopify_token()

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not token:
        return jsonify({"error": "Missing Shopify token"}), 500

    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    # optional limit
    limit = 5
    if request.is_json:
        try:
            limit = int((request.get_json(silent=True) or {}).get("limit", 5))
        except Exception:
            limit = 5

    products_url = f"https://{shop}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    try:
        products_response = requests.get(products_url, headers=headers, timeout=30)
        products_data = products_response.json()
    except Exception as e:
        return jsonify({
            "error": "Failed to fetch products",
            "details": str(e)
        }), 500

    if products_response.status_code != 200:
        return jsonify({
            "error": "Shopify fetch failed",
            "details": products_data
        }), products_response.status_code

    products = products_data.get("products", [])[:limit]
    results = []

    for product in products:
        product_id = product.get("id")
        title = product.get("title", "")

        try:
            generated_description = build_description_with_ai(product)

            update_response = update_shopify_product_description(
                shop=shop,
                token=token,
                product_id=product_id,
                description_html=generated_description
            )

            try:
                update_data = update_response.json()
            except Exception:
                update_data = {"raw_text": update_response.text}

            results.append({
                "product_id": product_id,
                "title": title,
                "success": update_response.status_code == 200,
                "status_code": update_response.status_code,
                "generated_description": generated_description,
                "shopify_response": update_data
            })

        except Exception as e:
            results.append({
                "product_id": product_id,
                "title": title,
                "success": False,
                "error": str(e)
            })

    success_count = sum(1 for item in results if item.get("success"))

    return jsonify({
        "shop": shop,
        "total_processed": len(results),
        "success_count": success_count,
        "failed_count": len(results) - success_count,
        "results": results
    }), 200
