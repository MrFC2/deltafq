"""绩效可视化工具。"""

from typing import Optional

import numpy as np
import pandas as pd

from ..core.base import BaseComponent

try:  # pragma: no cover - optional dependency
    from scipy.stats import gaussian_kde
except ImportError:  # pragma: no cover
    gaussian_kde = None

# ── 颜色常量 ──────────────────────────────────────────────
COLOR_STRATEGY     = "#2E86AB"  # 策略曲线：蓝色
COLOR_BENCHMARK    = "#E63946"  # 基准曲线：红色
COLOR_DRAWDOWN_LINE = "#C1121F" # 回撤折线：深红
COLOR_DRAWDOWN_FILL = "#F24236" # 回撤填充：橙红
COLOR_GAIN         = "#ef4444"  # 涨：红（A 股）
COLOR_LOSS         = "#22c55e"  # 跌：绿（A 股）
COLOR_DIST_FILL    = "#6B4C3F"  # 分布填充：棕色
COLOR_DIST_LINE    = "#8B6F5E"  # 分布轮廓：浅棕

# KDE 曲线采样点数
KDE_N_POINTS = 300


def _end_label(series, text: str) -> list:
    """返回只在最后一个点显示文字的列表，用于曲线末端 label。"""
    return [None] * (len(series) - 1) + [text]


def _to_ohlc(ohlcv_df: pd.DataFrame) -> pd.DataFrame:
    """统一 OHLCV DataFrame 的 index 为 DatetimeIndex。"""
    ohlc = ohlcv_df.copy()
    if "date" in ohlc.columns:
        ohlc = ohlc.set_index("date")
    ohlc.index = pd.to_datetime(ohlc.index)
    return ohlc


class PerformanceChart(BaseComponent):
    """多面板回测绩效图表（Plotly 交互）。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def plot_backtest_charts(
            self,
            values_df: pd.DataFrame,
            ohlcv_df: pd.DataFrame,
            trades_df: pd.DataFrame,
            benchmark_close: Optional[pd.Series] = None,
            metrics: Optional[dict] = None,
    ) -> None:
        """绘制回测绩效图表，生成 HTML 并在浏览器打开。"""
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError as exc:  # pragma: no cover
            raise ImportError(f"Plotly 不可用（{exc}），请安装 plotly") from exc

        # 数据准备
        df, has_price, date_text = self._prepare_df(values_df)
        strategy_nv, drawdown, returns_pct, price_norm = self._calc_series(df, has_price)
        bench_norm_price, bench_norm_nv = self._calc_benchmark(benchmark_close, df, has_price)

        has_metrics = bool(metrics)
        offset = 1 if has_metrics else 0
        # 固定面板：K线 + 成交量 + 5个基础面板
        total_rows = offset + 7

        # 行高比例：表格、K线、成交量、价格对比、净值、回撤、每日盈亏、分布
        table_h = 0.16 if has_metrics else 0.0
        panel_ratios = [0.20, 0.08, 0.13, 0.15, 0.14, 0.14, 0.13]
        scale = (1.0 - table_h) / sum(panel_ratios)
        row_heights = ([table_h] if has_metrics else []) + [r * scale for r in panel_ratios]

        specs = ([[{"type": "domain"}]] if has_metrics else []) + [[{"type": "scatter"}]] * 7

        fig = make_subplots(
            rows=total_rows, cols=1,
            shared_xaxes=False,
            vertical_spacing=0.02,
            specs=specs,
            row_heights=row_heights,
        )

        # 关闭所有行的 rangeslider（Candlestick 默认会开启）
        for i in range(1, total_rows + 1):
            fig.update_layout(**{f"xaxis{i if i > 1 else ''}": dict(rangeslider_visible=False)})

        if has_metrics:
            tip_map = self._add_metrics_table(fig, metrics, go)
        else:
            tip_map = {}

        # K 线 + 买卖点
        self._add_candle_traces(fig, go, ohlcv_df, trades_df, row=offset + 1)
        # 成交量
        self._add_volume_trace(fig, go, ohlcv_df, row=offset + 2)
        # 5 个基础面板
        self._add_chart_traces(
            fig, df, strategy_nv, drawdown, returns_pct,
            price_norm, bench_norm_price, bench_norm_nv,
            has_price, offset + 2, go,
        )

        self._update_axes(fig, offset + 2, candle_row=offset + 1, volume_row=offset + 2)

        fig.update_layout(
            title=f"策略表现分析<br><sup>{date_text}</sup>",
            template="plotly_white",
            showlegend=False,
            height=2000,
        )

        html_str = fig.to_html(include_plotlyjs=True, full_html=True)
        if tip_map:
            html_str = _inject_cell_click_panel(html_str, tip_map)

        import webbrowser
        from pathlib import Path

        temp_dir = Path(__file__).parents[2] / "temp"
        temp_dir.mkdir(exist_ok=True)

        html_path = temp_dir / "deltafq_chart.html"
        html_path.write_text(html_str, encoding="utf-8")

        webbrowser.open(f"file://{html_path}")

    # ------------------------------------------------------------------
    # 数据准备
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_df(values_df: pd.DataFrame):
        """统一 index、补全 returns 列，返回 (df, has_price, date_text)。"""
        df = values_df.copy()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        df.index = pd.to_datetime(df.index)

        if "total_value" not in df.columns:
            raise KeyError("values_df 必须包含 total_value 列")
        if "returns" not in df.columns:
            df["returns"] = df["total_value"].pct_change().fillna(0.0)

        has_price = "price" in df.columns
        date_text = (
            f"{df.index.min().date()} — {df.index.max().date()}"
            if not df.empty else "no data"
        )
        return df, has_price, date_text

    @staticmethod
    def _calc_series(df: pd.DataFrame, has_price: bool):
        """计算策略净值、回撤、日收益率、价格归一化序列。"""
        strategy_nv = df["total_value"] / df["total_value"].iloc[0]
        rolling_max = df["total_value"].expanding().max()
        drawdown = (rolling_max - df["total_value"]) / rolling_max * -100
        returns_pct = df["returns"] * 100
        price_norm = (
            df["price"].astype(float) / df["price"].iloc[0] if has_price else None
        )
        return strategy_nv, drawdown, returns_pct, price_norm

    @staticmethod
    def _calc_benchmark(benchmark_close, df: pd.DataFrame, has_price: bool):
        """对齐基准序列，返回 (bench_norm_price, bench_norm_nv)。"""
        if benchmark_close is None:
            return None, None

        bench = (
            pd.Series(benchmark_close, dtype=float)
            .rename_axis(None)
            .set_axis(pd.to_datetime(pd.Series(benchmark_close).index))
            .sort_index()
            .reindex(df.index)
            .ffill()
            .dropna()
        )
        if bench.empty:
            return None, None

        bench_nv = (1 + bench.pct_change().fillna(0.0)).cumprod()
        bench_norm_nv = bench_nv / bench_nv.iloc[0]
        bench_norm_price = bench / bench.iloc[0] if has_price else None
        return bench_norm_price, bench_norm_nv

    @staticmethod
    def _add_candle_traces(fig, go, ohlcv_df: pd.DataFrame,
                           trades_df: Optional[pd.DataFrame], row: int) -> None:
        """K 线图 + 买入/卖出标注。"""
        ohlc = _to_ohlc(ohlcv_df)

        # K 线
        fig.add_trace(
            go.Candlestick(
                x=ohlc.index,
                open=ohlc["Open"], high=ohlc["High"],
                low=ohlc["Low"],   close=ohlc["Close"],
                name="K线",
                increasing=dict(line=dict(color=COLOR_GAIN), fillcolor=COLOR_GAIN),
                decreasing=dict(line=dict(color=COLOR_LOSS), fillcolor=COLOR_LOSS),
                showlegend=False,
            ),
            row=row, col=1,
        )

        if trades_df is None or trades_df.empty:
            return
        if "timestamp" not in trades_df.columns:
            return

        trades = trades_df.copy()
        trades["timestamp"] = pd.to_datetime(trades["timestamp"])
        buys  = trades[trades["type"] == "buy"]
        sells = trades[trades["type"] == "sell"]

        # 买入：红色向上三角，标在 low 下方
        if not buys.empty:
            buy_dates  = pd.to_datetime(buys["timestamp"].values)
            buy_prices = buys["price"].values
            lows = ohlc["Low"].reindex(buy_dates)
            y    = np.where(lows.isna(), buy_prices, lows.values) * 0.995
            fig.add_trace(
                go.Scatter(
                    x=buy_dates, y=y,
                    mode="markers+text",
                    marker=dict(symbol="triangle-up", size=10,
                                color=COLOR_GAIN, line=dict(color="#fff", width=1)),
                    text=["买"] * len(buys),
                    textposition="bottom center",
                    textfont=dict(size=9, color=COLOR_GAIN),
                    showlegend=False,
                    hovertemplate="买入 %{x}<br>价格: %{customdata:.2f}<extra></extra>",
                    customdata=buy_prices,
                ),
                row=row, col=1,
            )

        # 卖出：绿色向下三角，标在 high 上方
        if not sells.empty:
            sell_dates  = pd.to_datetime(sells["timestamp"].values)
            sell_prices = sells["price"].values
            highs = ohlc["High"].reindex(sell_dates)
            y     = np.where(highs.isna(), sell_prices, highs.values) * 1.005
            fig.add_trace(
                go.Scatter(
                    x=sell_dates, y=y,
                    mode="markers+text",
                    marker=dict(symbol="triangle-down", size=10,
                                color=COLOR_LOSS, line=dict(color="#fff", width=1)),
                    text=["卖"] * len(sells),
                    textposition="top center",
                    textfont=dict(size=9, color=COLOR_LOSS),
                    showlegend=False,
                    hovertemplate="卖出 %{x}<br>价格: %{customdata:.2f}<extra></extra>",
                    customdata=sell_prices,
                ),
                row=row, col=1,
            )

    @staticmethod
    def _add_volume_trace(fig, go, ohlcv_df: pd.DataFrame, row: int) -> None:
        """成交量柱状图，涨红跌绿。"""
        ohlc = _to_ohlc(ohlcv_df)

        colors = [COLOR_GAIN if c >= o else COLOR_LOSS
                  for c, o in zip(ohlc["Close"], ohlc["Open"])]
        fig.add_trace(
            go.Bar(
                x=ohlc.index, y=ohlc["Volume"],
                name="成交量",
                marker_color=colors,
                showlegend=False,
            ),
            row=row, col=1,
        )

    @staticmethod
    def _add_metrics_table(fig, metrics: dict, go) -> dict:
        """在 row=1 添加指标汇总表格，返回 {cell文本: (标题, 说明)} 用于 JS 注入。"""
        m = metrics
        total_return = m.get("total_return", 0.0)
        end_capital = float(m.get("end_capital", 0.0))
        start_capital = float(m.get("start_capital", 0.0))
        growth = end_capital - start_capital

        headers = ["交易时间", "资金概况", "收益指标", "风险指标", "绩效指标", "交易统计"]

        # 收益指标
        c_total = f"总收益: {total_return:.2%}"
        c_annual = f"年化收益: {m.get('annualized_return', 0.0):.2%}"
        c_daily_r = f"日均收益: {m.get('avg_daily_return', 0.0):.2%}"
        # 风险指标
        c_dd = f"最大回撤: {m.get('max_drawdown', 0.0):.2%}"
        c_std = f"收益标准差: {m.get('return_std', 0.0):.2%}"
        c_vol = f"年化波动率: {m.get('volatility', 0.0):.2%}"
        # 绩效指标
        c_sharpe = f"夏普比率: {m.get('sharpe_ratio', 0.0):.2f}"
        c_calmar = f"收益回撤比: {m.get('return_drawdown_ratio', 0.0):.2f}"
        c_wr = f"胜率: {m.get('win_rate', 0.0):.2%}"
        c_plr = f"盈亏比: {m.get('profit_loss_ratio', 0.0):.2f}"
        c_avgwin = f"平均盈利: {m.get('avg_win', 0.0):,.0f}"

        cells = [
            [
                f"首笔: {m.get('first_trade_date', '-')}",
                f"末笔: {m.get('last_trade_date', '-')}",
                f"交易天数: {m.get('total_trading_days', 0)}",
                f"盈利天: {m.get('profitable_days', 0)}",
                f"亏损天: {m.get('losing_days', 0)}",
            ],
            [
                f"初始资金: {start_capital:,.0f}",
                f"期末资金: {end_capital:,.0f}",
                f"资金增长: {growth:,.0f} ({total_return:.2%})",
                "", "",
            ],
            [c_total, c_annual, c_daily_r, "", ""],
            [c_dd, c_std, c_vol, "", ""],
            [c_sharpe, c_calmar, c_wr, c_plr, c_avgwin],
            [
                f"总盈亏: {m.get('total_pnl', 0.0):,.0f}",
                f"总手续费: {m.get('total_commission', 0.0):,.0f}",
                f"总成交额: {m.get('total_turnover', 0.0):,.0f}",
                f"交易次数: {m.get('total_trade_count', 0)}",
                f"日均盈亏: {m.get('avg_daily_pnl', 0.0):,.0f}",
            ],
        ]

        # cell文本 -> (标题, 定义, 公式详解)
        tip_map = {
            c_total: (
                "总收益率",
                "回测期间账户总盈亏占初始资金的比例，反映策略整体赚了多少。",
                "总收益率 = (期末资金 ÷ 初始资金) - 1\n"
                "例：初始 100 万，期末 106.54 万 → (106.54 ÷ 100) - 1 = 6.54%",
            ),
            c_annual: (
                "年化收益率",
                "将总收益率折算为「每年」的等效收益，便于与其他投资横向比较。",
                "年化收益率 = (1 + 总收益率)^(252 ÷ 交易日数) - 1\n"
                "252 是 A 股全年交易日数（约定俗成的年化基数）。\n"
                "^(252÷n) 表示「把 n 天的收益率复利折算到 252 天」。\n"
                "例：6.54% / 241 天 → (1.0654)^(252÷241) - 1 ≈ 6.85%",
            ),
            c_daily_r: (
                "日均收益率",
                "所有交易日收益率的算术平均值，衡量每天平均赚多少。",
                "日均收益率 = Σ(每日收益率) ÷ 交易日数\n"
                "每日收益率 = (当日总资产 - 前日总资产) ÷ 前日总资产",
            ),
            c_dd: (
                "最大回撤",
                "回测期间净值从最高点下跌到最低点的最大幅度，衡量策略最坏情况下的亏损。",
                "最大回撤 = min((当日净值 - 历史最高净值) ÷ 历史最高净值)\n"
                "结果为负数，绝对值越大说明亏损越惨。\n"
                "例：净值从 1.2 跌到 1.02 → (1.02 - 1.2) ÷ 1.2 = -15%",
            ),
            c_std: (
                "收益标准差（日频）",
                "日收益率序列的标准差，衡量每天收益的波动程度，标准差越大说明日内涨跌越剧烈。",
                "收益标准差 = √[ Σ(每日收益率 - 日均收益率)² ÷ (n-1) ]\n"
                "这是统计学中的样本标准差公式，n 为交易日数。",
            ),
            c_vol: (
                "年化波动率",
                "将日收益率标准差折算为年度波动水平，是衡量策略风险最常用的指标。",
                "年化波动率 = 日收益率标准差 × √252\n"
                "乘以 √252 是因为波动率的年化需要乘以时间的平方根（统计学性质）。\n"
                "例：日标准差 1.41% × √252 ≈ 22.40%",
            ),
            c_sharpe: (
                "夏普比率",
                "每承担一单位风险所获得的超额收益，越高说明策略「性价比」越好。",
                "夏普比率 = (年化收益率 - 无风险利率) ÷ 年化波动率\n"
                "本系统无风险利率取 0（简化处理）。\n"
                "等价展开：(日均收益率 ÷ 日收益标准差) × √252\n"
                "例：(0.022% ÷ 1.41%) × √252 ≈ 0.41\n"
                "一般认为 > 1 良好，> 2 优秀。",
            ),
            c_calmar: (
                "收益回撤比（Calmar）",
                "年化收益率与最大回撤之比，衡量「用多大的亏损风险换来了多少年化收益」。",
                "收益回撤比 = 年化收益率 ÷ |最大回撤|\n"
                "例：年化 6.85% ÷ 14.58% ≈ 0.47\n"
                "比值越高说明单位风险获取的收益越多，一般 > 1 较好。",
            ),
            c_wr: (
                "胜率",
                "盈利交易笔数占总交易笔数的比例，反映策略「赢的次数多不多」。",
                "胜率 = 盈利交易笔数 ÷ 总有效交易笔数\n"
                "基于每笔卖出单的实现盈亏（profit_loss > 0 算盈利）。\n"
                "注意：高胜率不等于高收益，还需结合盈亏比综合判断。",
            ),
            c_plr: (
                "盈亏比",
                "平均每笔盈利与平均每笔亏损之比，反映策略「赚的是不是比亏的多」。",
                "盈亏比 = 平均盈利 ÷ |平均亏损|\n"
                "例：平均盈利 38,452 ÷ 平均亏损 21,128 ≈ 1.82\n"
                "盈亏比 > 1 说明平均赚的比亏的多；结合胜率才能判断策略整体是否盈利。",
            ),
            c_avgwin: (
                "平均盈利",
                "所有盈利交易的平均获利金额。",
                "平均盈利 = Σ(盈利交易的 profit_loss) ÷ 盈利交易笔数\n"
                "profit_loss 为每笔卖出成交后的已实现盈亏（含手续费）。",
            ),
        }

        fig.add_trace(
            go.Table(
                header=dict(values=headers, fill_color="#2E86AB",
                            font=dict(color="white", size=12),
                            align="center", height=28),
                cells=dict(values=cells,
                           fill_color=[["#f8f9fa", "#ffffff"] * 3],
                           align="left", font=dict(size=11), height=22),
            ),
            row=1, col=1,
        )
        return tip_map

    @staticmethod
    def _add_chart_traces(
            fig, df, strategy_nv, drawdown, returns_pct,
            price_norm, bench_norm_price, bench_norm_nv,
            has_price, offset, go,
    ) -> None:
        """依次向五个图表面板添加 trace，label 显示在曲线末端。"""

        def scatter(x, y, name, color, dash=None, pos="top right"):
            return go.Scatter(
                x=x, y=y, name=name,
                mode="lines+text",
                text=_end_label(y, name),
                textposition=pos,
                textfont=dict(color=color, size=11),
                line=dict(color=color, width=1.5 if dash else 2,
                          **({"dash": dash} if dash else {})),
                showlegend=False,
            )

        # 面板 1：价格对比（可选）
        if has_price and price_norm is not None:
            fig.add_trace(
                scatter(df.index, price_norm, "策略收盘价", COLOR_STRATEGY),
                row=1 + offset, col=1,
            )
            if bench_norm_price is not None:
                fig.add_trace(
                    scatter(bench_norm_price.index, bench_norm_price.values,
                            "基准收盘价", COLOR_BENCHMARK, dash="dash", pos="bottom right"),
                    row=1 + offset, col=1,
                )

        # 面板 2：策略净值 vs 基准净值
        fig.add_trace(
            scatter(df.index, strategy_nv, "策略净值", COLOR_STRATEGY),
            row=2 + offset, col=1,
        )
        if bench_norm_nv is not None:
            fig.add_trace(
                scatter(bench_norm_nv.index, bench_norm_nv.values,
                        "基准净值", COLOR_BENCHMARK, dash="dash", pos="bottom right"),
                row=2 + offset, col=1,
            )

        # 面板 3：回撤
        fig.add_trace(
            go.Scatter(
                x=df.index, y=drawdown, name="回撤",
                mode="lines+text",
                text=_end_label(drawdown, "回撤"),
                textposition="bottom right",
                textfont=dict(color=COLOR_DRAWDOWN_LINE, size=11),
                fill="tozeroy", fillcolor="rgba(242,66,54,0.4)",
                line=dict(color=COLOR_DRAWDOWN_LINE),
                showlegend=False,
            ),
            row=3 + offset, col=1,
        )

        # 面板 4：每日盈亏柱状图
        fig.add_trace(
            go.Bar(x=df.index, y=returns_pct, name="每日盈亏",
                   marker_color=np.where(returns_pct >= 0, COLOR_GAIN, COLOR_LOSS),
                   showlegend=False),
            row=4 + offset, col=1,
        )

        # 面板 5：收益率分布
        returns_for_dist = returns_pct[returns_pct != 0]
        if len(returns_for_dist) > 1 and gaussian_kde is not None:
            kde = gaussian_kde(returns_for_dist)
            kde.set_bandwidth(kde.factor * 0.5)
            x_range = np.linspace(returns_for_dist.min(), returns_for_dist.max(), KDE_N_POINTS)
            frequency = kde(x_range) * (x_range[1] - x_range[0]) * len(returns_for_dist)
            fig.add_trace(
                go.Scatter(
                    x=x_range, y=frequency, name="盈亏分布",
                    mode="lines+text",
                    text=_end_label(x_range, "盈亏分布"),
                    textposition="top right",
                    textfont=dict(color=COLOR_DIST_LINE, size=11),
                    fill="tozeroy", fillcolor="rgba(107,76,63,0.6)",
                    line=dict(color=COLOR_DIST_LINE),
                    showlegend=False,
                ),
                row=5 + offset, col=1,
            )
        else:
            src = returns_for_dist if len(returns_for_dist) > 1 else returns_pct
            fig.add_trace(
                go.Histogram(x=src, name="盈亏分布",
                             nbinsx=40, marker_color=COLOR_DIST_FILL, showlegend=False),
                row=5 + offset, col=1,
            )

    @staticmethod
    def _update_axes(fig, offset: int, candle_row: int, volume_row: int) -> None:
        """设置各面板 Y 轴标签、X 轴日期格式及边框。"""
        date_tickformat = [
            dict(dtickrange=[None, 86400000],       value="%m-%d"),
            dict(dtickrange=[86400000, 2592000000], value="%Y-%m-%d"),
            dict(dtickrange=[2592000000, None],      value="%Y-%m"),
        ]

        # K 线面板
        fig.update_yaxes(title_text="价格", row=candle_row, col=1)
        fig.update_xaxes(showticklabels=True, tickangle=0,
                         tickformatstops=date_tickformat, row=candle_row, col=1)

        # 成交量面板
        fig.update_yaxes(title_text="成交量", row=volume_row, col=1)
        fig.update_xaxes(showticklabels=True, tickangle=0,
                         tickformatstops=date_tickformat, row=volume_row, col=1)

        # 5 个基础面板
        y_labels = ["价格(归一化)", "净值", "回撤 (%)", "收益率 (%)", "频数"]
        for i, label in enumerate(y_labels, start=1):
            fig.update_yaxes(title_text=label, row=i + offset, col=1)

        for r in range(1 + offset, 5 + offset):
            fig.update_xaxes(showticklabels=True, tickangle=0,
                             tickformatstops=date_tickformat, row=r, col=1)
        fig.update_xaxes(title_text="收益率 (%)", tickangle=0, row=5 + offset, col=1)

        fig.update_xaxes(showline=True, linewidth=1, linecolor="#cccccc", mirror=True)
        fig.update_yaxes(showline=True, linewidth=1, linecolor="#cccccc", mirror=True)


# ── 模块级辅助：向 HTML 注入单元格点击说明面板 ──────────────────────────

def _inject_cell_click_panel(html: str, tip_map: dict) -> str:
    """
    向 Plotly 生成的 HTML 注入 JS，点击表格 cell 时右侧弹出说明面板。
    tip_map: {cell显示文本: (标题, 定义, 公式详解)}
    """
    import json

    tips = {k: list(v) for k, v in tip_map.items()}

    js = f"""
<div id="kiro-panel" style="
  display:none; position:fixed; top:60px; right:20px;
  background:#fff; border:1px solid #e0e0e0; border-radius:10px;
  padding:18px 20px; min-width:300px; max-width:380px;
  box-shadow:0 6px 24px rgba(0,0,0,0.13); z-index:9999;
  font-family:sans-serif; font-size:13px; line-height:1.6;
">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <strong id="kiro-panel-title" style="font-size:15px;color:#2E86AB;"></strong>
    <span onclick="document.getElementById('kiro-panel').style.display='none'"
          style="cursor:pointer;color:#bbb;font-size:20px;line-height:1;margin-left:12px;">&#x2715;</span>
  </div>
  <div id="kiro-panel-desc" style="color:#333;margin-bottom:12px;font-size:13px;"></div>
  <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;
    letter-spacing:0.5px;margin-bottom:6px;">公式 / 计算方式</div>
  <div id="kiro-panel-formula" style="
    background:#f5f7fa;border-radius:6px;padding:10px 12px;
    font-size:12px;color:#444;white-space:pre-wrap;line-height:1.8;
    border-left:3px solid #2E86AB;"></div>
</div>
<script>
(function() {{
  var TIPS = {json.dumps(tips, ensure_ascii=False)};
  function attach() {{
    var els = document.querySelectorAll("text.cell-text");
    if (els.length === 0) {{ setTimeout(attach, 300); return; }}
    els.forEach(function(el) {{
      var t = el.textContent.trim();
      if (!TIPS[t]) return;
      el.style.cursor = "pointer";
      el.addEventListener("click", function() {{
        var info = TIPS[t];
        document.getElementById("kiro-panel-title").textContent   = info[0];
        document.getElementById("kiro-panel-desc").textContent    = info[1];
        document.getElementById("kiro-panel-formula").textContent = info[2];
        document.getElementById("kiro-panel").style.display = "block";
      }});
    }});
  }}
  setTimeout(attach, 300);
}})();
</script>
"""
    return html.replace("</body>", js + "\n</body>")
