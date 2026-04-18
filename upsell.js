/**
 * getUserStateContext — Classify user into a state and return UI config.
 * Shared by index.html (pricing section) and dashboard.html (billing card).
 *
 * @param {Object|null} user — /api/me response, or null for logged-out
 * @returns {{ state, message, cta, ctaHref, ctaClass, secondaryCta, secondaryHref,
 *             secondaryClass, benefit, urgency, showPricing, nearLimit, atLimit,
 *             usagePressureMsg, lostFeatures, analysisCount, analysisLimit,
 *             pulseCta }}
 */
window.getUserStateContext = function (user) {
    if (!user) {
        return {
            state: "logged_out",
            message: "Start free \u2014 then upgrade to Pro",
            supportingLine: "No credit card required",
            cta: "Get Started Free",
            ctaHref: null,
            ctaClass: "primary",
            secondaryCta: null,
            secondaryHref: null,
            secondaryClass: null,
            benefit: "Limited free verdicts \u00b7 No credit card required",
            urgency: "Cancel anytime \u00b7 Instant activation",
            showPricing: true,
            nearLimit: false,
            atLimit: false,
            usagePressureMsg: null,
            lostFeatures: null,
            analysisCount: 0,
            analysisLimit: 0,
            pulseCta: false
        };
    }

    var subStatus = (user.subscription_status || "").toUpperCase();
    var count = user.analysis_count || 0;
    var limit = (typeof user.analysis_limit === "number") ? user.analysis_limit : 0;

    if (user.is_pro) {
        return {
            state: "pro_active",
            message: "You\u2019re on the Pro plan",
            supportingLine: "Unlimited verdicts \u00b7 All Pro features enabled",
            cta: "Manage Subscription",
            ctaHref: user.paypal_subscription_id
                ? "https://www.paypal.com/myaccount/autopay"
                : "/dashboard",
            ctaClass: "outline",
            secondaryCta: "Explore Advanced Features",
            secondaryHref: "/app",
            secondaryClass: "outline",
            benefit: "Unlimited verdicts \u00b7 All Pro features enabled",
            urgency: null,
            showPricing: false,
            nearLimit: false,
            atLimit: false,
            usagePressureMsg: null,
            lostFeatures: null,
            analysisCount: count,
            analysisLimit: limit,
            pulseCta: false
        };
    }

    /* Lost features list for cancelled / expired */
    var lostFeatures = [
        "Unlimited verdicts",
        "Saved decision history",
        "Premium category breakdowns"
    ];

    if (subStatus === "CANCELLED") {
        return {
            state: "cancelled",
            message: "Your Pro access ends soon",
            supportingLine: "Don\u2019t lose your saved decisions",
            cta: "Keep My Pro Access",
            ctaHref: "/#pricingSection",
            ctaClass: "primary",
            secondaryCta: null,
            secondaryHref: null,
            secondaryClass: null,
            benefit: "Don\u2019t lose your saved decisions",
            urgency: "No data loss \u00b7 Instant reactivation",
            showPricing: true,
            nearLimit: false,
            atLimit: false,
            usagePressureMsg: null,
            lostFeatures: lostFeatures,
            analysisCount: count,
            analysisLimit: limit,
            pulseCta: true
        };
    }

    if (subStatus === "SUSPENDED") {
        return {
            state: "suspended",
            message: "Payment issue detected",
            supportingLine: "Update payment to restore Pro access",
            cta: "Fix Payment & Continue",
            ctaHref: "https://www.paypal.com/myaccount/autopay",
            ctaClass: "warning",
            secondaryCta: "Re-subscribe",
            secondaryHref: "/#pricingSection",
            secondaryClass: "outline",
            benefit: "Restore unlimited verdicts and Pro features",
            urgency: "No data loss \u00b7 Update payment to continue",
            showPricing: true,
            nearLimit: false,
            atLimit: false,
            usagePressureMsg: null,
            lostFeatures: null,
            analysisCount: count,
            analysisLimit: limit,
            pulseCta: false
        };
    }

    if (subStatus === "EXPIRED") {
        return {
            state: "expired",
            message: "Your Pro access has ended",
            supportingLine: "Restore access to unlimited verdicts",
            cta: "Restore My Access",
            ctaHref: "/#pricingSection",
            ctaClass: "primary",
            secondaryCta: null,
            secondaryHref: null,
            secondaryClass: null,
            benefit: "Unlimited verdicts, premium decision reports",
            urgency: "Instant activation \u00b7 Cancel anytime",
            showPricing: true,
            nearLimit: false,
            atLimit: false,
            usagePressureMsg: null,
            lostFeatures: lostFeatures,
            analysisCount: count,
            analysisLimit: limit,
            pulseCta: true
        };
    }

    /* Default: free user — with usage pressure */
    var atLimit = (limit > 0 && count >= limit);
    var nearLimit = (!atLimit && limit > 0 && (count / limit) >= 0.8);
    var usagePressureMsg;
    var supportingLine;
    if (atLimit) {
        usagePressureMsg = "You\u2019ve used all your free verdicts \u2014 upgrade to continue";
        supportingLine = "Unlock unlimited verdicts now";
    } else if (nearLimit) {
        usagePressureMsg = "You\u2019re about to hit your limit";
        supportingLine = count + " of " + limit + " verdicts used";
    } else {
        usagePressureMsg = "You\u2019ve used " + count + " out of " + limit + " verdicts";
        supportingLine = "Upgrade for unlimited decisions";
    }

    return {
        state: "free",
        message: atLimit ? usagePressureMsg : (nearLimit ? usagePressureMsg : "Unlock unlimited verdicts"),
        supportingLine: supportingLine,
        cta: "Unlock Unlimited Verdicts",
        ctaHref: null,
        ctaClass: "primary",
        secondaryCta: null,
        secondaryHref: null,
        secondaryClass: null,
        benefit: usagePressureMsg,
        urgency: "Cancel anytime \u00b7 Instant activation",
        showPricing: true,
        nearLimit: nearLimit,
        atLimit: atLimit,
        usagePressureMsg: usagePressureMsg,
        lostFeatures: null,
        analysisCount: count,
        analysisLimit: limit,
        pulseCta: (atLimit || nearLimit)
    };
};
