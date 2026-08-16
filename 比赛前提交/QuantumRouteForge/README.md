# Quantum Route Forge — 最终项目代码

本目录是 DeepBlock 路线优化项目的精简提交版，只包含最终应用运行、核心算法实现和离线验收所需内容。

## 环境要求

- Python 3.12
- Windows PowerShell（以下命令也可按当前终端等价调整）

## 安装与运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py --port 8050
```

浏览器访问 `http://127.0.0.1:8050`。

默认 Hardware 模式只执行 dry-run，不会提交真实量子任务。若需真实硬件运行，请复制 `.env.example` 为 `.env`，填写自己的 Quafu 访问令牌，并在页面中明确确认真实提交。

## 验收测试

```powershell
python -m pytest -q
```

提交包内的测试覆盖最终 Web 入口、DeepBlock 分块/代理 QUBO/评估流程、运行历史，以及经典优化烟雾测试。测试不需要真实硬件令牌或网络访问。

## 目录说明

```text
app.py                         最终 Dash Web 应用入口
src/quantum_route_forge/       路线优化、量子测量与 DeepBlock 核心实现
tests/                         与最终项目直接相关的离线验收测试
requirements.txt               Python 依赖
.env.example                   可选的硬件访问配置模板
LICENSE                        开源许可证
```

运行时产生的历史记录会写入 `results/competition_history/`。该目录不是源码，因此未包含在提交包中。
