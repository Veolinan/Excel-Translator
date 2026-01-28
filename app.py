import streamlit as st
import pandas as pd
from deep_translator import GoogleTranslator
from langdetect import detect as detect_lang
import io
import time
import random

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Universal Multi-Sheet Translator", layout="wide", page_icon="🌍")

if "local_cache" not in st.session_state:
    st.session_state.local_cache = {}

# --- 2. ROBUST FILE HANDLING ---
def read_csv_robust(file):
    encodings = ['utf-8', 'latin1', 'cp1252', 'iso-8859-1']
    for enc in encodings:
        try:
            file.seek(0)
            return pd.read_csv(file, encoding=enc)
        except:
            continue
    file.seek(0)
    return pd.read_csv(file, encoding='utf-8', errors='replace')

# --- 3. TRANSLATION CORE WITH RETRIES & CHUNKING ---
def translate_batch(texts, source_lang, target_lang, ticker_placeholder):
    lang_pair = f"{source_lang}-{target_lang}".lower()
    results = {t: t for t in texts} # Default to original text on failure
    
    # Filter for unique, non-empty, non-cached strings
    to_translate = []
    for t in texts:
        clean_text = str(t).strip() if pd.notnull(t) else ""
        if clean_text and any(c.isalpha() for c in clean_text):
            if (lang_pair, clean_text) in st.session_state.local_cache:
                results[t] = st.session_state.local_cache[(lang_pair, clean_text)]
            else:
                to_translate.append(clean_text)

    if not to_translate:
        return [results[t] for t in texts]

    unique_list = list(set(to_translate))
    chunk_size = 15  # Small chunks to avoid triggering Google's bot detection
    translated_map = {}

    translator = GoogleTranslator(source=source_lang, target=target_lang)

    for i in range(0, len(unique_list), chunk_size):
        chunk = unique_list[i : i + chunk_size]
        ticker_placeholder.info(f"⏳ Progress: {i}/{len(unique_list)} unique strings...")
        
        # Retry Logic (Exponential Backoff)
        max_retries = 3
        success = False
        
        for attempt in range(max_retries):
            try:
                # Add a tiny jitter delay between chunks to look "human"
                time.sleep(random.uniform(0.5, 1.5))
                
                translated_chunk = translator.translate_batch(chunk)
                for orig, trans in zip(chunk, translated_chunk):
                    translated_map[orig] = trans
                    st.session_state.local_cache[(lang_pair, orig)] = trans
                success = True
                break 
            except Exception as e:
                wait_time = (2 ** attempt) + random.random()
                ticker_placeholder.warning(f"⚠️ Connection glitch. Retrying in {wait_time:.1f}s... ({e})")
                time.sleep(wait_time)
        
        if not success:
            ticker_placeholder.error(f"❌ Failed to translate chunk starting with: {str(chunk[0])[:30]}")
            for item in chunk:
                translated_map[item] = item

    return [translated_map.get(str(t).strip(), t) if pd.notnull(t) else t for t in texts]

# --- 4. UI LAYOUT ---
st.title("🌍 Universal Multi-Sheet Translator")
st.markdown("Upload files. This version includes **Auto-Retry** and **Rate-Limit protection**.")

with st.sidebar:
    st.header("Settings")
    if st.button("🗑️ Clear Session Cache"):
        st.session_state.local_cache = {}
        st.success("Cache cleared!")

files = st.file_uploader("Upload files", type=["xlsx", "csv"], accept_multiple_files=True)

if files:
    # Language Detection Logic
    try:
        first_file = files[0]
        if first_file.name.lower().endswith('.csv'):
            sample_df = read_csv_robust(first_file).head(5)
        else:
            sample_df = pd.read_excel(first_file).head(5)
        
        sample_text = ""
        for val in sample_df.values.flatten():
            if isinstance(val, str) and len(val) > 5:
                sample_text = val
                break
        detected = detect_lang(sample_text) if sample_text else 'fr'
    except:
        detected = 'fr'

    c1, c2 = st.columns(2)
    with c1:
        src = st.text_input("Source Language (ISO)", value=detected).lower()
    with c2:
        target = st.selectbox("Target Language", ["en", "fr", "es", "de", "it", "pt", "ja", "zh-CN"], index=0)

    if st.button("🚀 Start Global Translation", type="primary", use_container_width=True):
        processed_files = {}
        
        for file in files:
            ticker = st.empty()
            try:
                if file.name.lower().endswith('.csv'):
                    df = read_csv_robust(file)
                    for col in df.columns:
                        if df[col].dtype == 'object':
                            df[col] = translate_batch(df[col].tolist(), src, target, ticker)
                    processed_files[file.name] = df
                else:
                    excel_reader = pd.ExcelFile(file)
                    all_sheets = {}
                    for sheet_name in excel_reader.sheet_names:
                        ticker.write(f"📖 Reading Sheet: `{sheet_name}`...")
                        df = pd.read_excel(file, sheet_name=sheet_name)
                        for col in df.columns:
                            if df[col].dtype == 'object':
                                df[col] = translate_batch(df[col].tolist(), src, target, ticker)
                        all_sheets[sheet_name] = df
                    processed_files[file.name] = all_sheets
                
                ticker.success(f"✅ Finished: {file.name}")
            except Exception as e:
                st.error(f"Fatal error in {file.name}: {e}")

        st.session_state.results = processed_files

# --- 5. DOWNLOAD ---
if "results" in st.session_state:
    st.divider()
    st.subheader("📥 Download Results")
    cols = st.columns(3)
    
    for i, (fname, content) in enumerate(st.session_state.results.items()):
        with cols[i % 3]:
            buf = io.BytesIO()
            if fname.lower().endswith('.csv'):
                content.to_csv(buf, index=False, encoding='utf-8-sig')
                mime_type = "text/csv"
            else:
                with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                    for s_name, s_df in content.items():
                        s_df.to_excel(writer, sheet_name=s_name, index=False)
                mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            
            st.download_button(
                label=f"💾 {fname}",
                data=buf.getvalue(),
                file_name=f"translated_{fname}",
                mime=mime_type,
                key=f"dl_{i}",
                use_container_width=True
            )