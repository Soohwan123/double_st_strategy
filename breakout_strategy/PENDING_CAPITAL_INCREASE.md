# PENDING: 자본 재배치 — Phase 2 (eth_hyper 청산 후 실행)

**Phase 1 (2026-05-03 KST 13:48 완료)**
- hyper_v2 cap $2,361.28 → **$861.28** (-$1,500). v2 stopped.
- breakout_sol cap $186.82 → **$1,500** (clean restart, logs/trades/state 초기화). 가동 중 (PID 1663365).

**Phase 2 (eth_hyper 포지션 청산 후 트리거)**

조건: `eth_hyper.state.position == null` AND eth_hyper 프로세스 stopped.

### 변경 사항

| 대상 | 현재 cap | 변경 | 비고 |
|---|---|---|---|
| eth_hyper | $3,942.93 | → **$2,442.93** | -$1,500 (의도된 운용 자본 축소) |
| hyper_v2 | $861.28 | → **$1,361.28** | +$500 (eth 에서 받음 → v2 net -$1,000) |
| breakout_xrp | $200 | → **$1,000** | +$800 (eth 의 나머지 $1,000 중) |

→ Final state.capital: **eth $2,442 / v2 $1,361 / sol $1,500 / xrp $1,000**.

수학적 확인: eth -$1,500 = v2 +$500 + xrp 운용금 $1,000 (실제로는 wallet 내부 reallocation 만 — 이 부분 user 의도 그대로 처리).

### 실행 절차

```bash
# 0. 4개 strategy 모두 stop 확인 (eth + xrp 자연 청산 + v2/sol 이미 stopped/restarted)
# 단 sol 은 가동 중이라 stop 안 해도 됨 (cap 변경 없으니)

# 1. eth_hyper cap 변경
venv/bin/python -c "
import json
f = '/home/double_st_strategy/eth_hyper_live/state/state_eth_hyper.json'
with open(f) as h: s = json.load(h)
old = s['capital']
s['capital'] = round(old - 1500.0, 2)
with open(f,'w') as h: json.dump(s, h, indent=2)
print(f'eth_hyper: \${old:.2f} → \${s[\"capital\"]:.2f}')
"

# 2. hyper_v2 cap 변경 (+$500)
venv/bin/python -c "
import json
f = '/home/double_st_strategy/hyper_v2_sub_account/state/state_hyper_v2.json'
with open(f) as h: s = json.load(h)
old = s['capital']
s['capital'] = round(old + 500.0, 2)
with open(f,'w') as h: json.dump(s, h, indent=2)
print(f'hyper_v2: \${old:.2f} → \${s[\"capital\"]:.2f}')
"

# 3. breakout_xrp clean restart with cap $1000 (포지션 이미 청산됐다면)
# (option A: 그대로 cap 만 변경)
venv/bin/python -c "
import json
f = '/home/double_st_strategy/breakout_strategy/state/state_breakout_xrp.json'
with open(f) as h: s = json.load(h)
old = s['capital']
s['capital'] = 1000.0
with open(f,'w') as h: json.dump(s, h, indent=2)
print(f'breakout_xrp: \${old:.2f} → \${s[\"capital\"]:.2f}')
"

# 4. eth_hyper, hyper_v2, breakout_xrp 모두 재시작
bash /home/double_st_strategy/eth_hyper_live/scripts/start_eth_hyper.sh
bash /home/double_st_strategy/hyper_v2_sub_account/scripts/start_hyper_v2.sh
bash /home/double_st_strategy/breakout_strategy/scripts/start_breakout_xrp.sh
```

### 주의

- **포지션 진행 중** state.capital 변경 X (size/PnL 계산 꼬임)
- xrp 의 경우 clean restart 원하면 **state 의 candle_manager 블록 제거** 후 재시작 (sol 의 Phase 1 처럼). 그래야 trendline replay 가 새로 발동되어 정확한 state 로 시작.

### Phase 2 검증 체크리스트

- [ ] eth_hyper position == null 확인
- [ ] breakout_xrp position == null 확인 (혹은 진행 중이면 청산 대기)
- [ ] 4개 cap 변경 후 4개 startup 로그에서 `자본금 복구: $XXXX.XX` 정확히 표시
- [ ] eth_hyper 시작 로그: ADX 정상 (nan 아님)
- [ ] xrp 시작 로그: Trendline state 정상 (upper/lower 값 있음)

---

## 🛠 Phase 2 직전 — 코드 fix 1건 적용

### Bug: `breakout_strategy.py` 의 candle_manager 복원 logic

**현재 동작 (line 245-246)**:
```python
if hasattr(self, '_cm_state_to_restore') and self._cm_state_to_restore:
    self.candle_manager.from_dict(self._cm_state_to_restore)
```

state.json 에 `candle_manager` 블록이 **존재하면 무조건 from_dict 로 덮어씀**. clean restart 시 빈 candle_manager (upper_init=False) 가 들어있으면 → load_historical 의 정확한 trendline 시뮬 결과를 빈값으로 reset → entry 영구 차단 (새 pivot 발견까지).

**fix**:
```python
if hasattr(self, '_cm_state_to_restore') and self._cm_state_to_restore and self._cm_state_to_restore.get('upper_init', False):
    self.candle_manager.from_dict(self._cm_state_to_restore)
# else: load_historical 의 _replay_trendline_state 결과 유지 (clean restart 안전)
```

→ state 에 `upper_init=True` 인 의미 있는 trendline 값이 있을 때만 복원. 빈값/없음/false 면 load_historical 결과 유지.

### fix 효과 매트릭스

| 시나리오 | fix 전 | fix 후 |
|---|---|---|
| 정상 운영 중 재시작 (state 정상) | ✓ from_dict 적용 | ✓ from_dict 적용 (동일) |
| state.json 통째로 삭제 후 clean restart | ✓ candle_manager 키 없음 → replay 유지 | ✓ 동일 |
| state.json 새로 작성 + 빈 candle_manager 블록 | ❌ 빈값으로 덮어쓰기 → entry 차단 | ✓ upper_init=False → skip → replay 유지 |

### 적용 시점

- 코드 fix 자체는 **운영 중 strategy 에 영향 없음** (재시작 시점에 새 코드 적용)
- Phase 2 의 4개 strategy 재시작 직전에 fix 적용하면 자동 반영
- xrp clean restart 든 cap-only 변경이든 둘 다 안전하게 동작

### 적용 절차

```bash
# breakout_strategy.py 의 _restore_state 부분 수정 (line 245)
# 기존:
#   if hasattr(self, '_cm_state_to_restore') and self._cm_state_to_restore:
# 새로:
#   if hasattr(self, '_cm_state_to_restore') and self._cm_state_to_restore \
#      and self._cm_state_to_restore.get('upper_init', False):
```

### 다른 strategy 점검 결과 — 안전 ✓

| 전략 | candle_manager 복원 패턴 | 같은 버그? |
|---|---|---|
| breakout | state.json 에 candle_manager 블록 + from_dict 덮어쓰기 | **YES — fix 필요** |
| **fvg** | state 에 candle_manager 블록 없음 (capital/position/bar_idx/last_updated 만) | NO ✓ |
| **ob** | 동일 | NO ✓ |
| hyper / hyper_usdt / hyper_v2 / eth_hyper | state 에 trendline 누적 값 없음 | NO ✓ |

→ fix 대상은 **breakout_strategy.py 단 1개 파일**.
