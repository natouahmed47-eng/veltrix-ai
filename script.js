document.addEventListener("DOMContentLoaded", function () {
    var analyzeBtn = document.getElementById("analyzeBtn");
    var productInput = document.getElementById("productIdea");

    /* ── Auth State ── */
    var authToken = localStorage.getItem("veltrix_token") || "";
    var authUsername = localStorage.getItem("veltrix_username") || "";
    var lastAnalysisIdea = "";
    var lastAnalysisResult = null;

    function updateAuthUI() {
        var authArea = document.getElementById("authArea");
        var userArea = document.getElementById("userArea");
        if (authToken && authUsername) {
            authArea.style.display = "none";
            userArea.style.display = "flex";
            document.getElementById("usernameDisplay").textContent = authUsername;
            fetchUsage();
        } else {
            authArea.style.display = "flex";
            userArea.style.display = "none";
            /* Show pricing section for logged-out visitors */
            var pricingSection = document.getElementById("pricingSection");
            var pricingGrid = document.getElementById("pricingGrid");
            var proActive = document.getElementById("pricingProActive");
            var freeCta = document.getElementById("pricingFreeCta");
            if (pricingSection) {
                pricingSection.style.display = "block";
                if (pricingGrid) pricingGrid.style.display = "block";
                if (proActive) proActive.style.display = "none";
                if (freeCta) freeCta.textContent = "Get Started Free";
            }
        }
    }

    function fetchUsage() {
        fetch("/api/me", { headers: { "Authorization": "Bearer " + authToken } })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.analysis_count !== undefined) {
                    var label = d.analysis_count + "/" + d.analysis_limit + " analyses";
                    if (d.plan === "pro") {
                        label = "Pro · " + label;
                    }
                    document.getElementById("usageInfo").textContent = label;
                }
                /* ── Update pricing section visibility ── */
                var pricingSection = document.getElementById("pricingSection");
                var pricingGrid = document.getElementById("pricingGrid");
                var proActive = document.getElementById("pricingProActive");
                var freeCta = document.getElementById("pricingFreeCta");
                if (pricingSection) {
                    pricingSection.style.display = "block";
                    if (d.plan === "pro") {
                        /* Pro user: hide comparison grid, show active message */
                        if (pricingGrid) pricingGrid.style.display = "none";
                        if (proActive) proActive.style.display = "block";
                    } else {
                        /* Free user: show comparison grid */
                        if (pricingGrid) pricingGrid.style.display = "block";
                        if (proActive) proActive.style.display = "none";
                        if (freeCta) freeCta.textContent = "Your Current Plan";
                    }
                }
            })
            .catch(function () { /* ignore */ });
    }

    function logout() {
        authToken = "";
        authUsername = "";
        localStorage.removeItem("veltrix_token");
        localStorage.removeItem("veltrix_username");
        updateAuthUI();
    }

    /* ── Auth Modal ── */
    var authModal = document.getElementById("authModal");
    var authMode = "login"; // "login" or "register"

    function openAuthModal(mode) {
        authMode = mode;
        document.getElementById("authModalTitle").textContent = mode === "login" ? "Log In" : "Create Account";
        document.getElementById("authSubmitBtn").textContent = mode === "login" ? "Log In" : "Sign Up";
        document.getElementById("authSwitch").innerHTML = mode === "login"
            ? 'Don\'t have an account? <a href="#" id="switchToRegister" style="color:#4f46e5;font-weight:600;">Sign Up</a>'
            : 'Already have an account? <a href="#" id="switchToLogin" style="color:#4f46e5;font-weight:600;">Log In</a>';
        document.getElementById("authUsername").value = "";
        document.getElementById("authPassword").value = "";
        document.getElementById("authError").style.display = "none";
        authModal.style.display = "flex";

        setTimeout(function () {
            var switchLink = document.getElementById("switchToRegister") || document.getElementById("switchToLogin");
            if (switchLink) {
                switchLink.addEventListener("click", function (e) {
                    e.preventDefault();
                    openAuthModal(mode === "login" ? "register" : "login");
                });
            }
        }, 0);
    }

    document.getElementById("showLoginBtn").addEventListener("click", function () { openAuthModal("login"); });
    document.getElementById("showRegisterBtn").addEventListener("click", function () { openAuthModal("register"); });
    document.getElementById("closeAuthModal").addEventListener("click", function () { authModal.style.display = "none"; });
    document.getElementById("logoutBtn").addEventListener("click", logout);

    authModal.addEventListener("click", function (e) {
        if (e.target === authModal) authModal.style.display = "none";
    });

    document.getElementById("authSubmitBtn").addEventListener("click", async function () {
        var username = document.getElementById("authUsername").value.trim();
        var password = document.getElementById("authPassword").value;
        var errorEl = document.getElementById("authError");

        if (!username || !password) {
            errorEl.textContent = "Please fill in both fields.";
            errorEl.style.display = "block";
            return;
        }

        var url = authMode === "login" ? "/api/login" : "/api/register";
        try {
            var resp = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: username, password: password })
            });
            var data = await resp.json();
            if (!resp.ok) {
                errorEl.textContent = data.error || "Something went wrong";
                errorEl.style.display = "block";
                return;
            }
            authToken = data.token;
            authUsername = data.username;
            localStorage.setItem("veltrix_token", authToken);
            localStorage.setItem("veltrix_username", authUsername);
            authModal.style.display = "none";
            updateAuthUI();
        } catch (err) {
            errorEl.textContent = "Connection error";
            errorEl.style.display = "block";
        }
    });

    document.getElementById("authPassword").addEventListener("keydown", function (e) {
        if (e.key === "Enter") document.getElementById("authSubmitBtn").click();
    });

    updateAuthUI();

    /* ── Analyze Product ── */
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

        messageEl.innerHTML = "\u23F3 Analyzing, please wait...";
        resultsEl.innerHTML = "";
        analyzeBtn.disabled = true;

        var headers = { "Content-Type": "application/json" };
        if (authToken) {
            headers["Authorization"] = "Bearer " + authToken;
        }

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
                console.error("Non-JSON response:", response.status, rawText);
                analyzeBtn.disabled = false;
                return;
            }

            if (!response.ok) {
                var errMsg = data.message || data.error || "Analysis failed";
                if (data.trace) {
                    console.error("Backend trace:", data.trace);
                }
                messageEl.innerHTML = '<div class="error">' + errMsg + '</div>';
                console.error("API error:", data);
                analyzeBtn.disabled = false;
                return;
            }

            lastAnalysisIdea = idea;
            lastAnalysisResult = data;

            messageEl.innerHTML = '<div class="success">\u2705 Analysis completed successfully!</div>';
            resultsEl.innerHTML = buildResultCard(data) + buildSaveButton();
        } catch (error) {
            messageEl.innerHTML = '<div class="error">Connection error: ' + error.message + '</div>';
            console.error("Fetch error:", error);
        } finally {
            analyzeBtn.disabled = false;
        }
    }

    /* ── Save Button ── */
    function buildSaveButton() {
        if (!authToken) {
            return '<div style="text-align:center;margin:20px 0;"><span style="color:#64748b;font-size:14px;"><a href="#" id="loginToSave" style="color:#4f46e5;font-weight:600;">Log in</a> to save this analysis to your dashboard.</span></div>';
        }
        return (
            '<div style="text-align:center;margin:20px 0;">' +
                '<button id="saveAnalysisBtn" style="padding:12px 32px;border-radius:10px;border:none;font-size:15px;font-weight:600;background:linear-gradient(135deg,#059669,#10b981);color:#fff;cursor:pointer;font-family:inherit;transition:transform 0.15s,box-shadow 0.15s;">' +
                    '\uD83D\uDCBE Save Analysis' +
                '</button>' +
                '<div id="saveMessage" style="margin-top:10px;font-size:14px;"></div>' +
            '</div>'
        );
    }

    document.addEventListener("click", function (e) {
        if (e.target && e.target.id === "loginToSave") {
            e.preventDefault();
            openAuthModal("login");
        }
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
                    "Authorization": "Bearer " + authToken,
                },
                body: JSON.stringify({ idea: lastAnalysisIdea, result: lastAnalysisResult })
            });
            var data = await resp.json();
            if (!resp.ok) {
                msg.innerHTML = '<span style="color:#dc2626;">' + esc(data.error || "Failed to save") + '</span>';
                btn.disabled = false;
                btn.textContent = "\uD83D\uDCBE Save Analysis";
                return;
            }
            msg.innerHTML = '<span style="color:#059669;">\u2705 Saved! View it on your <a href="/dashboard" style="color:#4f46e5;font-weight:600;">Dashboard</a></span>';
            btn.style.display = "none";
            fetchUsage();
        } catch (err) {
            msg.innerHTML = '<span style="color:#dc2626;">Connection error</span>';
            btn.disabled = false;
            btn.textContent = "\uD83D\uDCBE Save Analysis";
        }
    }

    /* ── Helpers ── */

    function esc(str) {
        if (!str) return "";
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    /**
     * Calculate an AI confidence score (80-95) from the richness of the data.
     */
    function calculateAIScore(item) {
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

    /**
     * Extract 3-5 smart tags from the product data to show as badges.
     */
    function extractTags(item) {
        var tags = [];
        var category = (item.category || "").toLowerCase();

        /* Category-based tags */
        var catLabels = {
            fragrance: "Premium Scent",
            electronics: "Tech Product",
            fashion: "Fashion Item",
            beauty: "Beauty Essential",
            home: "Home & Living",
            general: "Everyday Product"
        };
        tags.push(catLabels[category] || "Product");

        /* Extract from benefits */
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

        /* Ensure at least 3 tags */
        var fillers = ["AI Analyzed", "Full Report", "Detailed"];
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
                '<div class="score-label">AI Score</div>' +
            '</div>'
        );
    }

    function sectionDivider(label) {
        return '<div class="section-divider">' + label + '</div>';
    }

    /* ── Main build function ── */

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

        /* AI Score */
        var aiScore = calculateAIScore(item);

        /* Smart Tags */
        var tags = extractTags(item);
        var tagsHtml = '<div class="tags-row">' + tags.map(function (t) { return '<span class="smart-tag">' + esc(t) + '</span>'; }).join("") + '</div>';

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
                buildScoreRing(aiScore) +
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
                    (item.meta_description ? '<div style="margin-bottom:8px;"><strong style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.05em;">Meta Description</strong><p style="margin:4px 0 0;">' + esc(item.meta_description) + '</p></div>' : '') +
                    (item.keywords ? '<div><strong style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.05em;">Keywords</strong><p style="margin:4px 0 0;">' + esc(item.keywords) + '</p></div>' : '') +
                '</div>';
        }

        /* ── Assemble ── */
        return (
            headerHtml +
            sectionDivider("\uD83D\uDD0D AI Analysis") +
            analysisHtml +
            audienceHtml +
            sectionDivider("\u2705 Product Intelligence") +
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
        var html = '<div class="card" style="border-left:3px solid #2563eb;">' +
            '<div class="card-header"><div class="card-icon" style="background:#dbeafe;">\uD83D\uDD0C</div><h4>Electronics Details</h4></div>';
        var fields = [
            { key: "battery", label: "Battery" },
            { key: "connectivity", label: "Connectivity" },
            { key: "compatibility", label: "Compatibility" },
            { key: "build_quality", label: "Build Quality" },
            { key: "performance_level", label: "Performance Level" }
        ];
        fields.forEach(function (f) {
            if (cs[f.key]) {
                html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#1e40af;">' + esc(f.label) + ':</strong> ' + esc(cs[f.key]) + "</div>";
            }
        });
        html += "</div>";
        return html;
    }

    /* ── Fashion category section ── */
    function buildFashionSection(cs) {
        var html = '<div class="card" style="border-left:3px solid #db2777;">' +
            '<div class="card-header"><div class="card-icon" style="background:#fce7f3;">\uD83D\uDC57</div><h4>Fashion Details</h4></div>';
        if (cs.style) html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#9d174d;">Style:</strong> ' + esc(cs.style) + "</div>";
        if (cs.material) html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#9d174d;">Material:</strong> ' + esc(formatMaterial(cs.material)) + "</div>";
        if (cs.fit) html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#9d174d;">Fit:</strong> ' + esc(cs.fit) + "</div>";
        if (Array.isArray(cs.occasion) && cs.occasion.length) {
            html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#9d174d;">Occasion:</strong> ' + esc(cs.occasion.join(", ")) + "</div>";
        } else if (typeof cs.occasion === "string" && cs.occasion) {
            html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#9d174d;">Occasion:</strong> ' + esc(cs.occasion) + "</div>";
        }
        if (cs.season) html += '<div style="font-size:14px;"><strong style="color:#9d174d;">Season:</strong> ' + esc(cs.season) + "</div>";
        html += "</div>";
        return html;
    }

    /* ── Beauty category section ── */
    function buildBeautySection(cs) {
        var html = '<div class="card" style="border-left:3px solid #9333ea;">' +
            '<div class="card-header"><div class="card-icon" style="background:#f3e8ff;">\u2728</div><h4>Beauty Details</h4></div>';
        if (cs.skin_type) html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#7e22ce;">Skin Type:</strong> ' + esc(cs.skin_type) + "</div>";
        if (Array.isArray(cs.key_ingredients) && cs.key_ingredients.length) {
            html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#7e22ce;">Key Ingredients:</strong> ' + esc(cs.key_ingredients.join(", ")) + "</div>";
        }
        if (cs.texture) html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#7e22ce;">Texture:</strong> ' + esc(cs.texture) + "</div>";
        if (cs.routine_fit) html += '<div style="font-size:14px;"><strong style="color:#7e22ce;">Routine Fit:</strong> ' + esc(cs.routine_fit) + "</div>";
        html += "</div>";
        return html;
    }

    /* ── Home category section ── */
    function buildHomeSection(cs) {
        var html = '<div class="card" style="border-left:3px solid #059669;">' +
            '<div class="card-header"><div class="card-icon" style="background:#d1fae5;">\uD83C\uDFE0</div><h4>Home & Living Details</h4></div>';
        if (cs.room_fit) html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#065f46;">Room Fit:</strong> ' + esc(cs.room_fit) + "</div>";
        if (cs.material) html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#065f46;">Material:</strong> ' + esc(cs.material) + "</div>";
        if (cs.practicality) html += '<div style="margin-bottom:8px;font-size:14px;"><strong style="color:#065f46;">Practicality:</strong> ' + esc(cs.practicality) + "</div>";
        if (cs.maintenance) html += '<div style="font-size:14px;"><strong style="color:#065f46;">Maintenance:</strong> ' + esc(cs.maintenance) + "</div>";
        html += "</div>";
        return html;
    }
});
/* ── PayPal Subscription Button ── */
(function() {
  /* Skip rendering PayPal button if user is already Pro */
  var token = localStorage.getItem("veltrix_token") || "";
  function renderPayPal() {
    fetch("/api/config")
      .then(function(res) { return res.json(); })
      .then(function(cfg) {
        var planId = cfg.paypal_plan_id;
        if (!planId) {
          console.warn("PayPal plan_id not configured — subscription button disabled.");
          return;
        }
        var container = document.getElementById("paypal-button-container");
        if (!container) return;
        paypal.Buttons({
          style: { label: "subscribe" },
          createSubscription: function(data, actions) {
            return actions.subscription.create({ plan_id: planId });
          },
          onApprove: function(data) {
            var t = localStorage.getItem("veltrix_token") || "";
            return fetch("/api/paypal/activate-subscription", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + t
              },
              body: JSON.stringify({ subscriptionID: data.subscriptionID })
            }).then(function(res) { return res.json(); })
              .then(function(details) {
                if (details.error) { alert("Subscription failed: " + details.error); return; }
                window.location.href = "/success";
              });
          },
          onCancel: function() {
            window.location.href = "/cancel";
          }
        }).render('#paypal-button-container');
      })
      .catch(function(err) {
        console.warn("Failed to load PayPal config:", err);
      });
  }

  if (token) {
    fetch("/api/me", { headers: { "Authorization": "Bearer " + token } })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (!d.is_pro) { renderPayPal(); }
      })
      .catch(function() { renderPayPal(); });
  } else {
    renderPayPal();
  }
})();
