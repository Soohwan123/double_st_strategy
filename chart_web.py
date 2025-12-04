"""
RB Strategy Web Chart Client

브라우저 기반 인터랙티브 차트
- 마우스 드래그로 차트 이동
- 마우스 휠로 줌 인/아웃
- 캔들스틱 + 볼린저 밴드 + RSI + 진입 신호

사용법:
    python chart_web.py
    브라우저에서 http://localhost:8050 접속
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import Dash, html, dcc, callback, Output, Input, State
import dash_bootstrap_components as dbc

# ================================================================================
# CONFIG
# ================================================================================

DEFAULT_DATA_FILE = 'backtest_data/BTCUSDT_rb_strategy.csv'
INITIAL_BARS = 150

# 색상
COLOR_BG = '#1e1e1e'
COLOR_CANDLE_UP = '#26a69a'
COLOR_CANDLE_DOWN = '#ef5350'
COLOR_BB_BASIS = '#ff9800'
COLOR_BB_BAND = '#2196f3'
COLOR_RSI = '#9c27b0'


# ================================================================================
# 데이터 로드
# ================================================================================

def load_data(filepath=DEFAULT_DATA_FILE):
    df = pd.read_csv(filepath)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


# ================================================================================
# 차트 생성
# ================================================================================

def create_chart(df, start_idx, end_idx):
    """Plotly 차트 생성"""
    df_view = df.iloc[start_idx:end_idx].copy()

    if len(df_view) == 0:
        return go.Figure()

    # 서브플롯 생성 (가격 + RSI)
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3],
        subplot_titles=('Price + Bollinger Bands', 'RSI(6)')
    )

    # 캔들스틱
    fig.add_trace(
        go.Candlestick(
            x=df_view['timestamp'],
            open=df_view['Open'],
            high=df_view['High'],
            low=df_view['Low'],
            close=df_view['Close'],
            name='BTCUSDT',
            increasing_line_color=COLOR_CANDLE_UP,
            decreasing_line_color=COLOR_CANDLE_DOWN,
        ),
        row=1, col=1
    )

    # 볼린저 밴드 - Basis
    fig.add_trace(
        go.Scatter(
            x=df_view['timestamp'],
            y=df_view['bb_basis'],
            mode='lines',
            name='BB Basis (200)',
            line=dict(color=COLOR_BB_BASIS, width=1)
        ),
        row=1, col=1
    )

    # 볼린저 밴드 - Upper
    fig.add_trace(
        go.Scatter(
            x=df_view['timestamp'],
            y=df_view['bb_upper'],
            mode='lines',
            name='BB Upper',
            line=dict(color=COLOR_BB_BAND, width=1, dash='dash')
        ),
        row=1, col=1
    )

    # 볼린저 밴드 - Lower
    fig.add_trace(
        go.Scatter(
            x=df_view['timestamp'],
            y=df_view['bb_lower'],
            mode='lines',
            name='BB Lower',
            line=dict(color=COLOR_BB_BAND, width=1, dash='dash'),
            fill='tonexty',
            fillcolor='rgba(33, 150, 243, 0.1)'
        ),
        row=1, col=1
    )

    # LONG 신호
    long_signals = df_view[df_view['long_signal'] == True]
    if len(long_signals) > 0:
        fig.add_trace(
            go.Scatter(
                x=long_signals['timestamp'],
                y=long_signals['Low'] * 0.998,
                mode='markers',
                name=f'LONG ({len(long_signals)})',
                marker=dict(
                    symbol='triangle-up',
                    size=15,
                    color='lime',
                    line=dict(width=1, color='white')
                )
            ),
            row=1, col=1
        )

    # SHORT 신호
    short_signals = df_view[df_view['short_signal'] == True]
    if len(short_signals) > 0:
        fig.add_trace(
            go.Scatter(
                x=short_signals['timestamp'],
                y=short_signals['High'] * 1.002,
                mode='markers',
                name=f'SHORT ({len(short_signals)})',
                marker=dict(
                    symbol='triangle-down',
                    size=15,
                    color='magenta',
                    line=dict(width=1, color='white')
                )
            ),
            row=1, col=1
        )

    # RSI
    fig.add_trace(
        go.Scatter(
            x=df_view['timestamp'],
            y=df_view['rsi'],
            mode='lines',
            name='RSI(6)',
            line=dict(color=COLOR_RSI, width=2)
        ),
        row=2, col=1
    )

    # RSI 기준선
    fig.add_hline(y=50, line_dash="dash", line_color="gray", row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="green", row=2, col=1)

    # 레이아웃 설정
    fig.update_layout(
        title=f'RB Strategy Chart | {df_view["timestamp"].iloc[0].strftime("%Y-%m-%d %H:%M")} ~ {df_view["timestamp"].iloc[-1].strftime("%Y-%m-%d %H:%M")}',
        template='plotly_dark',
        paper_bgcolor=COLOR_BG,
        plot_bgcolor=COLOR_BG,
        height=800,
        xaxis_rangeslider_visible=False,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        margin=dict(l=50, r=50, t=80, b=50)
    )

    # Y축 범위 고정 (RSI)
    fig.update_yaxes(range=[0, 100], row=2, col=1)

    # 그리드 설정
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#333333')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#333333')

    return fig


# ================================================================================
# Dash 앱
# ================================================================================

# Bootstrap 다크 테마 사용
app = Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])

# 데이터 로드
df = load_data()
total_bars = len(df)

# 신호 인덱스
long_indices = df[df['long_signal'] == True].index.tolist()
short_indices = df[df['short_signal'] == True].index.tolist()
all_signal_indices = sorted(long_indices + short_indices)

# 레이아웃
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H3("RB Strategy Chart", className="text-center my-3"),
        ])
    ]),

    # 컨트롤 패널
    dbc.Row([
        dbc.Col([
            dbc.ButtonGroup([
                dbc.Button("◀◀ 처음", id="btn-start", color="secondary", size="sm"),
                dbc.Button("◀ 이전 신호", id="btn-prev-signal", color="info", size="sm"),
                dbc.Button("이동 ◀", id="btn-left", color="primary", size="sm"),
                dbc.Button("▶ 이동", id="btn-right", color="primary", size="sm"),
                dbc.Button("다음 신호 ▶", id="btn-next-signal", color="info", size="sm"),
                dbc.Button("끝 ▶▶", id="btn-end", color="secondary", size="sm"),
            ], className="me-3"),
        ], width="auto"),

        dbc.Col([
            html.Label("봉 개수:", className="me-2"),
            dcc.Slider(
                id='slider-bars',
                min=50,
                max=500,
                step=50,
                value=INITIAL_BARS,
                marks={i: str(i) for i in range(50, 501, 100)},
            ),
        ], width=4),

        dbc.Col([
            html.Div(id='info-text', className="text-info")
        ], width="auto"),
    ], className="mb-3 align-items-center"),

    # 차트
    dbc.Row([
        dbc.Col([
            dcc.Graph(
                id='chart',
                config={
                    'scrollZoom': True,
                    'displayModeBar': True,
                    'modeBarButtonsToAdd': ['drawline', 'drawopenpath', 'eraseshape']
                }
            )
        ])
    ]),

    # 상태 저장
    dcc.Store(id='store-position', data={'start': max(0, total_bars - INITIAL_BARS), 'end': total_bars}),

], fluid=True)


# ================================================================================
# 콜백
# ================================================================================

@callback(
    Output('chart', 'figure'),
    Output('info-text', 'children'),
    Output('store-position', 'data'),
    Input('btn-start', 'n_clicks'),
    Input('btn-end', 'n_clicks'),
    Input('btn-left', 'n_clicks'),
    Input('btn-right', 'n_clicks'),
    Input('btn-prev-signal', 'n_clicks'),
    Input('btn-next-signal', 'n_clicks'),
    Input('slider-bars', 'value'),
    State('store-position', 'data'),
    prevent_initial_call=False
)
def update_chart(n_start, n_end, n_left, n_right, n_prev, n_next, bars, position):
    from dash import ctx

    start = position['start']
    end = position['end']
    step = max(1, bars // 5)

    triggered = ctx.triggered_id

    if triggered == 'btn-start':
        start = 0
        end = min(bars, total_bars)
    elif triggered == 'btn-end':
        end = total_bars
        start = max(0, end - bars)
    elif triggered == 'btn-left':
        start = max(0, start - step)
        end = start + bars
    elif triggered == 'btn-right':
        end = min(total_bars, end + step)
        start = max(0, end - bars)
    elif triggered == 'btn-prev-signal':
        center = (start + end) // 2
        prev_signals = [i for i in all_signal_indices if i < center]
        if prev_signals:
            target = prev_signals[-1]
            start = max(0, target - bars // 2)
            end = min(total_bars, start + bars)
    elif triggered == 'btn-next-signal':
        center = (start + end) // 2
        next_signals = [i for i in all_signal_indices if i > center]
        if next_signals:
            target = next_signals[0]
            start = max(0, target - bars // 2)
            end = min(total_bars, start + bars)
    elif triggered == 'slider-bars':
        # 봉 개수 변경 시 중심 유지
        center = (start + end) // 2
        start = max(0, center - bars // 2)
        end = min(total_bars, start + bars)

    # 범위 보정
    if end > total_bars:
        end = total_bars
        start = max(0, end - bars)
    if start < 0:
        start = 0
        end = min(bars, total_bars)

    fig = create_chart(df, start, end)

    # 현재 범위의 신호 수
    current_long = len([i for i in long_indices if start <= i < end])
    current_short = len([i for i in short_indices if start <= i < end])

    info = f"📊 {start:,} ~ {end:,} / {total_bars:,} | LONG: {current_long} | SHORT: {current_short}"

    return fig, info, {'start': start, 'end': end}


# ================================================================================
# 실행
# ================================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 RB Strategy Chart Server")
    print("=" * 60)
    print(f"📂 Data: {DEFAULT_DATA_FILE}")
    print(f"📊 Total bars: {total_bars:,}")
    print(f"📈 LONG signals: {len(long_indices)}")
    print(f"📉 SHORT signals: {len(short_indices)}")
    print()
    print("🌐 Open browser: http://localhost:8050")
    print("=" * 60)

    app.run(debug=False, host='0.0.0.0', port=8050)
