  martingale_live_trading/
  ├── .env                    # API 키
  ├── config.py               # 설정 로더 (동적 리로드)
  ├── config_btc.txt          # BTC 파라미터 (런타임 수정 가능)
  ├── config_eth.txt          # ETH 파라미터 (런타임 수정 가능)
  ├── state_manager.py        # 상태 스냅샷 저장/복구
  ├── binance_library.py      # 바이낸스 API 래퍼 (지정가 진입 포함)
  ├── grid_strategy.py        # 그리드 마틴게일 전략 클래스
  ├── trade_btc.py            # BTC 메인 트레이딩
  ├── trade_eth.py            # ETH 메인 트레이딩
  ├── scripts/
  │   ├── start_btc.sh        # BTC 시작
  │   ├── start_eth.sh        # ETH 시작
  │   ├── start_all.sh        # 전체 시작
  │   ├── stop_btc.sh         # BTC 중지
  │   ├── stop_eth.sh         # ETH 중지
  │   ├── stop_all.sh         # 전체 중지
  │   ├── status.sh           # 상태 확인
  │   └── logs.sh             # 실시간 로그
  ├── state/                  # 상태 파일 저장
  ├── logs/                   # 일별 로그 파일
  └── trades/                 # 거래 CSV 파일

  사용법:
  cd martingale_live_trading/scripts

  # 시작
  ./start_btc.sh          # BTC만
  ./start_eth.sh          # ETH만
  ./start_all.sh          # 둘 다

  # 상태 확인
  ./status.sh

  # 로그 확인
  ./logs.sh btc           # BTC만
  ./logs.sh eth           # ETH만
  ./logs.sh               # 둘 다

  # 중지
  ./stop_btc.sh
  ./stop_eth.sh
  ./stop_all.sh
