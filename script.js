document.addEventListener("DOMContentLoaded", function () {
    var analyzeBtn = document.getElementById("analyzeBtn");
    var productInput = document.getElementById("productIdea");

    analyzeBtn.addEventListener("click", analyzeProduct);

    productInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
            analyzeProduct();
        }
    });

    async function analyzeProduct() {
        var idea = productInput.value.trim();
        var messageEl = document.getElementById("message");
        var resultsEl = document.getElementById("results");

        if (!idea) {
            messageEl.innerHTML = '<div class="error">Please enter a product idea or name.</div>';
            return;
        }

        messageEl.innerHTML = "Analyzing, please wait...";
        resultsEl.innerHTML = "";
        analyzeBtn.disabled = true;

        try {
            var response = await fetch("/api/analyze-product", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ idea: idea })
            });

            var data = await response.json();

            if (!response.ok) {
                messageEl.innerHTML = '<div class="error">' + (data.error || "Analysis failed") + '</div>';
                console.error("API error:", data);
                analyzeBtn.disabled = false;
                return;
            }

            messageEl.innerHTML = '<div class="success">Analysis completed successfully!</div>';
            resultsEl.innerHTML = buildResultCard(data);
        } catch (error) {
            messageEl.innerHTML = '<div class="error">Connection error: ' + error.message + '</div>';
            console.error("Fetch error:", error);
        } finally {
            analyzeBtn.disabled = false;
        }
    }

    function esc(str) {
        if (!str) return "";
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function buildResultCard(item) {
        var category = (item.category || "").toLowerCase();
        var cs = item.category_specific || {};

        /* Category badge */
        var badgeColors = {
            fragrance:   { bg: "#fbbf24", icon: "\uD83C\uDF38" },
            electronics: { bg: "#60a5fa", icon: "\uD83D\uDCBB" },
            fashion:     { bg: "#f472b6", icon: "\uD83D\uDC57" },
            beauty:      { bg: "#c084fc", icon: "\u2728" },
            home:        { bg: "#34d399", icon: "\uD83C\uDFE0" },
            general:     { bg: "#9ca3af", icon: "\uD83D\uDCE6" }
        };
        var badge = badgeColors[category] || badgeColors.general;
        var categoryBadge = '<span class="badge" style="background:' + badge.bg + ';">' + badge.icon + " " + esc(item.category || "Product") + "</span>";

        /* Benefits & selling points */
        var benefits = Array.isArray(item.key_benefits) ? item.key_benefits.map(function (b) { return "<li>" + esc(b) + "</li>"; }).join("") : "";
        var sellingPts = Array.isArray(item.selling_points) ? item.selling_points.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") : "";

        /* Use cases */
        var useCasesHtml = "";
        if (Array.isArray(item.use_cases) && item.use_cases.length) {
            useCasesHtml = '<div style="margin-top:8px;"><strong style="font-size:13px;">\uD83C\uDFAF Use Cases</strong><ul class="tag-list">' + item.use_cases.map(function (u) { return "<li>" + esc(u) + "</li>"; }).join("") + "</ul></div>";
        }

        /* Performance */
        var performanceHtml = "";
        if (item.performance && typeof item.performance === "object" && Object.keys(item.performance).length) {
            var perfRows = Object.entries(item.performance).map(function (pair) { return '<div class="detail-chip"><span class="chip-label">' + esc(pair[0]) + "</span>" + esc(String(pair[1])) + "</div>"; }).join("");
            performanceHtml =
                '<div class="section-box" style="background:#fefce8;border:1px solid #fde68a;">' +
                    '<h4 style="color:#854d0e;">\uD83D\uDCCA Performance</h4>' +
                    '<div class="detail-row">' + perfRows + "</div>" +
                "</div>";
        }

        /* Specifications */
        var specsHtml = "";
        if (item.specifications && typeof item.specifications === "object" && Object.keys(item.specifications).length) {
            var specRows = Object.entries(item.specifications).map(function (pair) { return '<div class="detail-chip"><span class="chip-label">' + esc(pair[0]) + "</span>" + esc(String(pair[1])) + "</div>"; }).join("");
            specsHtml =
                '<div class="section-box" style="background:#f9fafb;border:1px solid #e5e7eb;">' +
                    '<h4 style="color:#374151;">\u2699\uFE0F Specifications</h4>' +
                    '<div class="detail-row">' + specRows + "</div>" +
                "</div>";
        }

        /* === Category-specific sections === */
        var categoryHtml = "";

        if (category === "fragrance" && Object.keys(cs).length) {
            categoryHtml = buildFragranceSection(cs);
        } else if (category === "electronics" && Object.keys(cs).length) {
            categoryHtml = buildElectronicsSection(cs);
        } else if (category === "fashion" && Object.keys(cs).length) {
            categoryHtml = buildFashionSection(cs);
        } else if (category === "beauty" && Object.keys(cs).length) {
            categoryHtml = buildBeautySection(cs);
        } else if (category === "home" && Object.keys(cs).length) {
            categoryHtml = buildHomeSection(cs);
        }

        /* Description */
        var descriptionHtml = "";
        if (item.long_description) {
            descriptionHtml =
                '<div class="section-box description-box">' +
                    '<h4>\uD83D\uDCDD Description</h4>' +
                    '<div class="description-html">' + item.long_description + "</div>" +
                "</div>";
        }

        /* SEO */
        var seoHtml = "";
        if (item.meta_description || item.keywords) {
            seoHtml =
                '<div class="section-box seo-box">' +
                    '<h4>\uD83D\uDD0E SEO</h4>' +
                    (item.meta_description ? '<div style="font-size:13px;margin-bottom:6px;"><strong>Meta Description:</strong> ' + esc(item.meta_description) + "</div>" : "") +
                    (item.keywords ? '<div style="font-size:13px;"><strong>Keywords:</strong> ' + esc(item.keywords) + "</div>" : "") +
                "</div>";
        }

        return (
            '<div class="result-card">' +
                '<div class="meta-row"><strong>Result</strong> ' + categoryBadge + "</div>" +
                '<div class="product-title">' + esc(item.title || "") + "</div>" +
                (item.short_summary ? '<p class="summary-text">' + esc(item.short_summary) + "</p>" : "") +
                (item.technical_analysis ? '<div class="meta-row"><strong>Technical Analysis:</strong> ' + esc(item.technical_analysis) + "</div>" : "") +
                (item.target_audience ? '<div class="meta-row"><strong>Target Audience:</strong> ' + esc(item.target_audience) + "</div>" : "") +
                (benefits ? '<div style="margin-top:8px;"><strong style="font-size:13px;">\u2705 Key Benefits</strong><ul style="margin:4px 0 0;padding-left:20px;">' + benefits + "</ul></div>" : "") +
                (sellingPts ? '<div style="margin-top:8px;"><strong style="font-size:13px;">\uD83D\uDCA1 Selling Points</strong><ul style="margin:4px 0 0;padding-left:20px;">' + sellingPts + "</ul></div>" : "") +
                useCasesHtml +
                performanceHtml +
                specsHtml +
                categoryHtml +
                descriptionHtml +
                seoHtml +
            "</div>"
        );
    }

    /* ── Fragrance category section ── */
    function buildFragranceSection(cs) {
        var html = '<div class="section-box fragrance-box"><h4>\uD83C\uDF38 Fragrance Details</h4>';

        if (cs.scent_family) {
            html += '<div style="margin-bottom:10px;"><span class="scent-family-value">' + esc(cs.scent_family) + "</span></div>";
        }

        var notes = cs.fragrance_notes || {};
        var hasNotes = (Array.isArray(notes.top) && notes.top.length) ||
                       (Array.isArray(notes.heart) && notes.heart.length) ||
                       (Array.isArray(notes.base) && notes.base.length);
        if (hasNotes) {
            var topN = Array.isArray(notes.top) ? notes.top.join(", ") : "";
            var heartN = Array.isArray(notes.heart) ? notes.heart.join(", ") : "";
            var baseN = Array.isArray(notes.base) ? notes.base.join(", ") : "";
            html += '<div class="notes-grid">' +
                (topN ? '<div class="note-card"><div class="note-label">Top Notes</div><div class="note-value">' + esc(topN) + "</div></div>" : "") +
                (heartN ? '<div class="note-card"><div class="note-label">Heart Notes</div><div class="note-value">' + esc(heartN) + "</div></div>" : "") +
                (baseN ? '<div class="note-card"><div class="note-label">Base Notes</div><div class="note-value">' + esc(baseN) + "</div></div>" : "") +
            "</div>";
        }

        if (cs.projection || cs.longevity) {
            html += '<div class="detail-row">' +
                (cs.projection ? '<div class="detail-chip"><span class="chip-label">Projection</span>' + esc(cs.projection) + "</div>" : "") +
                (cs.longevity ? '<div class="detail-chip"><span class="chip-label">Longevity</span>' + esc(cs.longevity) + "</div>" : "") +
            "</div>";
        }

        if (cs.best_season) {
            html += '<div style="margin-top:8px;font-size:13px;"><strong style="color:#92400e;">Best Season:</strong> ' + esc(cs.best_season) + "</div>";
        }
        if (Array.isArray(cs.best_occasions) && cs.best_occasions.length) {
            html += '<div style="margin-top:6px;"><strong style="font-size:13px;color:#92400e;">Best Occasions</strong><ul class="tag-list">' + cs.best_occasions.map(function (o) { return "<li>" + esc(o) + "</li>"; }).join("") + "</ul></div>";
        }

        html += "</div>";
        return html;
    }

    /* ── Electronics category section ── */
    function buildElectronicsSection(cs) {
        var html = '<div class="section-box" style="background:#eff6ff;border:1px solid #bfdbfe;"><h4 style="color:#1e40af;">\uD83D\uDD0C Electronics Details</h4>';
        var fields = [
            { key: "battery", label: "Battery" },
            { key: "connectivity", label: "Connectivity" },
            { key: "compatibility", label: "Compatibility" },
            { key: "build_quality", label: "Build Quality" },
            { key: "performance_level", label: "Performance Level" }
        ];
        fields.forEach(function (f) {
            if (cs[f.key]) {
                html += '<div style="margin-bottom:6px;font-size:13px;"><strong>' + esc(f.label) + ':</strong> ' + esc(cs[f.key]) + "</div>";
            }
        });
        html += "</div>";
        return html;
    }

    /* ── Fashion category section ── */
    function buildFashionSection(cs) {
        var html = '<div class="section-box" style="background:#fdf2f8;border:1px solid #fbcfe8;"><h4 style="color:#9d174d;">\uD83D\uDC57 Fashion Details</h4>';
        if (cs.style) html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Style:</strong> ' + esc(cs.style) + "</div>";
        if (cs.material) html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Material:</strong> ' + esc(Array.isArray(cs.material) ? cs.material.join(", ") : String(cs.material)) + "</div>";
        if (cs.fit) html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Fit:</strong> ' + esc(cs.fit) + "</div>";
        if (Array.isArray(cs.occasion) && cs.occasion.length) {
            html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Occasion:</strong> ' + esc(cs.occasion.join(", ")) + "</div>";
        } else if (typeof cs.occasion === "string" && cs.occasion) {
            html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Occasion:</strong> ' + esc(cs.occasion) + "</div>";
        }
        if (cs.season) html += '<div style="font-size:13px;"><strong>Season:</strong> ' + esc(cs.season) + "</div>";
        html += "</div>";
        return html;
    }

    /* ── Beauty category section ── */
    function buildBeautySection(cs) {
        var html = '<div class="section-box" style="background:#faf5ff;border:1px solid #e9d5ff;"><h4 style="color:#7e22ce;">\u2728 Beauty Details</h4>';
        if (cs.skin_type) html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Skin Type:</strong> ' + esc(cs.skin_type) + "</div>";
        if (Array.isArray(cs.key_ingredients) && cs.key_ingredients.length) {
            html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Key Ingredients:</strong> ' + esc(cs.key_ingredients.join(", ")) + "</div>";
        }
        if (cs.texture) html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Texture:</strong> ' + esc(cs.texture) + "</div>";
        if (cs.routine_fit) html += '<div style="font-size:13px;"><strong>Routine Fit:</strong> ' + esc(cs.routine_fit) + "</div>";
        html += "</div>";
        return html;
    }

    /* ── Home category section ── */
    function buildHomeSection(cs) {
        var html = '<div class="section-box" style="background:#ecfdf5;border:1px solid #a7f3d0;"><h4 style="color:#065f46;">\uD83C\uDFE0 Home Details</h4>';
        if (cs.room_fit) html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Room Fit:</strong> ' + esc(cs.room_fit) + "</div>";
        if (cs.material) html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Material:</strong> ' + esc(cs.material) + "</div>";
        if (cs.practicality) html += '<div style="margin-bottom:6px;font-size:13px;"><strong>Practicality:</strong> ' + esc(cs.practicality) + "</div>";
        if (cs.maintenance) html += '<div style="font-size:13px;"><strong>Maintenance:</strong> ' + esc(cs.maintenance) + "</div>";
        html += "</div>";
        return html;
    }
});
