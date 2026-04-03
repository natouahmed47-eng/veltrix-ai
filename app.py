import json


def build_title_and_description_with_ai(product: dict) -> dict:
    """
    Generate optimized Arabic title and description using OpenAI.
    
    Args:
        product: Shopify product dict with title, body_html, vendor, product_type, tags
        
    Returns:
        dict with "title" and "description" keys
        
    Raises:
        RuntimeError: If OpenAI not configured or response parsing fails
    """
    if not client:
        raise RuntimeError("OpenAI is not configured")

    title = (product.get("title") or "").strip()
    body_html = (product.get("body_html") or "").strip()
    vendor = (product.get("vendor") or "").strip()
    product_type = (product.get("product_type") or "").strip()
    tags = (product.get("tags") or "").strip()

    system_prompt = """أنت كاتب نصوص متخصص في التجارة الإلكترونية.

مهمتك:
أعد كتابة عنوان ووصف المنتج باللغة العربية لزيادة التحويل والجاذبية.

القواعد:
- استخدم العربية فقط
- اجعل العنوان قويًا وواضحًا وجذابًا
- اجعل الوصف إقناعيًا وسهل الفهم
- لا تضف رموز markdown أو hashtags أو emojis
- ركز على الفوائد والاستخدام العملي
- كن واقعيًا وليس مبالغًا فيه

أرجع نتيجة JSON فقط بهذا الشكل:
{
  "title": "العنوان العربي",
  "description": "الوصف العربي"
}
"""

    user_prompt = f"""العنوان الحالي: {title}
العلامة التجارية: {vendor}
الفئة: {product_type}
الكلمات المفتاحية: {tags}
الوصف الحالي: {body_html}

أعد كتابة العنوان والوصف باللغة العربية فقط.
أرجع JSON فقط بدون شرح أو نص إضافي.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )

        content = response.choices[0].message.content if response.choices else ""
        
        if not content:
            raise RuntimeError("Empty AI response")

        # Try to extract JSON if it's wrapped in markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)

        new_title = (data.get("title") or "").strip()
        new_description = (data.get("description") or "").strip()

        if not new_title or not new_description:
            raise RuntimeError("AI response missing title or description")

        return {
            "title": new_title,
            "description": new_description.replace("\n", "<br>")
        }
        
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse AI response as JSON: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Error generating title and description: {str(e)}")


@app.route("/optimize-all-products", methods=["GET", "POST"])
def optimize_all_products():
    """
    Optimize first 5 products with AI-generated titles and descriptions.
    
    Query params:
        shop: Shopify store domain (e.g., store.myshopify.com)
               If not provided, uses latest saved store from database
    """
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    try:
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
            return jsonify({"error": "No saved Shopify token for this shop"}), 500

        # Fetch products from Shopify
        products_response = requests.get(
            f"https://{shop}/admin/api/2024-01/products.json",
            headers={
                "X-Shopify-Access-Token": store.access_token,
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        if products_response.status_code != 200:
            return jsonify({
                "error": "Failed to fetch products from Shopify",
                "status_code": products_response.status_code
            }), 500

        products_data = products_response.json()
        products = products_data.get("products", [])

        if not products:
            return jsonify({
                "shop": shop,
                "total_processed": 0,
                "results": [],
                "message": "No products found"
            })

        results = []

        # Process first 5 products
        for product in products[:5]:
            try:
                # Generate new title and description
                ai_result = build_title_and_description_with_ai(product)
                new_title = ai_result["title"]
                new_description = ai_result["description"]

                # Update product in Shopify
                update_response = requests.put(
                    f"https://{shop}/admin/api/2024-01/products/{product['id']}.json",
                    headers={
                        "X-Shopify-Access-Token": store.access_token,
                        "Content-Type": "application/json",
                    },
                    json={
                        "product": {
                            "id": product["id"],
                            "title": new_title,
                            "body_html": new_description,
                        }
                    },
                    timeout=30,
                )

                success = update_response.status_code == 200

                results.append({
                    "product_id": product["id"],
                    "old_title": product.get("title"),
                    "new_title": new_title,
                    "success": success,
                    "status_code": update_response.status_code,
                    "new_description_preview": new_description[:150] + "..." if len(new_description) > 150 else new_description
                })

            except Exception as e:
                results.append({
                    "product_id": product.get("id"),
                    "old_title": product.get("title"),
                    "success": False,
                    "error": str(e),
                })

        return jsonify({
            "shop": shop,
            "total_processed": len(results),
            "successful": sum(1 for r in results if r.get("success")),
            "failed": sum(1 for r in results if not r.get("success")),
            "results": results,
        })

    except Exception as e:
        return jsonify({
            "error": "Unexpected error in optimize_all_products",
            "details": str(e)
        }), 500
