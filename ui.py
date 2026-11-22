"""Presentation helpers for app.py: styles, banner, header, small labels.

Status colors (red, yellow, green, purple, grey) are reserved for county
status from Phase 1 on. Nothing here may use them for decoration.
"""

import html

import streamlit as st

# Design tokens. Spacing is on a 4 px scale.
CSS = """
<style>
:root {
  --sk-ink: #1B2430;
  --sk-muted: #5A6778;
  --sk-accent: #1F4E79;
  --sk-accent-ink: #FFFFFF;
  --sk-surface: #FFFFFF;
  --sk-border: #D3DAE3;
  --sk-subtle: #E9EEF4;
}
.block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1400px; }

.sk-banner {
  display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px;
  padding: 8px 16px; border-radius: 4px;
  background: var(--sk-ink); color: #FFFFFF;
  font-size: 0.875rem; letter-spacing: 0.01em;
}
.sk-banner b { font-weight: 700; letter-spacing: 0.06em; }
.sk-banner .sk-note { margin-left: auto; color: #C9D3DF; font-size: 0.8125rem; }

.sk-header { display: flex; align-items: flex-end; justify-content: space-between;
  gap: 16px; flex-wrap: wrap; margin: 20px 0 4px; }
.sk-title { font-size: 1.75rem; font-weight: 700; color: var(--sk-ink);
  letter-spacing: 0.04em; line-height: 1.1; margin: 0; }
.sk-subtitle { color: var(--sk-muted); font-size: 0.9375rem; margin: 4px 0 0; }

.sk-tagline { color: var(--sk-muted); font-size: 0.8125rem; margin: 2px 0 0; }
dl.sk-stats, dl.sk-rows { margin: 0; padding: 0; }
.sk-stats { display: flex; gap: 24px; flex-wrap: wrap; }
.sk-stats div { display: flex; flex-direction: column; }
.sk-stats dt { order: 2; color: var(--sk-muted); font-size: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.06em; }
.sk-stats dd { order: 1; margin: 0; font-size: 1.25rem; font-weight: 600;
  color: var(--sk-ink); font-variant-numeric: tabular-nums; }

.sk-eyebrow { color: var(--sk-muted); font-size: 0.75rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em; margin: 0 0 4px; }

.sk-chip { display: inline-block; padding: 2px 8px; border-radius: 4px;
  border: 1px solid var(--sk-border); background: var(--sk-subtle);
  color: var(--sk-ink); font-size: 0.8125rem; font-variant-numeric: tabular-nums; }

.sk-empty-title { font-size: 1rem; font-weight: 600; color: var(--sk-ink); margin: 8px 0 4px; }
.sk-empty-body { font-size: 0.875rem; color: var(--sk-muted); margin: 0 0 8px; }
.sk-rows div { display: flex; justify-content: space-between; gap: 12px;
  padding: 8px 0; border-top: 1px solid var(--sk-border); font-size: 0.9375rem; }
.sk-rows div:first-child { border-top: 0; }
.sk-rows dt { color: var(--sk-ink); }
.sk-rows dd { margin: 0; color: var(--sk-muted); }
</style>
"""


def inject_styles() -> None:
    st.html(CSS)


def banner() -> None:
    # Wording from the design doc; it stays on screen the whole time.
    st.html(
        '<div class="sk-banner" role="note" aria-label="Test mode">'
        "<span><b>TEST MODE:</b> fictional event, synthetic data</span>"
        '<span class="sk-note">County boundaries are real public data. '
        "Everything else is synthetic.</span></div>"
    )


def header(title: str, subtitle: str, tagline: str, stats: list[tuple[str, str]]) -> None:
    items = "".join(
        f"<div><dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd></div>"
        for label, value in stats
    )
    st.html(
        '<div class="sk-header"><div>'
        f'<h1 class="sk-title">{html.escape(title)}</h1>'
        f'<p class="sk-subtitle">{html.escape(subtitle)}</p>'
        f'<p class="sk-tagline">{html.escape(tagline)}</p></div>'
        f'<dl class="sk-stats">{items}</dl></div>'
    )


def empty_state(title: str, body: str) -> None:
    st.html(
        f'<div role="status"><p class="sk-empty-title">{html.escape(title)}</p>'
        f'<p class="sk-empty-body">{html.escape(body)}</p></div>'
    )


def eyebrow(text: str) -> None:
    st.html(f'<p class="sk-eyebrow">{html.escape(text)}</p>')


def chip(text: str) -> str:
    return f'<span class="sk-chip">{html.escape(text)}</span>'


def rows(pairs: list[tuple[str, str]]) -> None:
    """A compact two-column definition list."""
    items = "".join(
        f"<div><dt>{html.escape(k)}</dt><dd>{html.escape(v)}</dd></div>"
        for k, v in pairs
    )
    st.html(f'<dl class="sk-rows">{items}</dl>')
