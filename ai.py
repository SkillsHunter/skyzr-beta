"""SKYZR AI intake. Empty stub until Phase 3.

Rules for when this is built (CLAUDE.md):
- The API key comes only from st.secrets.
- Never read answer_key.csv or pass any of it to the model.
- Each call gets one report's sim_hour, source, verified and text, and nothing else.
- If a call fails, show "AI unavailable: report not processed" and change nothing.
"""
