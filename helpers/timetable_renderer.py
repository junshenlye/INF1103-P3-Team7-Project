"""Render a Logic Manager payload as a standalone weekly HTML overview.

This renderer lives outside ``src`` because it is a presentation adapter, not
part of the assessed manager pipeline.
"""

import argparse
from html import escape
import json
import logging
from pathlib import Path


LOGGER = logging.getLogger(__name__)


def format_weight(item):
    """Return a short, honest weight label for a timetable tooltip."""
    if item["weight_percent"] is not None:
        return f"{item['weight_percent']}%"
    if item["group_weight_percent"] is not None:
        return f"{item['group_weight_percent']}% group total"
    return "weight unknown"


def render_dot(item, location):
    """Return one accessible assessment dot with hover and tap details."""
    role_labels = {
        "due": "due",
        "active": "active",
        "occurrence": "recurring occurrence",
        "unscheduled": "week unresolved",
    }
    detail = (
        f"{item['module_title']} — {item['name']} — {location} — "
        f"{role_labels[item['slot_role']]} — {format_weight(item)}"
    )
    if item["importance_score"] is not None:
        detail += f" — importance {item['importance_score']}"
        detail += (
            f" — rank {item['importance_rank']} of "
            f"{item['importance_ranked_count']}"
        )
    if item["slot_role"] == "unscheduled" and item["comments"]:
        detail += f" — {item['comments'][-1]}"
    safe_detail = escape(detail, quote=True)
    priority = item["priority"]
    module_title = escape(item["module_title"], quote=True)
    return (
        f'<button class="assessment-dot priority-{priority}" '
        f'type="button" aria-label="{safe_detail}" title="{safe_detail}" '
        f'data-module="{module_title}" data-priority="{priority}" '
        f'data-detail="{safe_detail}"></button>'
    )


def render_timetable(payload):
    """Return a standalone HTML timetable from a Logic Manager payload."""
    schedule = payload["schedule"]
    modules = [module["module_title"] for module in payload["modules"]]
    week_count = schedule["week_count"]

    weekly_items = {
        (item["module_title"], week["week"]): []
        for week in schedule["weeks"]
        for item in week["items"]
    }
    for week in schedule["weeks"]:
        for item in week["items"]:
            weekly_items[(item["module_title"], week["week"])].append(item)

    unscheduled_by_module = {module_title: [] for module_title in modules}
    for item in schedule["unscheduled"]:
        unscheduled_by_module.setdefault(item["module_title"], []).append(item)

    week_headers = "".join(
        f"<th scope=\"col\">{week}</th>"
        for week in range(1, week_count + 1)
    )
    module_options = "".join(
        f'<option value="{escape(module_title, quote=True)}">'
        f"{escape(module_title)}</option>"
        for module_title in modules
    )
    rows = []
    for module_title in modules:
        cells = []
        for week in range(1, week_count + 1):
            dots = "".join(
                render_dot(item, f"Week {week}")
                for item in weekly_items.get((module_title, week), [])
            )
            cells.append(f'<td><div class="dot-group">{dots}</div></td>')
        unscheduled_dots = "".join(
            render_dot(item, "Week unresolved")
            for item in unscheduled_by_module.get(module_title, [])
        )
        rows.append(
            f'<tr data-module="{escape(module_title, quote=True)}">'
            f'<th scope="row">{escape(module_title)}</th>'
            f"{''.join(cells)}"
            f'<td class="unresolved"><div class="dot-group">'
            f"{unscheduled_dots}</div></td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Assessment timetable</title>
  <style>
    :root {{
      color-scheme: light;
      --background: #f7f2ea;
      --surface: #fffdf9;
      --header: #efe5bd;
      --line: #e8e0d4;
      --text: #302d29;
      --muted: #77716a;
      --high: #b84f29;
      --medium: #e5b735;
      --low: #95ad7c;
      --unknown: #8b8b88;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 32px;
      background: var(--background);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
    }}
    .overview {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 32px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 12px 35px rgb(80 65 45 / 8%);
    }}
    h1 {{ margin: 0 0 4px; font-size: 26px; }}
    .subtitle {{ margin: 0; color: var(--muted); }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 18px;
      margin: 22px 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 7px; }}
    .legend-dot {{ width: 11px; height: 11px; border-radius: 50%; }}
    .filters {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 0 0 20px; }}
    .filter {{ display: grid; gap: 5px; color: var(--muted); font-size: 13px; }}
    select {{
      min-width: 150px;
      padding: 8px 30px 8px 10px;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: var(--surface);
      color: var(--text);
      font: inherit;
    }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 18px; }}
    table {{ width: 100%; min-width: 1080px; border-collapse: collapse; table-layout: fixed; }}
    th, td {{ border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }}
    tr:last-child th, tr:last-child td {{ border-bottom: 0; }}
    th:last-child, td:last-child {{ border-right: 0; }}
    thead th {{ height: 54px; background: var(--header); font-size: 13px; text-align: center; }}
    thead th:first-child {{ width: 150px; padding-left: 18px; text-align: left; }}
    thead th:last-child {{ width: 72px; }}
    tbody th {{ height: 66px; padding: 0 18px; text-align: left; font-size: 14px; font-weight: 500; }}
    tbody td {{ height: 66px; text-align: center; }}
    .unresolved {{ background: #f8f5f0; }}
    .dot-group {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 5px; }}
    .assessment-dot {{
      width: 17px;
      height: 17px;
      padding: 0;
      border: 0;
      border-radius: 50%;
      box-shadow: 0 1px 3px rgb(0 0 0 / 16%);
      cursor: pointer;
    }}
    .assessment-dot:focus-visible {{ outline: 3px solid #2563eb; outline-offset: 2px; }}
    .priority-high, .legend-high {{ background: var(--high); }}
    .priority-medium, .legend-medium {{ background: var(--medium); }}
    .priority-low, .legend-low {{ background: var(--low); }}
    .priority-unknown, .legend-unknown {{ background: var(--unknown); }}
    [hidden] {{ display: none !important; }}
    #assessment-detail {{ min-height: 22px; margin: 18px 0 0; color: var(--muted); font-size: 14px; }}
    @media (max-width: 700px) {{
      body {{ padding: 12px; }}
      .overview {{ padding: 20px; border-radius: 18px; }}
    }}
  </style>
</head>
<body>
  <main class="overview">
    <h1>Assessment overview</h1>
    <p class="subtitle">Each dot shows an assessment in that teaching week. Hover or tap for details.</p>
    <div class="legend" aria-label="Priority legend">
      <span class="legend-item"><span class="legend-dot legend-high"></span>High</span>
      <span class="legend-item"><span class="legend-dot legend-medium"></span>Medium</span>
      <span class="legend-item"><span class="legend-dot legend-low"></span>Low</span>
      <span class="legend-item"><span class="legend-dot legend-unknown"></span>Unranked</span>
    </div>
    <div class="filters" aria-label="Timetable filters">
      <label class="filter">Module
        <select id="module-filter">
          <option value="all">All modules</option>
          {module_options}
        </select>
      </label>
      <label class="filter">Priority
        <select id="priority-filter">
          <option value="all">All priorities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
          <option value="unknown">Unranked</option>
        </select>
      </label>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th scope="col">Module</th>{week_headers}<th scope="col" aria-label="Week unresolved" title="Week unresolved">?</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    <p id="assessment-detail" aria-live="polite">Select a dot to inspect it.</p>
  </main>
  <script>
    const detail = document.getElementById('assessment-detail');
    const moduleFilter = document.getElementById('module-filter');
    const priorityFilter = document.getElementById('priority-filter');
    const dots = [...document.querySelectorAll('.assessment-dot')];
    const rows = [...document.querySelectorAll('tbody tr')];

    dots.forEach((dot) => {{
      dot.addEventListener('click', () => {{ detail.textContent = dot.dataset.detail; }});
    }});

    function applyFilters() {{
      dots.forEach((dot) => {{
        const moduleMatches = moduleFilter.value === 'all' || dot.dataset.module === moduleFilter.value;
        const priorityMatches = priorityFilter.value === 'all' || dot.dataset.priority === priorityFilter.value;
        dot.hidden = !(moduleMatches && priorityMatches);
      }});
      rows.forEach((row) => {{
        const moduleMatches = moduleFilter.value === 'all' || row.dataset.module === moduleFilter.value;
        const hasVisibleDot = [...row.querySelectorAll('.assessment-dot')].some((dot) => !dot.hidden);
        row.hidden = !(moduleMatches && hasVisibleDot);
      }});
      detail.textContent = 'Select a dot to inspect it.';
    }}

    moduleFilter.addEventListener('change', applyFilters);
    priorityFilter.addEventListener('change', applyFilters);
  </script>
</body>
</html>
"""


def load_pipeline_payload(input_path):
    """Load either a raw payload or the complete CLI result document."""
    with input_path.open("r", encoding="utf-8") as input_stream:
        document = json.load(input_stream)
    payload = document.get("payload", document)
    if not isinstance(payload, dict) or "schedule" not in payload:
        raise ValueError("Input JSON does not contain a Logic Manager schedule.")
    return payload


def write_timetable(payload, output_path):
    """Write a rendered timetable to the requested HTML path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_timetable(payload), encoding="utf-8")
    LOGGER.info("Timetable written to %s", output_path)


def main(argv=None):
    """Render a saved pipeline JSON result as a standalone HTML file."""
    parser = argparse.ArgumentParser(
        description="Render a Stackplan weekly assessment timetable."
    )
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_html", type=Path)
    arguments = parser.parse_args(argv)

    try:
        payload = load_pipeline_payload(arguments.input_json)
        write_timetable(payload, arguments.output_html)
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
