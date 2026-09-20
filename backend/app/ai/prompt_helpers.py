"""Shared snippets composed into every Gemini prompt in the codebase.

Three universal rules surface here so individual prompts don't drift on
the JSON-boundary instruction, the Indian-macro context wording, or the
percentage encoding convention. Catalogue entries in
`docs/gemini-prompts-catalogue.md` reference these by name.

Import the constant; append it to the relevant section of your prompt.
Don't fork the wording per-prompt — that's the whole point of this file.
"""

from __future__ import annotations

# All prompts that emit JSON. Replaces "Return ONLY JSON, no markdown
# fences" — the old phrasing kept producing markdown fences anyway,
# necessitating six independent fence-strippers downstream. The new
# phrasing tells the model what to do positively, not what NOT to do.
STRICT_JSON_BOUNDARY = (
    'Start your response with "{" and end with "}". '
    'Do not output markdown fences or any prose before or after the JSON.'
)


# All prompts touching Indian markets / macro. Replaces seven different
# free-form wordings of the same idea ("RBI / FII / monsoon / commodity
# cycles / budget" etc.) with one canonical anchor list.
INDIAN_MACRO_CONTEXT = (
    "Consider Indian macroeconomic factors: RBI MPC decisions, FII/DII flow "
    "patterns, Nifty/Sensex broad trends, inflation prints, government "
    "capex/PLI schemes, and currency (INR/USD) dynamics."
)


# All prompts returning numeric percentages. Without this, the model
# sometimes emits "15%" as a string and sometimes 0.15 as a float, and
# downstream parsing has to handle both. Forces one convention.
DECIMAL_OUTPUT_RULE = (
    "Return all percentages as decimals (e.g., 15% = 0.15). "
    'Do not use the "%" symbol in output values.'
)
