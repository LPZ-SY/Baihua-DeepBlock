from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from quantum_route_forge import generate_dispatch_instance, run_optimization  # noqa: E402
from quantum_route_forge.assignment_bqm import build_assignment_bqm  # noqa: E402
from quantum_route_forge.candidate_quality import (  # noqa: E402
    evaluate_measurement,
    exact_assignment_reference,
)
from quantum_route_forge.quantum_measurements import measurement_from_evidence  # noqa: E402
from quantum_route_forge.result_store import ResultStore, list_experiments  # noqa: E402

EXPERIMENTS_DIR = ROOT / "experiments"
if str(EXPERIMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS_DIR))

from batch_candidate_quality import expand_matrix  # noqa: E402


COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#17becf",
    "#9467bd",
    "#8c564b",
    "#e377c2",
]

PAGE_STYLE = {
    "maxWidth": "1400px",
    "margin": "0 auto",
    "padding": "20px",
    "fontFamily": "Segoe UI, Microsoft YaHei, sans-serif",
    "color": "#0f1d2d",
    "background": "linear-gradient(180deg, #f4f8ff 0%, #fbfdff 100%)",
}

PANEL_STYLE = {
    "backgroundColor": "#ffffff",
    "border": "1px solid #dde7f3",
    "borderRadius": "14px",
    "padding": "14px",
    "boxShadow": "0 3px 14px rgba(39, 84, 126, 0.08)",
}

GRID_STYLE = {
    "display": "grid",
    "gridTemplateColumns": "repeat(auto-fit, minmax(190px, 1fr))",
    "gap": "12px",
}

FIELD_STYLE = {
    "display": "flex",
    "flexDirection": "column",
    "gap": "6px",
}

LABEL_STYLE = {
    "fontSize": "13px",
    "fontWeight": "700",
    "letterSpacing": "0.2px",
    "color": "#2a4159",
}

INPUT_STYLE = {
    "width": "100%",
    "height": "40px",
    "borderRadius": "10px",
}

HINT_STYLE = {
    "fontSize": "11px",
    "lineHeight": "1.2",
    "color": "#6582a0",
}

BUTTON_STYLE = {
    "width": "100%",
    "height": "42px",
    "border": "none",
    "borderRadius": "10px",
    "background": "linear-gradient(90deg, #0d63ce 0%, #1f8bff 100%)",
    "color": "white",
    "fontWeight": "700",
    "cursor": "pointer",
}

STATUS_BOX_STYLE = {
    "marginBottom": "8px",
    "fontWeight": "600",
    "wordBreak": "break-word",
    "lineHeight": "1.45",
    "backgroundColor": "#f7fbff",
    "border": "1px solid #d8e8fa",
    "borderRadius": "10px",
    "padding": "10px 12px",
}

METRICS_BOX_STYLE = {
    "fontWeight": "600",
    "marginBottom": "8px",
    "backgroundColor": "#f7fbff",
    "border": "1px solid #d8e8fa",
    "borderRadius": "10px",
    "padding": "10px 12px",
}


def _field(label: str, control, hint: str = "", span: int = 1):
    style = dict(FIELD_STYLE)
    if span > 1:
        style["gridColumn"] = f"span {span}"
    children = [html.Label(label, style=LABEL_STYLE), control]
    if hint:
        children.append(html.Div(hint, style=HINT_STYLE))
    return html.Div(children, style=style)


def _build_figure(result) -> go.Figure:
    depot = result.instance.depot
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[depot[0]],
            y=[depot[1]],
            mode="markers",
            name="Depot",
            marker={"size": 18, "symbol": "star", "color": "#111111"},
        )
    )

    for idx, route in enumerate(result.routes):
        color = COLORS[idx % len(COLORS)]
        xs = [depot[0]] + [c.x for c in route.customers] + [depot[0]]
        ys = [depot[1]] + [c.y for c in route.customers] + [depot[1]]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines+markers",
                name=f"Vehicle {route.vehicle_id}",
                line={"width": 3, "color": color},
                marker={"size": 8},
                hovertemplate="x=%{x:.2f}<br>y=%{y:.2f}<extra></extra>",
            )
        )

    fig.update_layout(
        template="plotly_white",
        title="Quantum Route Forge",
        xaxis_title="City X",
        yaxis_title="City Y",
        height=700,
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
        legend_title="Fleet",
    )
    return fig


def _build_result_table(result) -> html.Table:
    th_style = {
        "textAlign": "left",
        "padding": "10px 12px",
        "borderBottom": "1px solid #d6e4f2",
        "backgroundColor": "#eef5fd",
        "fontWeight": "700",
        "fontSize": "13px",
        "color": "#223b55",
    }
    td_style = {
        "padding": "9px 12px",
        "borderBottom": "1px solid #e7eef7",
        "fontSize": "13px",
        "color": "#1d3147",
        "verticalAlign": "top",
    }
    rows = []
    for route in result.routes:
        stop_ids = ", ".join(str(c.customer_id) for c in route.customers[:14])
        if len(route.customers) > 14:
            stop_ids += " ..."
        rows.append(
            html.Tr(
                [
                    html.Td(f"Vehicle {route.vehicle_id}", style=td_style),
                    html.Td(str(len(route.customers)), style=td_style),
                    html.Td(str(route.load), style=td_style),
                    html.Td(f"{route.distance:.2f}", style=td_style),
                    html.Td(stop_ids, style=td_style),
                ]
            )
        )

    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Route", style=th_style),
                        html.Th("Stops", style=th_style),
                        html.Th("Load", style=th_style),
                        html.Th("Distance", style=th_style),
                        html.Th("Customer IDs", style=th_style),
                    ]
                )
            ),
            html.Tbody(rows),
        ],
        style={
            "width": "100%",
            "borderCollapse": "separate",
            "borderSpacing": "0",
            "overflow": "hidden",
            "borderRadius": "10px",
            "border": "1px solid #d6e4f2",
            "backgroundColor": "white",
        },
    )


def _build_error_outputs(instance, detail: str):
    min_capacity = math.ceil(instance.total_demand / instance.num_vehicles)
    status = f"Input error: {detail}"
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        title="No Feasible Solution",
        height=190,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            {
                "text": "Capacity infeasible under strict mode.<br>"
                f"Demand={instance.total_demand}, vehicles={instance.num_vehicles}, "
                f"required capacity >= {min_capacity}.",
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"size": 15, "color": "#8a1f1f"},
            }
        ],
    )
    metrics = (
        f"Total demand={instance.total_demand}, fleet capacity={instance.num_vehicles * instance.vehicle_capacity} "
        f"(required >= {instance.num_vehicles * min_capacity})."
    )
    table = html.Div(
        "No route generated. Increase Capacity or Vehicles, then run again.",
        style={"fontWeight": "600", "color": "#8a1f1f", "padding": "8px"},
    )
    return status, fig, metrics, table


def _generate_outputs(
    seed,
    customers,
    vehicles,
    capacity,
    mode,
    time_limit,
    quafu_token,
    quafu_backend,
    quafu_base_url,
    quafu_shots,
    quafu_max_qubits,
    quafu_wait,
    quafu_timeout_sec,
    quafu_proxy_url,
    quafu_verify_ssl,
    quafu_result_task_id,
    quafu_manual_bitstring,
    quantum_action="auto",
):
    seed = int(seed or 2026)
    customers = max(8, int(customers or 48))
    vehicles = max(1, int(vehicles or 4))
    capacity = max(1, int(capacity or 34))
    time_limit = max(5, int(time_limit or 10))
    quafu_token = (quafu_token or "").strip() or os.getenv("QUAFU_API_TOKEN", "")
    quafu_backend = (quafu_backend or "").strip()
    quafu_base_url = (quafu_base_url or "").strip() or os.getenv("QUAFU_BASE_URL", "")
    quafu_shots = max(100, int(quafu_shots or 1000))
    quafu_max_qubits = max(2, min(32, int(quafu_max_qubits or 8)))
    quafu_wait = str(quafu_wait).lower().strip() == "true"
    quafu_timeout_sec = max(5, int(quafu_timeout_sec or os.getenv("QUAFU_TIMEOUT_SEC", "25")))
    quafu_proxy_url = (quafu_proxy_url or "").strip() or os.getenv("QUAFU_PROXY_URL", "")
    quafu_verify_ssl = str(quafu_verify_ssl).lower().strip() == "true"
    quafu_result_task_id = (quafu_result_task_id or "").strip()
    quafu_manual_bitstring = (quafu_manual_bitstring or "").strip()

    instance = generate_dispatch_instance(
        seed=seed,
        num_customers=customers,
        num_vehicles=vehicles,
        vehicle_capacity=capacity,
    )

    if not instance.feasible_capacity:
        min_capacity = math.ceil(instance.total_demand / instance.num_vehicles)
        return _build_error_outputs(
            instance,
            (
                "Total demand exceeds fleet capacity. "
                f"Set capacity >= {min_capacity} or increase vehicles."
            ),
        )

    try:
        result = run_optimization(
            instance=instance,
            mode=mode,
            time_limit=time_limit,
            num_reads=120,
            quafu_token=quafu_token,
            quafu_backend=quafu_backend,
            quafu_base_url=quafu_base_url,
            quafu_shots=quafu_shots,
            quafu_wait=quafu_wait,
            quafu_max_qubits=quafu_max_qubits,
            quafu_timeout_sec=quafu_timeout_sec,
            quafu_proxy_url=quafu_proxy_url,
            quafu_verify_ssl=quafu_verify_ssl,
            quafu_result_task_id=quafu_result_task_id,
            quafu_manual_bitstring=quafu_manual_bitstring,
            auto_repair_capacity=False,
            quantum_action=quantum_action,
        )
    except ValueError as exc:
        return _build_error_outputs(instance, str(exc))

    fig = _build_figure(result)
    used = result.metadata.used_mode
    msg = result.metadata.message
    qmeta = []
    if result.metadata.quantum_backend:
        qmeta.append(f"backend={result.metadata.quantum_backend}")
    if result.metadata.quantum_task_id:
        qmeta.append(f"task_id={result.metadata.quantum_task_id}")
    if result.metadata.quantum_bitstring:
        qmeta.append(f"seed_bitstring={result.metadata.quantum_bitstring}")
    if result.metadata.quantum_endpoint:
        qmeta.append(f"endpoint={result.metadata.quantum_endpoint}")
    qmeta_text = f" | Quafu: {', '.join(qmeta)}" if qmeta else ""
    measurement = result.metadata.quantum_measurement_summary or {}
    source = measurement.get("source")
    shots_received = measurement.get("shots_received", 0)
    source_text = f" | source={source}, shots_received={shots_received}" if source else ""
    coverage = min(quafu_max_qubits, len(instance.customers)) / len(instance.customers)
    coverage_text = (
        f" | quantum coverage={min(quafu_max_qubits, len(instance.customers))}/"
        f"{len(instance.customers)}={coverage:.1%}"
        if str(mode).lower() in {"quantum", "quafu"}
        else ""
    )
    status = (
        f"Requested solver: {mode} | Used: {used} | Classical full-assignment energy: "
        f"{result.metadata.energy:.3f}{qmeta_text}{source_text}{coverage_text} | {msg}"
    )
    total_load = sum(r.load for r in result.routes)
    metrics = (
        f"Total demand={instance.total_demand}, served load={total_load}, "
        f"fleet capacity={instance.num_vehicles * instance.vehicle_capacity}, "
        f"total route distance={result.total_distance:.2f}"
    )
    table = _build_result_table(result)
    return status, fig, metrics, table


def _candidate_quality_layout():
    return html.Div(
        [
            html.Div(
                [
                    _field(
                        "Evidence JSON",
                        dcc.Input(
                            id="cq-evidence-path",
                            value=str(ROOT / "results" / "quarkstudio_candidate_quality_validated" / "task_evidence.json"),
                            style=INPUT_STYLE,
                        ),
                        span=2,
                    ),
                    _field(
                        "Frozen thresholds",
                        dcc.Input(
                            id="cq-threshold-path",
                            value=str(ROOT / "results" / "quarkstudio_candidate_quality_validated" / "frozen_thresholds.json"),
                            style=INPUT_STYLE,
                        ),
                        span=2,
                    ),
                    _field("Seed", dcc.Input(id="cq-seed", type="number", value=2026, style=INPUT_STYLE)),
                    _field("Customers", dcc.Input(id="cq-customers", type="number", value=4, min=4, style=INPUT_STYLE)),
                    _field(
                        "Capacity pressure",
                        dcc.Dropdown(
                            id="cq-pressure",
                            options=[{"label": value.title(), "value": value} for value in ("loose", "medium", "tight")],
                            value="medium",
                            clearable=False,
                            style=INPUT_STYLE,
                        ),
                    ),
                    _field("Load and evaluate", html.Button("Load Evidence", id="cq-load-btn", n_clicks=0, style=BUTTON_STYLE)),
                ],
                style={**GRID_STYLE, **PANEL_STYLE, "marginBottom": "12px"},
            ),
            html.Div(id="cq-summary-cards", style={**GRID_STYLE, "marginBottom": "12px"}),
            dcc.Graph(id="cq-energy-graph", config={"displayModeBar": False}),
            html.Div(id="cq-conclusion", style=STATUS_BOX_STYLE),
            dash_table.DataTable(
                id="cq-candidate-table",
                page_size=12,
                sort_action="native",
                filter_action="native",
                style_table={"overflowX": "auto"},
                style_cell={"fontFamily": "Segoe UI", "fontSize": 12, "padding": "7px"},
                style_header={"fontWeight": "700", "backgroundColor": "#eaf3ff"},
            ),
        ],
        style={"paddingTop": "12px"},
    )


def _batch_layout():
    return html.Div(
        [
            html.Div(
                [
                    _field(
                        "Experiment config",
                        dcc.Input(
                            id="batch-config-path",
                            value=str(ROOT / "experiments" / "configs" / "formal_hardware_matrix_v2.json"),
                            style=INPUT_STYLE,
                        ),
                        span=2,
                    ),
                    _field(
                        "Results root",
                        dcc.Input(
                            id="batch-results-root",
                            value=str(ROOT / "results" / "experiments"),
                            style=INPUT_STYLE,
                        ),
                        span=2,
                    ),
                    _field("Preview", html.Button("Dry Run", id="batch-preview-btn", n_clicks=0, style=BUTTON_STYLE)),
                    _field(
                        "Max hardware tasks",
                        dcc.Input(id="batch-max-tasks", type="number", min=1, max=1, value=1, style=INPUT_STYLE),
                        "Formal UI submissions are capped at one fresh task per invocation.",
                    ),
                    _field(
                        "Live confirmation",
                        dcc.Checklist(
                            id="batch-confirm-live",
                            options=[
                                {
                                    "label": " I reviewed the dry run and confirm one fresh hardware task",
                                    "value": "confirmed",
                                }
                            ],
                            value=[],
                        ),
                    ),
                    _field("Start", html.Button("Start Background Batch", id="batch-start-btn", n_clicks=0, style=BUTTON_STYLE)),
                    _field("Resume", html.Button("Resume", id="batch-resume-btn", n_clicks=0, style=BUTTON_STYLE)),
                    _field("Pause", html.Button("Pause after current task", id="batch-pause-btn", n_clicks=0, style={**BUTTON_STYLE, "background": "#8b5e00"})),
                ],
                style={**GRID_STYLE, **PANEL_STYLE, "marginBottom": "12px"},
            ),
            html.Div(id="batch-control-output", style=STATUS_BOX_STYLE),
            html.Pre(id="batch-progress-output", style={**PANEL_STYLE, "whiteSpace": "pre-wrap", "maxHeight": "440px", "overflowY": "auto"}),
            dcc.Interval(id="batch-progress-interval", interval=3000, n_intervals=0),
        ],
        style={"paddingTop": "12px"},
    )


def _history_layout():
    return html.Div(
        [
            html.Div(
                [
                    _field(
                        "Results root",
                        dcc.Input(
                            id="history-results-root",
                            value=str(ROOT / "results" / "experiments"),
                            style=INPUT_STYLE,
                        ),
                        span=2,
                    ),
                    _field("Refresh", html.Button("Refresh History", id="history-refresh-btn", n_clicks=0, style=BUTTON_STYLE)),
                ],
                style={**GRID_STYLE, **PANEL_STYLE, "marginBottom": "12px"},
            ),
            dash_table.DataTable(
                id="history-table",
                page_size=15,
                sort_action="native",
                style_table={"overflowX": "auto"},
                style_cell={"fontFamily": "Segoe UI", "fontSize": 12, "padding": "7px", "textAlign": "left"},
                style_header={"fontWeight": "700", "backgroundColor": "#eaf3ff"},
            ),
        ],
        style={"paddingTop": "12px"},
    )


def _capacity_for_pressure(seed: int, customers: int, vehicles: int, pressure: str) -> tuple[int, int]:
    probe = generate_dispatch_instance(seed, customers, vehicles, 999999)
    minimum = math.ceil(probe.total_demand / vehicles)
    ratio = {"loose": 1.30, "medium": 1.15, "tight": 1.0}.get(pressure, 1.15)
    return max(minimum, math.ceil(minimum * ratio)), probe.total_demand


app = Dash(__name__)
app.title = "Quantum Route Forge"

_initial_status, _initial_figure, _initial_metrics, _initial_table = _generate_outputs(
    seed=2026,
    customers=8,
    vehicles=2,
    capacity=13,
    mode="classical",
    time_limit=8,
    quafu_token="",
    quafu_backend="",
    quafu_base_url="",
    quafu_shots=1024,
    quafu_max_qubits=8,
    quafu_wait="false",
    quafu_timeout_sec=25,
    quafu_proxy_url="",
    quafu_verify_ssl="true",
    quafu_result_task_id="",
    quafu_manual_bitstring="",
)

app.layout = html.Div(
    style=PAGE_STYLE,
    children=[
        html.Div(
            [
                html.H1(
                    "Quantum Route Forge",
                    style={"marginBottom": "8px", "fontSize": "44px", "lineHeight": "1.05"},
                ),
                html.P(
                    "Original competition project: quantum-enhanced fleet assignment + local route refinement.",
                    style={"marginTop": "0", "color": "#425d78", "fontSize": "18px"},
                ),
            ],
            style={"padding": "4px 4px 12px 4px"},
        ),
        dcc.Tabs(
            id="main-tabs",
            value="single-run",
            children=[
                dcc.Tab(
                    label="Single Run",
                    value="single-run",
                    children=[
        html.Div(
            style={**PANEL_STYLE, "marginBottom": "12px"},
            children=[
                html.Div(
                    "Scenario Settings",
                    style={"fontWeight": "700", "fontSize": "15px", "marginBottom": "10px", "color": "#1a3552"},
                ),
                html.Div(
                    style=GRID_STYLE,
                    children=[
                        _field("Seed", dcc.Input(id="seed", type="number", value=2026, style=INPUT_STYLE)),
                        _field(
                            "Customers",
                            dcc.Input(id="customers", type="number", min=8, max=160, value=8, style=INPUT_STYLE),
                        ),
                        _field(
                            "Vehicles",
                            dcc.Input(id="vehicles", type="number", min=1, max=8, value=2, style=INPUT_STYLE),
                        ),
                        _field(
                            "Capacity",
                            dcc.Input(id="capacity", type="number", min=5, max=120, value=13, style=INPUT_STYLE),
                        ),
                        _field(
                            "Mode",
                            dcc.Dropdown(
                                id="mode",
                                options=[
                                    {"label": "Quafu Real Quantum", "value": "quantum"},
                                    {"label": "Classical Simulated Annealing", "value": "classical"},
                                ],
                                value="classical",
                                clearable=False,
                                style=INPUT_STYLE,
                            ),
                        ),
                        _field(
                            "Time Limit (s)",
                            dcc.Input(id="time-limit", type="number", min=5, max=120, value=10, style=INPUT_STYLE),
                        ),
                        _field(
                            "Capacity Pressure",
                            dcc.Dropdown(
                                id="capacity-pressure",
                                options=[{"label": value.title(), "value": value} for value in ("loose", "medium", "tight")],
                                value="medium",
                                clearable=False,
                                style=INPUT_STYLE,
                            ),
                        ),
                        _field(
                            "Auto Capacity",
                            html.Button("Set feasible capacity", id="auto-capacity-btn", n_clicks=0, style=BUTTON_STYLE),
                        ),
                        html.Div(id="capacity-diagnostic", style=STATUS_BOX_STYLE),
                    ],
                ),
            ],
        ),
        html.Div(
            id="quantum-connection-panel",
            style={**PANEL_STYLE, "marginBottom": "12px", "display": "none"},
            children=[
                html.Div(
                    "Quantum Connection",
                    style={"fontWeight": "700", "fontSize": "15px", "marginBottom": "10px", "color": "#1a3552"},
                ),
                html.Div(
                    style=GRID_STYLE,
                    children=[
                        _field(
                            "Token",
                            dcc.Input(
                                id="quafu-token",
                                type="password",
                                placeholder="api_token or access_token (JWT)",
                                style=INPUT_STYLE,
                            ),
                            "Use browser access_token for quafu-sqc.",
                            span=2,
                        ),
                        _field("Backend", dcc.Input(id="quafu-backend", type="text", placeholder="ScQ-P10", style=INPUT_STYLE)),
                        _field(
                            "Base URL",
                            dcc.Input(
                                id="quafu-base-url",
                                type="text",
                                placeholder="https://quafu-sqc.baqis.ac.cn/",
                                style=INPUT_STYLE,
                            ),
                            span=2,
                        ),
                        _field(
                            "Shots",
                            dcc.Input(id="quafu-shots", type="number", min=100, max=20000, value=1024, style=INPUT_STYLE),
                        ),
                        _field(
                            "Max Qubits",
                            dcc.Input(id="quafu-max-qubits", type="number", min=2, max=32, value=8, style=INPUT_STYLE),
                            "Smaller value (2-4) may return results faster on busy real hardware.",
                        ),
                        _field(
                            "Timeout (s)",
                            dcc.Input(
                                id="quafu-timeout-sec",
                                type="number",
                                min=5,
                                max=120,
                                value=25,
                                style=INPUT_STYLE,
                            ),
                        ),
                        _field(
                            "Proxy URL",
                            dcc.Input(
                                id="quafu-proxy-url",
                                type="text",
                                value="",
                                placeholder="Optional: leave empty unless you use local proxy",
                                style=INPUT_STYLE,
                            ),
                        ),
                        _field(
                            "Manual Seed Bitstring",
                            dcc.Input(
                                id="quafu-manual-bitstring",
                                type="text",
                                value="",
                                placeholder="Optional override, e.g. 01011010",
                                style=INPUT_STYLE,
                            ),
                            "Use only 0/1. When provided, this seed overrides pending/missing Quafu bitstring.",
                            span=2,
                        ),
                        _field(
                            "Result Task ID",
                            dcc.Input(
                                id="quafu-result-task-id",
                                type="text",
                                value="",
                                placeholder="Optional: query existing task result first",
                                style=INPUT_STYLE,
                            ),
                            "When provided, the app first tries to fetch this task's bitstring before creating a new task.",
                            span=2,
                        ),
                    ],
                ),
            ],
        ),
        html.Div(
            style={**PANEL_STYLE, "marginBottom": "12px"},
            children=[
                html.Div(
                    "Execution",
                    style={"fontWeight": "700", "fontSize": "15px", "marginBottom": "10px", "color": "#1a3552"},
                ),
                html.Div(
                    style=GRID_STYLE,
                    children=[
                        _field(
                            "Wait For Quantum Result",
                            dcc.Dropdown(
                                id="quafu-wait",
                                options=[
                                    {"label": "Yes (sync)", "value": "true"},
                                    {"label": "No (submit only)", "value": "false"},
                                ],
                                value="true",
                                clearable=False,
                                style=INPUT_STYLE,
                            ),
                        ),
                        _field(
                            "SSL Verify",
                            dcc.Dropdown(
                                id="quafu-verify-ssl",
                                options=[
                                    {"label": "On", "value": "true"},
                                    {"label": "Off (diagnostic)", "value": "false"},
                                ],
                                value="true",
                                clearable=False,
                                style=INPUT_STYLE,
                            ),
                        ),
                        _field(
                            "Submit New Task",
                            html.Button("Submit / Run", id="submit-task-btn", n_clicks=0, style=BUTTON_STYLE),
                            "Classical mode runs locally; quantum mode submits a new task.",
                        ),
                        _field(
                            "Query Existing Task",
                            html.Button("Query Task", id="query-task-btn", n_clicks=0, style=BUTTON_STYLE),
                            "Requires Result Task ID and never submits a replacement task.",
                        ),
                        _field(
                            "Apply Manual Bitstring",
                            html.Button("Debug only", id="manual-task-btn", n_clicks=0, style={**BUTTON_STYLE, "background": "#8b5e00"}),
                            "MANUAL DEBUG source; excluded from formal statistics.",
                        ),
                    ],
                ),
            ],
        ),
        dcc.Loading(
            type="dot",
            children=[
                html.Div(
                    id="status-line",
                    children=_initial_status,
                    style=STATUS_BOX_STYLE,
                ),
                html.Div(
                    [dcc.Graph(id="route-graph", figure=_initial_figure, config={"displayModeBar": False})],
                    style=PANEL_STYLE,
                ),
                html.Div(
                    id="metrics-line",
                    children=_initial_metrics,
                    style=METRICS_BOX_STYLE,
                ),
                html.Div(id="table-area", children=_initial_table, style=PANEL_STYLE),
            ],
        ),
                    ],
                ),
                dcc.Tab(label="Candidate Quality", value="candidate-quality", children=[_candidate_quality_layout()]),
                dcc.Tab(label="Batch Experiment", value="batch", children=[_batch_layout()]),
                dcc.Tab(label="Experiment History", value="history", children=[_history_layout()]),
            ],
        ),
    ],
)


@app.callback(
    Output("status-line", "children"),
    Output("route-graph", "figure"),
    Output("metrics-line", "children"),
    Output("table-area", "children"),
    Input("submit-task-btn", "n_clicks"),
    Input("query-task-btn", "n_clicks"),
    Input("manual-task-btn", "n_clicks"),
    State("seed", "value"),
    State("customers", "value"),
    State("vehicles", "value"),
    State("capacity", "value"),
    State("mode", "value"),
    State("time-limit", "value"),
    State("quafu-token", "value"),
    State("quafu-backend", "value"),
    State("quafu-base-url", "value"),
    State("quafu-shots", "value"),
    State("quafu-max-qubits", "value"),
    State("quafu-wait", "value"),
    State("quafu-timeout-sec", "value"),
    State("quafu-proxy-url", "value"),
    State("quafu-verify-ssl", "value"),
    State("quafu-result-task-id", "value"),
    State("quafu-manual-bitstring", "value"),
)
def run_pipeline(
    _submit_clicks,
    _query_clicks,
    _manual_clicks,
    seed,
    customers,
    vehicles,
    capacity,
    mode,
    time_limit,
    quafu_token,
    quafu_backend,
    quafu_base_url,
    quafu_shots,
    quafu_max_qubits,
    quafu_wait,
    quafu_timeout_sec,
    quafu_proxy_url,
    quafu_verify_ssl,
    quafu_result_task_id,
    quafu_manual_bitstring,
):
    action_by_trigger = {
        "submit-task-btn": "submit",
        "query-task-btn": "query",
        "manual-task-btn": "manual",
    }
    quantum_action = action_by_trigger.get(ctx.triggered_id, "auto")
    return _generate_outputs(
        seed=seed,
        customers=customers,
        vehicles=vehicles,
        capacity=capacity,
        mode=mode,
        time_limit=time_limit,
        quafu_token=quafu_token,
        quafu_backend=quafu_backend,
        quafu_base_url=quafu_base_url,
        quafu_shots=quafu_shots,
        quafu_max_qubits=quafu_max_qubits,
        quafu_wait=quafu_wait,
        quafu_timeout_sec=quafu_timeout_sec,
        quafu_proxy_url=quafu_proxy_url,
        quafu_verify_ssl=quafu_verify_ssl,
        quafu_result_task_id=quafu_result_task_id,
        quafu_manual_bitstring=quafu_manual_bitstring,
        quantum_action=quantum_action,
    )


@app.callback(Output("quantum-connection-panel", "style"), Input("mode", "value"))
def toggle_quantum_connection(mode):
    style = {**PANEL_STYLE, "marginBottom": "12px"}
    if str(mode).lower() not in {"quantum", "quafu"}:
        style["display"] = "none"
    return style


@app.callback(
    Output("capacity-diagnostic", "children"),
    Input("seed", "value"),
    Input("customers", "value"),
    Input("vehicles", "value"),
    Input("capacity", "value"),
    Input("capacity-pressure", "value"),
)
def show_capacity_diagnostic(seed, customers, vehicles, capacity, pressure):
    seed = int(seed or 2026)
    customers = max(4, int(customers or 8))
    vehicles = max(1, int(vehicles or 2))
    recommended, demand = _capacity_for_pressure(seed, customers, vehicles, pressure or "medium")
    current = max(1, int(capacity or 1))
    feasible = current * vehicles >= demand
    return (
        f"Demand {demand} | fleet capacity {current * vehicles} | minimum {math.ceil(demand / vehicles)} "
        f"per vehicle | {str(pressure).title()} recommendation {recommended} | "
        f"{'FEASIBLE' if feasible else 'INFEASIBLE'}"
    )


@app.callback(
    Output("capacity", "value"),
    Input("auto-capacity-btn", "n_clicks"),
    State("seed", "value"),
    State("customers", "value"),
    State("vehicles", "value"),
    State("capacity-pressure", "value"),
    prevent_initial_call=True,
)
def set_auto_capacity(_clicks, seed, customers, vehicles, pressure):
    recommended, _demand = _capacity_for_pressure(
        int(seed or 2026),
        max(4, int(customers or 8)),
        max(1, int(vehicles or 2)),
        pressure or "medium",
    )
    return recommended


@app.callback(
    Output("cq-summary-cards", "children"),
    Output("cq-energy-graph", "figure"),
    Output("cq-conclusion", "children"),
    Output("cq-candidate-table", "data"),
    Output("cq-candidate-table", "columns"),
    Input("cq-load-btn", "n_clicks"),
    State("cq-evidence-path", "value"),
    State("cq-threshold-path", "value"),
    State("cq-seed", "value"),
    State("cq-customers", "value"),
    State("cq-pressure", "value"),
)
def load_candidate_quality(_clicks, evidence_path, threshold_path, seed, customers, pressure):
    try:
        seed = int(seed or 2026)
        customers = max(4, int(customers or 4))
        capacity, _demand = _capacity_for_pressure(seed, customers, 2, pressure or "medium")
        instance = generate_dispatch_instance(seed, customers, 2, capacity)
        selected = sorted(instance.customers, key=lambda customer: (-customer.demand, customer.customer_id))
        selected_ids = [customer.customer_id for customer in selected]
        measurement = measurement_from_evidence(
            Path(str(evidence_path)),
            source="replay",
            selected_customer_ids=selected_ids,
        )
        bqm = build_assignment_bqm(instance)
        thresholds = json.loads(Path(str(threshold_path)).read_text(encoding="utf-8"))
        preferred_ids = [
            f"seed{seed}_c{customers}_v2_{pressure}",
            f"seed{seed}_c{customers}_v2",
        ]
        info = None
        for instance_id in preferred_ids:
            if instance_id in thresholds.get("instances", {}):
                info = dict(thresholds["instances"][instance_id])
                selected_instance_id = instance_id
                break
        if info is None:
            selected_instance_id, raw_info = next(iter(thresholds.get("instances", {}).items()))
            info = dict(raw_info)
        if "best_classical_energy_all" not in info:
            info["best_classical_energy_all"] = info.get("threshold")
            info["best_classical_energy_feasible"] = info.get("threshold")
        if info.get("exact_optimum_energy") is None or info.get("random_median_energy") is None:
            info.update(exact_assignment_reference(instance, bqm, selected_customer_ids=selected_ids))
        evaluations, summary = evaluate_measurement(
            measurement,
            instance_id=selected_instance_id,
            instance=instance,
            bqm=bqm,
            threshold_info=info,
        )
        summary_dict = summary.to_dict()
        card_keys = [
            "shots_received",
            "unique_bitstrings",
            "raw_feasible_rate",
            "quality_hit_rate",
            "random_quality_hit_rate",
            "classical_reach_feasible_rate",
            "strict_improvement_rate",
            "best_gap",
        ]
        cards = [
            html.Div(
                [
                    html.Div(key.replace("_", " ").title(), style=LABEL_STYLE),
                    html.Div(
                        f"{summary_dict[key]:.4g}" if isinstance(summary_dict[key], float) else str(summary_dict[key]),
                        style={"fontSize": "24px", "fontWeight": "700"},
                    ),
                ],
                style=PANEL_STYLE,
            )
            for key in card_keys
        ]
        rows = [row.to_dict() for row in evaluations]
        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=[row.energy for row in evaluations],
                y=[row.probability for row in evaluations],
                mode="markers+text",
                text=[row.bitstring for row in evaluations],
                textposition="top center",
                marker={
                    "size": [8 + 35 * row.probability for row in evaluations],
                    "color": ["#1a8f5b" if row.quality_gate_pass else "#b54a4a" for row in evaluations],
                },
                name=measurement.source.upper(),
            )
        )
        for label, value, color in (
            ("Feasible classical threshold", info.get("best_classical_energy_feasible"), "#d97706"),
            ("Exact optimum", info.get("exact_optimum_energy"), "#2563eb"),
        ):
            if value is not None:
                figure.add_vline(x=float(value), line_dash="dash", line_color=color, annotation_text=label)
        figure.update_layout(
            template="plotly_white",
            title="Measured candidate probability versus BQM energy",
            xaxis_title="Quantum candidate energy (shared BQM evaluator)",
            yaxis_title="Probability",
            height=460,
        )
        columns = [{"name": key.replace("_", " ").title(), "id": key} for key in rows[0]] if rows else []
        source_label = measurement.source.upper().replace("_", " ")
        conclusion = f"{source_label} | {summary.decision}: {summary.conclusion}"
        return cards, figure, conclusion, rows, columns
    except Exception as exc:
        figure = go.Figure()
        figure.update_layout(template="plotly_white", height=250)
        return [], figure, f"NOT_EVALUABLE: {type(exc).__name__}: {exc}", [], []


def _batch_store(config_path, results_root):
    config = json.loads(Path(str(config_path)).read_text(encoding="utf-8"))
    return config, ResultStore(Path(str(results_root)), str(config["experiment_id"]))


@app.callback(
    Output("batch-control-output", "children"),
    Input("batch-preview-btn", "n_clicks"),
    Input("batch-start-btn", "n_clicks"),
    Input("batch-resume-btn", "n_clicks"),
    Input("batch-pause-btn", "n_clicks"),
    State("batch-config-path", "value"),
    State("batch-results-root", "value"),
    State("batch-max-tasks", "value"),
    State("batch-confirm-live", "value"),
    prevent_initial_call=True,
)
def control_batch(
    _preview,
    _start,
    _resume,
    _pause,
    config_path,
    results_root,
    max_tasks,
    live_confirmation,
):
    try:
        config, store = _batch_store(config_path, results_root)
        trigger = ctx.triggered_id
        if trigger == "batch-preview-btn":
            specs = expand_matrix(config)
            return (
                f"DRY RUN: {len(specs)} tasks, {sum(spec.shots for spec in specs)} requested shots. "
                f"Fixed backends: {', '.join(sorted({spec.backend for spec in specs}))}. "
                f"No hardware task was submitted."
            )
        pause_path = store.path / ".pause"
        if trigger == "batch-pause-btn":
            pause_path.write_text("pause requested\n", encoding="utf-8")
            return "Pause requested; the runner will stop before the next task."
        if pause_path.exists():
            pause_path.unlink()
        if "confirmed" not in (live_confirmation or []):
            return (
                "BLOCKED: review the dry run and check the live-confirmation box before "
                "submitting one fresh hardware task."
            )
        command = [
            sys.executable,
            str(ROOT / "experiments" / "batch_candidate_quality.py"),
            "--config",
            str(config_path),
            "--results-root",
            str(results_root),
            "--max-hardware-tasks",
            "1",
            "--confirm-live",
        ]
        if trigger == "batch-resume-btn":
            command.append("--resume")
        log_path = store.logs_dir / "batch_ui.log"
        with log_path.open("ab") as log_stream:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return f"Background batch started (pid={process.pid}). Progress is read from the result store."
    except Exception as exc:
        return f"Batch control error: {type(exc).__name__}: {exc}"


@app.callback(
    Output("batch-progress-output", "children"),
    Input("batch-progress-interval", "n_intervals"),
    State("batch-config-path", "value"),
    State("batch-results-root", "value"),
)
def refresh_batch_progress(_interval, config_path, results_root):
    try:
        _config, store = _batch_store(config_path, results_root)
        return json.dumps(
            {"integrity": store.integrity_report(), "latest_tasks": list(store.latest_tasks_by_hash().values())[-20:]},
            ensure_ascii=False,
            indent=2,
        )
    except Exception as exc:
        return f"No progress available: {type(exc).__name__}: {exc}"


@app.callback(
    Output("history-table", "data"),
    Output("history-table", "columns"),
    Input("history-refresh-btn", "n_clicks"),
    State("history-results-root", "value"),
)
def refresh_history(_clicks, results_root):
    rows = list_experiments(Path(str(results_root)))
    columns = [{"name": key.replace("_", " ").title(), "id": key} for key in rows[0]] if rows else []
    return rows, columns


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Quantum Route Forge web app.")
    parser.add_argument("--port", type=int, default=8050, help="Port for Dash server.")
    parser.add_argument("--debug", action="store_true", help="Enable Dash debug mode.")
    args = parser.parse_args()
    app.run(port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
