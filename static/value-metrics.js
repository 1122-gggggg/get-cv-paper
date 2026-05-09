(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.ValueMetrics = api;
})(typeof globalThis !== 'undefined' ? globalThis : window, function () {
    const WEIGHTS = {
        citation: 0.27,
        influence: 0.17,
        attention: 0.16,
        code: 0.15,
        velocity: 0.13,
        venue: 0.08,
        local: 0.04,
    };

    function clamp01(x) {
        return Math.max(0, Math.min(1, Number.isFinite(x) ? x : 0));
    }

    function logScale(value, cap) {
        const v = Math.max(0, Number(value) || 0);
        if (v <= 0) return 0;
        return clamp01(Math.log1p(v) / Math.log1p(cap));
    }

    function tierFor(score) {
        if (score >= 82) return { tier: 'high', label: '高價值' };
        if (score >= 65) return { tier: 'hot', label: '熱門' };
        if (score >= 42) return { tier: 'solid', label: '穩健' };
        if (score >= 20) return { tier: 'emerging', label: '升溫中' };
        return { tier: 'watch', label: '觀望' };
    }

    function computeValueMetrics(input) {
        const m = input || {};
        const citations = Math.max(0, Number(m.citations) || 0);
        const influential = Math.max(0, Number(m.influential) || 0);
        const hfUpvotes = Math.max(0, Number(m.hfUpvotes) || 0);
        const stars = Math.max(0, Number(m.stars) || 0);
        const speed = Math.max(0, Number(m.citationSpeed) || 0);
        const venueH5 = Math.max(0, Number(m.venueH5) || 0);
        const localViews = Math.max(0, Number(m.localViews) || 0);
        const hasCode = !!m.hasCode;

        const axes = {
            citation: logScale(citations, 500),
            influence: logScale(influential, 80),
            attention: logScale(hfUpvotes, 200),
            code: hasCode ? clamp01(0.35 + 0.65 * logScale(stars, 5000)) : 0,
            velocity: logScale(speed, 50),
            venue: logScale(venueH5, 440),
            local: logScale(localViews, 12),
        };

        let weighted = 0;
        for (const [axis, weight] of Object.entries(WEIGHTS)) {
            weighted += (axes[axis] || 0) * weight;
        }
        const score = Math.min(100, Math.round(weighted * 100));
        const tier = tierFor(score);
        const reasons = [];

        if (citations >= 100) reasons.push(`${citations} 引用`);
        else if (citations >= 20) reasons.push('引用累積中');
        if (influential >= 10) reasons.push(`${influential} 高影響引用`);
        if (hfUpvotes >= 30) reasons.push(`HF 熱度 ${hfUpvotes}`);
        if (hasCode) reasons.push(stars >= 100 ? `開源 ${formatCompact(stars)} stars` : '有開源實作');
        if (speed >= 5) reasons.push(`引用速度 ${speed >= 10 ? speed.toFixed(0) : speed.toFixed(1)}/月`);
        if (venueH5 >= 100) reasons.push('高 h5 venue');
        if (localViews > 0) reasons.push(`已點閱 ${localViews} 次`);

        return { score, axes, reasons: reasons.slice(0, 4), ...tier };
    }

    function formatCompact(n) {
        const value = Number(n) || 0;
        if (value >= 1000000) return `${(value / 1000000).toFixed(1)}m`;
        if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
        return String(Math.round(value));
    }

    return { computeValueMetrics, formatCompact, logScale };
});
