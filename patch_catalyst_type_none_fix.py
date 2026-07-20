content = open('kaal_scorer.py').read()

old = '            catalyst_type = llm.get("catalyst_type", cat).upper()'
new = '            catalyst_type = (llm.get("catalyst_type") or cat).upper()'

assert old in content, "catalyst_type line not found — file may have changed"
content = content.replace(old, new, 1)

open('kaal_scorer.py', 'w').write(content)
print("Done: catalyst_type now falls back to cat when the LLM explicitly returns null, not just when the key is missing.")
