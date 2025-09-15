import streamlit as st
import json
import pandas as pd
from opencc import OpenCC
import re, os, time
from io import StringIO
from dotenv import load_dotenv

from openai import OpenAI  # ✅ vLLM 用 OpenAI 相容 API

#! 執行命令 : streamlit run rag_chatroom.py
# ==== 環境設定 ====
load_dotenv()
LLM_MODEL = os.getenv("LLM_MODEL")
VLLM_ENDPOINT = os.getenv("VLLM_ENDPOINT", "http://vllm-service:8000/v1")  # vLLM API URL

client = OpenAI(base_url=VLLM_ENDPOINT, api_key="EMPTY")  # vLLM 預設不用 key，可隨便填

# ==== 工具函數 ====
def remove_think_tags(text):
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

cc = OpenCC("s2t")
def enforce_traditional(text):
    return cc.convert(text)

# ==== 讀取 ERP JSON 資料 ====
JSON_FILE = "erp_data.json"
with open(JSON_FILE, "r", encoding="utf-8") as f:
    DATA_JSON = json.load(f)

# ==== Streamlit 狀態 ====
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": "你是一個 ERP 助理，會根據 ERP JSON 資料回答問題。請用繁體中文，不要產生 SQL。回答格式優先考慮 CSV。表格內容全部使用中文"},
        {"role": "system", "content": f"以下是 ERP JSON 資料：\n{json.dumps(DATA_JSON, ensure_ascii=False, indent=2)}"}
    ]

# ==== 問答函數 ====
def ask_llm(question: str):
    st.session_state.messages.append({"role": "user", "content": question})

    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=st.session_state.messages,
        stream=False  # 如果要逐字輸出可設 True
    )

    answer = enforce_traditional(remove_think_tags(resp.choices[0].message.content))
    st.session_state.messages.append({"role": "assistant", "content": answer})
    return answer

# ==== Streamlit 介面 ====
st.set_page_config(page_title="ERP 聊天室", layout="centered")
st.title("💬 ERP 聊天室")

# 顯示歷史訊息
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    elif msg["role"] == "assistant":
        with st.chat_message("assistant"):
            st.markdown(msg["content"])

# 輸入框
if prompt := st.chat_input("請輸入問題，例如：B00022 的色碼？"):
    with st.chat_message("user"):
        st.markdown(prompt)

    answer = ask_llm(prompt)

    # ==== 逐字顯示效果 ====
    with st.chat_message("assistant"):
        placeholder = st.empty()
        typed_text = ""
        for ch in answer:
            typed_text += ch
            placeholder.markdown(typed_text)
            time.sleep(0.02)

    # ==== 直接解析 LLM 回答的 CSV 文字成表格 ====
    if "," in answer:  # 粗略判斷像 CSV
        try:
            df = pd.read_csv(StringIO(answer))
            st.dataframe(df, use_container_width=True)
        except Exception as e:
            st.warning(f"⚠️ 回答不是標準 CSV，無法顯示成表格：{e}")
            
        with open("output.csv", "w", encoding="utf-8-sig") as f:
            f.write(answer)
