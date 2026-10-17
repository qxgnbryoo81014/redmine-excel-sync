"""
合庫進度更新：Streamlit 介面

啟動：python -m streamlit run app.py （由 start.bat 執行）
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

BASE = Path(__file__).resolve().parent
PY = sys.executable                       # 可攜式 python\python.exe
CLAUDE = shutil.which("claude")           # 未安裝時為 None
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
HISTORY_DIR = BASE / "history"
HISTORY = HISTORY_DIR / "chat.json"       # 問答紀錄，只用於顯示，不會傳給 Claude
ARCHIVE = HISTORY_DIR / "archive"

QUICK_QUESTIONS = ["目前還剩哪些項目？", "哪些單已經逾期？", "這次有哪些單狀態退回？"]

st.set_page_config(page_title="合庫進度更新", page_icon="📋", layout="wide")

# ---------- 狀態 ----------
ss = st.session_state
ss.setdefault("check", None)       # 階段一結果
ss.setdefault("files", [])         # 階段二產出檔案
ss.setdefault("log", "")


# ---------- 問答紀錄：history/chat.json ----------
def load_history():
    """回傳 (紀錄, 錯誤訊息)；檔案損壞時移到 archive 保留，從空白紀錄開始"""
    if not HISTORY.exists():
        return [], None
    try:
        records = json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("格式不是清單")
        return records, None
    except Exception as e:
        try:
            ARCHIVE.mkdir(parents=True, exist_ok=True)
            HISTORY.replace(ARCHIVE / f"chat_損壞_{datetime.now():%Y%m%d_%H%M%S}.json")
        except OSError:
            pass
        return [], f"問答紀錄讀取失敗（{e}），已從空白紀錄開始"


def save_record(mode, question, answer, files=()):
    rec = {"time": f"{datetime.now():%Y-%m-%d %H:%M:%S}", "mode": mode,
           "question": question, "answer": answer, "files": list(files)}
    ss.history.append(rec)
    try:
        HISTORY_DIR.mkdir(exist_ok=True)
        tmp = HISTORY.with_suffix(".tmp")
        tmp.write_text(json.dumps(ss.history, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(HISTORY)
    except OSError as e:
        st.toast(f"問答紀錄存檔失敗：{e}")


def archive_history():
    if HISTORY.exists():
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        HISTORY.replace(ARCHIVE / f"chat_{datetime.now():%Y%m%d_%H%M%S}.json")


def rel_path(f):
    """產出檔案以專案相對路徑記錄，資料夾搬移後仍可找到"""
    p = Path(f)
    try:
        return p.resolve().relative_to(BASE).as_posix()
    except ValueError:
        return str(p)


if "history" not in ss:
    ss.history, history_error = load_history()
    if history_error:
        st.warning(history_error)


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
    # 每題都是新對話，不接續前面的內容
    cmd = [CLAUDE, "-p", question, "--output-format", "json",
           "--allowedTools", "Read", "Bash(python:*)", "--max-turns", "10"]
    try:
        r = subprocess.run(cmd, cwd=BASE, env=ENV, capture_output=True,
                           text=True, encoding="utf-8", timeout=180)
        out = json.loads(r.stdout)
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

    chk_sync = st.checkbox("同步 Redmine 進 Excel", value=True)
    chk_summary = st.checkbox("差異文件摘要", disabled=not (ai_ok and chk_sync))
    chk_teams = st.checkbox("Teams 通知", disabled=not chk_sync)

    st.divider()
    if st.button("開始更新", type="primary", width="stretch", disabled=not chk_sync):
        with st.spinner("從 Redmine 擷取並比對中..."):
            ok, result, log = run_main("--stage", "check")
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
            save_record("處理", "確認寫入", log, [rel_path(f) for f in ss.files])
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
    try:
        archive_history()
    except OSError as e:
        st.warning(f"紀錄封存失敗：{e}")
    ss.history = []
    st.rerun()

for i, rec in enumerate(ss.history):
    st.chat_message("user").write(rec.get("question", ""))
    with st.chat_message("assistant"):
        st.caption(f"{rec.get('time', '')}・{rec.get('mode', '')}")
        if rec.get("mode") == "處理":
            st.code(rec.get("answer", ""))
        else:
            st.write(rec.get("answer", ""))
        for j, f in enumerate(rec.get("files") or []):
            p = BASE / f
            if p.is_file():
                st.download_button(f"下載 {p.name}", p.read_bytes(), file_name=p.name,
                                   key=f"hist_dl_{i}_{j}")
            else:
                st.caption(f"{Path(f).name}：檔案已不存在")

st.caption("每題都是獨立提問，請把問題問完整，例如：李小華還剩哪些項目？")
question = st.chat_input("輸入問題…", disabled=not ai_ok) or quick
if question:
    st.chat_message("user").write(question)
    with st.chat_message("assistant"):
        with st.spinner("讀取最新 Excel 中..."):
            answer = ask_claude(question)
        st.write(answer)
    save_record("問答", question, answer)
    st.rerun()
