"""Presentation helpers for app.py: styles, banner, header, legend, small parts.

Red, yellow, green, purple and grey mean county status. Nothing decorative
uses them; the accent is navy.
"""

import html

import streamlit as st

# Status fills. Every use is paired with a word, so color never stands alone.
STATUS_FILL = {
    "red": "#C0392B",
    "yellow": "#F2C14E",
    "green": "#3A8F4B",
    "purple": "#7B3FA0",
    "grey": "#C3C8D0",
}

# Design tokens. Spacing is on a 4 px scale.
CSS = """
<style>
:root {
  --sk-ink: #1B2430;
  --sk-muted: #5A6778;
  --sk-accent: #1F4E79;
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

.sk-chip { display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px;
  border-radius: 4px; border: 1px solid var(--sk-border); background: var(--sk-subtle);
  color: var(--sk-ink); font-size: 0.8125rem; font-variant-numeric: tabular-nums; }
.sk-chip-live { background: var(--sk-accent); border-color: var(--sk-accent); color: #FFFFFF; }

.sk-swatch { display: inline-block; width: 12px; height: 12px; border-radius: 2px;
  border: 1px solid rgba(0,0,0,0.25); flex: none; }

.sk-clock { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.sk-clock-hour { font-size: 1.5rem; font-weight: 700; color: var(--sk-ink);
  font-variant-numeric: tabular-nums; }
.sk-clock-of { color: var(--sk-muted); font-size: 0.875rem; }

.sk-legend { display: flex; flex-wrap: wrap; gap: 8px 20px; margin: 4px 0 0; padding: 0;
  list-style: none; font-size: 0.8125rem; color: var(--sk-ink); }
.sk-legend li { display: flex; align-items: center; gap: 6px; }
.sk-legend b { font-weight: 600; }

.sk-empty-title { font-size: 1rem; font-weight: 600; color: var(--sk-ink); margin: 8px 0 4px; }
.sk-empty-body { font-size: 0.875rem; color: var(--sk-muted); margin: 0 0 8px; }
.sk-rows div { display: flex; justify-content: space-between; gap: 12px;
  padding: 8px 0; border-top: 1px solid var(--sk-border); font-size: 0.9375rem; }
.sk-rows div:first-child { border-top: 0; }
.sk-rows dt { color: var(--sk-ink); }
.sk-rows dd { margin: 0; color: var(--sk-muted); text-align: right; }

.sk-section { font-size: 0.875rem; font-weight: 600; color: var(--sk-ink);
  margin: 16px 0 4px; padding-top: 12px; border-top: 1px solid var(--sk-border); }
.sk-note-text { font-size: 0.8125rem; color: var(--sk-muted); margin: 0 0 8px; }

table.sk-table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
.sk-table th { text-align: left; font-weight: 600; color: var(--sk-muted); font-size: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.06em; padding: 4px 8px 4px 0;
  border-bottom: 1px solid var(--sk-border); }
.sk-table td { padding: 8px 8px 8px 0; border-bottom: 1px solid var(--sk-border);
  vertical-align: top; color: var(--sk-ink); }
.sk-table td.sk-muted { color: var(--sk-muted); }
.sk-table td.sk-num, .sk-table th.sk-num { text-align: right; font-variant-numeric: tabular-nums; }
.sk-status { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; }
.sk-status small { font-weight: 400; color: var(--sk-muted); display: block; }
</style>
"""

e = html.escape


def inject_styles() -> None:
    st.html(CSS)


def banner() -> None:
    # The first part is the design doc's wording; the second is plan v2 Fix 3.
    st.html(
        '<div class="sk-banner" role="note" aria-label="Test mode">'
        "<span><b>TEST MODE:</b> fictional event, synthetic data</span>"
        '<span class="sk-note">Each browser tab is its own temporary run. '
        "A reload or server restart loses it.</span></div>"
    )


def header(title: str, subtitle: str, tagline: str, stats: list[tuple[str, str]]) -> None:
    items = "".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in stats)
    st.html(
        '<div class="sk-header"><div>'
        f'<h1 class="sk-title">{e(title)}</h1>'
        f'<p class="sk-subtitle">{e(subtitle)}</p>'
        f'<p class="sk-tagline">{e(tagline)}</p></div>'
        f'<dl class="sk-stats">{items}</dl></div>'
    )


def eyebrow(text: str) -> None:
    st.html(f'<p class="sk-eyebrow">{e(text)}</p>')


def swatch(color: str) -> str:
    return f'<span class="sk-swatch" style="background:{STATUS_FILL[color]}" aria-hidden="true"></span>'


def chip(text: str, color: str | None = None, live: bool = False) -> str:
    cls = "sk-chip sk-chip-live" if live else "sk-chip"
    return f'<span class="{cls}">{swatch(color) if color else ""}{e(text)}</span>'


def clock(hour: int, last: int, live: bool, live_head: int) -> None:
    state = chip("LIVE", live=True) if live else chip(f"Reviewing · live is hour {live_head}")
    st.html(
        '<div class="sk-clock" aria-live="polite">'
        f'<span class="sk-clock-hour">Hour {hour}</span>'
        f'<span class="sk-clock-of">of {last} simulated hours</span>{state}</div>'
    )


def legend(items) -> None:
    lis = "".join(
        f"<li>{swatch(c)}<span><b>{e(name)}</b> = {e(meaning)}</span></li>"
        for c, name, meaning in items
    )
    st.html(f'<ul class="sk-legend" aria-label="Map legend">{lis}</ul>')


def empty_state(title: str, body: str) -> None:
    st.html(
        f'<div role="status"><p class="sk-empty-title">{e(title)}</p>'
        f'<p class="sk-empty-body">{e(body)}</p></div>'
    )


def rows(pairs: list[tuple[str, str]]) -> None:
    items = "".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in pairs)
    st.html(f'<dl class="sk-rows">{items}</dl>')


def section(title: str) -> None:
    st.html(f'<h4 class="sk-section">{e(title)}</h4>')


def note(text: str) -> None:
    st.html(f'<p class="sk-note-text">{e(text)}</p>')


def table(headers: list[str], body: list[list[str]], num_cols=(), caption: str = "") -> None:
    """A simple accessible table. Cells are pre-escaped HTML strings."""
    th = "".join(
        f'<th scope="col"{" class=sk-num" if i in num_cols else ""}>{e(h)}</th>'
        for i, h in enumerate(headers)
    )
    trs = "".join(
        "<tr>" + "".join(
            f'<td{" class=sk-num" if i in num_cols else ""}>{cell}</td>'
            for i, cell in enumerate(r)
        ) + "</tr>"
        for r in body
    )
    cap = f'<caption class="sk-note-text" style="text-align:left">{e(caption)}</caption>' if caption else ""
    st.html(f'<table class="sk-table">{cap}<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>')


def status_cell(color: str, word: str, detail: str = "") -> str:
    small = f"<small>{e(detail)}</small>" if detail else ""
    return f'<span class="sk-status">{swatch(color)}<span>{e(word)}{small}</span></span>'
