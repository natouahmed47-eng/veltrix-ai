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

        /* Category badge */
        var badgeColors = {
            fragrance:       { bg: "#fbbf24", icon: "\uD83C\uDF38" },
            electronics:     { bg: "#60a5fa", icon: "\uD83D\uDCBB" },
            fashion:         { bg: "#f472b6", icon: "\uD83D\uDC57" },
            software:        { bg: "#a78bfa", icon: "\uD83D\uDDA5\uFE0F" },
            business_idea:   { bg: "#34d399", icon: "\uD83D\uDCA1" },
            generic_product: { bg: "#9ca3af", icon: "\uD83D\uDCE6" }
        };
        var badge = badgeColors[category] || badgeColors.generic_product;
        var categoryBadge = '<span class="badge" style="background:' + badge.bg + ';">' + badge.icon + " " + esc(item.category || "Product") + "</span>";

        /* Fragrance sections */
        var scentFamilyHtml = "";
        if (item.scent_family) {
            scentFamilyHtml =
                '<div class="section-box fragrance-box">' +
                    '<h4>\uD83C\uDF3F Scent Family</h4>' +
                    '<div class="scent-family-value">' + esc(item.scent_family) + "</div>" +
                "</div>";
        }

        var fragranceNotesHtml = "";
        var notes = item.fragrance_notes || {};
        var hasNotes = (Array.isArray(notes.top) && notes.top.length) ||
                       (Array.isArray(notes.heart) && notes.heart.length) ||
                       (Array.isArray(notes.base) && notes.base.length);
        if (hasNotes) {
            var topN = Array.isArray(notes.top) ? notes.top.join(", ") : "";
            var heartN = Array.isArray(notes.heart) ? notes.heart.join(", ") : "";
            var baseN = Array.isArray(notes.base) ? notes.base.join(", ") : "";
            fragranceNotesHtml =
                '<div class="section-box fragrance-box">' +
                    '<h4>\uD83C\uDFB5 Fragrance Notes</h4>' +
                    '<div class="notes-grid">' +
                        (topN ? '<div class="note-card"><div class="note-label">Top Notes</div><div class="note-value">' + esc(topN) + "</div></div>" : "") +
                        (heartN ? '<div class="note-card"><div class="note-label">Heart Notes</div><div class="note-value">' + esc(heartN) + "</div></div>" : "") +
                        (baseN ? '<div class="note-card"><div class="note-label">Base Notes</div><div class="note-value">' + esc(baseN) + "</div></div>" : "") +
                    "</div>" +
                    (item.scent_evolution ? '<div style="margin-top:10px;font-size:13px;"><strong style="color:#92400e;">Scent Evolution:</strong> ' + esc(item.scent_evolution) + "</div>" : "") +
                "</div>";
        }

        var perfHtml = "";
        if (item.projection || item.longevity) {
            perfHtml =
                '<div class="section-box fragrance-box">' +
                    '<h4>\uD83D\uDCCA Performance</h4>' +
                    '<div class="detail-row">' +
                        (item.projection ? '<div class="detail-chip"><span class="chip-label">Projection</span>' + esc(item.projection) + "</div>" : "") +
                        (item.longevity ? '<div class="detail-chip"><span class="chip-label">Longevity</span>' + esc(item.longevity) + "</div>" : "") +
                    "</div>" +
                "</div>";
        }

        var usageHtml = "";
        if (item.best_season || (Array.isArray(item.best_occasions) && item.best_occasions.length)) {
            usageHtml =
                '<div class="section-box fragrance-box">' +
                    '<h4>\uD83D\uDDD3\uFE0F Usage</h4>' +
                    (item.best_season ? '<div style="margin-bottom:8px;"><strong style="font-size:13px;color:#92400e;">Best Season:</strong> <span style="font-size:13px;">' + esc(item.best_season) + "</span></div>" : "") +
                    (Array.isArray(item.best_occasions) && item.best_occasions.length ? '<div><strong style="font-size:13px;color:#92400e;">Best Occasions</strong><ul class="tag-list">' + item.best_occasions.map(function (o) { return "<li>" + esc(o) + "</li>"; }).join("") + "</ul></div>" : "") +
                "</div>";
        }

        var emotionalHtml = "";
        if (Array.isArray(item.emotional_triggers) && item.emotional_triggers.length) {
            emotionalHtml =
                '<div class="section-box fragrance-box">' +
                    '<h4>\uD83D\uDCAB Emotional Profile</h4>' +
                    '<ul class="tag-list">' + item.emotional_triggers.map(function (e) { return "<li>" + esc(e) + "</li>"; }).join("") + "</ul>" +
                "</div>";
        }

        var luxuryHtml = "";
        if (item.luxury_description) {
            luxuryHtml = '<div style="margin-top:10px;font-size:13px;font-style:italic;color:#78350f;padding:10px 14px;background:#fffbeb;border-radius:8px;border:1px solid #fde68a;">' + esc(item.luxury_description) + "</div>";
        }

        /* Electronics sections */
        var specsHtml = "";
        if (item.specs && typeof item.specs === "object" && Object.keys(item.specs).length) {
            var specRows = Object.entries(item.specs).map(function (pair) { return '<div class="detail-chip"><span class="chip-label">' + esc(pair[0]) + "</span>" + esc(String(pair[1])) + "</div>"; }).join("");
            specsHtml =
                '<div class="section-box" style="background:#eff6ff;border:1px solid #bfdbfe;">' +
                    '<h4 style="color:#1e40af;">\u2699\uFE0F Specifications</h4>' +
                    '<div class="detail-row">' + specRows + "</div>" +
                "</div>";
        }

        var prosHtml = "";
        if (Array.isArray(item.pros) && item.pros.length) {
            prosHtml = '<div style="margin-top:8px;"><strong style="font-size:13px;color:#166534;">\u2705 Pros</strong><ul style="margin:4px 0 0;padding-left:20px;">' + item.pros.map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("") + "</ul></div>";
        }

        var consHtml = "";
        if (Array.isArray(item.cons) && item.cons.length) {
            consHtml = '<div style="margin-top:8px;"><strong style="font-size:13px;color:#991b1b;">\u26A0\uFE0F Cons</strong><ul style="margin:4px 0 0;padding-left:20px;">' + item.cons.map(function (c) { return "<li>" + esc(c) + "</li>"; }).join("") + "</ul></div>";
        }

        /* Fashion sections */
        var fashionHtml = "";
        if (item.style || item.fit || (Array.isArray(item.materials) && item.materials.length)) {
            fashionHtml =
                '<div class="section-box" style="background:#fdf2f8;border:1px solid #fbcfe8;">' +
                    '<h4 style="color:#9d174d;">\uD83D\uDC57 Fashion Details</h4>' +
                    (item.style ? '<div style="margin-bottom:6px;font-size:13px;"><strong>Style:</strong> ' + esc(item.style) + "</div>" : "") +
                    (item.fit ? '<div style="margin-bottom:6px;font-size:13px;"><strong>Fit:</strong> ' + esc(item.fit) + "</div>" : "") +
                    (Array.isArray(item.materials) && item.materials.length ? '<div style="font-size:13px;"><strong>Materials:</strong> ' + esc(item.materials.join(", ")) + "</div>" : "") +
                "</div>";
        }

        /* Software sections */
        var softwareHtml = "";
        if (item.platform || (Array.isArray(item.features) && item.features.length)) {
            softwareHtml =
                '<div class="section-box" style="background:#f5f3ff;border:1px solid #ddd6fe;">' +
                    '<h4 style="color:#5b21b6;">\uD83D\uDDA5\uFE0F Software Details</h4>' +
                    (item.platform ? '<div style="margin-bottom:6px;font-size:13px;"><strong>Platform:</strong> ' + esc(item.platform) + "</div>" : "") +
                    (item.pricing_model ? '<div style="margin-bottom:6px;font-size:13px;"><strong>Pricing:</strong> ' + esc(item.pricing_model) + "</div>" : "") +
                    (Array.isArray(item.features) && item.features.length ? '<div style="font-size:13px;"><strong>Features:</strong><ul style="margin:4px 0 0;padding-left:20px;">' + item.features.map(function (f) { return "<li>" + esc(f) + "</li>"; }).join("") + "</ul></div>" : "") +
                "</div>";
        }

        /* Business idea sections */
        var businessHtml = "";
        if (item.problem || item.solution || item.monetization) {
            businessHtml =
                '<div class="section-box" style="background:#ecfdf5;border:1px solid #a7f3d0;">' +
                    '<h4 style="color:#065f46;">\uD83D\uDCA1 Business Analysis</h4>' +
                    (item.problem ? '<div style="margin-bottom:6px;font-size:13px;"><strong>Problem:</strong> ' + esc(item.problem) + "</div>" : "") +
                    (item.solution ? '<div style="margin-bottom:6px;font-size:13px;"><strong>Solution:</strong> ' + esc(item.solution) + "</div>" : "") +
                    (item.monetization ? '<div style="margin-bottom:6px;font-size:13px;"><strong>Monetization:</strong> ' + esc(item.monetization) + "</div>" : "") +
                    (item.competitive_advantage ? '<div style="margin-bottom:6px;font-size:13px;"><strong>Competitive Advantage:</strong> ' + esc(item.competitive_advantage) + "</div>" : "") +
                    (item.market_size ? '<div style="font-size:13px;"><strong>Market Size:</strong> ' + esc(item.market_size) + "</div>" : "") +
                "</div>";
        }

        /* Generic specifications */
        var genericSpecsHtml = "";
        if (item.specifications && typeof item.specifications === "object" && Object.keys(item.specifications).length) {
            var rows = Object.entries(item.specifications).map(function (pair) { return '<div class="detail-chip"><span class="chip-label">' + esc(pair[0]) + "</span>" + esc(String(pair[1])) + "</div>"; }).join("");
            genericSpecsHtml =
                '<div class="section-box" style="background:#f9fafb;border:1px solid #e5e7eb;">' +
                    '<h4 style="color:#374151;">\uD83D\uDCCB Specifications</h4>' +
                    '<div class="detail-row">' + rows + "</div>" +
                "</div>";
        }

        /* Use cases */
        var useCasesHtml = "";
        if (Array.isArray(item.use_cases) && item.use_cases.length) {
            useCasesHtml = '<div style="margin-top:8px;"><strong style="font-size:13px;">Use Cases</strong><ul class="tag-list">' + item.use_cases.map(function (u) { return "<li>" + esc(u) + "</li>"; }).join("") + "</ul></div>";
        }

        /* Benefits & selling points */
        var benefits = Array.isArray(item.key_benefits) ? item.key_benefits.map(function (b) { return "<li>" + esc(b) + "</li>"; }).join("") : "";
        var sellingPts = Array.isArray(item.selling_points) ? item.selling_points.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") : "";

        /* Description (rendered as HTML from backend) */
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
                (benefits ? '<div style="margin-top:8px;"><strong style="font-size:13px;">Key Benefits</strong><ul style="margin:4px 0 0;padding-left:20px;">' + benefits + "</ul></div>" : "") +
                (sellingPts ? '<div style="margin-top:8px;"><strong style="font-size:13px;">Selling Points</strong><ul style="margin:4px 0 0;padding-left:20px;">' + sellingPts + "</ul></div>" : "") +
                scentFamilyHtml +
                fragranceNotesHtml +
                perfHtml +
                usageHtml +
                emotionalHtml +
                luxuryHtml +
                specsHtml +
                prosHtml +
                consHtml +
                fashionHtml +
                softwareHtml +
                businessHtml +
                genericSpecsHtml +
                useCasesHtml +
                descriptionHtml +
                seoHtml +
            "</div>"
        );
    }
});
