import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- 1. ARAYÜZ VE HAFIZA AYARLARI ---
st.set_page_config(page_title="BESS Puant Tıraşlama Simülatörü", layout="wide")
st.title("Batarya Enerji Depolama Sistemi (BESS) - Optimizasyon Simülatörü")
st.markdown("Güç talebi belirlenen limitin üzerine çıktığında batarya devreye girer, altına indiğinde kendini şarj eder.")

if 'bess_capacity' not in st.session_state:
    st.session_state['bess_capacity'] = 5.0

# --- 2. SİMÜLASYON MOTORU ---
def simulate_bess(original_power, limit_mw, capacity, initial_soc, charge_eff, discharge_eff):
    grid_power = []
    bess_soc_mwh = []
    battery_supplied_mw = []
    penalized_energy_array = []
    
    current_energy = capacity * initial_soc
    penalties = 0
    total_charged = 0.0
    total_discharged = 0.0
    total_grid_pull = 0.0
    total_penalized_energy = 0.0
    
    for p in original_power:
        if pd.isna(p): 
            grid_power.append(0)
            bess_soc_mwh.append(current_energy)
            battery_supplied_mw.append(0)
            penalized_energy_array.append(0)
            continue
            
        supplied_mw = 0.0
        pen_energy = 0.0
            
        if p > limit_mw:
            req_power_from_grid = p - limit_mw
            req_energy_at_load = req_power_from_grid * 0.25 
            energy_needed_from_battery = req_energy_at_load / discharge_eff
            
            if current_energy >= energy_needed_from_battery:
                current_energy -= energy_needed_from_battery
                total_discharged += energy_needed_from_battery
                g_p = limit_mw 
            else:
                provided_energy_at_load = current_energy * discharge_eff 
                remaining_energy_req = req_energy_at_load - provided_energy_at_load
                total_discharged += current_energy
                g_p = limit_mw + (remaining_energy_req / 0.25)
                current_energy = 0.0
                penalties += 1 
                
            supplied_mw = p - g_p
            if g_p > limit_mw:
                pen_energy = (g_p - limit_mw) * 0.25
                total_penalized_energy += pen_energy
        else:
            avail_power = limit_mw - p
            avail_energy_from_grid = avail_power * 0.25 
            space_left_in_battery = capacity - current_energy
            energy_needed_from_grid_to_fill = space_left_in_battery / charge_eff
            
            grid_energy_to_pull = min(avail_energy_from_grid, energy_needed_from_grid_to_fill)
            actual_charge_amount = grid_energy_to_pull * charge_eff
            
            current_energy += actual_charge_amount
            total_grid_pull += grid_energy_to_pull
            total_charged += actual_charge_amount
            g_p = p + (grid_energy_to_pull / 0.25)
            
        grid_power.append(g_p)
        bess_soc_mwh.append(current_energy)
        battery_supplied_mw.append(supplied_mw)
        penalized_energy_array.append(pen_energy)
        
    return {
        'grid_power': grid_power, 'bess_soc_mwh': bess_soc_mwh, 'penalties': penalties,
        'total_charged': total_charged, 'total_discharged': total_discharged, 'total_grid_pull': total_grid_pull,
        'total_penalized_energy': total_penalized_energy, 'battery_supplied_mw': battery_supplied_mw,
        'penalized_energy_array': penalized_energy_array
    }

# --- 3. PARAMETRE GİRİŞLERİ ---
st.subheader("Sistem Parametreleri")
col1, col2, col3 = st.columns(3)
limit_mw = col1.number_input("Şebeke Ceza Sınırı (MW)", value=2.0, step=0.1)
bess_capacity = col2.number_input("BESS Toplam Kapasitesi (MWh)", value=float(st.session_state['bess_capacity']), step=0.5)
st.session_state['bess_capacity'] = bess_capacity 
initial_soc = col3.slider("Başlangıç Şarj Durumu (%)", 0, 100, 0) / 100.0

st.subheader("Verimlilik (Kayıp) Parametreleri")
col4, col5 = st.columns(2)
charge_eff = col4.number_input("Şarj Verimliliği (%)", min_value=50.0, max_value=100.0, value=95.0, step=0.5) / 100.0
discharge_eff = col5.number_input("Deşarj Verimliliği (%)", min_value=50.0, max_value=100.0, value=95.0, step=0.5) / 100.0

st.subheader("Finansal Parametreler")
col6, col7, col8 = st.columns(3)
capex_per_mwh = col6.number_input("BESS Yatırım Bedeli (USD/MWh)", value=250000)
kdv_rate = col7.number_input("Yatırım KDV Oranı (%)", value=20) / 100.0
penalty_rate = col8.number_input("Cezalı Tüketim Bedeli (USD/MWh)", value=1500)

# --- 4. DOSYA YÜKLEME VE İŞLEME ---
st.markdown("---")
uploaded_file = st.file_uploader("15 Dakikalık Tüketim Verisini Yükleyin (.csv, .xlsx)", type=["csv", "xlsx"])

if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        df.columns = df.columns.str.strip().str.upper()
        power_cols = [c for c in df.columns if 'POWER' in c]
        if not power_cols:
            st.error("Veri setinde 'POWER' kelimesini içeren bir sütun bulunamadı.")
            st.stop()
            
        original_power = df[power_cols[0]].values
        
        # --- OTOMATİK OPTİMİZASYON BUTONU ---
        if st.button("✨ İdeal Kapasiteyi Bul (Minimum Limit Aşımı İçin)"):
            with st.spinner("Mümkün olan en az sınır aşımını sağlayacak minimum batarya kapasitesi hesaplanıyor..."):
                # Önce 500 MWh (dev) bir batarya ile sınırların ne kadar aşıldığını gör (Fiziksel Minimum)
                res_max = simulate_bess(original_power, limit_mw, 500.0, initial_soc, charge_eff, discharge_eff)
                min_possible_penalties = res_max['penalties']
                
                low = 0.0
                high = 500.0 
                best_cap = high
                
                while (high - low) > 0.1: 
                    mid = (low + high) / 2
                    res = simulate_bess(original_power, limit_mw, mid, initial_soc, charge_eff, discharge_eff)
                    
                    if res['penalties'] <= min_possible_penalties:
                        best_cap = mid  # İstenilen min cezaya ulaştık, daha düşük kapasiteyle oluyor mu bakalım
                        high = mid
                    else:
                        low = mid  # Ceza arttı, kapasite yetersiz
                        
                st.session_state['bess_capacity'] = round(best_cap, 1)
                if min_possible_penalties > 0:
                    st.warning(f"Sistemdeki yoğun talepler nedeniyle 0 ceza fiziksel olarak imkansızdır. Mümkün olan minimum ceza ({min_possible_penalties} adet) için kapasite optimize edildi.")
                st.rerun() 
        
        # --- ANA SİMÜLASYONU ÇALIŞTIR ---
        results = simulate_bess(original_power, limit_mw, st.session_state['bess_capacity'], initial_soc, charge_eff, discharge_eff)
        
        grid_power = results['grid_power']
        bess_soc_mwh = results['bess_soc_mwh']
        
        df['SEBEKEDEN_CEKILEN_MW'] = grid_power
        df['BESS_SARJ_SEVIYESI_MWH'] = bess_soc_mwh
        df['BATARYADAN_KARSILANAN_GUC_MW'] = results['battery_supplied_mw']
        df['CEZAYA_GIREN_ENERJI_MWH'] = results['penalized_energy_array']
        
        # Analiz Özetleri
        total_penalties_before = len([p for p in original_power if not pd.isna(p) and p > limit_mw])
        base_penalized_energy = sum([max(0, p - limit_mw) * 0.25 for p in original_power if not pd.isna(p)])
        
        total_penalties_after = results['penalties']
        opt_penalized_energy = results['total_penalized_energy']
        
        # Finansal Hesaplamalar
        base_penalty_cost = base_penalized_energy * penalty_rate
        opt_penalty_cost = opt_penalized_energy * penalty_rate
        total_savings_usd = base_penalty_cost - opt_penalty_cost
        
        # Veri setinin kaç yıllık olduğunu bul (yıllık tasarrufu hesaplamak için)
        total_years = (len(original_power) * 0.25) / 8760.0
        annual_savings_usd = total_savings_usd / total_years if total_years > 0 else 0
        
        # Yatırım Bedeli (KDV dahil)
        total_investment_usd = st.session_state['bess_capacity'] * capex_per_mwh * (1 + kdv_rate)
        payback_years = total_investment_usd / annual_savings_usd if annual_savings_usd > 0 else float('inf')
        
        st.markdown("---")
        st.subheader("Optimizasyon ve Finansal Sonuçlar")
        colA, colB, colC, colD = st.columns(4)
        colA.metric("Opt. Öncesi Limit Aşımı", f"{total_penalties_before} adet")
        colB.metric("Opt. Sonrası Limit Aşımı", f"{total_penalties_after} adet")
        colC.metric("Tasarruf Edilen Enerji", f"{(base_penalized_energy - opt_penalized_energy):.2f} MWh")
        colD.metric("Yatırımın Geri Dönüşü (Amortisman)", f"{payback_years:.1f} Yıl")
        
        # --- GELİŞMİŞ GRAFİKLER (PLOTLY) ---
        st.subheader("Güç Tüketimi Karşılaştırması (MW)")
        fig_power = go.Figure()
        
        # 1. Orijinal Talep (Kırmızı Çizgi - Altta)
        fig_power.add_trace(go.Scatter(
            y=original_power, mode='lines', name='Orijinal Talep (MW)', 
            line=dict(color='red', width=1.5), opacity=0.7,
            hovertemplate='Talep: %{y:.2f} MW<extra></extra>'
        ))
        
        # 2. Şarj Alanı (Mavi Dolgu - Şebeke > Talep)
        charge_top_mw = [max(g_p, p) for g_p, p in zip(grid_power, original_power)]
        charge_mw = [max(0, g_p - p) for g_p, p in zip(grid_power, original_power)]
        
        fig_power.add_trace(go.Scatter(
            y=charge_top_mw, mode='lines', name='Şarj İçin Çekilen',
            line=dict(width=0), fill='tonexty', fillcolor='rgba(0, 191, 255, 0.3)',
            customdata=charge_mw,
            hovertemplate='Şarja Giden: %{customdata:.2f} MW<extra></extra>'
        ))
        
        # 3. Şebekeden Çekilen (Mavi Çizgi)
        fig_power.add_trace(go.Scatter(
            y=grid_power, mode='lines', name='Şebekeden Çekilen (MW)', 
            line=dict(color='blue', width=2),
            hovertemplate='Şebeke Çekimi: %{y:.2f} MW<extra></extra>'
        ))
        
        # 4. Deşarj Alanı (Yeşil Dolgu - Talep > Şebeke)
        fig_power.add_trace(go.Scatter(
            y=charge_top_mw, mode='lines', name='Bataryadan Karşılanan',
            line=dict(width=0), fill='tonexty', fillcolor='rgba(0, 255, 0, 0.4)',
            customdata=results['battery_supplied_mw'],
            hovertemplate='Batarya Katkısı: %{customdata:.2f} MW<extra></extra>'
        ))
        
        # Limit Çizgisi
        fig_power.add_hline(y=limit_mw, line_dash="dash", line_color="orange", 
                            annotation_text=f"Ceza Sınırı ({limit_mw} MW)", annotation_position="top left")
        
        fig_power.update_layout(xaxis_title="Zaman Periyodu (15 Dk)", yaxis_title="Güç (MW)",
                                hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_power, use_container_width=True)
        
        # 2. Batarya Grafiği
        st.subheader("Batarya Şarj Seviyesi (MWh)")
        fig_soc = go.Figure()
        fig_soc.add_trace(go.Scatter(y=bess_soc_mwh, mode='lines', fill='tozeroy', name='Batarya Şarjı (MWh)', 
                                     line=dict(color='mediumseagreen', width=2)))
        fig_soc.add_hline(y=st.session_state['bess_capacity'], line_dash="dash", line_color="gray", 
                          annotation_text=f"Maksimum Kapasite ({st.session_state['bess_capacity']} MWh)", annotation_position="top left")
                          
        fig_soc.update_layout(xaxis_title="Zaman Periyodu (15 Dk)", yaxis_title="Enerji (MWh)", hovermode="x unified")
        st.plotly_chart(fig_soc, use_container_width=True)
        
        # --- RAPORLAMA BÖLÜMÜ ---
        st.markdown("---")
        st.subheader("Rapor Çıktısı ve Veri İndirme")
        
        report_text = f"""# BESS Puant Tıraşlama Optimizasyon Raporu

## 1. Sistem ve Finansal Parametreler
- Şebeke Ceza Sınırı: {limit_mw} MW
- BESS Kapasitesi: {st.session_state['bess_capacity']} MWh
- Başlangıç Şarj Durumu: %{initial_soc*100}
- Şarj / Deşarj Verimliliği: %{charge_eff*100} / %{discharge_eff*100}
- BESS Yatırım Bedeli (MWh): ${capex_per_mwh:,.2f}
- KDV Oranı: %{kdv_rate*100}
- Cezalı Tüketim Bedeli (MWh): ${penalty_rate:,.2f}

## 2. Optimizasyon Sonuçları (Teknik)
- Optimizasyon Öncesi Limit Aşımı / Cezalı Enerji: {total_penalties_before} adet / {base_penalized_energy:.2f} MWh
- Optimizasyon Sonrası Kalan Limit Aşımı / Kalan Cezalı Enerji: {total_penalties_after} adet / {opt_penalized_energy:.2f} MWh
- BESS ile Engellenen (Tıraşlanan) Toplam Cezalı Enerji: {(base_penalized_energy - opt_penalized_energy):.2f} MWh

## 3. Batarya Enerji Hareketleri
- Şarj için Şebekeden Çekilen Toplam Enerji: {results['total_grid_pull']:.2f} MWh
- Talebi Karşılamak İçin Bataryadan Çıkan Toplam Enerji: {results['total_discharged']:.2f} MWh
- Sistemdeki Toplam Şarj/Deşarj Kaybı: {(results['total_grid_pull'] - results['total_charged']):.2f} MWh

## 4. Finansal Analiz (Veri Seti Süresine Göre Yıllıklandırılmış)
- Toplam Yatırım Maliyeti (KDV Dahil): ${total_investment_usd:,.2f}
- Veri Seti Süresince Elde Edilen Toplam Tasarruf: ${total_savings_usd:,.2f}
- Yıllık Öngörülen Ortalama Tasarruf: ${annual_savings_usd:,.2f} / Yıl
- Yatırımın Geri Dönüş Süresi (Amortisman): {payback_years:.1f} Yıl
"""
        with st.expander("Oluşturulan Raporu Görüntüle"):
            st.markdown(report_text)
            
        col_dl1, col_dl2 = st.columns(2)
        col_dl1.download_button("📄 Raporu İndir (.txt)", data=report_text, file_name="BESS_Rapor.txt", mime="text/plain")
        col_dl2.download_button("📊 Optimize Veriyi İndir (.csv)", data=df.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig'), file_name="BESS_Veri.csv", mime="text/csv")
        
    except Exception as e:
        st.error(f"Veri işlenirken bir hata oluştu: {e}")
