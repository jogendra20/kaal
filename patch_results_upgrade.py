content = open('kaal_scorer.py').read()

old = '''def _build_results_prompt(subject, details, pdf_text, macro_context):
    ctx = "Subject: " + subject + "\\nDetails: " + details[:600]
    if pdf_text:
        ctx += "\\nPDF Excerpt:\\n" + pdf_text[:3000]

    macro_str = ""
    if macro_context:
        macro_str = (
            "\\nMARKET CONTEXT: VIX=" + str(macro_context.get("vix", "N/A")) +
            ", GIFT Nifty Bias=" + macro_context.get("gift_nifty_bias", "Neutral") +
            ", SPX Change=" + str(macro_context.get("spx_chg", 0))
        )

    rules = (
        "Scoring rules:\\n"
        "- PAT growth >50% + no exceptional items + after-hours = 80-90\\n"
        "- PAT growth 20-50% + no exceptional items = 60-75\\n"
        "- PAT growth <20% or exceptional items = 30-50\\n"
        "- Revenue miss despite PAT beat = penalize 10\\n"
        "- Guidance cut = penalize 15\\n"
        "- Large cap >20000Cr = penalize 10\\n"
        "- Exceptional item inflated PAT = score max 35\\n"
    )
    schema = (
        "{\\n"
        "  \\"score\\": <0-100>,\\n"
        "  \\"pat_growth_pct\\": <PAT YoY growth as number>,\\n"
        "  \\"revenue_growth_pct\\": <Revenue YoY growth as number>,\\n"
        "  \\"margin_expanded\\": <true/false>,\\n"
        "  \\"exceptional_item\\": <true if one-time item inflated PAT>,\\n"
        "  \\"dividend_announced\\": <true/false>,\\n"
        "  \\"guidance_tone\\": \\"<POSITIVE|NEGATIVE|NEUTRAL|NONE>\\",\\n"
        "  \\"is_beat\\": <true if PAT >20% and no exceptional items>,\\n"
        "  \\"is_fresh\\": <true if announced after market hours>,\\n"
        "  \\"catalyst_type\\": \\"RESULTS_BEAT\\",\\n"
        "  \\"direction\\": \\"<BULLISH|BEARISH|NEUTRAL>\\",\\n"
        "  \\"key\\": \\"<PAT +X% YoY, Revenue +X% YoY, margin expanded/contracted>\\",\\n"
        "  \\"reason\\": \\"<two lines: why this will or will not move intraday>\\",\\n"
        "  \\"skip_reason\\": \\"<if score < 40 why, else empty>\\",\\n"
        "  \\"offer_price\\": 0\\n"
        "}"
    )
    return (
        "You are an expert NSE/BSE intraday trader analyzing quarterly results."
        + macro_str + "\\n\\n" + ctx
        + "\\n\\nReturn ONLY a JSON object:\\n" + schema
        + "\\n\\n" + rules
    )'''

new = '''def _build_results_prompt(subject, details, pdf_text, macro_context):
    ctx = "Subject: " + subject + "\\nDetails: " + details[:600]
    if pdf_text:
        ctx += "\\nPDF Excerpt:\\n" + pdf_text[:3000]

    macro_str = ""
    if macro_context:
        macro_str = (
            "\\nMARKET CONTEXT: VIX=" + str(macro_context.get("vix", "N/A")) +
            ", GIFT Nifty=" + macro_context.get("gift_nifty_bias", "Neutral") +
            ", SPX=" + str(macro_context.get("spx_chg", 0)) + "%"
        )

    schema = (
        "{\\n"
        "  \\"score\\": <0-100 intraday long potential>,\\n"
        "  \\"pat_growth_pct\\": <PAT this quarter vs same quarter last year, number only>,\\n"
        "  \\"revenue_growth_pct\\": <Revenue YoY growth, number only>,\\n"
        "  \\"margin_expanded\\": <true if EBITDA margin improved vs last year>,\\n"
        "  \\"exceptional_item\\": <true if one-time item inflated PAT>,\\n"
        "  \\"dividend_announced\\": <true if dividend declared with results>,\\n"
        "  \\"guidance_tone\\": \\"<POSITIVE|NEGATIVE|NEUTRAL|NONE>\\",\\n"
        "  \\"is_beat\\": <true if PAT growth >20% AND no exceptional items>,\\n"
        "  \\"is_fresh\\": <true if announced after 3:30PM market close>,\\n"
        "  \\"announced_time\\": \\"<AFTER_HOURS|DURING_MARKET|UNKNOWN>\\",\\n"
        "  \\"company_size\\": \\"<LARGE_CAP|MID_CAP|SMALL_CAP>\\",\\n"
        "  \\"catalyst_type\\": \\"RESULTS_BEAT or RESULTS_MISS\\",\\n"
        "  \\"direction\\": \\"<BULLISH|BEARISH|NEUTRAL>\\",\\n"
        "  \\"key\\": \\"<PAT +X% YoY | Revenue +X% YoY | Margin expanded/contracted | Dividend Rs X>\\",\\n"
        "  \\"reason\\": \\"<Line1: beat/miss magnitude. Line2: why it will/wont move intraday>\\",\\n"
        "  \\"skip_reason\\": \\"<if score<40, why. else empty>\\",\\n"
        "  \\"offer_price\\": 0,\\n"
        "  \\"buyback_type\\": \\"NA\\"\\n"
        "}"
    )

    rules = (
        "SCORING RULES (follow strictly):\\n"
        "BULLISH signals:\\n"
        "- PAT growth >50% + no exceptional items + after-hours announcement = 82-90\\n"
        "- PAT growth 30-50% + no exceptional items + after-hours = 72-80\\n"
        "- PAT growth 20-30% + no exceptional items = 62-70\\n"
        "- Dividend announced + PAT beat = +8 bonus\\n"
        "- Guidance POSITIVE = +5 bonus\\n"
        "BEARISH/PENALTY signals:\\n"
        "- Exceptional item inflated PAT = score MAX 35, direction BEARISH\\n"
        "- Revenue miss despite PAT beat = -10\\n"
        "- Guidance NEGATIVE = -15, direction BEARISH\\n"
        "- Announced during market hours (not fresh) = -15\\n"
        "- LARGE_CAP results beat = -10 (already priced in by institutions)\\n"
        "- PAT growth <20% = score MAX 45\\n"
        "- PAT decline = score MAX 25, direction BEARISH\\n"
        "HARD RULES:\\n"
        "- Never give BULLISH direction if exceptional items inflated PAT\\n"
        "- Never give score >60 for LARGE_CAP results\\n"
        "- Always check if announced after market hours for freshness\\n"
    )

    return (
        "You are an expert NSE/BSE intraday trader analyzing quarterly financial results."
        + macro_str + "\\n\\n" + ctx
        + "\\n\\nExtract numbers only from the PDF above. Do NOT invent numbers."
        + "\\n\\nReturn ONLY a JSON object:\\n" + schema
        + "\\n\\n" + rules
    )'''

content = content.replace(old, new)
open('kaal_scorer.py', 'w').write(content)
print('Done')
