content = open('kaal_scorer.py').read()

old = "        prompt = _build_prompt(subject, details, pdf_text, macro_context)"
new = (
    "        results_keywords = ['financial result', 'outcome of board', 'quarterly result', 'annual result']\n"
    "        is_results = any(k in (subject + details).lower() for k in results_keywords)\n"
    "        if is_results:\n"
    "            prompt = _build_results_prompt(subject, details, pdf_text, macro_context)\n"
    "        else:\n"
    "            prompt = _build_prompt(subject, details, pdf_text, macro_context)"
)
content = content.replace(old, new)
open('kaal_scorer.py', 'w').write(content)
print('Done')
