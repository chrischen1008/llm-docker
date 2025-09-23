import streamlit as st
import pandas as pd
import pymssql
import requests
import re
import os
import json
from dotenv import load_dotenv

load_dotenv()

# === LLM & SQL Server 設定 ===
DEFAULT_API_URL = os.getenv("VLLM_ENDPOINT", "http://vllm-service:8000/v1")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "Qwen2.5-Coder-1.5B-Instruct")
DEFAULT_SQL_SERVER = os.getenv("SQL_SERVER", "LAPTOP-FKSS2TJ6")
DEFAULT_SQL_DATABASE = os.getenv("SQL_DATABASE", "ERP0")
DEFAULT_SQL_USER = os.getenv("SQL_USER", "")
DEFAULT_SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")
DEFAULT_PORT = int(os.getenv("PORT", "1433"))
DEFAULT_TDS_Version = os.getenv("TDS_Version", "7.0")

# === SQL 連線測試 ===
@st.cache_resource(show_spinner=False)
def test_sql_connection():
    try:
        conn = pymssql.connect(
            server=DEFAULT_SQL_SERVER,
            user=DEFAULT_SQL_USER,
            password=DEFAULT_SQL_PASSWORD,
            database=DEFAULT_SQL_DATABASE,
            port=DEFAULT_PORT,
            tds_version=DEFAULT_TDS_Version
        )
        conn.close()
        return True, "SQL Server 連線成功！"
    except Exception as e:
        return False, f"SQL Server 連線失敗：{e}"

status, msg = test_sql_connection()
if status:
    st.success(msg)
else:
    st.error(msg)

# ========================
st.set_page_config(page_title="ERP 智慧查詢工具", layout="wide")
st.title("ERP 智慧查詢工具")

# === 共用函數 ===
def get_connection(server, database, uid, pwd):
    return pymssql.connect(
        server=server,
        user=uid,
        password=pwd,
        database=database,
        port=DEFAULT_PORT,
        tds_version=DEFAULT_TDS_Version
    )

def load_table_list(server, database, uid, pwd):
    with get_connection(server, database, uid, pwd) as cnxn:
        df = pd.read_sql("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE='BASE TABLE' AND TABLE_NAME like '%clothes%'
            ORDER BY TABLE_NAME
        """, cnxn)
    return df

def load_table_schema(server, database, uid, pwd, table_names):
    schema_lines = []
    with get_connection(server, database, uid, pwd) as cnxn:
        for tbl in table_names:
            cols = pd.read_sql(f"""
                SELECT COLUMN_NAME, DATA_TYPE 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME='{tbl}'
                ORDER BY ORDINAL_POSITION
            """, cnxn)
            col_desc = ", ".join(f"{c['COLUMN_NAME']}({c['DATA_TYPE']})" for _, c in cols.iterrows())
            schema_lines.append(f"{tbl}: {col_desc}")
    return "\n".join(schema_lines)

def generate_table_selection(nl_prompt, tables_df, api_url, model_name):
    tables_list = "\n".join(
        f"{row['TABLE_NAME']} ({row.get('中文名稱','')})"
        for _, row in tables_df.iterrows()
    )
    system = """You are a JSON generator. Your task is to select ONLY the tables that are absolutely necessary 
                    to answer the user's request. 

                   RULES:
                    1. Return a JSON array of table names ONLY.
                    2. DO NOT include unrelated tables.
                    3. You MUST select the minimal number of tables required to answer the request.
                    If a single table is enough, return only that table.
                    4. Select up to 3 tables only if absolutely necessary.
                    5. Do NOT include extra tables under any circumstances.
                    """
    user_msg = f"""資料庫所有表如下：
                {tables_list}

                使用者需求：
                {nl_prompt}

                請只選用戶需求絕對需要的表。
                如果一張表就足夠，不要加入其他表。
                最多回傳3張表，但如果1張就夠，就只回1張。
                請回傳 JSON，例如：
                ["clothes"]
                不要解釋，不要加程式碼區塊，僅回傳 JSON。
                """
    body = {
        "model": model_name,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user_msg}],
        "temperature": 0.0,
        "max_tokens": 512
    }
    resp = requests.post(f"{api_url}/chat/completions", json=body, timeout=60)
    content = resp.json()["choices"][0]["message"]["content"]
    # 移除程式碼區塊標記與前後空白
    content_clean = re.sub(r"^```(?:json)?\s*|```$", "", content.strip(), flags=re.MULTILINE)
    try:
        return json.loads(content_clean)
    except json.JSONDecodeError:
        st.error(f"無法解析 LLM 回傳的 JSON：{content_clean}")
        return []

def generate_sql_from_llm(nl_prompt, db_schema, selected_tables, api_url, model_name):
    tables_list = ", ".join(selected_tables)
    system = (
        "You are a SQL Server 2008 expert specializing in ERP systems.\n"
        "You are given the COMPLETE schema of the selected tables, including table names and their columns.\n\n"
        "CRITICAL REQUIREMENTS:\n"
        "1. Return ONLY the SQL statement - no explanations, no comments.\n"
        "2. Use SQL Server 2008 syntax: SELECT TOP N instead of LIMIT.\n"
        "3. Use ALL provided tables in the query with proper JOINs, and use a maximum of 3 tables.\n"
        "4. Follow the Primary Key (PK) and Foreign Key (FK) relationships exactly.\n"
        "5. Use meaningful Chinese column aliases based on business terms provided.\n"
        "6. Return raw SQL only - no markdown formatting, no explanations.\n"
        "7. Use ONLY columns listed in the provided schema. Do not invent new columns.\n"
        "8. If two tables share columns with the same name, use the column from the table in the FROM clause first, unless the user explicitly requests otherwise.\n"
        "9. Use proper table aliases and fully qualify columns (e.g., c.clothes_no, cc.c_color_no).\n"
        "10. All selected tables MUST appear in the JOIN clause with correct ON conditions.\n"
        "11. Generate SELECT statements with correct column-table mapping based on the schema.\n"
        "12. If two tables share the same COLUMN_NAME, they are considered related and must be joined together.\n"
        "13. If multiple tables contain columns with the same name, you MUST give them distinct column aliases "
        "by prefixing with the table alias name (e.g., c.input_date AS clothes_input_date, cc.input_date AS color_input_date) "
        "so that every column in the result set has a unique name.\n"
    )

    selected_tables_str = ""
    if selected_tables:
        selected_tables_str = f"只允許使用以下表格：{tables_list}\n"

    user_msg = f"""
            資料庫結構：
            {db_schema}

            {selected_tables_str}

            規則：
            1. **極度重要**：你必須使用 SQL Server 2008 語法。當需要限制筆數時，**絕對不准使用 LIMIT**，請使用 `TOP N` 語法，例如：`SELECT TOP 10 * FROM ...`。
            2. 只允許使用上面列出的表格，不可使用其他表，最多使用3張表。
            3. 所有選出的表必須使用，並根據 join key 自動加入 JOIN。
            4. 回傳結果使用中文欄位名稱。
            5. 僅生成 SELECT，禁止 INSERT/UPDATE/DELETE/ALTER/DROP。
            6. 不使用 MySQL 語法，如 LIMIT；如需要限制筆數，請使用 SQL Server 2008 語法 (TOP 或 ROW_NUMBER())。
            7. 聚合請使用 SUM(), COUNT(), AVG() 等 SQL Server 2008 標準函數。
            8. **僅回傳 SQL，不要任何文字說明、SQL 語句、假設條件或代碼塊。**

            使用者需求：
            {nl_prompt}
            """

    body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.0,
        "max_tokens": 1024
    }
    resp = requests.post(f"{api_url}/chat/completions", json=body, timeout=60)
    sql = resp.json()["choices"][0]["message"]["content"]
    # 移除任何中文或非 SQL 文字
    sql_clean = re.search(r"SELECT .*", sql, flags=re.DOTALL)
    if sql_clean:
        sql = sql_clean.group(0)
    else:
        st.error("LLM 回傳 SQL 無法解析")
        sql = ""

    return re.sub(r"^```(?:sql)?\n|```$", "", sql.strip())

def contains_dml(sql_text):
    return bool(re.search(r"\b(INSERT|UPDATE|DELETE|ALTER|TRUNCATE|DROP|CREATE|MERGE)\b", sql_text, flags=re.I))

# === Sidebar ===
with st.sidebar:
    # st.header("LLM 設定")
    # api_url = st.text_input("LLM API URL", value=DEFAULT_API_URL)
    # model_name = st.text_input("Model 名稱", value=DEFAULT_MODEL)
    # st.markdown("---")
    # st.header("資料庫連線設定")
    # server = st.text_input("SQL Server 主機", value=DEFAULT_SQL_SERVER)
    # database = st.text_input("Database", value=DEFAULT_SQL_DATABASE)
    # username = st.text_input("使用者", value=DEFAULT_SQL_USER)
    # password = st.text_input("密碼", value=DEFAULT_SQL_PASSWORD, type="password")
    if st.button("載入所有表名"):
        st.session_state['tables'] = load_table_list(DEFAULT_SQL_SERVER, DEFAULT_SQL_DATABASE, DEFAULT_SQL_USER, DEFAULT_SQL_PASSWORD)
        st.download_button(
            "下載表清單 (可加中文名稱再上傳)",
            st.session_state['tables'].to_csv(index=False).encode("utf-8-sig"),
            "table_list.csv", mime="text/csv"
        )
    uploaded = st.file_uploader("上傳含中文名稱的表清單", type="csv")
    if uploaded:
        st.session_state['tables'] = pd.read_csv(uploaded)
        st.success("已載入自訂表清單")

# === Main UI ===
nl_query = st.text_area("請用自然語言描述你想要查詢的內容：", height=140)

if st.button("產生 SQL 並執行"):
    if 'tables' not in st.session_state:
        st.warning("請先載入或上傳表清單。")
    elif not nl_query.strip():
        st.warning("請輸入查詢需求。")
    else:
        with st.spinner("呼叫 LLM 判斷要用哪些表..."):
            selected_tables = generate_table_selection(nl_query, st.session_state['tables'], DEFAULT_API_URL, DEFAULT_MODEL)

        if not selected_tables:
            st.error("LLM 沒有回傳任何表，請檢查需求或表清單。")
        else:
            st.info(f"LLM 選出的表: {selected_tables}")

            # 加入 join 關係描述
            schema_str = load_table_schema(DEFAULT_SQL_SERVER, DEFAULT_SQL_DATABASE, DEFAULT_SQL_USER, DEFAULT_SQL_PASSWORD, selected_tables)
            join_info = """ """
            db_schema = schema_str + "\n" + join_info

            with st.spinner("呼叫 LLM 產生 SQL..."):
                sql_input = generate_sql_from_llm(nl_query, db_schema, selected_tables, DEFAULT_API_URL, DEFAULT_MODEL)
            st.code(sql_input, language="sql")

            if contains_dml(sql_input):
                st.error("偵測到 DML 語句，出於安全只允許 SELECT！")
            else:
                try:
                    with get_connection(DEFAULT_SQL_SERVER, DEFAULT_SQL_DATABASE, DEFAULT_SQL_USER, DEFAULT_SQL_PASSWORD) as cnxn:
                        df = pd.read_sql_query(sql_input, cnxn)
                    st.success(f"查詢完成，共 {len(df)} 筆資料")
                    st.dataframe(df, use_container_width=True)
                    st.download_button(
                        "下載查詢結果 CSV",
                        df.to_csv(index=False).encode("utf-8-sig"),
                        "query_result.csv", mime="text/csv"
                    )
                except Exception as e:
                    st.error(f"執行 SQL 失敗：{e}")
