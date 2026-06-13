content = open('kaal_scorer.py').read()

old = "    # Boost if pre-open gap confirms catalyst\n    if 2.0 <= preopen_gap <= 8.0:\n        base_score = min(base_score + 8, 95)\n        signals.append(f'Pre-open gap +{preopen_gap:.1f}% confirms catalyst')"
new = (
    "    # Boost if pre-open gap confirms catalyst\n"
    "    if 2.0 <= preopen_gap <= 8.0:\n"
    "        base_score = min(base_score + 8, 95)\n"
    "        signals.append(f'Pre-open gap +{preopen_gap:.1f}% confirms catalyst')\n"
    "\n"
    "    # Sector strength boost/penalty\n"
    "    if isinstance(ann, dict):\n"
    "        if ann.get('sector_hot'):\n"
    "            base_score = min(base_score + 6, 95)\n"
    "            signals.append('Sector tailwind — hot sector today')\n"
    "        if ann.get('sector_cold'):\n"
    "            base_score = max(base_score - 8, 0)\n"
    "            signals.append('Sector headwind — cold sector today')"
)
content = content.replace(old, new)
open('kaal_scorer.py', 'w').write(content)
print('Done')
