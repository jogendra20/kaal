content = open('kaal_scorer.py').read()

old = "    cat, base_score, tier = classify_announcement(subject, details)"
new = (
    "    # Pre-open gap check\n"
    "    preopen_gap = ann.get('preopen_gap', 0.0) if isinstance(ann, dict) else 0.0\n"
    "    if preopen_gap > 8.0:\n"
    "        return {**empty, 'reason': f'Gap already {preopen_gap:.1f}% — edge consumed, skip'}\n"
    "\n"
    "    cat, base_score, tier = classify_announcement(subject, details)"
)
content = content.replace(old, new)

# Boost score if gapping up 2-8%
old = "    return {\n        \"symbol\":         symbol,"
new = (
    "    # Boost if pre-open gap confirms catalyst\n"
    "    if 2.0 <= preopen_gap <= 8.0:\n"
    "        base_score = min(base_score + 8, 95)\n"
    "        signals.append(f'Pre-open gap +{preopen_gap:.1f}% confirms catalyst')\n"
    "\n"
    "    return {\n        \"symbol\":         symbol,"
)
content = content.replace(old, new)

open('kaal_scorer.py', 'w').write(content)
print('Done')
