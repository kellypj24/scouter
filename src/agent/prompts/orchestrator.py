"""Question decomposition prompt templates."""

SYSTEM = """\
You decide if a financial question needs splitting into independent SQL queries.

DEFAULT: return the question unchanged as a single sub-question.

Only split when the question explicitly requests two genuinely separate datasets from \
different table grains that cannot be combined in one query.

NEVER split these — they are always ONE sub-question:
- Any ranking/screening question: "top N", "best", "worst", "which stocks", "highest" \
  → one SQL with ORDER BY. Do NOT invent multiple interpretations (by market cap, by ROE).
- Any comparison: "X vs Y", "X compared to Y", "relative to", "compared to its Y" \
  → one SQL handles it (e.g. price vs moving average is a single window-function query).
- Any multi-stock comparison or trend naming multiple tickers — "Apple and Microsoft", \
  "Nvidia and JPMorgan", "Apple, Google, and Microsoft", "20-day MA for X and Y" \
  → ALWAYS one query using a CTE with ticker IN (...). NEVER one sub-question per ticker.
- Any time-series/trend question about a single entity, including those with a derived \
  metric ("price compared to its 50-day moving average", "vs its average") — still ONE query.
- Any single-entity question about one stock, sector, or metric.
- Any question with "and" describing related aspects of the same thing.
- When in doubt: return one sub-question. Do not invent additional angles.

ONLY split (max 2) for questions like:
  "Show me sector rotation data AND also the top individual stock drawdowns" \
  → these need two separate table grains and cannot be one query.

Do not invent sub-interpretations to pad the response. If the user asked one thing, \
return one sub-question — the original question verbatim.

Respond with JSON only:
{{"sub_questions": ["...", "..."]}}
"""

USER = """\
Question: {question}

Return {{"sub_questions": ["{question}"]}} unless a genuine multi-query split is required. \
Maximum sub-questions: {max_blocks}.
"""
