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
ERROR_LOG = BASE / "logs" / "error.log"   # 錯誤細節只寫這裡，介面只顯示白話訊息
SEE_LOG = "若持續發生請聯絡管理者（詳細原因已記錄在 logs/error.log）"

QUICK_QUESTIONS = ["目前還剩哪些項目？", "哪些單已經逾期？", "這次有哪些單狀態退回？"]

st.set_page_config(page_title="合庫進度更新", page_icon="📋", layout="wide")

# ---------- 狀態 ----------
ss = st.session_state
ss.setdefault("check", None)       # 階段一結果
ss.setdefault("files", [])         # 階段二產出檔案
ss.setdefault("log", "")
ss.setdefault("notice", None)      # 下一次畫面要顯示一次的提醒


# ---------- 錯誤紀錄 ----------
def log_error(where, detail):
    try:
        ERROR_LOG.parent.mkdir(exist_ok=True)
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {where}\n{str(detail).strip()}\n\n")
    except OSError:
        pass


# ---------- 問答紀錄：history/chat.json ----------
def load_history():
    """回傳 (紀錄, 提醒)；檔案損壞時移到 archive 保留，從空白紀錄開始"""
    if not HISTORY.exists():
        return [], None
    try:
        records = json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            raise ValueError("格式不是紀錄清單")
        return records, None
    except Exception as e:
        log_error("讀取問答紀錄", repr(e))
        try:
            ARCHIVE.mkdir(parents=True, exist_ok=True)
            HISTORY.replace(ARCHIVE / f"chat_損壞_{datetime.now():%Y%m%d_%H%M%S}.json")
        except OSError as e2:
            log_error("備份損壞的問答紀錄", repr(e2))
        return [], "問答紀錄無法讀取，已另存備份並從空白紀錄開始。"


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
        log_error("儲存問答紀錄", repr(e))
        ss.notice = "問答紀錄存檔失敗，本次紀錄只會暫時顯示在畫面上。" + SEE_LOG


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


def download_or_note(p, **kwargs):
    """檔案在才顯示下載按鈕，否則顯示原因"""
    if not p.is_file():
        st.caption(f"{p.name}：檔案已不存在")
        return
    try:
        data = p.read_bytes()
    except OSError as e:
        log_error(f"讀取產出檔案 {p}", repr(e))
        st.caption(f"{p.name}：檔案無法讀取，請確認沒有被其他程式鎖住")
        return
    st.download_button(f"下載 {p.name}", data, file_name=p.name, **kwargs)


if "history" not in ss:
    ss.history, ss.notice = load_history()


# ---------- 共用：呼叫 main.py ----------
def run_main(*flags):
    """回傳 (成功, 結果, 執行紀錄)；錯誤細節寫入 logs/error.log，不放進執行紀錄"""
    try:
        r = subprocess.run([PY, "main.py", *flags], cwd=BASE, env=ENV, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        log_error(f"main.py {' '.join(flags)}", "執行超過 600 秒")
        return False, None, "執行時間過長，已中止。"
    except OSError as e:
        log_error(f"main.py {' '.join(flags)}", repr(e))
        return False, None, ""
    result = None
    for line in r.stdout.splitlines():
        if line.startswith("RESULT: "):
            try:
                result = json.loads(line[len("RESULT: "):])
            except ValueError:
                pass
    log = "\n".join(l for l in r.stdout.splitlines() if not l.startswith("RESULT: ")).strip()
    ok = r.returncode == 0 and isinstance(result, dict)
    if not ok:
        log_error(f"main.py {' '.join(flags)}（結束碼 {r.returncode}）",
                  f"{r.stderr}\n--- stdout ---\n{r.stdout}")
    return ok, result, log


# ---------- 共用：Claude Code 狀態 ----------
@st.cache_data(ttl=60, show_spinner=False)
def claude_status():
    """未安裝／未登入／已登入／無法確認；無法確認時不擋功能，交給提問時處理"""
    if not CLAUDE:
        return "未安裝"
    try:
        r = subprocess.run([CLAUDE, "auth", "status"], cwd=BASE, env=ENV, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=20)
        return "已登入" if json.loads(r.stdout).get("loggedIn") else "未登入"
    except Exception as e:
        log_error("查詢 Claude Code 登入狀態", repr(e))
        return "無法確認"


# ---------- 共用：呼叫 claude -p ----------
def ask_claude(question):
    """回傳 (成功, 回答)；失敗時回答為白話說明"""
    # 每題都是新對話，不接續前面的內容
    cmd = [CLAUDE, "-p", question, "--output-format", "json",
           "--allowedTools", "Read", "Bash(python:*)", "--max-turns", "10"]
    try:
        r = subprocess.run(cmd, cwd=BASE, env=ENV, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
    except subprocess.TimeoutExpired:
        return False, "回答逾時，請把問題問得更具體一點再試一次。"
    except OSError as e:
        log_error("啟動 Claude Code", repr(e))
        return False, "無法啟動 Claude Code。" + SEE_LOG
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = {}
    if out.get("is_error") is False and out.get("result"):
        return True, out["result"]

    log_error(f"Claude Code 回答失敗（結束碼 {r.returncode}）",
              f"問題：{question}\n{r.stdout}\n{r.stderr}")
    detail = f"{out.get('result', '')} {r.stdout} {r.stderr}".lower()
    if any(k in detail for k in ("login", "log in", "api key", "authenticat", "oauth")):
        claude_status.clear()   # 讓側邊欄重新檢查登入狀態
        return False, "Claude Code 尚未登入或登入已過期，問答功能暫時無法使用。"
    if out.get("subtype") == "error_max_turns":
        return False, "問題較複雜，未能在限定步驟內完成，請把問題問得更具體再試一次。"
    return False, "問答暫時無法完成，請稍後再試。" + SEE_LOG


AI_STATUS = claude_status()
ai_ok = AI_STATUS in ("已登入", "無法確認")
AI_OFF_REASON = {"未安裝": "尚未安裝 Claude Code", "未登入": "Claude Code 尚未登入"}.get(AI_STATUS)

# ---------- 側邊欄：檢查項目 ----------
with st.sidebar:
    st.subheader("檢查項目")
    if AI_OFF_REASON:
        st.caption(f"{AI_OFF_REASON}，AI 項目已停用")

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
            st.error("更新失敗，請稍後再試。" + SEE_LOG)

    st.caption(f"Claude Code：{AI_STATUS}")


# ---------- 主畫面 ----------
st.title("合庫進度更新")

if ss.notice:
    st.warning(ss.notice)
    ss.notice = None

if ss.check is None and not ss.files:
    st.info("在左側勾選檢查項目後，按「開始更新」。")

if ss.check:
    m = ss.check.get("metrics", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("本次異動", m.get("異動", "—"))
    c2.metric("未結案", m.get("未結案", "—"))
    c3.metric("逾期", m.get("逾期", "—"))

    for w in ss.check.get("warnings", []):
        st.warning(w)

    diffs = ss.check.get("diffs", [])
    with st.expander(f"異動明細（{len(diffs)} 筆）"):
        st.dataframe(diffs, width="stretch", hide_index=True)

    if st.button("確認寫入", type="primary"):
        flags = ["--stage", "write"]
        if chk_summary: flags.append("--doc-summary")
        if chk_teams:   flags.append("--notify-teams")
        with st.spinner("寫入 Excel、產生差異文件中..."):
            ok, result, log = run_main(*flags)
        ss.log = log
        if ok:
            ss.files = result.get("files", [])
            ss.check = None
            save_record("處理", "確認寫入", log, [rel_path(f) for f in ss.files])
            st.rerun()
        else:
            st.error("寫入失敗，請確認進度 Excel 沒有開著後再試一次。" + SEE_LOG)

if ss.files:
    st.success("更新完成")
    cols = st.columns(len(ss.files))
    for col, f in zip(cols, ss.files):
        with col:
            download_or_note(Path(f), width="stretch")

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
        log_error("封存問答紀錄", repr(e))
        ss.notice = "舊紀錄封存失敗，畫面已清空，但紀錄檔仍保留在 history 資料夾。"
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
            download_or_note(BASE / f, key=f"hist_dl_{i}_{j}")

st.caption("每題都是獨立提問，請把問題問完整，例如：李小華還剩哪些項目？")
placeholder = "輸入問題…" if ai_ok else f"{AI_OFF_REASON}，問答功能無法使用"
question = st.chat_input(placeholder, disabled=not ai_ok) or quick
if question:
    st.chat_message("user").write(question)
    with st.chat_message("assistant"):
        with st.spinner("讀取最新 Excel 中..."):
            ok, answer = ask_claude(question)
        if ok:
            st.write(answer)
        else:
            st.warning(answer)      # 失敗不寫入紀錄，只在這次畫面顯示
    if ok:
        save_record("問答", question, answer)
        st.rerun()
