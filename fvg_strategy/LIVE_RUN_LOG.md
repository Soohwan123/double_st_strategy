# FVG Strategy LIVE 운영 로그

라이브 실행 시점 / 중지·재시작 히스토리 / 버그 수정 기록 / 백테스트 비교 계획.

---

## 📌 현재 안정 운영 시작 시각 (버그 수정 없이 유지된 시점)

**최종 재시작 (price_feed 중앙화 구조 전환 — 2026-04-24 06:59 UTC / 15:59 KST):**
- **ETH**: 실포지션 SHORT @ $2310 오픈 상태 유지 → 비교 기준 시각 **그대로 `2026-04-24 02:15:00 UTC`** 유지
- **XRP/SOL**: 포지션 없이 재기동 → 비교 기준 시각 **`2026-04-24 07:15:00 UTC`** 로 갱신
- **Hyper 4개**: 새 price_feed 구조로 재기동 (포지션 없음)
- **MAX_LEVERAGE=5** 로 FVG 4개 config 조정 (부계정 제한)

ETH=bt_28, XRP=bt_27, SOL=bt_25 (1m entry-bar resolve 기반 v2 최적화)

> 이 시각이 "1주일 안정 운영" 시작점. 이 시각 이후 재시작이 없으면 +7일 뒤 백테스트 비교 진행.
> 재시작 발생 시 이 필드 갱신 + 아래 히스토리에 사유 기록.

---

## 실행 히스토리

| # | 시각 (UTC / KST) | 유형 | 사유 / 변경 내용 | 결과 |
|---|---|---|---|---|
| 1 | 2026-04-23 03:19:37 / 12:19:37 | **최초 LIVE 시작** | DRY_RUN → LIVE 전환. 4심볼 × $1,350 = $5,400 (지갑 $5,998 × 0.9). state/logs/trades 초기화 후 기동 | XRP/SOL 첫 봉(03:15 UTC)에서 SHORT pending 정상 배치 (XRP 147275593984, SOL 210441986495) |
| 2 | 2026-04-23 03:38:23 / 12:38:23 | **재시작 (버그 수정)** | `_get_best_entries`가 `get_newest()` 하나만 체크 → 현재 봉 FVG 뽑힐 때 이전 봉 FVG 있어도 진입 못 함. `get_newest_before(current_bar_idx)` 추가해 백테스트 로직과 일치시킴. ETH가 03:15 봉에서 진입 못 한 원인. XRP/SOL pending은 거래소에 그대로 있어 `_validate_pending_order`로 정상 복구 | 4개 전부 상태 복구 OK. XRP/SOL pending 유지 (NEW). 다음 봉부터 수정 로직 적용 |
| 3 | 2026-04-23 03:52:23 / 12:52:23 | **재시작 (버그 수정)** | `load_historical_data`에서 `if not has_position and not has_pending: _simulate_history_queue()` 가드로 인해 **재시작 시 pending/position이 있으면 simulation 스킵 → queue 빈 상태로 시작**. 12:45 봉 마감에서 XRP/SOL이 기존 pending 취소했지만 queue가 비어 있어 재배치 못 함 (`get_newest_before`가 current bar FVG밖에 없으니 None 반환). Fix: simulation은 항상 실행해 queue 재구축, 가상 포지션 takeover는 state에 이미 복구된 position/pending 없을 때만 (overwrite 방지) | ETH pending 복구 + 전 심볼 queue 재구축: BTC=4 ETH=4 XRP=3 SOL=1 short queue. 다음 봉부터 정상 동작 |
| 4 | 2026-04-23 04:33:23 / 13:33:23 | **재시작 (semantic 정합성 수정)** | ETH에서 "직전 봉이 이미 터치한 FVG에 pending 재주문" 현상 관찰 → 사용자 전량 취소 후 프로그램 전면 중지. 원인 분석: 시뮬레이션은 백테스트와 100% 동일한 로직(FVG 감지/invalidation/entry 순서, `l[i] <= top` 조건, close 기반 invalidation)이라 버그 아님. 실제 문제는 **LIVE 모드에서 시뮬 종료 시점의 가상 포지션을 "폐기"하고 즉시 실거래 시작한 것** → 백테스트라면 그 시점 포지션이 열려있어 진입 막혔을 FVG에 LIVE가 pending을 배치. Fix: DRY/LIVE 모두 가상 포지션 `takeover` 동일 적용 → `is_virtual=True` 로 표시하고 가상 LIQ/SL/TP 도달할 때까지 실주문 금지, 가상 청산 후 정상 LIVE 진입. 로그/trades 파일 초기화 | 4개 전부 정상 기동. BTC/SOL: 가상 포지션 없음 + 큐 재구축 (long=0/short=3, long=0/short=1). ETH: 가상 SHORT @ $2339.28 이어받음. XRP: 가상 SHORT @ $1.4191 이어받음. 에러/예외 없음 |
| 5 | 2026-04-23 13:20:33 / 22:20:33 | **재시작 (exit-bar FVG detection divergence 수정)** | 운영 중 trade-by-trade 대조 결과 ETH 07:21 LONG @ 2347.52 가 백테스트에 없는 엉뚱한 진입으로 판명. 원인: 백테스트 `_common.py` 는 LIQ/SL/TP exit 직후 `continue` 로 같은 봉의 FVG 감지/invalidation/entry 를 스킵하는데, live/sim 엔 해당 `continue` 가 없어 exit 봉에서도 FVG 가 queue 에 추가되어 이후 pending 배치로 이어짐. ETH 06:00-06:15 봉: 가상 SHORT SL 히트와 동시에 LONG FVG top=2347.52 형성 → 백테스트는 FVG 스킵, live 는 추가 → 07:21 엉뚱한 LONG 진입. Fix: (1) `_simulate_history_queue` 에 `exited=True` 시 `continue` 추가 (2) strategy 에 `_exit_this_bar` 플래그 추가, 모든 exit 경로 (virtual, LIQ DRY, on_tp_filled, on_sl_filled, _emergency_close) 에서 True 세팅, `on_candle_close` 에서 pending fill 체크 직후 True 면 FVG 감지/invalidation/entry 스킵하고 플래그 리셋 | 4개 모두 기존 상태 유지 기동: BTC LONG@77649.9, ETH LONG@2327.43, XRP virtual SHORT@1.4191, SOL pending LONG@85.51. 에러/예외 없음 |
| 6 | 2026-04-23 23:08:33 / 2026-04-24 08:08:33 | **재시작 (WebSocket heartbeat + capital 축소)** | 17:00 UTC 경 ETH/SOL WebSocket kline substream 이 죽어서 약 3시간 bar close 미처리 → 백테스트 18:00 UTC ETH SHORT entry 등 여러 봉 놓침. 원인: `await ws.recv()` 가 connection 끊김 감지 못하고 무한대기. Fix: `asyncio.wait_for(ws.recv(), timeout=30)` 로 30초 무수신 시 `asyncio.TimeoutError` 발생시켜 강제 재연결. 4개 trade_fvg_*.py 전부 적용. 사용자 요청으로 BTC 는 제외 (최대 레버리지 cap 때문에 백테스트 괴리 큼) 하고 ETH/XRP/SOL 자본 $200 씩으로 축소. logs/trades 전부 초기화, state position=null + capital=200 으로 재설정, config INITIAL_CAPITAL 200 으로 동기화. BTC 는 정지 상태 유지 | ETH/XRP/SOL 3개 정상 기동, 자본 $200, 가상 포지션 없음. ⚠️ 이전 SOL pending LONG @ 85.51 이 fill 되어 실포지션 59 SOL @ 85.74 가 거래소에 남아있음 (SL/TP 없는 naked) — 별도 처리 필요 |
| 7 | 2026-04-24 00:53:57 / 09:53:57 | **재시작 (ETH/XRP 새 파라미터)** | 새 fvg_winners 로직 (1m entry-bar resolve 추가) 기반 재최적화된 파일로 교체. XRP: bt_15 (v6_2, RR=1.4, SL_BUF=0.0045, MAX_WAIT=15, RPT=0.025) → **bt_27 (v6_1, RR=1.2, SL_BUF=0.004, MAX_WAIT=20, RPT=0.02)**. ETH: bt_10 (v3, MAX_WAIT=20, RPT=0.02) → **bt_28 (v3, MAX_WAIT=10, RPT=0.015)**. config_fvg_eth.txt / config_fvg_xrp.txt 업데이트. ETH/XRP logs/trades 삭제, state position=null + capital=$200 초기화. SOL 은 기존 파라미터 유지 (bt_18, 사용자가 나중에 bt_25 로 교체 요청 시 바꿀 예정) | ETH 가상 LONG @ $2328.22 takeover, XRP 가상 없음 (long_queue=2 대기), SOL 기존 유지 |
| 8 | 2026-04-24 01:19:42 / 10:19:42 (ETH/XRP)<br>2026-04-24 01:21:09 / 10:21:09 (SOL) | **재시작 (1봉 지연 버그 수정 + SOL 새 파라미터)** | (1) 버그: `_get_best_entries` 에서 `get_newest_before(self._bar_idx)` 를 `get_newest()` 로 교체. 문제: backtest 는 바 i 처리 중 `long_bar[k] < i` 로 같은 봉 FVG 를 제외하지만 이는 "바 i OHLC 를 같은 loop iteration 에서 관측" 전제. Live 는 "바 N 마감 후 pending 을 올려 바 N+1 체결" 구조라 바 N 에서 방금 감지된 FVG(bar_idx=N) 도 포함해야 backtest 의 바 N+1 entry 와 타이밍이 맞음. 기존 `<` 필터 때문에 **live 가 backtest 보다 1봉 늦게 pending 배치 → 1봉 늦게 체결** 되고 있었음. 정상 retest 케이스는 1봉 지연, 가격이 FVG top 을 한 번만 찍고 안 돌아오는 케이스에선 backtest 는 진입하는데 live 는 아예 놓침. `_simulate_history_queue` 는 여전히 인라인 `entry.bar_idx < i` 사용 (backtest semantic 재현용 유지). (2) SOL 파라미터 교체: bt_18 (v6_1, RR=1.7, SL_BUF=0.004, MAX_WAIT=7, RPT=0.025) → **bt_25 (v6_1, RR=1.2, SL_BUF=0.003, MAX_WAIT=10, RPT=0.03)**. 사용자가 수동으로 ETH/XRP/SOL 전부 정지 + 거래소 주문·포지션 정리 후 로그/trades/state 전체 초기화하고 재기동 | ETH/XRP/SOL 3개 정상 기동, 자본 $200, 가상 포지션 없음 (ETH HTF 양방향, XRP/SOL HTF bull). 에러 없음 |
| 11 | 2026-04-24 06:59:32 / 15:59:32 (전 전략 + price_feed) | **중앙 시세 프로세스 (price_feed) 구조로 전환** | Binance WS `aggTrade` 스트림 **글로벌 이슈** (2026-04-24, 여러 IP 에서 aggTrade 0 msg 확인 / trade 는 정상 수신) 로 전 전략 시세 끊김. 해결: (1) 7개 개별 WS connection → **1개 중앙 `price_feed.py`** (단일 combined stream 15 streams 구독) + ZMQ PUB 로 localhost 뿌리기. (2) 각 전략은 `IPCSubscriber` 로 SUB 연결 (web socket_handler 대체). (3) `aggTrade` → **`trade` 스트림** 교체 (같은 p/q 필드, 더 실시간). (4) heartbeat timeout 30s → 90s, exponential backoff 5→300s 적용. (5) FVG 4개 config `MAX_LEVERAGE=90→5` (부계정 -4421 에러 대응, VIP 1 까지 유지). (6) crontab 에 price_feed @reboot + 매일 09:00 로그 정리 추가 | 8개 프로세스 (price_feed 1 + 전략 7) 정상 기동. ZMQ 검증: 4초에 79 메시지 (BTCUSDT.trade 47, ETHUSDT 17, SOL 11, XRP 4). ETH 실포지션 SHORT @ $2310 보존. XRP/SOL 가상 포지션 없이 clean start |
| 10 | 2026-04-24 02:01:50 / 11:01:50 (ETH 만) | **ETH state 리셋 재기동** | 사용자가 state 의 가상 LONG 이 혼란스럽다 하여 ETH 만 정지 후 logs/trades/state 초기화하고 재시작. 시뮬레이션이 동일한 가상 LONG @ $2328.22 (SL $2316.36 / TP $2346.01) 를 다시 takeover — backtest semantic 상 이 시점 포지션 보유 중이 맞음을 재확인. 부수적으로 `_simulate_history_queue` 의 `[시뮬레이션 완료]` 로그 메시지 개선 (`이어받음 (신규 takeover)` / `기존 state 유지 (is_virtual=True, ...)` / `실포지션 (state 복구)` / `pending 복구` / `없음` 구분 표시). XRP/SOL/Hyper 4 개는 건드리지 않음 | ETH clean takeover 성공, 실거래 대기. 새 로그 포맷 정상 |
| 9 | 2026-04-24 01:48:00 / 10:48:00 (전 전략) | **재시작 (WebSocket 끊김/재연결 Telegram 알림 + crontab 정리 + 로직 최종 검증)** | (1) 8개 파일 (FVG 4 + Hyper 4: trade_hyper, trade_hyper_usdt, trade_hyper_v2, trade_eth_hyper) 에 `_send_telegram_alert` 헬퍼 + `ws_alerted_down` 플래그 추가. 연결 끊김 (TimeoutError / ConnectionClosed / Exception) 시 🔴 1회, 재연결 성공 시 🟢 1회 알림. 중복 방지 플래그로 스팸 방지. (2) crontab 에서 `start_fvg_btc.sh` @reboot 엔트리 제거 (BTC 운영 안 함). (3) **Live vs backtest 최종 검증 완료**: FVG 감지/Invalidation/Timeout/HTF/Entry candidate 선택(get_newest)/SL·TP·LIQ 공식/레버리지/사이징/수수료/Exit 우선순위(LIQ>SL>TP)/Exit bar `continue` 스킵/Queue clear 시점/진입봉 SL/TP 순서 판별 **전부 1:1 일치**. 수정 후 남은 gap 은 전부 실거래 구조상 불가피: ① 슬리피지(user OK) ② `l[i] == top` 동률 touch 시 거래소 order book queue priority 에 따라 live LIMIT 이 체결 안 될 수 있음 (고유동성 심볼엔 거의 영향 없음, XRP/SOL thin bar 에서 드물게 발생) ③ API 지연 ~100ms (봉 마감 → pending 배치) ④ 포지션 사이즈 거래소 qty step rounding ⑤ 진입가 clamp (backtest `_common.py` L459-461 에서 `ep>h[i]` or `ep<l[i]` 시 OHLC 로 clamp — FVG top 이 바 범위 밖인 극단 케이스, 실제 발생 거의 없음). 1m entry-bar resolve 는 live 의 tick 기반 exit 보다 **덜 정확** — live 가 오히려 우위 | 7개 전부 정상 기동. Hyper 4: 포지션 없음 clean start. FVG 3: ETH 가상 LONG@2328.22 state 복구 + XRP/SOL 가상 없음. Telegram 테스트 메시지 도착 확인 |

---

## 백테스트 비교 계획

### 조건
- **현재 안정 시작 시각 + 7일 이상 재시작 없음** 시에 수행
- 목적: DRY 때와 동일 방식 (`verify_dry_btc_eth.py` 참고)으로 `bt_04 / bt_10 / bt_15 / bt_18` 백테스트 결과와 trade-by-trade 비교

### 비교 시 사용할 파라미터

각 심볼의 백테스트 script:
- BTC: `backtest/fvg_winners/bt_04_BTC_15m_mdd60.py` (v6_1 HTF)
- ETH: `backtest/fvg_winners/bt_10_ETH_15m_mdd60.py` (v3, no HTF)
- XRP: `backtest/fvg_winners/bt_15_XRP_15m_mdd60.py` (v6_2 HTF)
- SOL: `backtest/fvg_winners/bt_18_SOL_15m_mdd40_v6_1.py` (v6_1 HTF)

백테스트 기간:
- `_common.py`의 `START`를 **최종 안정 시작 시각 - 14일**로 설정 (500개 15m봉 + 200개 1h봉 warmup 커버)
- `END`를 비교 시점까지

### Cutoff 필터 (entry_time 기준, bar open 시각)

비교는 **최종 안정 시작 시각 이후 첫 LIVE 봉 open 시각**부터:
- **ETH** (현재 열린 SHORT @ $2310 진입 시각 `2026-04-24 04:23:12 UTC` 기준): 첫 LIVE 봉 = `2026-04-24 04:15:00` (진입 봉 open)
  - 파일: `trades_bt_28_ETH_15m_mdd50_v3_1m.csv`
  - ※ price_feed 재기동 (06:59 / 07:33 UTC) 때 실포지션 state 복구로 보존 — 진입 시점 기준 비교 유지
- **XRP/SOL** (2026-04-24 07:33 UTC 재기동, logs/trades/state 전부 초기화 clean start): 첫 LIVE 봉 = `2026-04-24 07:45:00` (봉 open)
  - XRP: `trades_bt_27_XRP_15m_mdd50_v6_1_1m.csv`
  - SOL: `trades_bt_25_SOL_15m_mdd50_v6_1_1m.csv`
- BTC 는 정지 상태라 제외. 자본 $200 기준이라 포지션 사이즈는 백테스트의 `cap * lev / ep` 공식에 $200 대입해 재계산. 수익률 % 는 동일해야 매치.
- 비교 전 `historical_data/{SYMBOL}_1m_futures.csv` / `{SYMBOL}_15m_futures.csv` 가 cutoff 시점까지 커버하는지 확인, 부족하면 Binance `futures_klines` 로 tail 받아 append 후 backtest 실행.

```python
import pandas as pd
# ETH (bt_28, 현재 열린 SHORT @ $2310 진입 봉부터)
df_eth = pd.read_csv('trades_bt_28_ETH_15m_mdd50_v3_1m.csv')
df_eth['entry_time'] = pd.to_datetime(df_eth['entry_time'])
df_eth_compare = df_eth[df_eth['entry_time'] >= '2026-04-24 04:15:00']
# XRP (bt_27, 07:33 UTC clean 재기동 후)
df_xrp = pd.read_csv('trades_bt_27_XRP_15m_mdd50_v6_1_1m.csv')
df_xrp['entry_time'] = pd.to_datetime(df_xrp['entry_time'])
df_xrp_compare = df_xrp[df_xrp['entry_time'] >= '2026-04-24 07:45:00']
# SOL (bt_25, 07:33 UTC clean 재기동 후)
df_sol = pd.read_csv('trades_bt_25_SOL_15m_mdd50_v6_1_1m.csv')
df_sol['entry_time'] = pd.to_datetime(df_sol['entry_time'])
df_sol_compare = df_sol[df_sol['entry_time'] >= '2026-04-24 07:45:00']
```

DRY 방식과 동일하게 entry_time / direction / entry_price / exit_price / SL / TP 대조.

### 매칭 기준
- ✅ 진입 시각 일치 (15m 봉 단위)
- ✅ 진입 가격 동일 (지정가)
- ✅ 청산 가격·시각 동일
- ⚠️ PnL은 capital 차이로 미세 차이 가능하되 % 수익률은 같아야 함

---

## 재시작 프로토콜 (앞으로 준수)

1. 중지 전 현재 상태 확인:
   - `ps aux | grep trade_fvg_`
   - `cat state/state_fvg_*.json` (pending/position 유무)
2. 4개 심볼 stop:
   - `cd /home/double_st_strategy/fvg_strategy && ./scripts/stop_fvg_{btc,eth,xrp,sol}.sh`
3. 코드 수정 / 배포
4. 4개 심볼 start:
   - `./scripts/start_fvg_{btc,eth,xrp,sol}.sh`
5. 로그 확인:
   - `복구된 대기주문 정상` / `포지션 복구` / 에러 없는지
6. **이 파일(LIVE_RUN_LOG.md)에 기록**:
   - 📌 "현재 안정 운영 시작 시각" 필드 갱신
   - 실행 히스토리 표에 한 줄 추가 (시각 / 유형 / 사유 / 결과)
7. 백테스트 비교용 entry_time cutoff 업데이트 (15m 단위로 올림)

---

## Known 구조적 한계 (버그 아님)

- **히스테리시스 방향 스위칭 (ETH만 해당)**: one-way 모드에서 pending LIMIT 1개 제약. HTF 없는 ETH만 양방향 동시 valid 가능 → tick 기반 스위칭 필요. 백테스트 "봉 단위 LONG 우선"과 미세 차이.
- **다운 중 pending 체결 리스크**: pending 주문은 거래소에 살아있고, 다운 중 체결되면 재시작까지 naked position. monitor.sh 텔레그램 알림 → 즉시 수동 재시작 필요.
- **capital local 누적**: hyper_scalper처럼 wallet auto-sync 없음. 출금/입금 시 `state/state_fvg_*.json` 수동 편집.
