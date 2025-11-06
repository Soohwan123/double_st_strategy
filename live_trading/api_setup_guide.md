# 🔑 Binance API 설정 가이드

## ⚠️ 현재 상태
API 키는 연결되었지만 권한 오류가 발생했습니다:
- 오류: `Invalid API-key, IP, or permissions for action`
- 현재 IP: 211.181.25.138

## 📝 해결 방법

### 1. Binance에서 API 권한 확인

1. **Binance.com 로그인**
2. **계정 → API 관리** 이동
3. 생성한 API 키 찾기
4. **편집(Edit)** 클릭

### 2. 필수 권한 설정

다음 권한이 모두 체크되어 있는지 확인:

- ✅ **Enable Reading** (읽기 활성화)
- ✅ **Enable Futures** (선물 거래 활성화) ← 가장 중요!
- ✅ **Enable Spot & Margin Trading** (선택사항)

### 3. IP 제한 설정

두 가지 옵션 중 선택:

#### 옵션 A: IP 제한 해제 (간단하지만 보안 약함)
- "Restrict access to trusted IPs only" 체크 해제
- 모든 IP에서 접근 가능

#### 옵션 B: 현재 IP 추가 (보안 강함)
- "Restrict access to trusted IPs only" 체크
- IP 주소 추가: `211.181.25.138`
- 여러 IP 추가 가능 (집, 사무실 등)

### 4. 저장 및 확인

1. **Save** 클릭
2. 2FA 인증 (Google Authenticator/SMS)
3. 이메일 확인 링크 클릭

## 🔍 추가 확인사항

### Futures 계정 활성화 확인
1. Binance 앱/웹 → Futures 메뉴
2. BTCUSDC 선택
3. 잔고 확인 (최소 10 USDC 필요)

### API 키 재생성 (필요시)
권한 수정이 안 되면 새로운 API 키 생성:
1. 기존 키 삭제
2. 새 API 키 생성
3. **처음부터 Futures 권한 활성화**
4. .env 파일 업데이트

## ✅ 권한 설정 완료 후

```bash
# API 연결 재테스트
../venv/bin/python test_api_orders.py
```

성공시 표시될 내용:
- ✅ Account balance 표시
- ✅ Open positions 확인
- ✅ 주문 테스트 가능

## 🚨 보안 주의사항

1. **API 키 노출 금지**: 절대 공유하지 마세요
2. **출금 권한 금지**: Enable Withdrawals는 체크하지 마세요
3. **IP 제한 권장**: 가능하면 IP 화이트리스트 사용
4. **정기 교체**: 3-6개월마다 API 키 교체

---

설정 완료 후 다시 테스트하세요!