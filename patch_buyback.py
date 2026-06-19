content = open('kaal_scorer.py').read()

old = '''    rules = (
        'Scoring rules:\\n'
        '- PAT growth >50% + no exceptional items + after-hours = 80-90\\n'
        '- PAT growth 20-50% + no exceptional items = 60-75\\n'
        '- PAT growth <20% or exceptional items = 30-50\\n'
        '- Revenue miss despite PAT beat = penalize 10\\n'
        '- Guidance cut = penalize 15\\n'
        '- Large cap >20000Cr = penalize 10\\n'
    )'''
new = '''    rules = (
        'Scoring rules:\\n'
        '- PAT growth >50% + no exceptional items + after-hours = 80-90\\n'
        '- PAT growth 20-50% + no exceptional items = 60-75\\n'
        '- PAT growth <20% or exceptional items = 30-50\\n'
        '- Revenue miss despite PAT beat = penalize 10\\n'
        '- Guidance cut = penalize 15\\n'
        '- Large cap >20000Cr = penalize 10\\n'
        '- Exceptional item inflated PAT = score max 35\\n'
    )'''
content = content.replace(old, new)

# Add buyback type to main prompt
old = '  "offer_price": <for open offers: the offer price per share as number, else 0>,'
new = (
    '  "offer_price": <for open offers: the offer price per share as number, else 0>,\n'
    '  "buyback_type": "<TENDER|OPEN_MARKET|NA> — TENDER=fixed price fixed date, OPEN_MARKET=company buys daily from market",'
)
content = content.replace(old, new)
open('kaal_scorer.py', 'w').write(content)
print('Done')
