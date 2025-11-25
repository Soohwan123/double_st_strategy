## 전략

5분봉 기준

길이 20 표준편차 2 인 볼린저밴드
길이 4 표준편가 4 인 볼린저밴드

두개의 upper, lower band 총 4개의 지표를 추적함.
하나의 캔들이 진행중일때 20/2, 4/4 를 동시에 터치하면 4/4 값에 시장가로 진입
동시에 진행방향의 0.3프로 거리에 지정가 익절을 걸어놓음.

해당 캔들이 마무리되고 다음 캔들이 시작되면 ( 거의 99 퍼센트 진입가보다 위일 것)
    진입가에 본절 스탑로스를 걸어놓음


ex))5:40 해당하는 5분봉 진행중 해당 봉이 20/2 볼린저밴드 터치
-> 4/4 터치 (즉시 시장가로 진입)(즉 이경우에는 틱데이터로 확인해야한다. 틱데이터를 받으면서 가격  터치
시 바로 진입 할 수 있도록)
-> 5:45 5분봉 마감 ->본절 스탑로스 걸기 (만에하나라도 가격이  본절라인보다
        롱일경우 아래, 숏일경우 위라면 즉시 해당 가격에 청산-> 이럴경우는 본절로
        탈출 불가능 손절해야함)
-> 진입가격의 0.5% 거리에 익절 청산 지정가로 걸어놓기

레버리지는 항상 10배 고정

## Tip
파이선 사용
/mnt/c/Users/rlatn/casper_bitcoin/ema_strategy_3x/ema_strategy_3x/venv/bin/python

## TODO

기존의 라이브 트레이딩 코드를 그대로 live_trading 디렉토리에 모두 넣어놨음.
라이브 트레이딩이 어떤식으로 실행되고 어떤 파일을 참조하는지 면밀히 분석후 정리하고 
우리의 전략을 어떻게 수정해서 넣을지 정리해라.

새로운 파일을 만들지말고 기존의 파일을 수정하는식으로 해 토큰양은 걱정하지말고.

가장중요한점은 

                order = self.client.futures_create_order(
                    symbol=self.symbol,
                    side=SIDE_BUY,
                    type='STOP_MARKET',
                    stopPrice=stop_price,
                    closePosition=True  # 전체 포지션 청산
                )

                order = self.client.futures_create_order(
                    symbol=self.symbol,
                    side=SIDE_SELL,
                    type='STOP_MARKET',
                    stopPrice=stop_price,
                    closePosition=True  # 전체 포지션 청산
                )

                
            # 실제 바이낸스 주문 실행
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )

같은 바이낸스에 실제 주문 내는 부분의 함수 인자들은 시장가 진입, 스탑마켓 설정 등 같은경우에 완전히 동일하게 설정해라.

