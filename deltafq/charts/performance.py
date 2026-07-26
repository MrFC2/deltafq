"""绩效可视化工具。"""

from typing import Optional

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..core.base import BaseComponent

try:  # pragma: no cover - optional dependency
    from scipy.stats import gaussian_kde
except ImportError:  # pragma: no cover
    gaussian_kde = None

# ── 颜色常量 ──────────────────────────────────────────────
COLOR_STRATEGY = "#2E86AB"  # 策略曲线：蓝色
COLOR_BENCHMARK = "#E63946"  # 基准曲线：红色
COLOR_DRAWDOWN_LINE = "#C1121F"  # 回撤折线：深红
COLOR_DRAWDOWN_FILL = "#F24236"  # 回撤填充：橙红
COLOR_GAIN = "#ef4444"  # 正收益柱：红（A 股涨红）
COLOR_LOSS = "#22c55e"  # 负收益柱：绿（A 股跌绿）
COLOR_DIST_FILL = "#6B4C3F"  # 分布填充：棕色
COLOR_DIST_LINE = "#8B6F5E"  # 分布轮廓：浅棕

# ── 字体候选列表（按优先级，用于 Matplotlib 中文显示）──────
CHINESE_FONTS = ["Microsoft YaHei", "SimHei", "Heiti TC", "Arial Unicode MS", "DejaVu Sans"]

# ── 其他常量 ──────────────────────────────────────────────
KDE_N_POINTS = 300
FIG_WIDTH = 16
FIG_HEIGHT_WITH_PRICE = 14
FIG_HEIGHT_WITHOUT_PRICE = 12
DATE_FMT = "%Y-%m"
DATE_INTERVAL_MONTHS = 6


def _end_label(series, text: str) -> list:
    """返回只在最后一个点显示文字的列表，用于曲线末端 label。"""
    return [None] * (len(series) - 1) + [text]


class PerformanceChart(BaseComponent):
    """多面板回测绩效图表（Plotly 交互 / Matplotlib 静态）。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def plot_backtest_charts(
            self,
            values_df: pd.DataFrame,
            benchmark_close: Optional[pd.Series] = None,
            title: Optional[str] = None,
            save_path: Optional[str] = None,
            use_plotly: bool = True,
            metrics: Optional[dict] = None,
    ) -> None:
        """绘制回测绩效图表。"""
        plt.rcParams["font.sans-serif"] = CHINESE_FONTS
        plt.rcParams["axes.unicode_minus"] = False

        df, has_price, date_text = self._prepare_df(values_df)
        strategy_nv, drawdown, returns_pct, price_norm = self._calc_series(df, has_price)
        bench_norm_price, bench_norm_nv = self._calc_benchmark(benchmark_close, df, has_price)

        if use_plotly:
            try:
                import plotly.graph_objects as go
                from plotly.subplots import make_subplots
            except ImportError as exc:  # pragma: no cover
                self.logger.info(f"Plotly 不可用（{exc}），回退到 Matplotlib")
            else:
                self._plot_plotly(
                    df=df, strategy_nv=strategy_nv, drawdown=drawdown,
                    returns_pct=returns_pct, price_norm=price_norm,
                    bench_norm_price=bench_norm_price, bench_norm_nv=bench_norm_nv,
                    has_price=has_price, title=title, date_text=date_text,
                    save_path=save_path, metrics=metrics, go=go,
                    make_subplots=make_subplots,
                )
                return

        self._plot_matplotlib(
            df=df, strategy_nv=strategy_nv, drawdown=drawdown,
            returns_pct=returns_pct, price_norm=price_norm,
            bench_norm_price=bench_norm_price, bench_norm_nv=bench_norm_nv,
            has_price=has_price, title=title, date_text=date_text,
            save_path=save_path,
        )

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
            pd.Series(benchmark_close).astype(float)
            .pipe(lambda s: s.set_axis(pd.to_datetime(s.index)))
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

    # ------------------------------------------------------------------
    # Plotly 交互图
    # ------------------------------------------------------------------

    def _plot_plotly(
            self, df, strategy_nv, drawdown, returns_pct,
            price_norm, bench_norm_price, bench_norm_nv,
            has_price, title, date_text, save_path, metrics, go, make_subplots,
    ) -> None:
        """绘制指标表格 + 五面板交互图，保存为 HTML 或在浏览器展示。"""
        has_metrics = bool(metrics)
        offset = 1 if has_metrics else 0
        chart_rows = 5
        total_rows = chart_rows + offset

        # 行高：表格占 18%，剩余按比例分配给五个图表面板
        table_h = 0.18 if has_metrics else 0.0
        panel_ratios = [0.15, 0.18, 0.17, 0.17, 0.15]
        scale = (1.0 - table_h) / sum(panel_ratios)
        row_heights = (([table_h] if has_metrics else [])
                       + [r * scale for r in panel_ratios])

        specs = (([[{"type": "domain"}]] if has_metrics else [])
                 + [[{"type": "scatter"}]] * chart_rows)

        fig = make_subplots(
            rows=total_rows, cols=1,
            shared_xaxes=False,
            vertical_spacing=0.03,
            specs=specs,
            row_heights=row_heights,
        )

        if has_metrics:
            self._add_metrics_table(fig, metrics, go)

        self._add_chart_traces(
            fig, df, strategy_nv, drawdown, returns_pct,
            price_norm, bench_norm_price, bench_norm_nv,
            has_price, offset, go,
        )

        self._update_axes(fig, offset)

        base_title = title or "策略表现分析"
        fig.update_layout(
            title=f"{base_title}<br><sup>{date_text}</sup>",
            template="plotly_white",
            showlegend=False,
            height=1600,
        )

        if save_path:
            html_path = (save_path if str(save_path).lower().endswith(".html")
                         else f"{save_path}.html")
            fig.write_html(html_path, include_plotlyjs="cdn")
            self.logger.info(f"图表已保存至 {html_path}")
        else:
            fig.show()

    @staticmethod
    def _add_metrics_table(fig, metrics: dict, go) -> None:
        """在 row=1 添加指标汇总表格。"""
        m = metrics
        total_return = m.get("total_return", 0.0)
        end_capital = float(m.get("end_capital", 0.0))
        start_capital = float(m.get("start_capital", 0.0))
        growth = end_capital - start_capital

        headers = ["交易时间", "资金概况", "收益指标", "风险指标", "绩效指标", "交易统计"]

        # cells[col][row]
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
            [
                f"总收益: {total_return:.2%}",
                f"年化收益: {m.get('annualized_return', 0.0):.2%}",
                f"日均收益: {m.get('avg_daily_return', 0.0):.2%}",
                "", "",
            ],
            [
                f"最大回撤: {m.get('max_drawdown', 0.0):.2%}",
                f"收益标准差: {m.get('return_std', 0.0):.2%}",
                f"年化波动率: {m.get('volatility', 0.0):.2%}",
                "", "",
            ],
            [
                f"夏普比率: {m.get('sharpe_ratio', 0.0):.2f}",
                f"收益回撤比: {m.get('return_drawdown_ratio', 0.0):.2f}",
                f"胜率: {m.get('win_rate', 0.0):.2%}",
                f"盈亏比: {m.get('profit_loss_ratio', 0.0):.2f}",
                f"平均盈利: {m.get('avg_win', 0.0):,.0f}",
            ],
            [
                f"总盈亏: {m.get('total_pnl', 0.0):,.0f}",
                f"总手续费: {m.get('total_commission', 0.0):,.0f}",
                f"总成交额: {m.get('total_turnover', 0.0):,.0f}",
                f"交易次数: {m.get('total_trade_count', 0)}",
                f"日均盈亏: {m.get('avg_daily_pnl', 0.0):,.0f}",
            ],
        ]

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
    def _update_axes(fig, offset: int) -> None:
        """设置各面板 Y 轴标签、X 轴日期格式及边框。"""
        y_labels = ["价格(归一化)", "净值", "回撤 (%)", "收益率 (%)", "频数"]
        for i, label in enumerate(y_labels, start=1):
            fig.update_yaxes(title_text=label, row=i + offset, col=1)

        for r in range(1 + offset, 5 + offset):
            fig.update_xaxes(showticklabels=True, tickformat="%Y-%m",
                             tickangle=0, row=r, col=1)
        fig.update_xaxes(title_text="收益率 (%)", tickangle=0, row=5 + offset, col=1)

        fig.update_xaxes(showline=True, linewidth=1, linecolor="#cccccc", mirror=True)
        fig.update_yaxes(showline=True, linewidth=1, linecolor="#cccccc", mirror=True)

    # ------------------------------------------------------------------
    # Matplotlib 静态图
    # ------------------------------------------------------------------

    def _plot_matplotlib(
            self, df, strategy_nv, drawdown, returns_pct,
            price_norm, bench_norm_price, bench_norm_nv,
            has_price, title, date_text, save_path,
    ) -> None:
        n_panels = 5 if has_price else 4
        fig_height = FIG_HEIGHT_WITH_PRICE if has_price else FIG_HEIGHT_WITHOUT_PRICE
        fig, axes = plt.subplots(n_panels, 1, figsize=(FIG_WIDTH, fig_height))

        base_title = title or "策略表现分析"
        fig.suptitle(f"{base_title} | {date_text}", fontsize=16, y=0.995)

        idx = 0
        if has_price and price_norm is not None:
            self._plot_price_compare(axes[idx], df, price_norm, bench_norm_price)
            idx += 1

        self._plot_net_value(axes[idx], df, strategy_nv, bench_norm_nv)
        self._plot_drawdown(axes[idx + 1], drawdown)
        self._plot_daily_returns(axes[idx + 2], returns_pct)
        self._plot_return_distribution(axes[idx + 3], returns_pct)

        for ax in axes[:-1]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter(DATE_FMT))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=DATE_INTERVAL_MONTHS))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

        plt.tight_layout(rect=[0, 0, 1, 0.97])

        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches="tight")
            self.logger.info(f"图表已保存至 {save_path}")
        else:
            plt.show()

    # ------------------------------------------------------------------
    # Matplotlib 各面板静态方法
    # ------------------------------------------------------------------

    @staticmethod
    def _plot_price_compare(ax, df, price_norm, bench_norm):
        ax.plot(df.index, price_norm, linewidth=1.5, color=COLOR_STRATEGY, label="策略收盘价")
        if bench_norm is not None:
            ax.plot(bench_norm.index, bench_norm.values,
                    linewidth=1.5, color=COLOR_BENCHMARK, linestyle="--", label="基准收盘价")
            ax.legend()
        ax.set_title("价格对比", fontsize=14)
        ax.set_ylabel("价格(归一化)", fontsize=11)
        ax.grid(True, alpha=0.3, linestyle="--")

    @staticmethod
    def _plot_net_value(ax, df, strategy_nv, bench_norm):
        ax.plot(df.index, strategy_nv, linewidth=2, color=COLOR_STRATEGY, label="策略净值")
        if bench_norm is not None:
            ax.plot(bench_norm.index, bench_norm.values,
                    linewidth=2, color=COLOR_BENCHMARK, linestyle="--", label="基准净值")
            ax.legend()
        ax.set_title("账户净值", fontsize=14)
        ax.set_ylabel("净值(起始=1)", fontsize=11)
        ax.grid(True, alpha=0.3, linestyle="--")

    @staticmethod
    def _plot_drawdown(ax, drawdown):
        ax.fill_between(drawdown.index, drawdown, 0, color=COLOR_DRAWDOWN_FILL, alpha=0.5)
        ax.plot(drawdown.index, drawdown, color=COLOR_DRAWDOWN_LINE, linewidth=1.5)
        ax.set_title("净值回撤", fontsize=14)
        ax.set_ylabel("回撤 (%)", fontsize=11)
        ax.grid(True, alpha=0.3, linestyle="--")

    @staticmethod
    def _plot_daily_returns(ax, returns_pct):
        colors = [COLOR_GAIN if x >= 0 else COLOR_LOSS for x in returns_pct]
        ax.bar(returns_pct.index, returns_pct, color=colors, alpha=0.7, width=0.8)
        ax.axhline(y=0, color="black", linewidth=0.5)
        y_max = max(abs(returns_pct.max()), abs(returns_pct.min()), 1) * 1.1
        ax.set_ylim(-y_max, y_max)
        ax.set_title("每日盈亏", fontsize=14)
        ax.set_ylabel("收益率 (%)", fontsize=11)
        ax.grid(True, alpha=0.3, linestyle="--", axis="y")

    @staticmethod
    def _plot_return_distribution(ax, returns_pct):
        returns_for_dist = returns_pct[returns_pct != 0]
        ax.set_title("盈亏分布（已交易日期）", fontsize=14)
        ax.set_xlabel("盈亏值 (%)", fontsize=11)
        ax.set_ylabel("频数", fontsize=11)
        ax.grid(True, alpha=0.3, linestyle="--", axis="y")

        if len(returns_for_dist) < 2:
            return

        if gaussian_kde is None:
            ax.hist(returns_for_dist, bins=40, color=COLOR_DIST_FILL, alpha=0.7, edgecolor="white")
            ax.axvline(x=0, color="gray", linestyle="--", linewidth=1, alpha=0.7)
            return

        kde = gaussian_kde(returns_for_dist)
        kde.set_bandwidth(kde.factor * 0.5)
        x_range = np.linspace(returns_for_dist.min(), returns_for_dist.max(), KDE_N_POINTS)
        frequency = kde(x_range) * (x_range[1] - x_range[0]) * len(returns_for_dist)
        ax.fill_between(x_range, 0, frequency, color=COLOR_DIST_FILL, alpha=0.7)
        ax.plot(x_range, frequency, color=COLOR_DIST_LINE, linewidth=2)
        ax.axvline(x=0, color="gray", linestyle="--", linewidth=1, alpha=0.7)
