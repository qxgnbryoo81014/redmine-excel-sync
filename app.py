"""
合庫進度更新：Streamlit 介面

啟動：python -m streamlit run app.py （由 start.bat 執行）
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import streamlit as st

BASE = Path(__file__).resolve().parent
PY = sys.executable                       # 可攜式 python\python.exe
CLAUDE = shutil.which("claude")           # 未安裝時為 None
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

QUICK_QUESTIONS = ["目前還剩哪些項目？", "哪些單已經逾期？", "這次有哪些單狀態退回？"]

st.set_page_config(page_title="合庫進度更新", page_icon="📋", layout="wide")

# ---------- 狀態 ----------
ss = st.session_state
ss.setdefault("check", None)       # 階段一結果
ss.setdefault("files", [])         # 階段二產出檔案
ss.setdefault("log", "")
ss.setdefault("messages", [])
ss.setdefault("session_id", None)


# ---------- 共用：呼叫 main.py ----------
def run_main(*flags):
    r = subprocess.run([PY, "main.py", *flags], cwd=BASE, env=ENV,
                       capture_output=True, text=True, encoding="utf-8")
    result = None
    for line in r.stdout.splitlines():
        if line.startswith("RESULT: "):
            result = json.loads(line[len("RESULT: "):])
    log = "\n".join(l for l in r.stdout.splitlines() if not l.startswith("RESULT: "))
    return r.returncode == 0, result, (log + "\n" + r.stderr).strip()


# ---------- 共用：呼叫 claude -p ----------
def ask_claude(question):
    if not CLAUDE:
        return "（尚未安裝 Claude Code，問答功能無法使用）"
    cmd = [CLAUDE, "-p", question, "--output-format", "json",
           "--allowedTools", "Read", "Bash(python:*)", "--max-turns", "10"]
    if ss.session_id:
        cmd += ["--resume", ss.session_id]          # 延續上一題
    try:
        r = subprocess.run(cmd, cwd=BASE, env=ENV, capture_output=True,
                           text=True, encoding="utf-8", timeout=180)
        out = json.loads(r.stdout)
        ss.session_id = out.get("session_id", ss.session_id)
        return out.get("result", "（沒有取得回答）")
    except subprocess.TimeoutExpired:
        return "回答逾時，請把問題問得更具體一點再試一次。"
    except Exception as e:
        return f"問答失敗：{e}"


# ---------- 側邊欄：檢查項目 ----------
with st.sidebar:
    st.subheader("檢查項目")
    ai_ok = CLAUDE is not None
    if not ai_ok:
        st.caption("未偵測到 Claude Code，AI 項目已停用")

    chk_structure = st.checkbox("Excel 結構檢查", value=ai_ok, disabled=not ai_ok)
    chk_diff = st.checkbox("異動合理性檢查", value=ai_ok, disabled=not ai_ok)
    chk_quality = st.checkbox("Redmine 資料品質", disabled=not ai_ok)
    chk_summary = st.checkbox("差異文件摘要", disabled=not ai_ok)
    chk_teams = st.checkbox("Teams 通知")

    st.divider()
    if st.button("開始更新", type="primary", width="stretch"):
        flags = ["--stage", "check"]
        if chk_structure: flags.append("--check-structure")
        if chk_diff:      flags.append("--check-diff")
        if chk_quality:   flags.append("--check-quality")
        with st.spinner("從 Redmine 擷取並比對中..."):
            ok, result, log = run_main(*flags)
        ss.check = result if ok else None
        ss.files = []
        ss.log = log
        if not ok:
            st.error("更新失敗，請看下方執行紀錄")

    st.caption(f"Claude Code：{'已安裝' if ai_ok else '未安裝'}")


# ---------- 主畫面 ----------
st.title("合庫進度更新")

if ss.check is None and not ss.files:
    st.info("在左側勾選檢查項目後，按「開始更新」。")

if ss.check:
    m = ss.check["metrics"]
    c1, c2, c3 = st.columns(3)
    c1.metric("本次異動", m["異動"])
    c2.metric("未結案", m["未結案"])
    c3.metric("逾期", m["逾期"])

    for w in ss.check["warnings"]:
        st.warning(w)

    with st.expander(f"異動明細（{len(ss.check['diffs'])} 筆）"):
        st.dataframe(ss.check["diffs"], width="stretch", hide_index=True)

    if st.button("確認寫入", type="primary"):
        flags = ["--stage", "write"]
        if chk_summary: flags.append("--doc-summary")
        if chk_teams:   flags.append("--notify-teams")
        with st.spinner("寫入 Excel、產生差異文件中..."):
            ok, result, log = run_main(*flags)
        ss.log = log
        if ok:
            ss.files = result["files"]
            ss.check = None
            st.rerun()
        else:
            st.error("寫入失敗，請確認進度 Excel 沒有開著")

if ss.files:
    st.success("更新完成")
    cols = st.columns(len(ss.files))
    for col, f in zip(cols, ss.files):
        p = Path(f)
        col.download_button(f"下載 {p.name}", p.read_bytes(), file_name=p.name,
                            width="stretch")

if ss.log:
    with st.expander("執行紀錄"):
        st.code(ss.log)

# ---------- 問答 ----------
st.divider()
st.subheader("問答")

q_cols = st.columns(len(QUICK_QUESTIONS) + 1)
quick = None
for col, q in zip(q_cols, QUICK_QUESTIONS):
    if col.button(q, width="stretch", disabled=not ai_ok):
        quick = q
if q_cols[-1].button("清除對話", width="stretch"):
    ss.messages, ss.session_id = [], None
    st.rerun()

for msg in ss.messages:
    st.chat_message(msg["role"]).write(msg["content"])

question = st.chat_input("輸入問題…", disabled=not ai_ok) or quick
if question:
    st.chat_message("user").write(question)
    with st.chat_message("assistant"):
        with st.spinner("讀取最新 Excel 中..."):
            answer = ask_claude(question)
        st.write(answer)
    ss.messages += [{"role": "user", "content": question},
                    {"role": "assistant", "content": answer}]
