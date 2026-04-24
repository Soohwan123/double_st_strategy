"""
=============================================================
Strategy 3: Order Block / Fair Value Gap (BTC 15m)
=============================================================
FVG 감지:
  - Bullish FVG: candle[i-2].high < candle[i].low (갭 상승)
  - Bearish FVG: candle[i-2].low > candle[i].high (갭 하락)
  - 최소 갭 크기: 가격의 0.1% (FVG_MIN=0.001)
  - FVG 유효기간: 50봉 이내

진입 조건:
  - 가격이 FVG 영역에 되돌아옴 (low가 bullish FVG zone 터치)
  - EMA(50) 위: LONG, EMA(50) 아래: SHORT
  - ADX(14) >= 50 필수
  - 시그널 발생 봉의 close 확인 후 → 다음 봉 open에 진입

청산 조건:
  - TP: ATR(14) * 4 + fee_offset (지정가)
  - SL: 직전 20봉 저점(롱) / 고점(숏) (시장가)
  - 한봉에서 SL/TP 둘다 터치 → SL 처리
  - 청산 우선순위: 청산(LIQ) > SL > TP

레버리지: RISK(7%) / (SL거리% + TAKER*2), max 100x
수수료: 시장가(TAKER) 0.05%, 지정가(MAKER) 0.02%

최적 파라미터 (BTC 15m, 2020-01 ~ 2026-03):
  TP_ATR=4, ADX_THRESH=50, RISK=7%, SL_LOOKBACK=20, FVG_MIN=0.001
  → 7,652% 수익, MDD 52.33%, WR 57.27%, 440 trades
=============================================================
"""
import pandas as pd, numpy as np
import time

# ── 설정 ──
INITIAL_CAPITAL = 10000.0; MAX_LEVERAGE = 100
EMA_TREND = 50; ATR_LENGTH = 14; ADX_LENGTH = 14; MAX_SL_DISTANCE = 0.03
MAKER_FEE = 0.0002; TAKER_FEE = 0.0005
START_DATE = '2020-01-02'; END_DATE = '2026-03-03'
FVG_LOOKBACK = 50

# ── 최적 파라미터 (15m) ──
TP_ATR = 4; ADX_THRESH = 50; RISK = 0.07; SL_LOOKBACK = 20; FVG_MIN = 0.001

DATA_FILE = 'historical_data/BTCUSDT_15m_futures.csv'
SYMBOL = 'BTC'

def calculate_rma_np(s, l):
    a = 1.0/l; r = np.full(len(s), np.nan)
    if len(s)>=l:
        r[l-1]=np.nanmean(s[:l])
        for i in range(l,len(s)): r[i]=a*s[i]+(1-a)*r[i-1]
    return r

def calc_atr(h,l,c,ln):
    pc=np.roll(c,1);pc[0]=np.nan
    tr=np.maximum(h-l,np.maximum(np.abs(h-pc),np.abs(l-pc)))
    return calculate_rma_np(tr,ln)

def calc_adx(h,l,c,ln):
    um=np.diff(h,prepend=h[0]);dm=-np.diff(l,prepend=l[0])
    pdm=np.where((um>dm)&(um>0),um,0.0);mdm=np.where((dm>um)&(dm>0),dm,0.0)
    pc=np.roll(c,1);pc[0]=c[0]
    tr=np.maximum(h-l,np.maximum(np.abs(h-pc),np.abs(l-pc)))
    atr=calculate_rma_np(tr,ln);pdi_r=calculate_rma_np(pdm,ln);mdi_r=calculate_rma_np(mdm,ln)
    pdi=np.where(atr>0,100*pdi_r/atr,0.0);mdi=np.where(atr>0,100*mdi_r/atr,0.0)
    ds=pdi+mdi;dx=np.where(ds>0,100*np.abs(pdi-mdi)/ds,0.0)
    return calculate_rma_np(dx,ln)

if __name__=="__main__":
    st=time.time()
    print(f"=== Strategy 3: Order Block / FVG ({SYMBOL} 15m) ===")
    df=pd.read_csv(DATA_FILE)
    df['timestamp']=pd.to_datetime(df['timestamp'])
    df=df[(df['timestamp']>=START_DATE)&(df['timestamp']<=END_DATE)].sort_values('timestamp').reset_index(drop=True)
    o=df['open'].values.astype(np.float64)
    h=df['high'].values.astype(np.float64);l=df['low'].values.astype(np.float64)
    c=df['close'].values.astype(np.float64)
    ts=df['timestamp'].values
    n=len(c)
    print(f"Data: {n} candles")

    # Indicators
    ema=pd.Series(c).ewm(span=EMA_TREND,adjust=False).mean().values
    atrs=calc_atr(h,l,c,ATR_LENGTH); adx=calc_adx(h,l,c,ADX_LENGTH)
    sl_l=pd.Series(l).rolling(window=SL_LOOKBACK+1,min_periods=1).min().values
    sl_s=pd.Series(h).rolling(window=SL_LOOKBACK+1,min_periods=1).max().values

    # Pre-scan FVGs
    bull_fvg_top=np.full(n,np.nan); bull_fvg_bot=np.full(n,np.nan)
    bear_fvg_top=np.full(n,np.nan); bear_fvg_bot=np.full(n,np.nan)
    bull_fvg_idx=np.full(n,-1,dtype=np.int64)
    bear_fvg_idx=np.full(n,-1,dtype=np.int64)
    for i in range(2,n):
        gap=l[i]-h[i-2]
        if gap>0 and gap/c[i-1]>=FVG_MIN:
            bull_fvg_top[i]=l[i]; bull_fvg_bot[i]=h[i-2]; bull_fvg_idx[i]=i
        gap2=l[i-2]-h[i]
        if gap2>0 and gap2/c[i-1]>=FVG_MIN:
            bear_fvg_top[i]=l[i-2]; bear_fvg_bot[i]=h[i]; bear_fvg_idx[i]=i

    # Backtest
    cap=INITIAL_CAPITAL; bals=[cap]; pos=0; ep=sz=tp=sl_p=lev=0.0; ei=0
    tt=w=lq=0; trades=[]
    start=max(SL_LOOKBACK+1,EMA_TREND+5)
    active_bull=[]; active_bear=[]

    for idx in range(start,n):
        # FVG 등록: 이전 봉에서 형성된 FVG만 등록 (같은 봉 진입 방지)
        if idx>0 and bull_fvg_idx[idx-1]==idx-1:
            active_bull.append((bull_fvg_top[idx-1],bull_fvg_bot[idx-1],idx-1))
        if idx>0 and bear_fvg_idx[idx-1]==idx-1:
            active_bear.append((bear_fvg_top[idx-1],bear_fvg_bot[idx-1],idx-1))
        active_bull=[(t,b,ci) for t,b,ci in active_bull if idx-ci<=FVG_LOOKBACK]
        active_bear=[(t,b,ci) for t,b,ci in active_bear if idx-ci<=FVG_LOOKBACK]

        if pos!=0:
            if idx<=ei: continue
            ch,cl=h[idx],l[idx]; ld=1.0/lev; se=False; xp=0.0; r=''
            if pos==1:
                lp=ep*(1-ld)
                if cl<=lp: se,xp,r=True,lp,'LIQ'
                elif cl<=sl_p: se,xp,r=True,sl_p,'SL'
                elif ch>=tp: se,xp,r=True,tp,'TP'
            else:
                lp=ep*(1+ld)
                if ch>=lp: se,xp,r=True,lp,'LIQ'
                elif ch>=sl_p: se,xp,r=True,sl_p,'SL'
                elif cl<=tp: se,xp,r=True,tp,'TP'
            if se:
                pnl=(xp-ep)*sz if pos==1 else (ep-xp)*sz
                ef=ep*sz*TAKER_FEE; xf=xp*sz*(TAKER_FEE if r in('SL','LIQ') else MAKER_FEE)
                net=pnl-ef-xf; cap+=net
                if net>0: w+=1
                if r=='LIQ': lq+=1
                tt+=1; bals.append(cap)
                trades.append({
                    'signal_time':str(ts[ei-1]),'entry_time':str(ts[ei]),'exit_time':str(ts[idx]),
                    'dir':'LONG' if pos==1 else 'SHORT',
                    'entry':round(ep,4),'exit':round(xp,4),'reason':r,
                    'size':round(sz,6),'leverage':round(lev,2),
                    'sl':round(sl_p,4),'tp':round(tp,4),
                    'pnl':round(net,2),'entry_fee':round(ef,2),'exit_fee':round(xf,2),
                    'balance':round(cap,2),
                    'adx':round(adx[ei-1],2),'atr':round(atrs[ei-1],2),
                    'ema50':round(ema[ei-1],2),
                    'signal_close':round(c[ei-1],4),
                    'hold_bars':idx-ei
                })
                pos=0
        else:
            ca=atrs[idx]
            if np.isnan(ca): continue
            cadx=adx[idx]
            if np.isnan(cadx) or cadx<ADX_THRESH: continue
            if idx+1>=n: continue
            cc=c[idx]; cl_=l[idx]; ch_=h[idx]
            entry_p=o[idx+1]  # 다음 봉 open에 진입
            if np.isnan(ema[idx]): continue

            if cc>ema[idx]:
                for fi,(ft,fb,fci) in enumerate(active_bull):
                    if cl_<=ft and cl_>=fb:
                        s=sl_l[idx]
                        if np.isnan(s): continue
                        if s>=entry_p: s=entry_p*(1-0.001)
                        sd=abs(entry_p-s)/entry_p
                        if sd>MAX_SL_DISTANCE: s=entry_p*(1-MAX_SL_DISTANCE)
                        sp=abs(entry_p-s)/entry_p; eff=sp+TAKER_FEE*2
                        lv=max(1.0,min(RISK/eff,MAX_LEVERAGE)); lv=round(lv,2)
                        fo=entry_p*(TAKER_FEE*2+MAKER_FEE)
                        pos=1;ep=entry_p;ei=idx+1;sz=cap*lv/entry_p;sl_p=s;lev=lv;tp=entry_p+ca*TP_ATR+fo
                        active_bull.pop(fi)
                        break
            elif cc<ema[idx]:
                for fi,(ft,fb,fci) in enumerate(active_bear):
                    if ch_>=fb and ch_<=ft:
                        s=sl_s[idx]
                        if np.isnan(s): continue
                        if s<=entry_p: s=entry_p*(1+0.001)
                        sd=abs(entry_p-s)/entry_p
                        if sd>MAX_SL_DISTANCE: s=entry_p*(1+MAX_SL_DISTANCE)
                        sp=abs(entry_p-s)/entry_p; eff=sp+TAKER_FEE*2
                        lv=max(1.0,min(RISK/eff,MAX_LEVERAGE)); lv=round(lv,2)
                        fo=entry_p*(TAKER_FEE*2+MAKER_FEE)
                        pos=-1;ep=entry_p;ei=idx+1;sz=cap*lv/entry_p;sl_p=s;lev=lv;tp=entry_p-ca*TP_ATR-fo
                        active_bear.pop(fi)
                        break
    if pos!=0:
        xp=c[-1]; pnl=(xp-ep)*sz if pos==1 else (ep-xp)*sz
        cap+=pnl-ep*sz*TAKER_FEE-xp*sz*MAKER_FEE; tt+=1; bals.append(cap)

    # Stats
    pk=INITIAL_CAPITAL; md=0.0
    for b in bals:
        if b>pk: pk=b
        dd=(pk-b)/pk
        if dd>md: md=dd
    ret=(cap/INITIAL_CAPITAL-1)*100; wr=(w/tt*100) if tt>0 else 0
    print(f"\n{'='*60}")
    print(f"  {SYMBOL} FVG 15m Backtest Results")
    print(f"{'='*60}")
    print(f"  Return:    {ret:.2f}%")
    print(f"  MDD:       {md*100:.2f}%")
    print(f"  Win Rate:  {wr:.2f}%")
    print(f"  Trades:    {tt}")
    print(f"  Liq:       {lq}")
    print(f"  Final:     ${cap:.2f}")
    print(f"  Time:      {time.time()-st:.1f}s")
    print(f"{'='*60}")
    if trades:
        print(f"\nLast 10 trades:")
        for t in trades[-10:]:
            print(f"  {t['dir']} {t['entry']} -> {t['exit']} ({t['reason']}) lev={t['leverage']}x pnl={t['pnl']} bal={t['balance']}")
        # Save all trades to CSV
        tdf=pd.DataFrame(trades)
        csv_name=f'trades_s3_fvg_{SYMBOL.lower()}_15m.csv'
        tdf.to_csv(csv_name,index=False)
        print(f"\nAll {len(trades)} trades saved to {csv_name}")
