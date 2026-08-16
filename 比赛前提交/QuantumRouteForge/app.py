from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html, no_update
from dotenv import load_dotenv
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
PROJECT_ENV_FILE = ROOT / ".env"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quantum_route_forge.competition_history import CompetitionHistory  # noqa: E402
from quantum_route_forge.deepblock_service import run_deepblock_optimization  # noqa: E402
from quantum_route_forge.scenario import generate_dispatch_instance  # noqa: E402


COLORS = ["#2f80ed", "#7c5cfc", "#f2a93b", "#22a06b", "#e65f8e", "#5b8def"]
INK = "#183153"
MUTED = "#6e809b"
PANEL = {
    "background": "linear-gradient(145deg, rgba(255,255,255,.99), rgba(248,251,255,.99))",
    "border": "1px solid #dce6f2",
    "borderRadius": "18px",
    "boxShadow": "0 14px 38px rgba(67,90,124,.10)",
}
HISTORY = CompetitionHistory(ROOT / "results" / "competition_history")
CHINA_STANDARD_TIME = timezone(timedelta(hours=8))
MODE_DISPLAY_NAMES = {
    "deepblock_hardware": "DeepBlock Hardware",
    "deepblock_random": "Random Baseline",
    "deepblock_simulator": "Ideal Simulator",
    "deepblock_exact": "Exact Baseline",
}
STATUS_DISPLAY_NAMES = {
    "COMPLETED": "已完成",
    "FAILED": "失败",
    "NOT_EVALUABLE": "不可评估",
    "PENDING": "等待中",
}


def _configure_quafu_token(env_file: Path = PROJECT_ENV_FILE) -> str:
    """Load the project-local .env without logging or returning the credential."""
    had_environment_token = bool(os.getenv("QUAFU_API_TOKEN", "").strip())
    load_dotenv(dotenv_path=env_file, override=False)
    if not os.getenv("QUAFU_API_TOKEN", "").strip():
        return "missing"
    return "environment" if had_environment_token else "project_env"


QUAFU_TOKEN_SOURCE = _configure_quafu_token()


def _format_china_time(raw_time: Any, *, compact: bool = False) -> str:
    """Render stored timestamps consistently in China Standard Time."""
    value = str(raw_time or "").strip()
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        localized = parsed.astimezone(CHINA_STANDARD_TIME)
    except ValueError:
        return value
    if compact:
        return localized.strftime("%m-%d %H:%M")
    return localized.strftime("%Y-%m-%d %H:%M:%S")


def _display_mode(mode: Any) -> str:
    value = str(mode or "").strip()
    return MODE_DISPLAY_NAMES.get(value, value.replace("_", " ").title() or "Unknown")


def _run_summary(payload: dict[str, Any], lead: str) -> str:
    """Build a human-readable status banner without exposing internal IDs."""
    selected = payload.get("selected") or {}
    parameters = payload.get("parameters") or {}
    status = str(selected.get("status") or "UNKNOWN").upper()
    baseline = selected.get("baseline_distance", payload.get("initial", {}).get("distance"))
    final = selected.get("final_distance")
    distance = (
        f"{float(baseline):.3f} → {float(final):.3f}"
        if baseline is not None and final is not None
        else "—"
    )
    accepted = int(selected.get("accepted_moves") or 0)
    return (
        f"{lead} · {_display_mode(parameters.get('mode'))} · "
        f"{STATUS_DISPLAY_NAMES.get(status, status)} · 路线距离 {distance} · "
        f"接受改进 {accepted} 次"
    )


def _overlapping_trajectories(trajectories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return groups whose complete x/y trajectories overlap visually."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for trajectory in trajectories:
        xs = list(trajectory.get("xs") or [])
        ys = [round(float(value), 9) for value in (trajectory.get("ys") or [])]
        key = tuple(zip(xs, ys))
        groups.setdefault(key, []).append(trajectory)
    return [
        {
            "names": [row["name"] for row in rows],
            "x": rows[0]["xs"][-1],
            "y": rows[0]["ys"][-1],
        }
        for rows in groups.values()
        if len(rows) > 1 and rows[0].get("xs") and rows[0].get("ys")
    ]


def _history_option_label(row: dict[str, Any]) -> str:
    """Build a compact, single-line label for the history selector."""
    display_time = _format_china_time(row.get("time"), compact=True)
    mode = _display_mode(row.get("mode"))
    status = str(row.get("status") or "UNKNOWN").upper()
    run_id = str(row.get("run_id") or "")
    short_id = run_id.rsplit("-", 1)[-1] if run_id else "--------"
    return f"{display_time} | {mode} | {status} | {short_id}"


def _latest_history_payload():
    try:
        rows = HISTORY.rows()
        return HISTORY.load(rows[0]["run_id"]) if rows else None
    except (OSError, ValueError, KeyError):
        return None


INITIAL_PAYLOAD = _latest_history_payload()


def _initial_status_text():
    if not INITIAL_PAYLOAD:
        return "尚未运行。Hardware 未明确确认时仅进行 dry-run，不会提交任务。"
    return _run_summary(INITIAL_PAYLOAD, "最近一次运行")


def _field(label: str, control, hint: str = ""):
    return html.Div(
        [
            html.Label(label, style={"fontSize": "13px", "fontWeight": 700, "color": "#405b7d"}),
            control,
            html.Small(hint, style={"color": "#7b8da6", "lineHeight": "1.25"}) if hint else None,
        ],
        style={"display": "flex", "flexDirection": "column", "gap": "6px"},
    )


def _number(component_id: str, value: int, minimum: int, maximum: int, step: int = 1):
    return dcc.Input(
        id=component_id,
        type="number",
        value=value,
        min=minimum,
        max=maximum,
        step=step,
        style={"width": "100%", "height": "38px"},
    )


def _empty_figure(title: str, subtitle: str = "运行后显示"):
    figure = go.Figure()
    figure.add_annotation(
        text=f"<b>{title}</b><br><span style='font-size:13px;color:#7188aa'>{subtitle}</span>",
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"color": "#7186a2", "size": 17},
    )
    figure.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=410,
        margin={"l": 25, "r": 25, "t": 40, "b": 25},
        xaxis={"visible": False},
        yaxis={"visible": False},
    )
    return figure


def _route_figure(instance: dict[str, Any], routes: list[dict[str, Any]], title: str):
    figure = go.Figure()
    depot = instance.get("depot", [0, 0])
    figure.add_trace(
        go.Scatter(
            x=[depot[0]],
            y=[depot[1]],
            mode="markers+text",
            text=["DEPOT"],
            textposition="top center",
            name="Depot",
            marker={"size": 19, "symbol": "star", "color": "#183153", "line": {"color": "#73b8ff", "width": 2}},
        )
    )
    for index, route in enumerate(routes or []):
        customers = route.get("customers", [])
        xs = [depot[0]] + [row["x"] for row in customers] + [depot[0]]
        ys = [depot[1]] + [row["y"] for row in customers] + [depot[1]]
        labels = ["Depot"] + [f"C{row['customer_id']} · d={row['demand']}" for row in customers] + ["Depot"]
        figure.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines+markers",
                name=f"车辆 {route.get('vehicle_id')}",
                text=labels,
                hovertemplate="%{text}<br>x=%{x:.2f}, y=%{y:.2f}<extra></extra>",
                line={"width": 2.6, "color": COLORS[index % len(COLORS)]},
                marker={"size": 8, "color": COLORS[index % len(COLORS)]},
            )
        )
    figure.update_layout(
        template="plotly_white",
        title={"text": title, "x": 0.03, "font": {"size": 17}},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#fbfdff",
        height=440,
        margin={"l": 35, "r": 20, "t": 55, "b": 35},
        legend={"orientation": "h", "y": -0.14},
        font={"color": INK},
        xaxis={"gridcolor": "#e8eef6", "zeroline": False},
        yaxis={"gridcolor": "#e8eef6", "zeroline": False, "scaleanchor": "x", "scaleratio": 1},
    )
    return figure


def _metric(label: str, value: str, tone: str = "#2f80ed"):
    return html.Div(
        [
            html.Div(label, style={"fontSize": "12px", "letterSpacing": "1px", "textTransform": "uppercase", "color": MUTED}),
            html.Div(value, style={"fontSize": "26px", "fontWeight": 800, "color": tone, "marginTop": "5px"}),
        ],
        style={**PANEL, "padding": "15px 17px", "minHeight": "70px"},
    )


def _table(
    component_id: str,
    page_size: int = 10,
    column_widths: dict[str, str] | None = None,
    fill_width: bool = False,
):
    widths = {
        "run_id": "230px",
        "time": "175px",
        "task_id": "260px",
        "task_ids": "300px",
        **(column_widths or {}),
    }
    return dash_table.DataTable(
        id=component_id,
        data=[],
        columns=[],
        page_size=page_size,
        fill_width=fill_width,
        sort_action="native",
        filter_action="native",
        filter_options={"case": "insensitive", "placeholder_text": "筛选…"},
        style_table={"overflowX": "auto", "borderRadius": "12px", "width": "100%"},
        style_header={
            "backgroundColor": "#edf4fc",
            "color": "#294866",
            "fontWeight": 700,
            "border": "1px solid #d5e1ef",
        },
        style_cell={
            "backgroundColor": "#ffffff",
            "color": "#405b7d",
            "border": "1px solid #e0e8f2",
            "fontFamily": "Segoe UI, Microsoft YaHei, sans-serif",
            "fontSize": "13px",
            "lineHeight": "1.4",
            "padding": "10px",
            "textAlign": "left",
            "minWidth": "90px",
            "maxWidth": "360px",
            "whiteSpace": "normal",
            "height": "auto",
            "overflowWrap": "anywhere",
        },
        style_cell_conditional=[
            {
                "if": {"column_id": column_id},
                "minWidth": width,
                "width": width,
                "maxWidth": width,
            }
            for column_id, width in widths.items()
        ] + [
            {
                "if": {"column_id": column_id},
                "whiteSpace": "nowrap",
                "overflowX": "auto",
                "overflowY": "hidden",
                "textOverflow": "clip",
            }
            for column_id in ("run_id", "time", "task_id", "task_ids")
        ],
        style_data_conditional=[
            {"if": {"filter_query": "{accepted} = true"}, "backgroundColor": "#e8f8f1", "color": "#137b55"}
        ],
    )


controls = html.Div(
    [
        html.Div(
            [
                html.Div("RUN CONFIG", style={"fontSize": "12px", "letterSpacing": "2px", "color": "#2f80ed"}),
                html.H3("同条件公平对照", style={"margin": "5px 0 0", "fontSize": "20px"}),
            ]
        ),
        html.Div(
            [
                _field("客户数", _number("num-customers", 16, 4, 60)),
                _field("车辆数", _number("num-vehicles", 3, 2, 10)),
                _field("车辆容量", _number("vehicle-capacity", 24, 2, 100)),
                _field("Seed", _number("seed", 2026, 0, 999999)),
                _field(
                    "运行模式",
                    dcc.Dropdown(
                        id="mode",
                        value="deepblock_simulator",
                        clearable=False,
                        options=[
                            {"label": "DeepBlock Hardware · Baihua", "value": "deepblock_hardware"},
                            {"label": "Uniform Random", "value": "deepblock_random"},
                            {"label": "Ideal Simulator", "value": "deepblock_simulator"},
                            {"label": "Local Exact", "value": "deepblock_exact"},
                        ],
                    ),
                ),
                _field("Backend", dcc.Input(id="backend", value="Baihua", style={"width": "100%", "height": "38px"})),
                _field("Shots", _number("shots", 4096, 1, 100000)),
                _field("Top-k", _number("candidate-k", 64, 1, 256)),
                _field(
                    "QAOA depth",
                    dcc.Dropdown(
                        id="qaoa-depth",
                        value=1,
                        clearable=False,
                        options=[{"label": f"p = {value}", "value": value} for value in (1, 2, 3)],
                    ),
                ),
            ],
            style={"display": "grid", "gridTemplateColumns": "repeat(3, minmax(135px, 1fr))", "gap": "12px", "marginTop": "16px"},
        ),
        dcc.Checklist(
            id="hardware-confirm",
            options=[
                {
                    "label": " 我确认：Hardware 模式将真实提交最多 3 个 Baihua 任务",
                    "value": "confirm",
                }
            ],
            value=[],
            style={"fontSize": "13px", "color": "#a86800", "marginTop": "13px"},
        ),
        html.Div(
            [
                html.Button("运行 DeepBlock 对照", id="run-btn", n_clicks=0, className="run-button"),
                html.Div("同一实例 · 同一初始分配 · 同一 Top-k · 严格改善才接受", style={"fontSize": "12px", "color": MUTED}),
            ],
            style={"display": "flex", "alignItems": "center", "gap": "15px", "marginTop": "14px"},
        ),
    ],
    style={**PANEL, "padding": "20px"},
)


route_page = html.Div(
    [
        html.Div(id="metric-row", style={"display": "grid", "gridTemplateColumns": "repeat(5, 1fr)", "gap": "12px"}),
        html.Div(
            [
                html.Div(dcc.Graph(id="initial-route", figure=_empty_figure("初始路线")), style={**PANEL, "padding": "5px"}),
                html.Div(dcc.Graph(id="final-route", figure=_empty_figure("最终路线")), style={**PANEL, "padding": "5px"}),
            ],
            style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "14px", "marginTop": "14px"},
        ),
        html.Div(
            [
                html.H3("车辆路线明细"),
                _table(
                    "route-table",
                    10,
                    fill_width=True,
                ),
            ],
            style={**PANEL, "padding": "18px", "marginTop": "14px"},
        ),
    ]
)


process_page = html.Div(
    [
        html.Div(
            [
                html.Div([html.Div("DEEPBLOCK TRACE", className="eyebrow"), html.H2("B1 · B2 · B3 扫描过程", style={"margin": "6px 0"})]),
                html.Div(id="process-badges", style={"display": "flex", "gap": "8px", "flexWrap": "wrap"}),
            ],
            style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
        ),
        html.Div(
            [
                html.H3("Block 与接受决策"),
                _table(
                    "block-table",
                    10,
                    {
                        "sequence": "80px", "block": "65px", "vehicle_pair": "105px", "customers": "220px",
                        "width": "65px", "depth": "65px", "backend": "90px", "shots": "75px",
                        "accepted": "90px", "distance": "105px", "decision": "360px", "status": "105px",
                    },
                ),
            ],
            style={**PANEL, "padding": "18px", "marginTop": "14px"},
        ),
        html.Div(
            [
                html.H3("Top-k 候选（逐 bitstring 真路线评价）"),
                _table(
                    "candidate-table",
                    16,
                    fill_width=True,
                ),
            ],
            style={**PANEL, "padding": "18px", "marginTop": "14px"},
        ),
        html.Details(
            [
                html.Summary("查看完整 counts / QASM / 编译审计", style={"cursor": "pointer", "fontWeight": 700, "color": "#2f80ed"}),
                html.Pre(id="evidence-json", style={"whiteSpace": "pre-wrap", "fontSize": "12px", "lineHeight": "1.5", "color": "#5f7390", "maxHeight": "560px", "overflow": "auto"}),
            ],
            style={**PANEL, "padding": "18px", "marginTop": "14px"},
        ),
    ]
)


comparison_page = html.Div(
    [
        html.Div(id="fairness-strip", style={**PANEL, "padding": "14px 18px"}),
        html.Div(
            [
                html.Div(dcc.Graph(id="comparison-bars", figure=_empty_figure("最终距离对比")), style={**PANEL, "padding": "5px"}),
                html.Div(dcc.Graph(id="scan-lines", figure=_empty_figure("扫描距离变化")), style={**PANEL, "padding": "5px"}),
            ],
            style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "14px", "marginTop": "14px"},
        ),
        html.Div(
            [
                html.H3("Initial / Hardware / Random / Simulator / Exact"),
                _table(
                    "comparison-table",
                    10,
                    fill_width=True,
                ),
            ],
            style={**PANEL, "padding": "18px", "marginTop": "14px"},
        ),
    ]
)


history_page = html.Div(
    [
        html.Div(
            [
                html.Div([html.Div("LOCAL HISTORY", className="eyebrow"), html.H2("运行历史与证据重载", style={"margin": "6px 0"})]),
                html.Div(
                    [
                        dcc.Dropdown(
                            id="history-run-id",
                            placeholder="选择运行记录",
                            className="history-dropdown",
                            style={"width": "520px", "maxWidth": "65vw"},
                        ),
                        html.Button("重新打开", id="open-history-btn", n_clicks=0, className="secondary-button"),
                        html.Button("刷新", id="refresh-history-btn", n_clicks=0, className="secondary-button"),
                    ],
                    style={"display": "flex", "gap": "10px", "alignItems": "center", "flexWrap": "wrap"},
                ),
            ],
            style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
        ),
        html.Div(
            [
                _table(
                    "history-table",
                    12,
                    {
                        "seed": "75px", "customers": "95px", "vehicles": "85px", "mode": "155px",
                        "source": "100px", "backend": "90px", "shots": "75px", "initial_distance": "130px",
                        "final_distance": "125px", "improvement_pct": "125px", "status": "110px",
                    },
                )
            ],
            style={**PANEL, "padding": "18px", "marginTop": "14px"},
        ),
        html.Div(id="history-detail", style={**PANEL, "padding": "18px", "marginTop": "14px"}),
    ]
)


app = Dash(__name__, title="Quantum Route Forge · DeepBlock", suppress_callback_exceptions=True)
app.layout = html.Div(
    [
        dcc.Store(id="run-store", data=INITIAL_PAYLOAD),
        html.Div(
            [
                html.Div(
                    [
                        html.Div("QRF", className="logo-mark"),
                        html.Div(
                            [
                                html.Div("QUANTUM ROUTE FORGE", className="eyebrow"),
                                html.H1("Baihua DeepBlock 控制台", style={"margin": "3px 0", "fontSize": "30px"}),
                                html.Div("可复核的量子候选生成 · 经典约束修复 · 真实路线单调接受", style={"color": MUTED}),
                            ]
                        ),
                    ],
                    style={"display": "flex", "gap": "16px", "alignItems": "center"},
                ),
                html.Div(
                    [
                        html.Span("Baihua", className="status-pill"),
                        html.Span("≤ 8 qubits / block", className="status-pill"),
                        html.Span("Hardware ≠ fallback", className="status-pill"),
                    ],
                    style={"display": "flex", "gap": "8px"},
                ),
            ],
            style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "18px"},
        ),
        controls,
        html.Div(id="run-status", children=_initial_status_text(), className="status-banner"),
        dcc.Tabs(
            id="tabs",
            value="route",
            children=[
                dcc.Tab(label="01  路线优化", value="route", children=[route_page]),
                dcc.Tab(label="02  DeepBlock 过程", value="process", children=[process_page]),
                dcc.Tab(label="03  方法对比", value="comparison", children=[comparison_page]),
                dcc.Tab(label="04  运行历史", value="history", children=[history_page]),
            ],
        ),
        html.Div(
            "Quantum Route Forge · competition/deepblock-ui-integration · Hardware failures never become Exact results",
            style={"textAlign": "center", "color": "#8291a7", "fontSize": "12px", "padding": "28px 0 10px"},
        ),
    ],
    style={"maxWidth": "1500px", "margin": "0 auto", "padding": "24px", "color": INK},
)


@app.callback(
    Output("run-store", "data"),
    Output("run-status", "children"),
    Input("run-btn", "n_clicks"),
    Input("open-history-btn", "n_clicks"),
    State("history-run-id", "value"),
    State("num-customers", "value"),
    State("num-vehicles", "value"),
    State("vehicle-capacity", "value"),
    State("seed", "value"),
    State("mode", "value"),
    State("backend", "value"),
    State("shots", "value"),
    State("candidate-k", "value"),
    State("qaoa-depth", "value"),
    State("hardware-confirm", "value"),
    prevent_initial_call=True,
)
def execute_or_open(
    _run_clicks,
    _open_clicks,
    history_run_id,
    num_customers,
    num_vehicles,
    vehicle_capacity,
    seed,
    mode,
    backend,
    shots,
    candidate_k,
    qaoa_depth,
    hardware_confirm,
):
    if ctx.triggered_id == "open-history-btn":
        if not history_run_id:
            return no_update, "请选择一个历史 run ID。"
        try:
            payload = HISTORY.load(history_run_id)
            return payload, _run_summary(payload, "历史结果已载入")
        except Exception as exc:
            return no_update, f"历史结果读取失败：{type(exc).__name__}: {exc}"
    try:
        instance = generate_dispatch_instance(
            seed=int(seed),
            num_customers=int(num_customers),
            num_vehicles=int(num_vehicles),
            vehicle_capacity=int(vehicle_capacity),
        )
        confirmed = "confirm" in (hardware_confirm or [])
        quafu_token = os.getenv("QUAFU_API_TOKEN", "").strip()
        if mode == "deepblock_hardware" and confirmed and not quafu_token:
            raise RuntimeError(f"QUAFU_API_TOKEN is missing from {PROJECT_ENV_FILE}")
        payload = run_deepblock_optimization(
            instance=instance,
            mode=mode,
            backend=backend,
            shots=int(shots),
            candidate_k=int(candidate_k),
            qaoa_depth=int(qaoa_depth),
            pool_size=16,
            block_size=8,
            overlap=3,
            seed=int(seed),
            api_token=quafu_token,
            submit_hardware=(mode == "deepblock_hardware" and confirmed),
            confirm_hardware_submit=(mode == "deepblock_hardware" and confirmed),
            history_root=HISTORY.root,
        )
        return (
            payload,
            _run_summary(payload, "运行结果"),
        )
    except Exception as exc:
        return no_update, f"运行失败：{type(exc).__name__}: {exc}"


@app.callback(
    Output("metric-row", "children"),
    Output("initial-route", "figure"),
    Output("final-route", "figure"),
    Output("route-table", "data"),
    Output("route-table", "columns"),
    Output("block-table", "data"),
    Output("block-table", "columns"),
    Output("candidate-table", "data"),
    Output("candidate-table", "columns"),
    Output("process-badges", "children"),
    Output("evidence-json", "children"),
    Output("comparison-bars", "figure"),
    Output("scan-lines", "figure"),
    Output("comparison-table", "data"),
    Output("comparison-table", "columns"),
    Output("fairness-strip", "children"),
    Output("history-detail", "children"),
    Input("run-store", "data"),
)
def render_run(payload):
    if not payload:
        metrics = [
            _metric("Initial", "—"),
            _metric("Final", "—"),
            _metric("Improvement", "—"),
            _metric("Accepted", "—"),
            _metric("Source", "—", "#6b50d9"),
        ]
        empty = _empty_figure("等待 DeepBlock 运行")
        return (
            metrics,
            empty,
            empty,
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            "{}",
            empty,
            empty,
            [],
            [],
            "公平性参数将在运行后锁定。",
            "选择历史记录可查看完整详情。",
        )

    instance = payload["instance"]
    initial = payload["initial"]
    selected = payload["selected"]
    improvement = float(selected.get("improvement", 0.0))
    metrics = [
        _metric("Initial distance", f"{initial['distance']:.3f}", "#183153"),
        _metric("Final distance", f"{selected['final_distance']:.3f}", "#2f80ed"),
        _metric("Improvement", f"{improvement:.3f} · {selected['improvement_pct']:.2f}%", "#168f62" if improvement > 0 else "#b87513"),
        _metric("Accepted moves", str(selected.get("accepted_moves", 0)), "#b87513"),
        _metric("Source / status", f"{selected.get('source')} · {selected.get('status')}", "#6b50d9"),
    ]
    initial_figure = _route_figure(instance, initial.get("routes", []), "容量约束初始路线")
    final_figure = _route_figure(instance, selected.get("routes", []), "DeepBlock 最终路线")

    route_rows = [
        {
            "vehicle": route["vehicle_id"],
            "customers": " → ".join(f"C{value}" for value in route["customer_ids"]) or "—",
            "load": route["load"],
            "capacity": instance["vehicle_capacity"],
            "distance": round(route["distance"], 6),
        }
        for route in selected.get("routes", [])
    ]
    route_columns = [{"name": name, "id": key} for name, key in [
        ("车辆", "vehicle"), ("客户顺序", "customers"), ("载荷", "load"), ("容量", "capacity"), ("距离", "distance")
    ]]

    block_rows = []
    candidate_rows = []
    evidence = []
    for trace in selected.get("traces", []):
        block = trace["block"]
        run = trace["run"]
        batch = trace.get("candidates") or {}
        block_rows.append(
            {
                "sequence": trace["sequence"],
                "block": block["block_id"],
                "vehicle_pair": str(block["vehicle_pair"]),
                "customers": str(block["customer_ids"]),
                "width": block["width"],
                "depth": run["parameters"]["depth"],
                "task_id": run.get("task_id") or "—",
                "backend": run.get("backend") or "—",
                "shots": sum(run.get("counts", {}).values()),
                "accepted": trace["accepted"],
                "distance": round(trace["distance_after"], 6),
                "decision": trace["decision"],
                "status": trace["status"],
            }
        )
        for rank, row in enumerate(batch.get("top_frequency", []), start=1):
            candidate_rows.append(
                {
                    "block": block["block_id"],
                    "rank": rank,
                    "bitstring": row["bitstring"],
                    "count": row["count"],
                    "probability": round(row["probability"], 6),
                    "proxy_energy": round(row["proxy_energy"], 6),
                    "feasible": row["feasible_after_repair"],
                    "repaired": row["repaired"],
                    "repair": row["repair_summary"],
                    "true_distance": round(row["true_distance"], 6),
                    "improvement": round(row["improvement"], 6),
                    "accepted": bool(batch.get("accepted") and batch["accepted"]["bitstring"] == row["bitstring"]),
                }
            )
        evidence.append(
            {
                "block": block,
                "source": trace["source"],
                "status": trace["status"],
                "task_id": run.get("task_id"),
                "backend": run.get("backend"),
                "shots": run.get("shots"),
                "counts": run.get("counts"),
                "qasm": run.get("qasm"),
                "physical_qasm": run.get("physical_qasm"),
                "compilation": run.get("compilation"),
                "message": run.get("message"),
            }
        )
    block_columns = [{"name": key.replace("_", " ").title(), "id": key} for key in (block_rows[0].keys() if block_rows else [])]
    candidate_columns = [{"name": key.replace("_", " ").title(), "id": key} for key in (candidate_rows[0].keys() if candidate_rows else [])]
    badges = [
        html.Span(f"source={selected.get('source')}", className="status-pill"),
        html.Span(f"backend={selected.get('backend') or '—'}", className="status-pill"),
        html.Span(f"tasks={len(selected.get('task_ids', []))}", className="status-pill"),
        html.Span(f"shots received={selected.get('shots_received', 0)}", className="status-pill"),
    ]
    quantum_effect = payload.get("quantum_effect") or {}
    if quantum_effect.get("evaluable"):
        badges.extend(
            [
                html.Span(
                    f"最低10%能量质量={100 * quantum_effect['mean_hardware_mass']:.2f}%",
                    className="status-pill",
                ),
                html.Span(
                    f"相对均匀随机={quantum_effect['enrichment']:.2f}×",
                    className="status-pill",
                ),
            ]
        )

    comparisons = payload.get("comparisons", [])
    bar = go.Figure(
        go.Bar(
            x=[row["method"] for row in comparisons],
            y=[
                row["final_distance"]
                if row["status"] == "COMPLETED"
                else None
                for row in comparisons
            ],
            text=[
                f"{row['final_distance']:.2f}"
                if row["status"] == "COMPLETED"
                else "N/E"
                for row in comparisons
            ],
            textposition="outside",
            marker={"color": ["#8291a7", "#7c5cfc", "#f2a93b", "#2f80ed", "#22a06b"]},
        )
    )
    bar.update_layout(
        template="plotly_white",
        title="最终真实路线距离（越低越好）",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#fbfdff",
        height=410,
        margin={"l": 45, "r": 20, "t": 55, "b": 35},
        font={"color": INK},
        yaxis={"gridcolor": "#e8eef6"},
    )
    scan = go.Figure()
    trajectories = []
    for index, (arm_mode, arm) in enumerate(payload.get("arms", {}).items()):
        ys = [arm["baseline_distance"]] + [trace["distance_after"] for trace in arm.get("traces", [])]
        xs = ["Initial"] + [f"{trace['block']['block_id']}·{trace['sequence']}" for trace in arm.get("traces", [])]
        display_name = _display_mode(arm_mode)
        trajectories.append({"name": display_name, "xs": xs, "ys": ys})
        scan.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines+markers",
                name=display_name,
                line={"color": COLORS[index % len(COLORS)], "width": 2.4},
            )
        )
    for index, overlap in enumerate(_overlapping_trajectories(trajectories)):
        scan.add_annotation(
            x=overlap["x"],
            y=overlap["y"],
            text="<b>曲线完全重合</b><br>" + " = ".join(overlap["names"]),
            showarrow=True,
            arrowhead=2,
            arrowcolor="#5f7390",
            ax=-125,
            ay=-55 - 42 * index,
            align="left",
            bgcolor="rgba(255,255,255,.94)",
            bordercolor="#cddbed",
            borderpad=7,
            font={"size": 11, "color": "#405b7d"},
        )
    scan.update_layout(
        template="plotly_white",
        title="各方法扫描距离变化",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#fbfdff",
        height=410,
        margin={"l": 45, "r": 20, "t": 55, "b": 35},
        font={"color": INK},
        yaxis={"gridcolor": "#e8eef6"},
    )
    comparison_rows = [
        {
            "method": row["method"],
            "source": row["source"],
            "status": row["status"],
            "final_distance": round(row["final_distance"], 6),
            "improvement": round(row["improvement"], 6),
            "improvement_pct": round(row["improvement_pct"], 3),
            "accepted_moves": row["accepted_moves"],
            "task_ids": ", ".join(row.get("task_ids", [])) or "—",
        }
        for row in comparisons
    ]
    comparison_columns = [{"name": key.replace("_", " ").title(), "id": key} for key in comparison_rows[0]]
    fairness = payload.get("fairness", {})
    fairness_text = html.Div(
        [
            html.Strong("公平性锁定：", style={"color": "#2f80ed"}),
            html.Span("  相同实例 / 初始分配 / B1-B3 / shots / Top-k / 修复 / 路线评价器 / 严格接受规则"),
            html.Span("  ·  全部通过" if all(fairness.values()) else "  ·  请检查", style={"color": "#168f62"}),
        ]
    )
    history_detail = html.Div(
        [
            html.H3(f"当前结果 · {payload.get('run_id')}"),
            html.P(
                f"{_format_china_time(payload.get('created_at'))} · seed={payload['parameters']['seed']} · "
                f"{payload['parameters']['num_customers']} customers · {payload['parameters']['num_vehicles']} vehicles",
                style={"color": MUTED},
            ),
            html.P(
                f"source={selected.get('source')} · backend={selected.get('backend') or '—'} · "
                f"task IDs={', '.join(selected.get('task_ids', [])) or '—'} · status={selected.get('status')}"
            ),
            (
                html.P(
                    f"最低10% QUBO 能量区域：Hardware "
                    f"{100 * quantum_effect['mean_hardware_mass']:.2f}% vs Uniform "
                    f"{100 * quantum_effect['mean_uniform_mass']:.2f}% · "
                    f"{quantum_effect['enrichment']:.2f}× · "
                    f"{quantum_effect['positive_blocks']}/{quantum_effect['total_blocks']} blocks 为正向",
                    style={"color": "#168f62", "fontWeight": 700},
                )
                if quantum_effect.get("evaluable")
                else None
            ),
            html.P("Warnings: " + (" | ".join(payload.get("warnings", [])) or "none"), style={"color": "#a86800"}),
        ]
    )
    return (
        metrics,
        initial_figure,
        final_figure,
        route_rows,
        route_columns,
        block_rows,
        block_columns,
        candidate_rows,
        candidate_columns,
        badges,
        json.dumps(evidence, ensure_ascii=False, indent=2),
        bar,
        scan,
        comparison_rows,
        comparison_columns,
        fairness_text,
        history_detail,
    )


@app.callback(
    Output("history-table", "data"),
    Output("history-table", "columns"),
    Output("history-run-id", "options"),
    Input("refresh-history-btn", "n_clicks"),
    Input("run-store", "data"),
)
def refresh_history(_clicks, _payload):
    source_rows = HISTORY.rows()
    rows = [
        {
            **row,
            "time": _format_china_time(row.get("time")),
            "mode": _display_mode(row.get("mode")),
        }
        for row in source_rows
    ]
    column_labels = {
        "run_id": "Run ID",
        "time": "时间",
        "task_id": "Task ID",
        "improvement_pct": "Improvement %",
    }
    columns = [
        {"name": column_labels.get(key, key.replace("_", " ").title()), "id": key}
        for key in (rows[0].keys() if rows else [])
    ]
    options = [
        {"label": _history_option_label(row), "value": row["run_id"]}
        for row in source_rows
    ]
    return rows, columns, options


app.index_string = """
<!DOCTYPE html>
<html>
  <head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <style>
      :root { color-scheme: light; }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-size: 15px;
        line-height: 1.45;
        background:
          radial-gradient(circle at 12% 4%, rgba(95,171,255,.20), transparent 31%),
          radial-gradient(circle at 88% 0%, rgba(151,123,255,.14), transparent 28%),
          linear-gradient(180deg, #f7faff 0%, #f3f6fb 100%);
        font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
      }
      .logo-mark {
        width: 54px; height: 54px; display: grid; place-items: center;
        border-radius: 16px; color: #ffffff; font-weight: 900; letter-spacing: -1px;
        background: linear-gradient(145deg,#3da7f5,#7c5cfc);
        box-shadow: 0 10px 28px rgba(67,124,218,.22);
      }
      .eyebrow { font-size: 11px; letter-spacing: 2.4px; color: #2f80ed; font-weight: 800; }
      .status-pill {
        display: inline-flex; align-items: center; min-height: 28px; padding: 5px 10px;
        border: 1px solid #cfe0f4; border-radius: 999px;
        background: #edf5ff; color: #315b8f; font-size: 12px; font-weight: 700;
      }
      .status-banner {
        margin: 13px 0; padding: 11px 15px; border-left: 3px solid #2f80ed;
        border-radius: 8px; background: #edf6ff; color: #496783; font-size: 13px;
        box-shadow: 0 6px 18px rgba(63,107,158,.07);
      }
      .run-button, .secondary-button {
        border: 0; border-radius: 10px; padding: 11px 18px; cursor: pointer;
        font-size: 14px; font-weight: 800; color: #ffffff; background: linear-gradient(90deg,#3da7f5,#7c5cfc);
        box-shadow: 0 8px 18px rgba(79,126,211,.18);
      }
      .secondary-button { color: #365978; background: #ffffff; border: 1px solid #cedbea; box-shadow: none; }
      input[type="number"], #backend, .Select-control, .dash-dropdown .Select-control {
        border-radius: 9px !important; border: 1px solid #cfdaea !important;
        background: #ffffff !important; color: #183153 !important;
        font-size: 14px !important;
        box-shadow: 0 2px 5px rgba(69,92,125,.04);
      }
      input[type="number"]:focus, #backend:focus {
        border-color: #68a9f5 !important; outline: none;
        box-shadow: 0 0 0 3px rgba(47,128,237,.10);
      }
      .Select-control { min-height: 42px !important; height: 42px !important; }
      .Select-placeholder,
      .Select--single > .Select-control .Select-value {
        line-height: 40px !important; padding-left: 12px !important; padding-right: 38px !important;
      }
      .Select-input { height: 40px !important; padding-left: 12px !important; }
      .Select-input > input {
        border: 0 !important; border-radius: 0 !important; box-shadow: none !important;
        height: auto !important; margin: 0 !important; padding: 10px 0 !important;
        line-height: 20px !important;
      }
      .Select-arrow-zone { width: 38px !important; }
      .Select-menu-outer { background: #ffffff !important; border-color: #cfdaea !important; }
      .Select-value-label, .Select-placeholder { color: #183153 !important; }
      .Select-option { color: #294866 !important; background: #ffffff !important; }
      .Select-option.is-focused { background: #edf5ff !important; }
      .dash-filter--case { display: none !important; }
      .dash-table-container .dash-filter input:not(.dash-filter--case) {
        width: 100% !important; min-width: 0 !important; max-width: 100% !important; height: 30px !important;
        padding: 5px 8px !important; border: 1px solid #cfdaea !important;
        border-radius: 7px !important; background: #ffffff !important;
        color: #405b7d !important; font-size: 12px !important; text-align: left !important;
      }
      .dash-table-container .dash-filter input::placeholder {
        color: #8291a7 !important; opacity: 1;
      }
      .dash-table-container td[data-dash-column="run_id"] .dash-cell-value,
      .dash-table-container td[data-dash-column="time"] .dash-cell-value,
      .dash-table-container td[data-dash-column="task_id"] .dash-cell-value,
      .dash-table-container td[data-dash-column="task_ids"] .dash-cell-value {
        display: block !important; width: 100% !important; overflow-x: auto !important;
        overflow-y: hidden !important; scrollbar-width: none; -ms-overflow-style: none;
        overscroll-behavior-inline: contain; touch-action: pan-x pan-y;
        user-select: text; cursor: ew-resize;
      }
      .dash-table-container td[data-dash-column="run_id"] .dash-cell-value::-webkit-scrollbar,
      .dash-table-container td[data-dash-column="time"] .dash-cell-value::-webkit-scrollbar,
      .dash-table-container td[data-dash-column="task_id"] .dash-cell-value::-webkit-scrollbar,
      .dash-table-container td[data-dash-column="task_ids"] .dash-cell-value::-webkit-scrollbar {
        display: none; width: 0; height: 0;
      }
      .history-dropdown .Select-control { min-height: 42px !important; height: 42px !important; }
      .history-dropdown .Select-placeholder,
      .history-dropdown .Select-value { line-height: 40px !important; }
      .history-dropdown .Select-value-label {
        display: block !important; overflow: hidden !important;
        text-overflow: ellipsis !important; white-space: nowrap !important;
      }
      .history-dropdown .Select-menu-outer {
        min-width: 520px !important; z-index: 1100 !important;
      }
      .history-dropdown .Select-option {
        min-height: 40px !important; padding: 10px 12px !important;
        line-height: 20px !important; overflow: visible !important;
        white-space: normal !important; overflow-wrap: anywhere !important;
      }
      .tab { background: rgba(255,255,255,.76) !important; color: #70849f !important; border: 0 !important; padding: 14px !important; font-size: 15px !important; }
      .tab--selected { color: #2f80ed !important; border-top: 2px solid #2f80ed !important; background: #ffffff !important; font-weight: 700; }
      .tab-content { padding-top: 15px; }
      @media (max-width: 900px) {
        #metric-row { grid-template-columns: 1fr 1fr !important; }
      }
    </style>
    <script>
      (() => {
        const draggableColumns = new Set(["run_id", "time", "task_id", "task_ids"]);
        let drag = null;
        document.addEventListener("pointerdown", (event) => {
          if (event.button !== 0) return;
          const value = event.target.closest(".dash-cell-value");
          const cell = value && value.closest("td[data-dash-column]");
          if (!cell || !draggableColumns.has(cell.dataset.dashColumn)) return;
          if (value.scrollWidth <= value.clientWidth) return;
          drag = {
            value,
            startX: event.clientX,
            startLeft: value.scrollLeft,
            active: false,
          };
        });
        document.addEventListener("pointermove", (event) => {
          if (!drag) return;
          const distance = event.clientX - drag.startX;
          if (!drag.active && Math.abs(distance) < 4) return;
          drag.active = true;
          drag.value.style.userSelect = "none";
          drag.value.style.cursor = "grabbing";
          drag.value.scrollLeft = drag.startLeft - distance;
          event.preventDefault();
        });
        const finishDrag = () => {
          if (!drag) return;
          drag.value.style.userSelect = "text";
          drag.value.style.cursor = "ew-resize";
          drag = null;
        };
        document.addEventListener("pointerup", finishDrag);
        document.addEventListener("pointercancel", finishDrag);
      })();
    </script>
  </head>
  <body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
  </body>
</html>
"""


if __name__ == "__main__":
    if QUAFU_TOKEN_SOURCE == "missing":
        print(
            f"WARNING: QUAFU_API_TOKEN is unavailable in {PROJECT_ENV_FILE}. "
            "Hardware submission will fail.",
            flush=True,
        )
    else:
        print(f"Quafu token configured from {QUAFU_TOKEN_SOURCE}.", flush=True)
    parser = argparse.ArgumentParser(description="Quantum Route Forge competition UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)
