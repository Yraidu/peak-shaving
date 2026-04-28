import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- 1. ARAYÜZ VE HAFIZA (SESSION STATE) AYARLARI ---
st.set_page_config(page_title="BESS Puant Tıraşlama Simülatörü", layout="wide")
st.title("Batarya Enerji Depolama Sistemi (BESS) - Optimizasyon Simülatörü")
st.markdown("Güç talebi belirlenen limitin üzerine çıktığında batarya devreye girer, altına indiğinde kendini şarj eder. 'İdeal Kapasiteyi Bul' butonu ile 0 ceza için gereken minimum batarya yatırımını hesaplayabilirsiniz.")

if 'bess_capacity' not in st.session_state:
    st.session_state['bess_capacity'] = 5.0

# --- 2. SİMÜLASYON MOTORU ---
def simulate_bess(original_power, limit_mw, capacity, initial_soc, charge_eff, discharge_eff):
    grid_power = []
    bess_soc_mwh = []
    current_energy = capacity * initial_soc
    penalties = 0
    
    total_charged = 0.0
    total_discharged = 0.0
    total_grid_pull = 0.0
    
    for p in original_power:
        if pd.isna(p): 
            grid_power.append(0)
            bess_soc_mwh.append(current_energy)
            continue
            
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
        
    return {
        'grid_power': grid_power, 'bess_soc_mwh': bess_soc_mwh, 'penalties': penalties,
        'total_charged': total_charged, 'total_discharged': total_discharged, 'total_grid_pull': total_grid_pull
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
        if st.button("✨ İdeal Kapasiteyi Bul (0 Limit Aşımı İçin)"):
            with st.spinner("İdeal kapasite hesaplanıyor..."):
                mean_power = np.nanmean(original_power)
                if mean_power >= limit_mw:
                    st.error(f"Fiziksel İmkansızlık: Tesisin ortalama tüketimi ({mean_power:.2f} MW), hedeften ({limit_mw} MW) yüksek.")
                else:
                    low = 0.0
                    high = 500.0 
                    best_cap = high
                    
                    while (high - low) > 0.1: 
                        mid = (low + high) / 2
                        res = simulate_bess(original_power, limit_mw, mid, initial_soc, charge_eff, discharge_eff)
                        
                        if res['penalties'] == 0:
                            best_cap = mid 
                            high = mid
                        else:
                            low = mid 
                            
                    st.session_state['bess_capacity'] = round(best_cap, 1)
                    st.rerun() 
        
        # --- ANA SİMÜLASYONU ÇALIŞTIR ---
        results = simulate_bess(original_power, limit_mw, st.session_state['bess_capacity'], initial_soc, charge_eff, discharge_eff)
        
        grid_power = results['grid_power']
        bess_soc_mwh = results['bess_soc_mwh']
        df['SEBEKEDEN_CEKILEN_MW'] = grid_power
        df['BESS_SARJ_SEVIYESI_MWH'] = bess_soc_mwh
        
        total_penalties_before = len([p for p in original_power if p > limit_mw])
        total_penalties_after = results['penalties']
        
        st.markdown("---")
        st.subheader("Optimizasyon Sonuçları")
        colA, colB, colC = st.columns(3)
        colA.metric("Opt. Öncesi Limit Aşımı", f"{total_penalties_before} adet")
        colB.metric("Opt. Sonrası Limit Aşımı", f"{total_penalties_after} adet")
        colC.metric("Maksimum Çekilen Güç", f"{max(grid_power):.2f} MW")
        
        # --- GELİŞMİŞ GRAFİKLER (PLOTLY) ---
        
        # 1. Güç Grafiği
        st.subheader("Güç Tüketimi Karşılaştırması (MW)")
        fig_power = go.Figure()
        
        # Orijinal Talep (Kırmızı, hafif şeffaf)
        fig_power.add_trace(go.Scatter(y=original_power, mode='lines', name='Orijinal Talep (MW)', 
                                       line=dict(color='red', width=1.5), opacity=0.5))
        # Şebekeden Çekilen (Mavi, daha kalın)
        fig_power.add_trace(go.Scatter(y=grid_power, mode='lines', name='Şebekeden Çekilen (MW)', 
                                       line=dict(color='blue', width=2)))
        # Limit Çizgisi
        fig_power.add_hline(y=limit_mw, line_dash="dash", line_color="orange", 
                            annotation_text=f"Ceza Sınırı ({limit_mw} MW)", annotation_position="top left")
        
        fig_power.update_layout(xaxis_title="Zaman Periyodu (15 Dk)", yaxis_title="Güç (MW)",
                                hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_power, use_container_width=True)
        
        # 2. Batarya Grafiği
        st.subheader("Batarya Şarj Seviyesi (MWh)")
        fig_soc = go.Figure()
        
        # Batarya Şarj Seviyesi (Yeşil, Alan Grafiği)
        fig_soc.add_trace(go.Scatter(y=bess_soc_mwh, mode='lines', fill='tozeroy', name='Batarya Şarjı (MWh)', 
                                     line=dict(color='mediumseagreen', width=2)))
        # Maksimum Kapasite Çizgisi
        fig_soc.add_hline(y=st.session_state['bess_capacity'], line_dash="dash", line_color="gray", 
                          annotation_text=f"Maksimum Kapasite ({st.session_state['bess_capacity']} MWh)", annotation_position="top left")
                          
        fig_soc.update_layout(xaxis_title="Zaman Periyodu (15 Dk)", yaxis_title="Enerji (MWh)",
                              hovermode="x unified")
        st.plotly_chart(fig_soc, use_container_width=True)
        
        # --- RAPORLAMA BÖLÜMÜ ---
        st.markdown("---")
        st.subheader("Rapor Çıktısı ve Veri İndirme")
        
        report_text = f"""# BESS Puant Tıraşlama Optimizasyon Raporu

## 1. Sistem Parametreleri
- Şebeke Ceza Sınırı: {limit_mw} MW
- BESS Kapasitesi: {st.session_state['bess_capacity']} MWh
- Başlangıç Şarj Durumu: %{initial_soc*100}
- Şarj / Deşarj Verimliliği: %{charge_eff*100} / %{discharge_eff*100}

## 2. Optimizasyon Sonuçları
- Optimizasyon Öncesi Toplam Limit Aşımı: {total_penalties_before} adet
- Optimizasyon Sonrası Kalan Limit Aşımı: {total_penalties_after} adet
- Optimizasyon Öncesi / Sonrası Maksimum Puant: {max(original_power):.2f} MW / {max(grid_power):.2f} MW

## 3. Batarya Enerji Hareketleri
- Şarj için Şebekeden Çekilen Toplam Enerji: {results['total_grid_pull']:.2f} MWh
- Bataryaya Depolanan Net Enerji: {results['total_charged']:.2f} MWh
- Şarj Kaybı: {(results['total_grid_pull'] - results['total_charged']):.2f} MWh
- Talebi Karşılamak İçin Bataryadan Çıkan Enerji: {results['total_discharged']:.2f} MWh
"""
        with st.expander("Oluşturulan Raporu Görüntüle"):
            st.markdown(report_text)
            
        col_dl1, col_dl2 = st.columns(2)
        col_dl1.download_button("📄 Raporu İndir (.txt)", data=report_text, file_name="BESS_Rapor.txt", mime="text/plain")
        col_dl2.download_button("📊 Optimize Veriyi İndir (.csv)", data=df.to_csv(index=False).encode('utf-8'), file_name="BESS_Veri.csv", mime="text/csv")
        
    except Exception as e:
        st.error(f"Veri işlenirken bir hata oluştu: {e}")