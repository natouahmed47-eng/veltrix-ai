document.addEventListener("DOMContentLoaded", function () {
    /* ── Auth Check ── */
    var authToken = localStorage.getItem("veltrix_token") || "";
    var authUsername = localStorage.getItem("veltrix_username") || "";
    if (!authToken) {
        window.location.replace("/login");
        return;
    }

    /* ── DOM References ── */
    var analyzeBtn = document.getElementById("analyzeBtn");
    var productInput = document.getElementById("productIdea");
    var messageEl = document.getElementById("message");
    var resultsEl = document.getElementById("results");
    var usageInfo = document.getElementById("usageInfo");
    var usernameDisplay = document.getElementById("usernameDisplay");
    var logoutBtn = document.getElementById("logoutBtn");
    var upgradeBar = document.getElementById("upgradeBar");
    var paywallOverlay = document.getElementById("paywallOverlay");
    var paywallClose = document.getElementById("paywallClose");

    /* ── Auth State ── */
    var lastAnalysisIdea = "";
    var lastAnalysisResult = null;

    if (usernameDisplay) usernameDisplay.textContent = authUsername;

    /* ── Logout ── */
    logoutBtn.addEventListener("click", function () {
        localStorage.removeItem("veltrix_token");
        localStorage.removeItem("veltrix_username");
        if (window.trackEvent) window.trackEvent("logout", { source: "app_page" });
        window.location.replace("/login");
    });

    /* ── Usage Fetching + Upgrade Bar ── */
    fetchUsage();

    function fetchUsage() {
        fetch("/api/me", { headers: { "Authorization": "Bearer " + authToken } })
            .then(function (r) {
                if (r.status === 401) {
                    localStorage.removeItem("veltrix_token");
                    localStorage.removeItem("veltrix_username");
                    window.location.replace("/login");
                    return null;
                }
                return r.json();
            })
            .then(function (d) {
                if (!d) return;

                if (usernameDisplay) usernameDisplay.textContent = d.username || authUsername;

                /* Usage info in navbar */
                if (d.is_pro) {
                    usageInfo.textContent = "Pro \u00b7 Unlimited";
                } else {
                    var count = d.analysis_count || 0;
                    var limit = (typeof d.analysis_limit === "number") ? d.analysis_limit : 0;
                    usageInfo.textContent = count + "/" + limit + " verdicts";
                }

                /* Build state context for paywall checks */
                if (typeof window.getUserStateContext === "function") {
                    var ctx = window.getUserStateContext(d);
                    window._veltrixCtx = ctx;
                    updateUpgradeBar(d, ctx);
                } else {
                    updateUpgradeBarFallback(d);
                }
            })
            .catch(function () { /* ignore */ });
    }

    function updateUpgradeBar(user, ctx) {
        if (user.is_pro) {
            upgradeBar.style.display = "none";
            return;
        }
        if (ctx.atLimit) {
            upgradeBar.innerHTML = "You\u2019ve used all free verdicts \u00b7 <a href=\"/#pricingSection\">Upgrade to Pro</a>";
            upgradeBar.className = "upgrade-bar at-limit";
            upgradeBar.style.display = "block";
        } else if (ctx.analysisLimit > 0) {
            upgradeBar.innerHTML = ctx.analysisCount + " of " + ctx.analysisLimit + " verdicts used \u00b7 <a href=\"/#pricingSection\">Upgrade to Pro</a>";
            upgradeBar.className = "upgrade-bar";
            upgradeBar.style.display = "block";
        }
    }

    function updateUpgradeBarFallback(user) {
        if (user.is_pro) {
            upgradeBar.style.display = "none";
            return;
        }
        var count = user.analysis_count || 0;
        var limit = (typeof user.analysis_limit === "number") ? user.analysis_limit : 0;
        if (limit > 0 && count >= limit) {
            upgradeBar.innerHTML = "You\u2019ve used all free verdicts \u00b7 <a href=\"/#pricingSection\">Upgrade to Pro</a>";
            upgradeBar.className = "upgrade-bar at-limit";
            upgradeBar.style.display = "block";
        } else if (limit > 0) {
            upgradeBar.innerHTML = count + " of " + limit + " verdicts used \u00b7 <a href=\"/#pricingSection\">Upgrade to Pro</a>";
            upgradeBar.className = "upgrade-bar";
            upgradeBar.style.display = "block";
        }
    }

    /* ── Analyze Product Flow ── */
    analyzeBtn.addEventListener("click", analyzeProduct);
    productInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") analyzeProduct();
    });

    async function analyzeProduct() {
        var idea = productInput.value.trim();

        if (!idea) {
            messageEl.innerHTML = '<div class="error">Please enter a product idea or name.</div>';
            return;
        }

        /* Soft paywall: delay 0.5s with loading feel, then show paywall */
        var ctx = window._veltrixCtx;
        if (ctx && ctx.atLimit && ctx.state === "free") {
            messageEl.innerHTML = "\u23F3 Evaluating, please wait...";
            analyzeBtn.disabled = true;
            setTimeout(function () {
                messageEl.innerHTML = "";
                analyzeBtn.disabled = false;
                showPaywallModal();
            }, 500);
            return;
        }

        messageEl.innerHTML = "\u23F3 Running decision engine...";
        resultsEl.innerHTML = "";
        analyzeBtn.disabled = true;

        var headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + authToken
        };

        try {
            var response = await fetch("/api/analyze-product", {
                method: "POST",
                headers: headers,
                body: JSON.stringify({ idea: idea })
            });

            var rawText = await response.text();
            var data;
            try {
                data = JSON.parse(rawText);
            } catch (jsonErr) {
                messageEl.innerHTML = '<div class="error">Server returned non-JSON response (HTTP ' + response.status + '): ' + (rawText || "Unknown error") + '</div>';
                analyzeBtn.disabled = false;
                return;
            }

            if (!response.ok) {
                var errMsg = data.message || data.error || "Decision engine failed";
                if (data.trace) console.error("Backend trace:", data.trace);
                messageEl.innerHTML = '<div class="error">' + errMsg + '</div>';
                analyzeBtn.disabled = false;
                return;
            }

            lastAnalysisIdea = idea;
            lastAnalysisResult = data;

            messageEl.innerHTML = '<div class="success">\u2705 Verdict ready.</div>';
            resultsEl.innerHTML = buildResultCard(data) + buildSaveButton();

            if (window.trackEvent) {
                window.trackEvent("analyze_complete", { idea: idea, verdict: data.verdict || "" });
            }
        } catch (error) {
            messageEl.innerHTML = '<div class="error">Connection error: ' + error.message + '</div>';
        } finally {
            analyzeBtn.disabled = false;
        }
    }

    /* ── Result Rendering ── */

    function esc(str) {
        if (!str) return "";
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function getConfidenceScore(item) {
        if (item.confidence && typeof item.confidence === "number") {
            return Math.min(Math.max(item.confidence, 60), 97);
        }
        var score = 80;
        var perf = item.performance;
        if (perf && typeof perf === "object" && Object.keys(perf).length) {
            score += Math.min(Object.keys(perf).length, 3);
        }
        var benefits = item.key_benefits;
        if (Array.isArray(benefits)) {
            score += Math.min(benefits.length, 5);
        }
        var sp = item.selling_points;
        if (Array.isArray(sp)) {
            score += Math.min(sp.length, 3);
        }
        var uc = item.use_cases;
        if (Array.isArray(uc) && uc.length) { score += 1; }
        if (item.technical_analysis) { score += 1; }
        if (item.category_specific && Object.keys(item.category_specific).length) { score += 2; }
        return Math.min(score, 95);
    }

    function extractTags(item) {
        var tags = [];
        var category = (item.category || "").toLowerCase();

        var catLabels = {
            fragrance: "Premium Scent",
            electronics: "Tech Product",
            fashion: "Fashion Item",
            beauty: "Beauty Essential",
            home: "Home & Living",
            general: "Everyday Product"
        };
        tags.push(catLabels[category] || "Product");

        var benefits = item.key_benefits || [];
        var selling = item.selling_points || [];
        var pool = benefits.concat(selling);

        var tagMap = [
            { words: ["durable", "long-lasting", "sturdy", "robust", "quality"], label: "Durable" },
            { words: ["luxury", "premium", "high-end", "exclusive"], label: "Luxury" },
            { words: ["daily", "everyday", "routine", "regular"], label: "Best for daily use" },
            { words: ["value", "affordable", "budget", "cost"], label: "Great Value" },
            { words: ["portable", "compact", "lightweight", "travel"], label: "Portable" },
            { words: ["eco", "sustainable", "natural", "organic"], label: "Eco-Friendly" },
            { words: ["innovative", "smart", "advanced", "technology"], label: "Innovative" },
            { words: ["comfort", "comfortable", "soft", "gentle"], label: "Comfortable" },
            { words: ["versatile", "multi", "flexible", "adaptable"], label: "Versatile" }
        ];

        var poolStr = pool.join(" ").toLowerCase();
        for (var i = 0; i < tagMap.length && tags.length < 5; i++) {
            var match = tagMap[i];
            for (var j = 0; j < match.words.length; j++) {
                if (poolStr.indexOf(match.words[j]) !== -1) {
                    tags.push(match.label);
                    break;
                }
            }
        }

        var fillers = ["Verified", "Full Report", "Detailed"];
        for (var k = 0; k < fillers.length && tags.length < 3; k++) {
            tags.push(fillers[k]);
        }

        return tags.slice(0, 5);
    }

    function formatMaterial(material) {
        if (Array.isArray(material)) return material.join(", ");
        return String(material || "");
    }

    function buildScoreRing(score) {
        var circumference = 2 * Math.PI * 26;
        var offset = circumference - (score / 100) * circumference;
        var color = score >= 90 ? "#10b981" : score >= 85 ? "#3b82f6" : "#f59e0b";
        return (
            '<div class="ai-score">' +
                '<svg viewBox="0 0 64 64">' +
                    '<circle class="score-track" cx="32" cy="32" r="26" />' +
                    '<circle class="score-fill" cx="32" cy="32" r="26" stroke="' + color + '" stroke-dasharray="' + circumference + '" stroke-dashoffset="' + offset + '" transform="rotate(-90 32 32)" />' +
                    '<text class="score-text" x="32" y="36" text-anchor="middle">' + score + '</text>' +
                '</svg>' +
                '<div class="score-label">Confidence</div>' +
            '</div>'
        );
    }

    function sectionDivider(label) {
        return '<div class="section-divider">' + label + '</div>';
    }

    /* ── Main Result Card Builder ── */

    function buildResultCard(item) {
        var category = (item.category || "").toLowerCase();
        var cs = item.category_specific || {};

        /* Category badge */
        var badgeColors = {
            fragrance:   { bg: "#d97706", icon: "\uD83C\uDF38" },
            electronics: { bg: "#2563eb", icon: "\uD83D\uDCBB" },
            fashion:     { bg: "#db2777", icon: "\uD83D\uDC57" },
            beauty:      { bg: "#9333ea", icon: "\u2728" },
            home:        { bg: "#059669", icon: "\uD83C\uDFE0" },
            general:     { bg: "#64748b", icon: "\uD83D\uDCE6" }
        };
        var badge = badgeColors[category] || badgeColors.general;
        var categoryBadge = '<span class="badge" style="background:' + badge.bg + ';">' + badge.icon + " " + esc(item.category || "Product") + "</span>";

        /* Confidence Score */
        var confidenceScore = getConfidenceScore(item);

        /* Smart Tags */
        var tags = extractTags(item);
        var tagsHtml = '<div class="tags-row">' + tags.map(function (t) { return '<span class="smart-tag">' + esc(t) + '</span>'; }).join("") + '</div>';

        /* ── Verdict Banner ── */
        var verdict = (item.verdict || "DON'T BUILD").toUpperCase();
        var isBuild = verdict === "BUILD";
        var isConditional = verdict.indexOf("CONDITION") !== -1;
        var isDontBuild = !isBuild && !isConditional;
        var verdictType = isBuild ? "build" : (isConditional ? "conditional" : "dont");
        var verdictColor = isBuild ? "#059669" : (isConditional ? "#d97706" : "#dc2626");
        var verdictIcon = isBuild ? "\u2705" : (isConditional ? "\u26A0\uFE0F" : "\u274C");
        var verdictLabel = isBuild ? "BUILD" : (isConditional ? "BUILD WITH CONDITIONS" : "DON\u2019T BUILD");
        var verdictArrow = isBuild ? "\u25B2" : (isConditional ? "\u25C6" : "\u25BC");

        /* Opportunity Summary + Biggest Risk */
        var opportunitySummary = item.opportunity_summary || "";
        var biggestRisk = item.biggest_risk || "";
        var opportunityRiskHtml = "";
        if (opportunitySummary || biggestRisk) {
            opportunityRiskHtml =
                '<div class="verdict-grid">' +
                    (opportunitySummary ? '<div class="verdict-insight verdict-insight--opportunity">' +
                        '<div class="verdict-insight-label verdict-insight-label--opportunity">\uD83D\uDCA1 Opportunity</div>' +
                        '<p>' + esc(opportunitySummary) + '</p>' +
                    '</div>' : '') +
                    (biggestRisk ? '<div class="verdict-insight verdict-insight--risk">' +
                        '<div class="verdict-insight-label verdict-insight-label--risk">\u26A0\uFE0F Biggest Risk</div>' +
                        '<p>' + esc(biggestRisk) + '</p>' +
                    '</div>' : '') +
                '</div>';
        }

        /* Required Conditions (BUILD WITH CONDITIONS only) */
        var requiredConditions = Array.isArray(item.required_conditions) && item.required_conditions.length ? item.required_conditions.slice(0, 3) : [];
        var conditionsHtml = "";
        if (isConditional && requiredConditions.length) {
            conditionsHtml =
                '<div class="verdict-conditions">' +
                    '<div class="verdict-conditions-label">\uD83D\uDD12 Required Conditions</div>' +
                    '<ul>' +
                        requiredConditions.map(function (c, i) {
                            return '<li>' +
                                '<span>' + (i + 1) + '.</span>' +
                                '<span>' + esc(c) + '</span>' +
                            '</li>';
                        }).join("") +
                    '</ul>' +
                '</div>';
        }

        /* Top 3 Reasons */
        var topReasons = Array.isArray(item.top_reasons) && item.top_reasons.length ? item.top_reasons.slice(0, 3) : [
            "FRONTEND FALLBACK 1",
            "FRONTEND FALLBACK 2",
            "FRONTEND FALLBACK 3"
        ];
        var topReasonsHtml =
            '<div class="verdict-reasons">' +
                '<div class="verdict-reasons-label" style="color:' + verdictColor + ';">Top 3 Reasons</div>' +
                '<ul>' +
                    topReasons.map(function (r) {
                        return '<li>' +
                            '<span style="color:' + verdictColor + ';">' + verdictArrow + '</span>' +
                            '<span>' + esc(r) + '</span>' +
                        '</li>';
                    }).join("") +
                '</ul>' +
            '</div>';

        /* Verdict Reasoning */
        var verdictReasoning = item.verdict_reasoning || "Insufficient data to justify a BUILD. No clear competitive moat, demand validation, or margin evidence was found.";
        var reasoningHtml =
            '<div class="verdict-why">' +
                '<div class="verdict-why-label">Why This Verdict</div>' +
                '<p>' + esc(verdictReasoning) + '</p>' +
            '</div>';

        /* Next Actions */
        var nextActions = Array.isArray(item.next_actions) && item.next_actions.length ? item.next_actions.slice(0, 3) : [
            "Define the exact target customer and validate demand with 30+ survey responses",
            "Identify the top 3 direct competitors and document how this product is concretely different",
            "Calculate landed cost per unit and target retail price to confirm 50%+ margins"
        ];
        var actionIcons = ["\u0031\uFE0F\u20E3", "\u0032\uFE0F\u20E3", "\u0033\uFE0F\u20E3"];
        var nextActionsHtml =
            '<div class="verdict-actions">' +
                '<div class="verdict-actions-label" style="color:' + verdictColor + ';">\uD83D\uDE80 What Should I Do Next?</div>' +
                nextActions.map(function (a, i) {
                    return '<div class="verdict-action-item verdict-action-item--' + verdictType + '">' +
                        '<span>' + (actionIcons[i] || "\u27A1\uFE0F") + '</span>' +
                        '<span>' + esc(a) + '</span>' +
                    '</div>';
                }).join("") +
            '</div>';

        var verdictHtml =
            '<div class="verdict-banner verdict-banner--' + verdictType + '">' +
                '<div class="verdict-icon">' + verdictIcon + '</div>' +
                '<div class="verdict-label verdict-label--' + verdictType + '">VERDICT: ' + verdictLabel + '</div>' +
                '<div class="verdict-confidence">' + (item.confidence || 70) + '% Confidence</div>' +
                opportunityRiskHtml +
                conditionsHtml +
                topReasonsHtml +
                reasoningHtml +
                nextActionsHtml +
            '</div>';

        /* ── Product Header ── */
        var headerHtml =
            '<div class="product-header">' +
                '<div class="ph-image">' + badge.icon + '</div>' +
                '<div class="ph-info">' +
                    '<div class="ph-top-row">' +
                        '<h2 class="product-title">' + esc(item.title || "") + '</h2>' +
                        categoryBadge +
                    '</div>' +
                    (item.short_summary ? '<p class="summary-text">' + esc(item.short_summary) + '</p>' : '') +
                    tagsHtml +
                '</div>' +
                buildScoreRing(confidenceScore) +
            '</div>';

        /* ── Technical Analysis Card ── */
        var analysisHtml = "";
        if (item.technical_analysis) {
            analysisHtml =
                '<div class="card card--analysis">' +
                    '<div class="card-header"><div class="card-icon">\uD83D\uDD2C</div><h4>Technical Analysis</h4></div>' +
                    '<p>' + esc(item.technical_analysis) + '</p>' +
                '</div>';
        }

        /* ── Target Audience Card ── */
        var audienceHtml = "";
        if (item.target_audience) {
            audienceHtml =
                '<div class="card card--audience">' +
                    '<div class="card-header"><div class="card-icon">\uD83C\uDFAF</div><h4>Target Audience</h4></div>' +
                    '<p>' + esc(item.target_audience) + '</p>' +
                '</div>';
        }

        /* ── Key Benefits Card ── */
        var benefitsHtml = "";
        if (Array.isArray(item.key_benefits) && item.key_benefits.length) {
            var benefitsList = item.key_benefits.map(function (b) { return "<li>" + esc(b) + "</li>"; }).join("");
            benefitsHtml =
                '<div class="card card--benefits">' +
                    '<div class="card-header"><div class="card-icon">\u2705</div><h4>Key Benefits</h4></div>' +
                    '<ul>' + benefitsList + '</ul>' +
                '</div>';
        }

        /* ── Selling Points Card ── */
        var sellingHtml = "";
        if (Array.isArray(item.selling_points) && item.selling_points.length) {
            var sellingList = item.selling_points.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("");
            sellingHtml =
                '<div class="card card--selling">' +
                    '<div class="card-header"><div class="card-icon">\uD83D\uDCA1</div><h4>Selling Points</h4></div>' +
                    '<ul>' + sellingList + '</ul>' +
                '</div>';
        }

        /* ── Use Cases Card ── */
        var useCasesHtml = "";
        if (Array.isArray(item.use_cases) && item.use_cases.length) {
            useCasesHtml =
                '<div class="card card--usecases">' +
                    '<div class="card-header"><div class="card-icon">\uD83D\uDCCB</div><h4>Use Cases</h4></div>' +
                    '<ul class="tag-list">' + item.use_cases.map(function (u) { return "<li>" + esc(u) + "</li>"; }).join("") + '</ul>' +
                '</div>';
        }

        /* ── Performance Card ── */
        var performanceHtml = "";
        if (item.performance && typeof item.performance === "object" && Object.keys(item.performance).length) {
            var perfRows = Object.entries(item.performance).map(function (pair) {
                return '<div class="detail-chip"><span class="chip-label">' + esc(pair[0]) + "</span>" + esc(String(pair[1])) + "</div>";
            }).join("");
            performanceHtml =
                '<div class="card card--performance">' +
                    '<div class="card-header"><div class="card-icon">\u26A1</div><h4>Performance</h4></div>' +
                    '<div class="detail-row">' + perfRows + '</div>' +
                '</div>';
        }

        /* ── Specifications Card ── */
        var specsHtml = "";
        if (item.specifications && typeof item.specifications === "object" && Object.keys(item.specifications).length) {
            var specRows = Object.entries(item.specifications).map(function (pair) {
                return '<div class="detail-chip"><span class="chip-label">' + esc(pair[0]) + "</span>" + esc(String(pair[1])) + "</div>";
            }).join("");
            specsHtml =
                '<div class="card card--specs">' +
                    '<div class="card-header"><div class="card-icon">\u2699\uFE0F</div><h4>Specifications</h4></div>' +
                    '<div class="detail-row">' + specRows + '</div>' +
                '</div>';
        }

        /* ── Category-specific sections ── */
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

        /* ── Description Card ── */
        var descriptionHtml = "";
        if (item.long_description) {
            descriptionHtml =
                '<div class="card card--description">' +
                    '<div class="card-header"><div class="card-icon">\uD83D\uDCDD</div><h4>Full Description</h4></div>' +
                    '<div class="description-html">' + item.long_description + '</div>' +
                '</div>';
        }

        /* ── SEO Card ── */
        var seoHtml = "";
        if (item.meta_description || item.keywords) {
            seoHtml =
                '<div class="card card--seo">' +
                    '<div class="card-header"><div class="card-icon">\uD83D\uDCC8</div><h4>SEO Optimization</h4></div>' +
                    (item.meta_description ? '<div style="margin-bottom:12px;"><strong class="chip-label">Meta Description</strong><p style="margin:6px 0 0;">' + esc(item.meta_description) + '</p></div>' : '') +
                    (item.keywords ? '<div><strong class="chip-label">Keywords</strong><p style="margin:6px 0 0;">' + esc(item.keywords) + '</p></div>' : '') +
                '</div>';
        }

        /* ── Assemble ── */
        var secondaryDivider =
            '<div class="detail-break">' +
                '<span>Detailed Breakdown</span>' +
            '</div>';
        return (
            verdictHtml +
            headerHtml +
            secondaryDivider +
            sectionDivider("\uD83D\uDD0D Market Assessment") +
            analysisHtml +
            audienceHtml +
            sectionDivider("\u2705 Key Strengths") +
            benefitsHtml +
            sellingHtml +
            useCasesHtml +
            sectionDivider("\u26A1 Performance & Specs") +
            performanceHtml +
            specsHtml +
            (categoryHtml ? sectionDivider("\uD83C\uDFF7\uFE0F Category Details") + categoryHtml : "") +
            sectionDivider("\uD83D\uDCDD Content & SEO") +
            descriptionHtml +
            seoHtml
        );
    }

    /* ── Fragrance category section ── */
    function buildFragranceSection(cs) {
        var html = '<div class="card fragrance-box">' +
            '<div class="card-header"><div class="card-icon">\uD83C\uDF38</div><h4>Fragrance Profile</h4></div>';

        if (cs.scent_family) {
            html += '<div style="margin-bottom:12px;"><span class="scent-family-value">' + esc(cs.scent_family) + "</span></div>";
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
            html += '<div style="margin-top:10px;font-size:13px;"><strong style="color:#92400e;">Best Season:</strong> ' + esc(cs.best_season) + "</div>";
        }
        if (Array.isArray(cs.best_occasions) && cs.best_occasions.length) {
            html += '<div style="margin-top:8px;"><strong style="font-size:13px;color:#92400e;">Best Occasions</strong><ul class="tag-list">' + cs.best_occasions.map(function (o) { return "<li>" + esc(o) + "</li>"; }).join("") + "</ul></div>";
        }

        html += "</div>";
        return html;
    }

    /* ── Electronics category section ── */
    function buildElectronicsSection(cs) {
        var html = '<div class="card" style="border-left:3px solid #3b82f6;">' +
            '<div class="card-header"><div class="card-icon" style="background:#eff6ff;color:#3b82f6;">\uD83D\uDD0C</div><h4>Electronics Details</h4></div>';
        var fields = [
            { key: "battery", label: "Battery" },
            { key: "connectivity", label: "Connectivity" },
            { key: "compatibility", label: "Compatibility" },
            { key: "build_quality", label: "Build Quality" },
            { key: "performance_level", label: "Performance Level" }
        ];
        fields.forEach(function (f) {
            if (cs[f.key]) {
                html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#1e40af;">' + esc(f.label) + ':</strong> <span style="color:#475569;">' + esc(cs[f.key]) + '</span></div>';
            }
        });
        html += "</div>";
        return html;
    }

    /* ── Fashion category section ── */
    function buildFashionSection(cs) {
        var html = '<div class="card" style="border-left:3px solid #ec4899;">' +
            '<div class="card-header"><div class="card-icon" style="background:#fdf2f8;color:#ec4899;">\uD83D\uDC57</div><h4>Fashion Details</h4></div>';
        if (cs.style) html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#9d174d;">Style:</strong> <span style="color:#475569;">' + esc(cs.style) + '</span></div>';
        if (cs.material) html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#9d174d;">Material:</strong> <span style="color:#475569;">' + esc(formatMaterial(cs.material)) + '</span></div>';
        if (cs.fit) html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#9d174d;">Fit:</strong> <span style="color:#475569;">' + esc(cs.fit) + '</span></div>';
        if (Array.isArray(cs.occasion) && cs.occasion.length) {
            html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#9d174d;">Occasion:</strong> <span style="color:#475569;">' + esc(cs.occasion.join(", ")) + '</span></div>';
        } else if (typeof cs.occasion === "string" && cs.occasion) {
            html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#9d174d;">Occasion:</strong> <span style="color:#475569;">' + esc(cs.occasion) + '</span></div>';
        }
        if (cs.season) html += '<div style="font-size:14px;line-height:1.6;"><strong style="color:#9d174d;">Season:</strong> <span style="color:#475569;">' + esc(cs.season) + '</span></div>';
        html += "</div>";
        return html;
    }

    /* ── Beauty category section ── */
    function buildBeautySection(cs) {
        var html = '<div class="card" style="border-left:3px solid #a855f7;">' +
            '<div class="card-header"><div class="card-icon" style="background:#faf5ff;color:#a855f7;">\u2728</div><h4>Beauty Details</h4></div>';
        if (cs.skin_type) html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#7e22ce;">Skin Type:</strong> <span style="color:#475569;">' + esc(cs.skin_type) + '</span></div>';
        if (Array.isArray(cs.key_ingredients) && cs.key_ingredients.length) {
            html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#7e22ce;">Key Ingredients:</strong> <span style="color:#475569;">' + esc(cs.key_ingredients.join(", ")) + '</span></div>';
        }
        if (cs.texture) html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#7e22ce;">Texture:</strong> <span style="color:#475569;">' + esc(cs.texture) + '</span></div>';
        if (cs.routine_fit) html += '<div style="font-size:14px;line-height:1.6;"><strong style="color:#7e22ce;">Routine Fit:</strong> <span style="color:#475569;">' + esc(cs.routine_fit) + '</span></div>';
        html += "</div>";
        return html;
    }

    /* ── Home category section ── */
    function buildHomeSection(cs) {
        var html = '<div class="card" style="border-left:3px solid #10b981;">' +
            '<div class="card-header"><div class="card-icon" style="background:#ecfdf5;color:#10b981;">\uD83C\uDFE0</div><h4>Home & Living Details</h4></div>';
        if (cs.room_fit) html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#065f46;">Room Fit:</strong> <span style="color:#475569;">' + esc(cs.room_fit) + '</span></div>';
        if (cs.material) html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#065f46;">Material:</strong> <span style="color:#475569;">' + esc(cs.material) + '</span></div>';
        if (cs.practicality) html += '<div style="margin-bottom:10px;font-size:14px;line-height:1.6;"><strong style="color:#065f46;">Practicality:</strong> <span style="color:#475569;">' + esc(cs.practicality) + '</span></div>';
        if (cs.maintenance) html += '<div style="font-size:14px;line-height:1.6;"><strong style="color:#065f46;">Maintenance:</strong> <span style="color:#475569;">' + esc(cs.maintenance) + '</span></div>';
        html += "</div>";
        return html;
    }

    /* ── Save Analysis ── */

    function buildSaveButton() {
        return (
            '<div style="text-align:center;margin:20px 0;">' +
                '<button id="saveAnalysisBtn" style="padding:12px 32px;border-radius:10px;border:none;font-size:15px;font-weight:600;background:linear-gradient(135deg,#059669,#10b981);color:#fff;cursor:pointer;font-family:inherit;transition:transform 0.15s,box-shadow 0.15s;">' +
                    '\uD83D\uDCBE Save Decision' +
                '</button>' +
                '<div id="saveMessage" style="margin-top:10px;font-size:14px;"></div>' +
            '</div>'
        );
    }

    document.addEventListener("click", function (e) {
        if (e.target && e.target.id === "saveAnalysisBtn") {
            saveAnalysis();
        }
    });

    async function saveAnalysis() {
        var btn = document.getElementById("saveAnalysisBtn");
        var msg = document.getElementById("saveMessage");
        if (!btn || !lastAnalysisResult) return;

        btn.disabled = true;
        btn.textContent = "Saving...";

        try {
            var resp = await fetch("/api/save-analysis", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + authToken
                },
                body: JSON.stringify({ idea: lastAnalysisIdea, result: lastAnalysisResult })
            });
            var data = await resp.json();
            if (!resp.ok) {
                msg.innerHTML = '<span style="color:#dc2626;">' + esc(data.error || "Failed to save") + '</span>';
                btn.disabled = false;
                btn.textContent = "\uD83D\uDCBE Save Decision";
                return;
            }
            msg.innerHTML = '<span style="color:#059669;">\u2705 Saved! View it on your <a href="/dashboard" style="color:#4f46e5;font-weight:600;">Dashboard</a></span>';
            btn.style.display = "none";
            fetchUsage();
        } catch (err) {
            msg.innerHTML = '<span style="color:#dc2626;">Connection error</span>';
            btn.disabled = false;
            btn.textContent = "\uD83D\uDCBE Save Decision";
        }
    }

    /* ── Paywall Handlers ── */

    function showPaywallModal() {
        if (paywallOverlay) {
            paywallOverlay.style.display = "flex";
            if (window.trackEvent) {
                window.trackEvent("paywall_view", {
                    user_state: "free",
                    source: "analyze"
                });
            }
        }
    }

    function hidePaywallModal() {
        if (paywallOverlay) paywallOverlay.style.display = "none";
    }

    if (paywallClose) {
        paywallClose.addEventListener("click", hidePaywallModal);
    }

    if (paywallOverlay) {
        paywallOverlay.addEventListener("click", function (e) {
            if (e.target === paywallOverlay) hidePaywallModal();
        });
    }

    /* Track paywall CTA clicks */
    document.addEventListener("click", function (e) {
        if (e.target && e.target.classList.contains("paywall-cta")) {
            if (window.trackEvent) {
                window.trackEvent("cta_primary_click", {
                    user_state: (window._veltrixCtx && window._veltrixCtx.state) || "unknown",
                    source: "paywall"
                });
            }
        }
    });
});
