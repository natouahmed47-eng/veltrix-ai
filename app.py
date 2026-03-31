@app.route("/dashboard", methods=["GET"])
def dashboard():
    html = """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
        <title>VELTRIX AI Dashboard</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 900px;
                margin: auto;
            }
            .card {
                background: #1e293b;
                padding: 20px;
                border-radius: 16px;
                margin-bottom: 20px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.25);
            }
            input, textarea, button, select {
                width: 100%;
                padding: 12px;
                margin-top: 10px;
                margin-bottom: 10px;
                border-radius: 10px;
                border: none;
                font-size: 16px;
                box-sizing: border-box;
            }
            input, textarea, select {
                background: #334155;
                color: white;
            }
            button {
                background: #22c55e;
                color: white;
                cursor: pointer;
                font-weight: bold;
            }
            button:hover {
                background: #16a34a;
            }
            h1, h2 {
                margin-top: 0;
            }
            .small {
                color: #cbd5e1;
                font-size: 14px;
            }
            .result-box {
                white-space: pre-wrap;
                word-wrap: break-word;
                background: #0f172a;
                padding: 12px;
                border-radius: 10px;
                overflow-x: auto;
                min-height: 60px;
            }
            .product-card {
                background: #020617;
                padding: 15px;
                margin-bottom: 15px;
                border-radius: 12px;
            }
            .product-card img {
                width: 100%;
                border-radius: 10px;
                margin-bottom: 10px;
            }
            .muted {
                color: #94a3b8;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>VELTRIX AI</h1>
                <p class="small">لوحة تحكم لتوليد وتحديث أوصاف المنتجات بالذكاء الاصطناعي</p>
            </div>

            <div class="card">
                <h2>1) جلب المنتجات</h2>
                <input type="text" id="shop" value="cg1ypm-rd.myshopify.com" placeholder="اسم المتجر"/>
                <button type="button" onclick="loadProducts()">جلب المنتجات</button>
                <div id="products_result" class="result-box">لم يتم تحميل المنتجات بعد.</div>
            </div>

            <div class="card">
                <h2>2) توليد وصف بالذكاء الاصطناعي</h2>
                <input type="text" id="title" placeholder="اسم المنتج"/>
                <input type="text" id="product_type" placeholder="نوع المنتج"/>
                <input type="text" id="audience" placeholder="الجمهور المستهدف"/>
                <input type="text" id="tone" value="احترافي" placeholder="النبرة"/>
                <input type="text" id="language" value="ar" placeholder="اللغة"/>
                <button type="button" onclick="generateDescription()">توليد الوصف</button>
                <div id="ai_result" class="result-box">لم يتم توليد وصف بعد.</div>
            </div>

            <div class="card">
                <h2>3) تحديث وصف المنتج في Shopify</h2>
                <input type="text" id="product_id" placeholder="Product ID"/>
                <button type="button" onclick="updateDescription()">تحديث المنتج</button>
                <div id="update_result" class="result-box">لم يتم تحديث أي منتج بعد.</div>
            </div>
        </div>

        <script>
            function selectProduct(id, title) {
                document.getElementById("product_id").value = id;
                document.getElementById("title").value = title;
                alert("تم اختيار المنتج: " + title);
            }

            async function loadProducts() {
                const shop = document.getElementById("shop").value;
                const container = document.getElementById("products_result");
                container.innerHTML = "جاري تحميل المنتجات...";

                try {
                    const res = await fetch("/products?shop=" + encodeURIComponent(shop));
                    const data = await res.json();

                    if (!res.ok) {
                        container.textContent = "خطأ: " + JSON.stringify(data, null, 2);
                        return;
                    }

                    if (!data.products || data.products.length === 0) {
                        container.textContent = "لا توجد منتجات.";
                        return;
                    }

                    let html = "";

                    data.products.forEach(product => {
                        const image = product.images && product.images.length > 0
                            ? product.images[0].src
                            : "";

                        const cleanDescription = product.body_html
                            ? product.body_html.replace(/<[^>]+>/g, "")
                            : "لا يوجد وصف";

                        const safeTitle = String(product.title || "").replace(/'/g, "\\\\'");

                        html += `
                            <div class="product-card">
                                ${image ? `<img src="${image}" alt="${product.title}">` : ""}
                                <h3>${product.title || "بدون اسم"}</h3>
                                <p>${cleanDescription}</p>
                                <p class="muted">ID: ${product.id}</p>
                                <button type="button" onclick="selectProduct('${product.id}', '${safeTitle}')">
                                    اختيار هذا المنتج
                                </button>
                            </div>
                        `;
                    });

                    container.innerHTML = html;
                } catch (error) {
                    container.textContent = "فشل تحميل المنتجات: " + error.message;
                }
            }

            async function generateDescription() {
                const resultBox = document.getElementById("ai_result");
                resultBox.textContent = "جاري توليد الوصف...";

                const payload = {
                    title: document.getElementById("title").value,
                    product_type: document.getElementById("product_type").value,
                    audience: document.getElementById("audience").value,
                    tone: document.getElementById("tone").value,
                    language: document.getElementById("language").value
                };

                try {
                    const res = await fetch("/ai/product-description", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });

                    const data = await res.json();
                    resultBox.textContent = JSON.stringify(data, null, 2);
                } catch (error) {
                    resultBox.textContent = "فشل توليد الوصف: " + error.message;
                }
            }

            async function updateDescription() {
                const resultBox = document.getElementById("update_result");
                resultBox.textContent = "جاري تحديث المنتج...";

                const payload = {
                    shop: document.getElementById("shop").value,
                    product_id: document.getElementById("product_id").value,
                    title: document.getElementById("title").value,
                    product_type: document.getElementById("product_type").value,
                    audience: document.getElementById("audience").value,
                    tone: document.getElementById("tone").value,
                    language: document.getElementById("language").value
                };

                try {
                    const res = await fetch("/ai/update-product-description", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });

                    const data = await res.json();
                    resultBox.textContent = JSON.stringify(data, null, 2);
                } catch (error) {
                    resultBox.textContent = "فشل تحديث المنتج: " + error.message;
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

