content = open('kaal_sources.py').read()

old = '''            stocks = [d.get("nsecode", "") for d in data.get("data", []) if d.get("nsecode")]
            # Filter out index symbols
            stocks = [s for s in stocks if not any(x in s for x in ["NIFTY", "CNX", "SENSEX", "BSE"])]
            results[name] = stocks[:30]'''

new = '''            rows = data.get("data", [])

            def _pct(row):
                try:
                    return float(str(row.get("per_chg", 0)).replace("%", "").replace("+", "").strip())
                except Exception:
                    return 0.0

            # Chartink's API does not return rows sorted by magnitude - without
            # this, the [:30] truncation below took an arbitrary slice of
            # whatever order Chartink happened to return, which could silently
            # drop the actual day's top movers even though they matched the
            # screener criteria.
            rows = sorted(rows, key=_pct, reverse=True)
            stocks = [d.get("nsecode", "") for d in rows if d.get("nsecode")]
            # Filter out index symbols
            stocks = [s for s in stocks if not any(x in s for x in ["NIFTY", "CNX", "SENSEX", "BSE"])]
            results[name] = stocks[:30]'''

assert old in content, "Chartink stocks-extraction block not found — file may have changed"
content = content.replace(old, new, 1)

open('kaal_sources.py', 'w').write(content)
print("Done: Chartink screener results now sorted by percent change before truncating to top 30.")
