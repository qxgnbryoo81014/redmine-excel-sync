"""
固定流程主程式（目前為假資料版本，供介面骨架開發使用）

用法：
    python main.py --stage check [--check-structure] [--check-diff] [--check-quality]
    python main.py --stage write [--doc-summary] [--notify-teams]
    python main.py --stage all   （命令列 / 排程用：一次跑完，不含 AI）

輸出：
    最後一行印出 JSON（RESULT: {...}），供介面讀取
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"
PENDING = OUTPUT / ".pending.json"

sys.stdout.reconfigure(encoding="utf-8")


# ---------- 假資料（之後由步驟 3～5 取代） ----------
def fake_issues():
    return [
        {"單號": 1234, "主旨": "匯款限額調整", "狀態": "測試中", "負責人": "王小明", "完成率": 80, "預計完成日": "2026-10-20"},
        {"單號": 1235, "主旨": "報表格式修正", "狀態": "已結案", "負責人": "李小華", "完成率": 100, "預計完成日": "2026-10-10"},
        {"單號": 1240, "主旨": "登入逾時處理", "狀態": "開發中", "負責人": "王小明", "完成率": 30, "預計完成日": "2026-10-12"},
        {"單號": 1247, "主旨": "批次重送機制", "狀態": "開發中", "負責人": "王小明", "完成率": 50, "預計完成日": "2026-10-25"},
        {"單號": 1251, "主旨": "對帳檔格式", "狀態": "新建", "負責人": "李小華", "完成率": 0, "預計完成日": "2026-10-15"},
        {"單號": 1102, "主旨": "交易查詢分頁", "狀態": "開發中", "負責人": "陳大文", "完成率": 60, "預計完成日": "2026-10-30"},
    ]


def fake_diffs():
    return [
        {"單號": 1234, "類型": "狀態變更", "舊值": "開發中", "新值": "測試中"},
        {"單號": 1235, "類型": "狀態變更", "舊值": "已解決", "新值": "已結案"},
        {"單號": 1251, "類型": "新增", "舊值": "", "新值": "新建"},
        {"單號": 1102, "類型": "狀態變更", "舊值": "已結案", "新值": "開發中"},
    ]


# ---------- 階段一：擷取、比對、檢查 ----------
def stage_check(args):
    issues = fake_issues()
    diffs = fake_diffs()
    today = date.today().isoformat()

    open_items = [i for i in issues if i["狀態"] != "已結案"]
    overdue = [i for i in open_items if i["預計完成日"] < today]

    warnings = []
    if args.check_structure:
        warnings.append("結構檢查：「狀態」欄下拉選單多了「暫停」，對照表與 CLAUDE.md 尚未包含")
    if args.check_diff:
        warnings.append("異動檢查：#1102 由「已結案」退回「開發中」，請確認")
    if args.check_quality:
        warnings.append("資料品質：#1251 已逾預計完成日，完成率仍為 0")

    result = {
        "stage": "check",
        "issues": issues,
        "diffs": diffs,
        "metrics": {"異動": len(diffs), "未結案": len(open_items), "逾期": len(overdue)},
        "warnings": warnings,
    }
    OUTPUT.mkdir(exist_ok=True)
    PENDING.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("擷取完成：%d 張單，%d 筆異動" % (len(issues), len(diffs)))
    return result


# ---------- 階段二：寫入 Excel、產差異文件 ----------
def stage_write(args):
    if not PENDING.exists():
        raise SystemExit("找不到比對結果，請先執行 --stage check")
    data = json.loads(PENDING.read_text(encoding="utf-8"))
    stamp = date.today().strftime("%Y%m%d")

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "進度"
    raw = wb.create_sheet("原始資料")
    headers = list(data["issues"][0].keys())
    for sheet in (ws, raw):
        sheet.append(headers)
        for i in data["issues"]:
            sheet.append([i[h] for h in headers])
    xlsx = OUTPUT / f"進度_{stamp}.xlsx"
    wb.save(xlsx)

    lines = [f"# 進度差異文件 {stamp}", ""]
    if args.doc_summary:
        lines += ["## 本次重點", "", "（AI 摘要待接上，目前為假資料）", ""]
    lines += ["## 本次異動", "", "| 單號 | 類型 | 舊值 | 新值 |", "|---|---|---|---|"]
    lines += [f"| {d['單號']} | {d['類型']} | {d['舊值']} | {d['新值']} |" for d in data["diffs"]]
    doc = OUTPUT / f"差異文件_{stamp}.md"
    doc.write_text("\n".join(lines), encoding="utf-8")

    if args.notify_teams:
        print("Teams 通知：（待接上 Workflows webhook）")

    PENDING.unlink()
    print("寫入完成：%s、%s" % (xlsx.name, doc.name))
    return {"stage": "write", "files": [str(xlsx), str(doc)]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["check", "write", "all"], default="all")
    p.add_argument("--check-structure", action="store_true")
    p.add_argument("--check-diff", action="store_true")
    p.add_argument("--check-quality", action="store_true")
    p.add_argument("--doc-summary", action="store_true")
    p.add_argument("--notify-teams", action="store_true")
    args = p.parse_args()

    if args.stage == "check":
        result = stage_check(args)
    elif args.stage == "write":
        result = stage_write(args)
    else:
        stage_check(args)
        result = stage_write(args)

    print("RESULT: " + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
