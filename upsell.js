/**
 * getUserStateContext — Classify user into a state and return UI config.
 * Shared by index.html (pricing section) and dashboard.html (billing card).
 *
 * @param {Object|null} user — /api/me response, or null for logged-out
 * @returns {{ state: string, message: string, cta: string, ctaHref: string|null,
 *             ctaClass: string, secondaryCta: string|null, secondaryHref: string|null,
 *             secondaryClass: string|null, benefit: string, urgency: string|null,
 *             showPricing: boolean }}
 */
window.getUserStateContext = function (user) {
    if (!user) {
        return {
            state: "logged_out",
            message: "Start free \u2014 then upgrade to Pro",
            cta: "Get Started Free",
            ctaHref: null,
            ctaClass: "primary",
            secondaryCta: null,
            secondaryHref: null,
            secondaryClass: null,
            benefit: "Limited free usage \u00b7 No credit card required",
            urgency: "Cancel anytime \u00b7 Instant activation",
            showPricing: true
        };
    }

    var subStatus = (user.subscription_status || "").toUpperCase();

    if (user.is_pro) {
        return {
            state: "pro_active",
            message: "You\u2019re on the Pro plan",
            cta: "Manage Subscription",
            ctaHref: user.paypal_subscription_id
                ? "https://www.paypal.com/myaccount/autopay"
                : "/dashboard",
            ctaClass: "outline",
            secondaryCta: "Explore Advanced Features",
            secondaryHref: "/",
            secondaryClass: "outline",
            benefit: "Unlimited analyses \u00b7 All Pro features enabled",
            urgency: null,
            showPricing: false
        };
    }

    if (subStatus === "CANCELLED") {
        return {
            state: "cancelled",
            message: "Your Pro access will end soon",
            cta: "Keep Pro Access",
            ctaHref: "/",
            ctaClass: "primary",
            secondaryCta: null,
            secondaryHref: null,
            secondaryClass: null,
            benefit: "Unlimited analyses, premium insights",
            urgency: "No data loss \u00b7 Instant reactivation",
            showPricing: true
        };
    }

    if (subStatus === "SUSPENDED") {
        return {
            state: "suspended",
            message: "Payment issue detected",
            cta: "Fix Payment on PayPal",
            ctaHref: "https://www.paypal.com/myaccount/autopay",
            ctaClass: "warning",
            secondaryCta: "Re-subscribe",
            secondaryHref: "/",
            secondaryClass: "outline",
            benefit: "Restore unlimited analyses and Pro features",
            urgency: "No data loss \u00b7 Update payment to continue",
            showPricing: true
        };
    }

    if (subStatus === "EXPIRED") {
        return {
            state: "expired",
            message: "Your Pro access has ended",
            cta: "Restore Pro Access",
            ctaHref: "/",
            ctaClass: "primary",
            secondaryCta: null,
            secondaryHref: null,
            secondaryClass: null,
            benefit: "Unlimited analyses, premium insights",
            urgency: "Instant activation \u00b7 Cancel anytime",
            showPricing: true
        };
    }

    /* Default: free user */
    var count = user.analysis_count || 0;
    var limit = user.analysis_limit || 0;
    return {
        state: "free",
        message: "Unlock unlimited analyses",
        cta: "Get Unlimited Analyses",
        ctaHref: null,
        ctaClass: "primary",
        secondaryCta: null,
        secondaryHref: null,
        secondaryClass: null,
        benefit: "You\u2019ve used " + count + "/" + limit + " analyses",
        urgency: "Cancel anytime \u00b7 Instant activation",
        showPricing: true
    };
};
