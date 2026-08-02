from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html, no_update
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quantum_route_forge.competition_history import CompetitionHistory  # noqa: E402
from quantum_route_forge.deepblock_service import run_deepblock_optimization  # noqa: E402
from quantum_route_forge.scenario import generate_dispatch_instance  # noqa: E402


COLORS = ["#69e2ff", "#9478ff", "#ffca6b", "#55e6a5", "#ff7f9f", "#82a7ff"]
INK = "#dce8ff"
MUTED = "#8fa7c9"
PANEL = {
    "background": "linear-gradient(145deg, rgba(19,31,57,.96), rgba(12,21,40,.96))",
    "border": "1px solid rgba(132,166,220,.18)",
    "borderRadius": "18px",
    "boxShadow": "0 18px 50px rgba(0,0,0,.24)",
}
HISTORY = CompetitionHistory(ROOT / "results" / "competition_history")


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
    selected = INITIAL_PAYLOAD.get("selected", {})
    return (
        f"已载入最近运行 {INITIAL_PAYLOAD.get('run_id')} · "
        f"{selected.get('status')} · source={selected.get('source')}"
    )


def _field(label: str, control, hint: str = ""):
    return html.Div(
        [
            html.Label(label, style={"fontSize": "12px", "fontWeight": 700, "color": "#b9c9e4"}),
            control,
            html.Small(hint, style={"color": "#647fa6", "lineHeight": "1.25"}) if hint else None,
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
        text=f"<b>{title}</b><br><span style='font-size:12px;color:#7188aa'>{subtitle}</span>",
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"color": "#a9bedc", "size": 16},
    )
    figure.update_layout(
        template="plotly_dark",
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
            marker={"size": 19, "symbol": "star", "color": "#ffffff", "line": {"color": "#69e2ff", "width": 2}},
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
        template="plotly_dark",
        title={"text": title, "x": 0.03, "font": {"size": 16}},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(5,12,25,.25)",
        height=440,
        margin={"l": 35, "r": 20, "t": 55, "b": 35},
        legend={"orientation": "h", "y": -0.14},
        xaxis={"gridcolor": "rgba(120,150,200,.10)", "zeroline": False},
        yaxis={"gridcolor": "rgba(120,150,200,.10)", "zeroline": False, "scaleanchor": "x", "scaleratio": 1},
    )
    return figure


def _metric(label: str, value: str, tone: str = "#69e2ff"):
    return html.Div(
        [
            html.Div(label, style={"fontSize": "11px", "letterSpacing": "1px", "textTransform": "uppercase", "color": MUTED}),
            html.Div(value, style={"fontSize": "25px", "fontWeight": 800, "color": tone, "marginTop": "5px"}),
        ],
        style={**PANEL, "padding": "15px 17px", "minHeight": "70px"},
    )


def _table(component_id: str, page_size: int = 10):
    return dash_table.DataTable(
        id=component_id,
        data=[],
        columns=[],
        page_size=page_size,
        sort_action="native",
        filter_action="native",
        style_table={"overflowX": "auto", "borderRadius": "12px"},
        style_header={
            "backgroundColor": "#152544",
            "color": "#cfe0fb",
            "fontWeight": 700,
            "border": "1px solid #263a5e",
        },
        style_cell={
            "backgroundColor": "#0e1a31",
            "color": "#b9c9e4",
            "border": "1px solid #213452",
            "fontFamily": "Segoe UI, Microsoft YaHei, sans-serif",
            "fontSize": "12px",
            "padding": "10px",
            "textAlign": "left",
            "maxWidth": "280px",
            "overflow": "hidden",
            "textOverflow": "ellipsis",
        },
        style_data_conditional=[
            {"if": {"filter_query": "{accepted} = true"}, "backgroundColor": "rgba(45,180,125,.16)", "color": "#8af2c5"}
        ],
    )


controls = html.Div(
    [
        html.Div(
            [
                html.Div("RUN CONFIG", style={"fontSize": "11px", "letterSpacing": "2px", "color": "#69e2ff"}),
                html.H3("同条件公平对照", style={"margin": "5px 0 0", "fontSize": "18px"}),
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
                            {"label": "Baihua Hardware", "value": "deepblock_hardware"},
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
            style={"fontSize": "12px", "color": "#d8b56f", "marginTop": "13px"},
        ),
        html.Div(
            [
                html.Button("运行 DeepBlock 对照", id="run-btn", n_clicks=0, className="run-button"),
                html.Div("同一实例 · 同一初始分配 · 同一 Top-k · 严格改善才接受", style={"fontSize": "11px", "color": MUTED}),
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
        html.Div([html.H3("车辆路线明细"), _table("route-table", 10)], style={**PANEL, "padding": "18px", "marginTop": "14px"}),
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
        html.Div([html.H3("Block 与接受决策"), _table("block-table", 10)], style={**PANEL, "padding": "18px", "marginTop": "14px"}),
        html.Div([html.H3("Top-k 候选（逐 bitstring 真路线评价）"), _table("candidate-table", 16)], style={**PANEL, "padding": "18px", "marginTop": "14px"}),
        html.Details(
            [
                html.Summary("查看完整 counts / QASM / 编译审计", style={"cursor": "pointer", "fontWeight": 700, "color": "#9fc6ff"}),
                html.Pre(id="evidence-json", style={"whiteSpace": "pre-wrap", "fontSize": "11px", "color": "#94abd0", "maxHeight": "560px", "overflow": "auto"}),
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
        html.Div([html.H3("Initial / Hardware / Random / Simulator / Exact"), _table("comparison-table", 10)], style={**PANEL, "padding": "18px", "marginTop": "14px"}),
    ]
)


history_page = html.Div(
    [
        html.Div(
            [
                html.Div([html.Div("LOCAL HISTORY", className="eyebrow"), html.H2("运行历史与证据重载", style={"margin": "6px 0"})]),
                html.Div(
                    [
                        dcc.Dropdown(id="history-run-id", placeholder="选择 run ID", style={"minWidth": "310px"}),
                        html.Button("重新打开", id="open-history-btn", n_clicks=0, className="secondary-button"),
                        html.Button("刷新", id="refresh-history-btn", n_clicks=0, className="secondary-button"),
                    ],
                    style={"display": "flex", "gap": "10px", "alignItems": "center"},
                ),
            ],
            style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
        ),
        html.Div([_table("history-table", 12)], style={**PANEL, "padding": "18px", "marginTop": "14px"}),
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
                                html.H1("Baihua DeepBlock 控制台", style={"margin": "3px 0", "fontSize": "28px"}),
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
            style={"textAlign": "center", "color": "#536b8e", "fontSize": "11px", "padding": "28px 0 10px"},
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
            return payload, f"已重新打开历史结果 {history_run_id}。"
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
            submit_hardware=(mode == "deepblock_hardware" and confirmed),
            confirm_hardware_submit=(mode == "deepblock_hardware" and confirmed),
            history_root=HISTORY.root,
        )
        selected = payload["selected"]
        return (
            payload,
            f"{payload['run_id']} · {selected['status']} · source={selected['source']} · "
            f"{selected['baseline_distance']:.3f} → {selected['final_distance']:.3f} · "
            f"accepted={selected['accepted_moves']}",
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
            _metric("Source", "—", "#9478ff"),
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
        _metric("Initial distance", f"{initial['distance']:.3f}", "#dce8ff"),
        _metric("Final distance", f"{selected['final_distance']:.3f}", "#69e2ff"),
        _metric("Improvement", f"{improvement:.3f} · {selected['improvement_pct']:.2f}%", "#55e6a5" if improvement > 0 else "#ffca6b"),
        _metric("Accepted moves", str(selected.get("accepted_moves", 0)), "#ffca6b"),
        _metric("Source / status", f"{selected.get('source')} · {selected.get('status')}", "#9478ff"),
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
            marker={"color": ["#536b8e", "#9478ff", "#ffca6b", "#69e2ff", "#55e6a5"]},
        )
    )
    bar.update_layout(
        template="plotly_dark",
        title="最终真实路线距离（越低越好）",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(5,12,25,.25)",
        height=410,
        margin={"l": 45, "r": 20, "t": 55, "b": 35},
        yaxis={"gridcolor": "rgba(120,150,200,.12)"},
    )
    scan = go.Figure()
    for index, (arm_mode, arm) in enumerate(payload.get("arms", {}).items()):
        ys = [arm["baseline_distance"]] + [trace["distance_after"] for trace in arm.get("traces", [])]
        xs = ["Initial"] + [f"{trace['block']['block_id']}·{trace['sequence']}" for trace in arm.get("traces", [])]
        scan.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines+markers",
                name=arm["source"].title(),
                line={"color": COLORS[index % len(COLORS)], "width": 2.4},
            )
        )
    scan.update_layout(
        template="plotly_dark",
        title="DeepBlock 扫描距离变化",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(5,12,25,.25)",
        height=410,
        margin={"l": 45, "r": 20, "t": 55, "b": 35},
        yaxis={"gridcolor": "rgba(120,150,200,.12)"},
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
            html.Strong("公平性锁定：", style={"color": "#69e2ff"}),
            html.Span("  相同实例 / 初始分配 / B1-B3 / shots / Top-k / 修复 / 路线评价器 / 严格接受规则"),
            html.Span("  ·  全部通过" if all(fairness.values()) else "  ·  请检查", style={"color": "#55e6a5"}),
        ]
    )
    history_detail = html.Div(
        [
            html.H3(f"当前结果 · {payload.get('run_id')}"),
            html.P(
                f"{payload['created_at']} · seed={payload['parameters']['seed']} · "
                f"{payload['parameters']['num_customers']} customers · {payload['parameters']['num_vehicles']} vehicles",
                style={"color": MUTED},
            ),
            html.P(
                f"source={selected.get('source')} · backend={selected.get('backend') or '—'} · "
                f"task IDs={', '.join(selected.get('task_ids', [])) or '—'} · status={selected.get('status')}"
            ),
            html.P("Warnings: " + (" | ".join(payload.get("warnings", [])) or "none"), style={"color": "#d8b56f"}),
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
    rows = HISTORY.rows()
    columns = [{"name": key.replace("_", " ").title(), "id": key} for key in (rows[0].keys() if rows else [])]
    options = [{"label": f"{row['time']} · {row['run_id']} · {row['mode']}", "value": row["run_id"]} for row in rows]
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
      :root { color-scheme: dark; }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background:
          radial-gradient(circle at 12% 4%, rgba(51,112,180,.24), transparent 31%),
          radial-gradient(circle at 88% 0%, rgba(113,70,180,.19), transparent 28%),
          #07101f;
        font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
      }
      .logo-mark {
        width: 54px; height: 54px; display: grid; place-items: center;
        border-radius: 16px; color: #06101d; font-weight: 900; letter-spacing: -1px;
        background: linear-gradient(145deg,#69e2ff,#9478ff);
        box-shadow: 0 0 30px rgba(105,226,255,.22);
      }
      .eyebrow { font-size: 10px; letter-spacing: 2.4px; color: #69e2ff; font-weight: 800; }
      .status-pill {
        display: inline-flex; align-items: center; min-height: 28px; padding: 5px 10px;
        border: 1px solid rgba(122,166,225,.22); border-radius: 999px;
        background: rgba(28,49,82,.58); color: #aecdff; font-size: 11px; font-weight: 700;
      }
      .status-banner {
        margin: 13px 0; padding: 11px 15px; border-left: 3px solid #69e2ff;
        border-radius: 8px; background: rgba(15,30,54,.72); color: #a9bedc; font-size: 12px;
      }
      .run-button, .secondary-button {
        border: 0; border-radius: 10px; padding: 11px 18px; cursor: pointer;
        font-weight: 800; color: #06101d; background: linear-gradient(90deg,#69e2ff,#9478ff);
      }
      .secondary-button { color: #bcd3f5; background: #1a2b4a; border: 1px solid #30486f; }
      input, .Select-control, .dash-dropdown .Select-control {
        border-radius: 9px !important; border: 1px solid #2b4267 !important;
        background: #0d192e !important; color: #dce8ff !important;
      }
      .Select-menu-outer { background: #101e36 !important; border-color: #2b4267 !important; }
      .Select-value-label, .Select-placeholder { color: #dce8ff !important; }
      .tab { background: #0c172b !important; color: #8299bd !important; border: 0 !important; padding: 14px !important; }
      .tab--selected { color: #69e2ff !important; border-top: 2px solid #69e2ff !important; background: #111f38 !important; }
      .tab-content { padding-top: 15px; }
      @media (max-width: 900px) {
        #metric-row { grid-template-columns: 1fr 1fr !important; }
      }
    </style>
  </head>
  <body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
  </body>
</html>
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quantum Route Forge competition UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)
