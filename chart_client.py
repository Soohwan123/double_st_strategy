"""
RB Strategy Interactive Chart Client

TradingView 스타일의 인터랙티브 차트 클라이언트
- 마우스 드래그로 차트 이동
- 마우스 휠로 줌 인/아웃
- 캔들스틱 + 볼린저 밴드 + RSI + 진입 신호

사용법:
    python chart_client.py
"""

import sys
import numpy as np
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QFileDialog,
                             QStatusBar, QComboBox, QSpinBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
import pyqtgraph as pg
from pyqtgraph import DateAxisItem

# ================================================================================
# CONFIG
# ================================================================================

DEFAULT_DATA_FILE = 'backtest_data/BTCUSDT_rb_strategy.csv'
INITIAL_BARS = 100  # 초기 표시할 봉 개수

# 색상 설정
COLOR_BG = '#1e1e1e'
COLOR_GRID = '#333333'
COLOR_TEXT = '#ffffff'
COLOR_CANDLE_UP = '#26a69a'
COLOR_CANDLE_DOWN = '#ef5350'
COLOR_BB_BASIS = '#ff9800'
COLOR_BB_BAND = '#2196f3'
COLOR_RSI = '#9c27b0'
COLOR_LONG_SIGNAL = '#00ff00'
COLOR_SHORT_SIGNAL = '#ff00ff'


# ================================================================================
# Custom Candlestick Item
# ================================================================================

class CandlestickItem(pg.GraphicsObject):
    """캔들스틱 차트 아이템"""

    def __init__(self, data):
        pg.GraphicsObject.__init__(self)
        self.data = data  # DataFrame with OHLC
        self.generatePicture()

    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)

        w = 0.3  # 캔들 폭

        for i, row in self.data.iterrows():
            idx = row['idx']
            o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']

            if c >= o:
                color = pg.mkColor(COLOR_CANDLE_UP)
            else:
                color = pg.mkColor(COLOR_CANDLE_DOWN)

            p.setPen(pg.mkPen(color))
            p.setBrush(pg.mkBrush(color))

            # 심지
            p.drawLine(pg.QtCore.QPointF(idx, l), pg.QtCore.QPointF(idx, h))

            # 몸통
            p.drawRect(pg.QtCore.QRectF(idx - w, min(o, c), w * 2, abs(c - o)))

        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())

    def updateData(self, data):
        self.data = data
        self.generatePicture()
        self.informViewBoundsChanged()


# ================================================================================
# Main Chart Window
# ================================================================================

class ChartWindow(QMainWindow):
    """메인 차트 윈도우"""

    def __init__(self):
        super().__init__()
        self.df = None
        self.current_start = 0
        self.current_end = INITIAL_BARS

        self.initUI()
        self.loadData(DEFAULT_DATA_FILE)

    def initUI(self):
        """UI 초기화"""
        self.setWindowTitle('RB Strategy Chart - TradingView Style')
        self.setGeometry(100, 100, 1600, 900)
        self.setStyleSheet(f"background-color: {COLOR_BG}; color: {COLOR_TEXT};")

        # 메인 위젯
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # 상단 툴바
        toolbar = QHBoxLayout()

        # 파일 선택 버튼
        self.btn_load = QPushButton('CSV 불러오기')
        self.btn_load.clicked.connect(self.openFile)
        toolbar.addWidget(self.btn_load)

        # 표시할 봉 개수
        toolbar.addWidget(QLabel('봉 개수:'))
        self.spin_bars = QSpinBox()
        self.spin_bars.setRange(50, 500)
        self.spin_bars.setValue(INITIAL_BARS)
        self.spin_bars.valueChanged.connect(self.onBarsChanged)
        toolbar.addWidget(self.spin_bars)

        # 처음/끝으로 이동
        self.btn_start = QPushButton('◀◀ 처음')
        self.btn_start.clicked.connect(self.goToStart)
        toolbar.addWidget(self.btn_start)

        self.btn_end = QPushButton('끝 ▶▶')
        self.btn_end.clicked.connect(self.goToEnd)
        toolbar.addWidget(self.btn_end)

        # 신호 점프
        self.btn_prev_signal = QPushButton('◀ 이전 신호')
        self.btn_prev_signal.clicked.connect(self.goToPrevSignal)
        toolbar.addWidget(self.btn_prev_signal)

        self.btn_next_signal = QPushButton('다음 신호 ▶')
        self.btn_next_signal.clicked.connect(self.goToNextSignal)
        toolbar.addWidget(self.btn_next_signal)

        toolbar.addStretch()

        # 현재 위치 라벨
        self.lbl_info = QLabel('')
        self.lbl_info.setFont(QFont('Consolas', 10))
        toolbar.addWidget(self.lbl_info)

        layout.addLayout(toolbar)

        # 차트 영역 (GraphicsLayoutWidget 사용)
        self.graphics_layout = pg.GraphicsLayoutWidget()
        self.graphics_layout.setBackground(COLOR_BG)
        layout.addWidget(self.graphics_layout)

        # 가격 차트 (상단 70%)
        self.price_plot = self.graphics_layout.addPlot(row=0, col=0)
        self.price_plot.setLabel('left', 'Price', color=COLOR_TEXT)
        self.price_plot.showGrid(x=True, y=True, alpha=0.3)
        self.price_plot.setMouseEnabled(x=True, y=False)

        # RSI 차트 (하단 30%)
        self.graphics_layout.nextRow()
        self.rsi_plot = self.graphics_layout.addPlot(row=1, col=0)
        self.rsi_plot.setLabel('left', 'RSI', color=COLOR_TEXT)
        self.rsi_plot.showGrid(x=True, y=True, alpha=0.3)
        self.rsi_plot.setYRange(0, 100)
        self.rsi_plot.setMouseEnabled(x=True, y=False)

        # X축 연동
        self.rsi_plot.setXLink(self.price_plot)

        # 차트 크기 비율 설정
        self.graphics_layout.ci.layout.setRowStretchFactor(0, 3)
        self.graphics_layout.ci.layout.setRowStretchFactor(1, 1)

        # 마우스 드래그 이벤트
        self.price_plot.scene().sigMouseMoved.connect(self.onMouseMoved)
        self.price_plot.sigXRangeChanged.connect(self.onRangeChanged)

        # 상태바
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage('Ready')

    def loadData(self, filepath):
        """CSV 데이터 로드"""
        try:
            self.df = pd.read_csv(filepath)
            self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
            self.df['idx'] = range(len(self.df))  # 인덱스 추가

            # 신호 인덱스 저장
            self.long_signal_indices = self.df[self.df['long_signal'] == True]['idx'].tolist()
            self.short_signal_indices = self.df[self.df['short_signal'] == True]['idx'].tolist()
            self.all_signal_indices = sorted(self.long_signal_indices + self.short_signal_indices)

            # 초기 범위 설정 (끝에서 시작)
            self.current_end = len(self.df)
            self.current_start = max(0, self.current_end - self.spin_bars.value())

            self.updateChart()
            self.statusBar.showMessage(f'Loaded: {filepath} ({len(self.df):,} rows, '
                                       f'LONG: {len(self.long_signal_indices)}, '
                                       f'SHORT: {len(self.short_signal_indices)})')
        except Exception as e:
            self.statusBar.showMessage(f'Error: {str(e)}')

    def updateChart(self):
        """차트 업데이트"""
        if self.df is None:
            return

        # 현재 범위의 데이터
        df_view = self.df.iloc[self.current_start:self.current_end].copy()

        if len(df_view) == 0:
            return

        # 가격 차트 초기화
        self.price_plot.clear()

        # 캔들스틱
        candle_item = CandlestickItem(df_view)
        self.price_plot.addItem(candle_item)

        # 볼린저 밴드
        idx = df_view['idx'].values
        self.price_plot.plot(idx, df_view['bb_basis'].values,
                            pen=pg.mkPen(COLOR_BB_BASIS, width=1), name='BB Basis')
        self.price_plot.plot(idx, df_view['bb_upper'].values,
                            pen=pg.mkPen(COLOR_BB_BAND, width=1, style=Qt.DashLine), name='BB Upper')
        self.price_plot.plot(idx, df_view['bb_lower'].values,
                            pen=pg.mkPen(COLOR_BB_BAND, width=1, style=Qt.DashLine), name='BB Lower')

        # BB 영역 채우기
        fill = pg.FillBetweenItem(
            pg.PlotDataItem(idx, df_view['bb_upper'].values),
            pg.PlotDataItem(idx, df_view['bb_lower'].values),
            brush=pg.mkBrush(COLOR_BB_BAND + '20')
        )
        self.price_plot.addItem(fill)

        # LONG 신호 (녹색 삼각형)
        long_signals = df_view[df_view['long_signal'] == True]
        if len(long_signals) > 0:
            self.price_plot.plot(long_signals['idx'].values,
                                long_signals['Low'].values * 0.999,
                                pen=None, symbol='t', symbolSize=15,
                                symbolBrush=COLOR_LONG_SIGNAL, name='LONG')

        # SHORT 신호 (마젠타 역삼각형)
        short_signals = df_view[df_view['short_signal'] == True]
        if len(short_signals) > 0:
            self.price_plot.plot(short_signals['idx'].values,
                                short_signals['High'].values * 1.001,
                                pen=None, symbol='t1', symbolSize=15,
                                symbolBrush=COLOR_SHORT_SIGNAL, name='SHORT')

        # RSI 차트 초기화
        self.rsi_plot.clear()

        # RSI 라인
        self.rsi_plot.plot(idx, df_view['rsi'].values,
                          pen=pg.mkPen(COLOR_RSI, width=2), name='RSI')

        # RSI 기준선
        self.rsi_plot.addLine(y=50, pen=pg.mkPen('#666666', width=1, style=Qt.DashLine))
        self.rsi_plot.addLine(y=70, pen=pg.mkPen('#ff0000', width=1, style=Qt.DotLine))
        self.rsi_plot.addLine(y=30, pen=pg.mkPen('#00ff00', width=1, style=Qt.DotLine))

        # X축 범위 설정
        self.price_plot.setXRange(idx[0], idx[-1], padding=0.02)

        # 정보 라벨 업데이트
        start_time = df_view['timestamp'].iloc[0].strftime('%Y-%m-%d %H:%M')
        end_time = df_view['timestamp'].iloc[-1].strftime('%Y-%m-%d %H:%M')
        self.lbl_info.setText(f'{start_time} ~ {end_time} | {len(df_view)} bars')

    def onRangeChanged(self, view, range):
        """X축 범위 변경 시 호출"""
        if self.df is None:
            return

        x_min, x_max = range
        visible_bars = int(x_max - x_min)

        # 범위를 벗어나면 데이터 로드
        if x_min < self.current_start + 10:
            # 왼쪽으로 이동 (과거 데이터 필요)
            new_start = max(0, int(x_min) - 50)
            if new_start < self.current_start:
                self.current_start = new_start
                self.updateChart()

        if x_max > self.current_end - 10:
            # 오른쪽으로 이동 (미래 데이터 필요)
            new_end = min(len(self.df), int(x_max) + 50)
            if new_end > self.current_end:
                self.current_end = new_end
                self.updateChart()

    def onMouseMoved(self, pos):
        """마우스 이동 시 호출"""
        if self.df is None:
            return

        mouse_point = self.price_plot.vb.mapSceneToView(pos)
        idx = int(mouse_point.x())

        if 0 <= idx < len(self.df):
            row = self.df.iloc[idx]
            time_str = row['timestamp'].strftime('%Y-%m-%d %H:%M')
            price_info = f"O:{row['Open']:.1f} H:{row['High']:.1f} L:{row['Low']:.1f} C:{row['Close']:.1f}"
            rsi_info = f"RSI:{row['rsi']:.1f}"

            signal = ""
            if row['long_signal']:
                signal = " [LONG]"
            elif row['short_signal']:
                signal = " [SHORT]"

            self.statusBar.showMessage(f'{time_str} | {price_info} | {rsi_info}{signal}')

    def onBarsChanged(self, value):
        """봉 개수 변경"""
        self.current_start = max(0, self.current_end - value)
        self.updateChart()

    def goToStart(self):
        """처음으로 이동"""
        bars = self.spin_bars.value()
        self.current_start = 0
        self.current_end = min(bars, len(self.df))
        self.updateChart()

    def goToEnd(self):
        """끝으로 이동"""
        bars = self.spin_bars.value()
        self.current_end = len(self.df)
        self.current_start = max(0, self.current_end - bars)
        self.updateChart()

    def goToPrevSignal(self):
        """이전 신호로 이동"""
        if not self.all_signal_indices:
            return

        current_center = (self.current_start + self.current_end) // 2

        # 현재 위치보다 작은 신호 찾기
        prev_signals = [i for i in self.all_signal_indices if i < current_center]
        if prev_signals:
            target = prev_signals[-1]
            bars = self.spin_bars.value()
            self.current_start = max(0, target - bars // 2)
            self.current_end = min(len(self.df), self.current_start + bars)
            self.updateChart()

    def goToNextSignal(self):
        """다음 신호로 이동"""
        if not self.all_signal_indices:
            return

        current_center = (self.current_start + self.current_end) // 2

        # 현재 위치보다 큰 신호 찾기
        next_signals = [i for i in self.all_signal_indices if i > current_center]
        if next_signals:
            target = next_signals[0]
            bars = self.spin_bars.value()
            self.current_start = max(0, target - bars // 2)
            self.current_end = min(len(self.df), self.current_start + bars)
            self.updateChart()

    def openFile(self):
        """파일 열기 대화상자"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, 'CSV 파일 선택', '', 'CSV Files (*.csv)'
        )
        if filepath:
            self.loadData(filepath)

    def keyPressEvent(self, event):
        """키보드 이벤트"""
        bars = self.spin_bars.value()
        step = max(1, bars // 10)  # 10% 씩 이동

        if event.key() == Qt.Key_Left:
            self.current_start = max(0, self.current_start - step)
            self.current_end = self.current_start + bars
            self.updateChart()
        elif event.key() == Qt.Key_Right:
            self.current_end = min(len(self.df), self.current_end + step)
            self.current_start = max(0, self.current_end - bars)
            self.updateChart()
        elif event.key() == Qt.Key_Home:
            self.goToStart()
        elif event.key() == Qt.Key_End:
            self.goToEnd()
        elif event.key() == Qt.Key_PageUp:
            self.goToPrevSignal()
        elif event.key() == Qt.Key_PageDown:
            self.goToNextSignal()


# ================================================================================
# Main
# ================================================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # 다크 테마
    palette = app.palette()
    palette.setColor(palette.Window, pg.mkColor(COLOR_BG))
    palette.setColor(palette.WindowText, pg.mkColor(COLOR_TEXT))
    palette.setColor(palette.Base, pg.mkColor('#2d2d2d'))
    palette.setColor(palette.AlternateBase, pg.mkColor(COLOR_BG))
    palette.setColor(palette.ToolTipBase, pg.mkColor(COLOR_TEXT))
    palette.setColor(palette.ToolTipText, pg.mkColor(COLOR_TEXT))
    palette.setColor(palette.Text, pg.mkColor(COLOR_TEXT))
    palette.setColor(palette.Button, pg.mkColor('#3d3d3d'))
    palette.setColor(palette.ButtonText, pg.mkColor(COLOR_TEXT))
    palette.setColor(palette.Highlight, pg.mkColor('#2196f3'))
    palette.setColor(palette.HighlightedText, pg.mkColor(COLOR_TEXT))
    app.setPalette(palette)

    window = ChartWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
