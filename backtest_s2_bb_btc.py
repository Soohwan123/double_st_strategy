"""
=============================================================
Strategy 2: Bollinger Band Squeeze Breakout (BTC 5m)
=============================================================
진입 조건:
  - BB(20, 2) bandwidth가 이전봉 기준 squeeze_thresh(0.03) 미만 → squeeze 감지
  - 현재봉 close > upper band → LONG 진입
  - 현재봉 close < lower band → SHORT 진입
  - ADX(14) >= 50 필수

청산 조건:
  - TP: ATR(14) * 10 + fee_offset (지정가)
  - SL: 직전 30봉 저점(롱) / 고점(숏) (시장가)
  - 한봉에서 SL/TP 둘다 터치 → SL 처리
  - 청산 우선순위: 청산(LIQ) > SL > TP

레버리지: RISK(7%) / (SL거리% + TAKER*2), max 100x
수수료: 시장가(TAKER) 0.05%, 지정가(MAKER) 0.02%

최적 파라미터 (BTC 5m, 2020-01 ~ 2026-03):
  TP_ATR=10, ADX_THRESH=50, RISK=7%, SL_LOOKBACK=30, SQUEEZE=0.03
  → 5,404% 수익, MDD 61.9%, WR 46.8%, 556 trades
=============================================================
"""
import pandas as pd, numpy as np
import time

# ── 설정 ──
INITIAL_CAPITAL = 10000.0; MAX_LEVERAGE = 100
BB_LENGTH = 20; BB_MULT = 2.0
ATR_LENGTH = 14; ADX_LENGTH = 14; MAX_SL_DISTANCE = 0.03
MAKER_FEE = 0.0002; TAKER_FEE = 0.0005
START_DATE = '2020-01-02'; END_DATE = '2026-03-03'

# ── 최적 파라미터 ──
TP_ATR = 10; ADX_THRESH = 50; RISK = 0.07; SL_LOOKBACK = 30; SQUEEZE_THRESH = 0.03

DATA_FILE = 'historical_data/BTCUSDT_5m_futures.csv'
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
    print(f"=== Strategy 2: BB Squeeze Breakout ({SYMBOL} 5m) ===")
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
    sma=pd.Series(c).rolling(BB_LENGTH).mean().values
    std=pd.Series(c).rolling(BB_LENGTH).std().values
    ub=sma+BB_MULT*std; lb_=sma-BB_MULT*std
    bw=np.where(sma>0,(ub-lb_)/sma,np.nan)
    atrs=calc_atr(h,l,c,ATR_LENGTH); adx=calc_adx(h,l,c,ADX_LENGTH)
    sl_l=pd.Series(l).rolling(window=SL_LOOKBACK+1,min_periods=1).min().values
    sl_s=pd.Series(h).rolling(window=SL_LOOKBACK+1,min_periods=1).max().values

    # Backtest
    cap=INITIAL_CAPITAL; bals=[cap]; pos=0; ep=sz=tp=sl_p=lev=0.0; ei=0
    tt=w=lq=0; trades=[]
    start=max(SL_LOOKBACK+1,BB_LENGTH+5)
    for idx in range(start,n):
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
                    'bb_upper':round(ub[ei-1],2),'bb_lower':round(lb_[ei-1],2),
                    'bb_sma':round(sma[ei-1],2),'bandwidth':round(bw[ei-1],6),
                    'prev_bandwidth':round(bw[ei-2],6) if ei>=2 and not np.isnan(bw[ei-2]) else 0,
                    'signal_close':round(c[ei-1],4),
                    'hold_bars':idx-ei
                })
                pos=0
        else:
            ca=atrs[idx]
            if np.isnan(ca): continue
            cadx=adx[idx]
            if np.isnan(cadx) or cadx<ADX_THRESH: continue
            cc=c[idx]
            if np.isnan(bw[idx]) or idx<1 or idx+1>=n: continue
            pbw=bw[idx-1]
            if np.isnan(pbw) or pbw>=SQUEEZE_THRESH: continue
            entry_p=o[idx+1]  # 다음 봉 open에 진입
            if cc>ub[idx]:  # LONG signal
                s=sl_l[idx]
                if np.isnan(s): continue
                if s>=entry_p: s=entry_p*(1-0.001)
                sd=abs(entry_p-s)/entry_p
                if sd>MAX_SL_DISTANCE: s=entry_p*(1-MAX_SL_DISTANCE)
                sp=abs(entry_p-s)/entry_p; eff=sp+TAKER_FEE*2
                lv=max(1.0,min(RISK/eff,MAX_LEVERAGE)); lv=round(lv,2)
                fo=entry_p*(TAKER_FEE*2+MAKER_FEE)
                pos=1;ep=entry_p;ei=idx+1;sz=cap*lv/entry_p;sl_p=s;lev=lv;tp=entry_p+ca*TP_ATR+fo
            elif cc<lb_[idx]:  # SHORT signal
                s=sl_s[idx]
                if np.isnan(s): continue
                if s<=entry_p: s=entry_p*(1+0.001)
                sd=abs(entry_p-s)/entry_p
                if sd>MAX_SL_DISTANCE: s=entry_p*(1+MAX_SL_DISTANCE)
                sp=abs(entry_p-s)/entry_p; eff=sp+TAKER_FEE*2
                lv=max(1.0,min(RISK/eff,MAX_LEVERAGE)); lv=round(lv,2)
                fo=entry_p*(TAKER_FEE*2+MAKER_FEE)
                pos=-1;ep=entry_p;ei=idx+1;sz=cap*lv/entry_p;sl_p=s;lev=lv;tp=entry_p-ca*TP_ATR-fo
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
    print(f"  {SYMBOL} BB Squeeze Backtest Results")
    print(f"{'='*60}")
    print(f"  Return:    {ret:.2f}%")
    print(f"  MDD:       {md*100:.2f}%")
    print(f"  Win Rate:  {wr:.2f}%")
    print(f"  Trades:    {tt}")
    print(f"  Liq:       {lq}")
    print(f"  Final:     ${cap:.2f}")
    print(f"  Time:      {time.time()-st:.1f}s")
    print(f"{'='*60}")
    # Last 10 trades
    if trades:
        print(f"\nLast 10 trades:")
        for t in trades[-10:]:
            print(f"  {t['dir']} {t['entry']} -> {t['exit']} ({t['reason']}) lev={t['leverage']}x pnl={t['pnl']} bal={t['balance']}")
        # Save all trades to CSV
        tdf=pd.DataFrame(trades)
        csv_name=f'trades_s2_bb_{SYMBOL.lower()}.csv'
        tdf.to_csv(csv_name,index=False)
        print(f"\nAll {len(trades)} trades saved to {csv_name}")
