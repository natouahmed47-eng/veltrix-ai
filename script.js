document.addEventListener("DOMContentLoaded", function () {
    var analyzeBtn = document.getElementById("analyzeBtn");
    var productInput = document.getElementById("productIdea");

    /* ── Auth State ── */
    var authToken = localStorage.getItem("veltrix_token") || "";
    var authUsername = localStorage.getItem("veltrix_username") || "";
    var lastAnalysisIdea = "";
    var lastAnalysisResult = null;

    /* ── A/B Experiment: upsell_v1 ── */
    var _upsellVariant = localStorage.getItem("upsell_variant");
    if (!_upsellVariant) {
        _upsellVariant = Math.random() < 0.5 ? "A" : "B";
        localStorage.setItem("upsell_variant", _upsellVariant);
    }
    window._upsellVariant = _upsellVariant;

    /**
     * applyPricingState — update pricing section on index.html based on user state.
     * Shows only 1 main message + 1 supporting line per priority logic.
     * @param {Object} ctx — result of getUserStateContext()
     */
    function applyPricingState(ctx) {
        var pricingSection = document.getElementById("pricingSection");
        var pricingGrid = document.getElementById("pricingGrid");
        var proActive = document.getElementById("pricingProActive");
        var freeCta = document.getElementById("pricingFreeCta");
        var stateMsg = document.getElementById("pricingStateMsg");

        if (!pricingSection) return;

        /* Store context globally for paywall check */
        window._veltrixCtx = ctx;

        /* ── A/B variant override (skip Pro users) ── */
        if (window._upsellVariant === "B" && ctx.state !== "pro_active") {
            ctx.cta = "Upgrade to Pro Now";
            ctx.supportingLine = (ctx.supportingLine || "") + " \u00b7 Most users upgrade after hitting their limit";
        }

        pricingSection.style.display = "block";

        if (ctx.state === "pro_active") {
            /* Pro user: hide comparison grid, show active message */
            if (pricingGrid) pricingGrid.style.display = "none";
            if (proActive) proActive.style.display = "block";
            if (stateMsg) stateMsg.style.display = "none";
        } else {
            if (pricingGrid) pricingGrid.style.display = "block";
            if (proActive) proActive.style.display = "none";
            if (freeCta) {
                freeCta.textContent = ctx.state === "logged_out"
                    ? "Get Started Free"
                    : "Your Current Plan";
            }

            /* Simplified message banner: 1 main message + 1 supporting line only */
            if (stateMsg) {
                if (ctx.state === "logged_out") {
                    stateMsg.style.display = "none";
                } else {
                    stateMsg.style.display = "block";
                    var msgHtml = '<span class="psm-text">' + escHtml(ctx.message) + '</span>';

                    /* Supporting line */
                    if (ctx.supportingLine) {
                        var supportCls = ctx.atLimit ? "psm-pressure-critical" : (ctx.nearLimit ? "psm-pressure-warn" : "");
                        msgHtml += '<span class="psm-benefit ' + supportCls + '">' + escHtml(ctx.supportingLine) + '</span>';
                    }

                    /* Progress bar for free users */
                    if (ctx.state === "free" && ctx.analysisLimit > 0) {
                        var pct = Math.min(Math.round((ctx.analysisCount / ctx.analysisLimit) * 100), 100);
                        var barCls = pct >= 100 ? "progress-critical" : (pct >= 80 ? "progress-warn" : "");
                        msgHtml += '<div class="usage-progress-wrap">' +
                            '<div class="usage-progress-bar"><div class="usage-progress-fill ' + barCls + '" style="width:' + pct + '%"></div></div>' +
                            '<span class="usage-progress-label">' + ctx.analysisCount + ' / ' + ctx.analysisLimit + ' verdicts used</span>' +
                            '</div>';
                    }

                    stateMsg.innerHTML = msgHtml;
                    stateMsg.className = "pricing-state-msg psm-" + ctx.state;
                }
            }
        }

        /* Track upsell view */
        if (ctx.showPricing && window.trackEvent) {
            window.trackEvent("upsell_view", {
                user_state: ctx.state,
                variant: window._upsellVariant,
                source: "pricing"
            });
        }
        /* Track retention view for cancelled/expired */
        if ((ctx.state === "cancelled" || ctx.state === "expired") && window.trackEvent) {
            window.trackEvent("retention_view", {
                user_state: ctx.state,
                source: "pricing"
            });
        }
        /* Track urgency view for cancelled */
        if (ctx.state === "cancelled" && window.trackEvent) {
            window.trackEvent("urgency_view", {
                user_state: ctx.state,
                source: "pricing"
            });
        }
        /* Track limit reached */
        if (ctx.atLimit && window.trackEvent) {
            window.trackEvent("limit_reached", {
                user_state: ctx.state,
                analysis_count: ctx.analysisCount,
                analysis_limit: ctx.analysisLimit,
                source: "pricing"
            });
        }

        /* Activate mobile sticky CTA for conversion states */
        var stickyBar = document.getElementById("stickyCta");
        if (stickyBar) {
            if (ctx.showPricing && ctx.state !== "logged_out" && ctx.state !== "pro_active") {
                stickyBar.style.display = "flex";
                /* Add bottom padding so sticky CTA doesn't overlap content */
                document.body.style.paddingBottom = "64px";
            } else {
                stickyBar.style.display = "none";
                document.body.style.paddingBottom = "";
            }
        }

        /* ── A/B variant: update paywall + sticky CTA text ── */
        if (window._upsellVariant === "B" && ctx.state !== "pro_active") {
            var paywallCta = document.querySelector(".paywall-cta");
            if (paywallCta) paywallCta.textContent = "Upgrade to Pro Now";
            var stickyBtn = document.querySelector(".sticky-cta-btn");
            if (stickyBtn) stickyBtn.textContent = "\u26a1 Upgrade to Pro Now";
        }

        /* ── Track experiment variant exposure ── */
        if (window.trackEvent && ctx.state !== "pro_active") {
            window.trackEvent("experiment_view", {
                experiment: "upsell_v1",
                variant: window._upsellVariant,
                user_state: ctx.state
            });
        }
    }

    /** Minimal HTML escaper */
    function escHtml(str) {
        if (!str) return "";
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

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
            var ctx = window.getUserStateContext(null);
            applyPricingState(ctx);
        }
    }

    function fetchUsage() {
        fetch("/api/me", { headers: { "Authorization": "Bearer " + authToken } })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.analysis_count !== undefined) {
                    var label = d.analysis_count + "/" + d.analysis_limit + " verdicts";
                    if (d.plan === "pro") {
                        label = "Pro \u00b7 " + label;
                    }
                    document.getElementById("usageInfo").textContent = label;
                }
                /* ── Update pricing section using state context ── */
                var ctx = window.getUserStateContext(d);
                applyPricingState(ctx);
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

    /* ── Soft Paywall Modal ── */
    function showPaywallModal() {
        var overlay = document.getElementById("paywallOverlay");
        if (overlay) {
            overlay.style.display = "flex";
            if (window.trackEvent) {
                window.trackEvent("paywall_view", {
                    user_state: "free",
                    variant: window._upsellVariant,
                    source: "analyze"
                });
                window.trackEvent("paywall_shown_after_click", {
                    user_state: "free",
                    variant: window._upsellVariant,
                    source: "analyze"
                });
            }
        }
    }
    function hidePaywallModal() {
        var overlay = document.getElementById("paywallOverlay");
        if (overlay) overlay.style.display = "none";
    }
    /* Wire close handlers for paywall modal */
    document.addEventListener("click", function(e) {
        if (e.target && e.target.id === "paywallClose") hidePaywallModal();
        if (e.target && e.target.id === "paywallOverlay") hidePaywallModal();
        /* Track primary CTA clicks */
        if (e.target && (e.target.classList.contains("paywall-cta") || e.target.classList.contains("sticky-cta-btn"))) {
            if (window.trackEvent) {
                window.trackEvent("cta_primary_click", {
                    user_state: (window._veltrixCtx && window._veltrixCtx.state) || "unknown",
                    variant: window._upsellVariant,
                    source: e.target.classList.contains("sticky-cta-btn") ? "sticky_cta" : "paywall"
                });
            }
        }
    });

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

        /* ── Soft paywall: delay 0.5s with loading feel, then show paywall ── */
        var ctx = window._veltrixCtx;
        if (ctx && ctx.atLimit && ctx.state === "free") {
            messageEl.innerHTML = "\u23F3 Evaluating, please wait...";
            analyzeBtn.disabled = true;
            setTimeout(function() {
                messageEl.innerHTML = "";
                analyzeBtn.disabled = false;
                showPaywallModal();
            }, 500);
            return;
        }

        messageEl.innerHTML = "\u23F3 Running decision engine...";
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
                var errMsg = data.message || data.error || "Decision engine failed";
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

            messageEl.innerHTML = '<div class="success">\u2705 Verdict ready.</div>';
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
            return '<div style="text-align:center;margin:20px 0;"><span style="color:#64748b;font-size:14px;"><a href="#" id="loginToSave" style="color:#4f46e5;font-weight:600;">Log in</a> to save this verdict to your dashboard.</span></div>';
        }
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

    /* ── Helpers ── */

    function esc(str) {
        if (!str) return "";
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    /**
     * Get the decision confidence score from the API response,
     * or calculate a fallback from the richness of the data.
     */
    function getConfidenceScore(item) {
        /* Use AI-provided confidence if available */
        if (item.confidence && typeof item.confidence === "number") {
            return Math.min(Math.max(item.confidence, 60), 97);
        }
        /* Fallback: calculate from data richness */
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

        /* Confidence Score */
        var confidenceScore = getConfidenceScore(item);

        /* Smart Tags */
        var tags = extractTags(item);
        var tagsHtml = '<div class="tags-row">' + tags.map(function (t) { return '<span class="smart-tag">' + esc(t) + '</span>'; }).join("") + '</div>';

        /* ── Verdict Banner ── */
        var verdict = (item.verdict || "BUILD").toUpperCase();
        var isBuild = verdict === "BUILD";
        var verdictColor = isBuild ? "#059669" : "#dc2626";
        var verdictBg = isBuild ? "#f0fdf4" : "#fef2f2";
        var verdictBorder = isBuild ? "#bbf7d0" : "#fecaca";
        var verdictIcon = isBuild ? "\u2705" : "\u274C";
        var verdictLabel = isBuild ? "BUILD" : "DON\u2019T BUILD";

        /* Top 3 Reasons */
        var topReasons = Array.isArray(item.top_reasons) && item.top_reasons.length ? item.top_reasons.slice(0, 3) : [
            "No verifiable demand signals or market data available",
            "Competitive landscape unclear — risk of entering a saturated space",
            "Unit economics and margin potential cannot be assessed"
        ];
        var topReasonsHtml =
            '<div style="text-align:left;max-width:560px;margin:16px auto 0;">' +
                '<div style="font-size:13px;font-weight:700;color:' + verdictColor + ';text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px;">Top 3 Reasons</div>' +
                '<ul style="list-style:none;padding:0;margin:0;">' +
                    topReasons.map(function (r) {
                        return '<li style="padding:6px 0;font-size:14px;color:#1e293b;line-height:1.5;display:flex;align-items:flex-start;gap:8px;">' +
                            '<span style="color:' + verdictColor + ';font-size:16px;flex-shrink:0;margin-top:1px;">' + (isBuild ? "\u25B2" : "\u25BC") + '</span>' +
                            '<span>' + esc(r) + '</span>' +
                        '</li>';
                    }).join("") +
                '</ul>' +
            '</div>';

        /* Verdict Reasoning */
        var verdictReasoning = item.verdict_reasoning || "Insufficient data to justify a BUILD. No clear competitive moat, demand validation, or margin evidence was found.";
        var reasoningHtml =
            '<div style="max-width:560px;margin:14px auto 0;text-align:left;">' +
                '<div style="font-size:13px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">Why This Verdict</div>' +
                '<p style="font-size:14px;color:#334155;line-height:1.65;margin:0;">' + esc(verdictReasoning) + '</p>' +
            '</div>';

        /* Next Actions */
        var nextActions = Array.isArray(item.next_actions) && item.next_actions.length ? item.next_actions.slice(0, 3) : [
            "Define the exact target customer and validate demand with 30+ survey responses",
            "Identify the top 3 direct competitors and document how this product is concretely different",
            "Calculate landed cost per unit and target retail price to confirm 50%+ margins"
        ];
        var actionIcons = ["\u0031\uFE0F\u20E3", "\u0032\uFE0F\u20E3", "\u0033\uFE0F\u20E3"];
        var nextActionsHtml =
            '<div style="text-align:left;max-width:560px;margin:18px auto 0;padding-top:14px;border-top:1px solid ' + verdictBorder + ';">' +
                '<div style="font-size:13px;font-weight:700;color:' + verdictColor + ';text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px;">\uD83D\uDE80 What Should I Do Next?</div>' +
                nextActions.map(function (a, i) {
                    return '<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 12px;margin-bottom:6px;background:' + (isBuild ? "rgba(5,150,105,0.06)" : "rgba(220,38,38,0.06)") + ';border-radius:8px;">' +
                        '<span style="font-size:16px;flex-shrink:0;">' + (actionIcons[i] || "\u27A1\uFE0F") + '</span>' +
                        '<span style="font-size:14px;color:#1e293b;line-height:1.5;">' + esc(a) + '</span>' +
                    '</div>';
                }).join("") +
            '</div>';

        var verdictHtml =
            '<div class="verdict-banner" style="background:' + verdictBg + ';border:2px solid ' + verdictBorder + ';border-radius:14px;padding:28px 28px 24px;margin-bottom:24px;text-align:center;">' +
                '<div style="font-size:36px;margin-bottom:8px;">' + verdictIcon + '</div>' +
                '<div style="font-size:28px;font-weight:800;color:' + verdictColor + ';letter-spacing:-0.3px;margin-bottom:4px;">VERDICT: ' + verdictLabel + '</div>' +
                '<div style="font-size:13px;color:#94a3b8;font-weight:600;margin-bottom:2px;">' + (item.confidence || 70) + '% Confidence</div>' +
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
                    (item.meta_description ? '<div style="margin-bottom:8px;"><strong style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.05em;">Meta Description</strong><p style="margin:4px 0 0;">' + esc(item.meta_description) + '</p></div>' : '') +
                    (item.keywords ? '<div><strong style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.05em;">Keywords</strong><p style="margin:4px 0 0;">' + esc(item.keywords) + '</p></div>' : '') +
                '</div>';
        }

        /* ── Assemble ── */
        var secondaryDivider =
            '<div style="text-align:center;margin:28px 0 18px;position:relative;">' +
                '<div style="position:absolute;top:50%;left:0;right:0;height:1px;background:#e2e8f0;"></div>' +
                '<span style="position:relative;background:#f8fafc;padding:0 16px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.1em;">Detailed Breakdown</span>' +
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

  function _initPayPalButton() {
    fetch("/api/config")
      .then(function(res) { return res.json(); })
      .then(function(cfg) {
        var planId = cfg.paypal_plan_id;
        if (!planId) return;
        var container = document.getElementById("paypal-button-container");
        if (!container) return;
        /* Track click on the PayPal / upgrade area (once per render) */
        container.addEventListener("click", function() {
          if (window.trackEvent) {
            window.trackEvent("upgrade_click", {
              plan: "pro",
              source: "pricing",
              user_state: (localStorage.getItem("veltrix_token") ? "logged_in" : "logged_out")
            });
          }
        }, { once: true });

        paypal.Buttons({
          style: { label: "pay" },
          createSubscription: function(data, actions) {
            return actions.subscription.create({ plan_id: planId });
          },
          onApprove: function(data) {
            if (window.trackEvent) {
              window.trackEvent("paypal_subscription_approved", {
                plan: "pro",
                source: "pricing",
                subscription_id: data.subscriptionID
              });
            }
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
        }).render('#paypal-button-container').then(function() {
          if (window.trackEvent) {
            window.trackEvent("paypal_button_rendered", {
              plan: "pro",
              source: "pricing"
            });
          }
        });
      })
      .catch(function(err) { if (typeof console !== "undefined") console.warn("PayPal init skipped:", err); });
  }

  function renderPayPal() {
    /* Wait for dynamically-loaded PayPal SDK */
    if (typeof paypal !== "undefined") {
      _initPayPalButton();
    } else {
      document.addEventListener("paypal-sdk-ready", _initPayPalButton);
    }
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
