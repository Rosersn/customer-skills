#!/usr/bin/env python3
"""
从 jisuapi.com 拉取驾考题库数据，存储为本地 JSON。

用法:
  python scripts/import_questions.py --subject 1    # 仅科目一
  python scripts/import_questions.py --subject 4    # 仅科目四
  python scripts/import_questions.py                # 科目一 + 科目四

首次使用前，需将浏览器 Cookie 保存到 scripts/cookies.txt（单行纯文本）。
获取方式:
  1. 打开 https://www.jisuapi.com/debug/driverexam/
  2. F12 → Network → 发一次请求 → 复制 Request Headers 里的 Cookie 值
"""

import argparse
import gzip
import io
import json
import os
import sys
import time
import urllib.request
import urllib.parse

API_URL = "https://www.jisuapi.com/debug/driverexam?act=relay"
ACTUAL_API = "https://api.jisuapi.com/driverexam/query"
PAGE_SIZE = 100
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")

HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh,en-US;q=0.9,en;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.jisuapi.com",
    "Referer": "https://www.jisuapi.com/debug/driverexam/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


def load_cookies():
    if not os.path.exists(COOKIE_FILE):
        print(f"[ERROR] 未找到 cookies 文件: {COOKIE_FILE}")
        print("请将浏览器中的 Cookie 字符串保存到该文件（单行纯文本）")
        sys.exit(1)
    with open(COOKIE_FILE, "r") as f:
        cookie = f.read().strip()
    if not cookie:
        print("[ERROR] cookies.txt 为空")
        sys.exit(1)
    return cookie


def fetch_page(subject, pagenum, cookie, vehicle_type="C1"):
    params = {
        "type": vehicle_type,
        "url": ACTUAL_API,
        "subject": str(subject),
        "pagesize": str(PAGE_SIZE),
        "pagenum": str(pagenum),
        "sort": "normal",
        "chapter": "null",
    }
    data = urllib.parse.urlencode(params).encode("utf-8")
    headers = dict(HEADERS)
    headers["Cookie"] = cookie

    req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            encoding = resp.headers.get("Content-Encoding", "")
            if encoding == "gzip":
                raw = gzip.decompress(raw)
            elif encoding == "deflate":
                import zlib
                raw = zlib.decompress(raw)
    except Exception as e:
        raise RuntimeError(f"网络请求失败: {e}")

    if not raw or len(raw) == 0:
        raise RuntimeError(
            "API 返回空响应，Cookie 可能已过期。\n"
            "请重新获取 Cookie 并更新 scripts/cookies.txt"
        )

    text = raw.decode("utf-8")

    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        if "<html" in text.lower():
            raise RuntimeError("API 返回了 HTML 页面，Cookie 可能已过期")
        raise RuntimeError(f"API 返回非 JSON 内容: {text[:200]}")

    if "body" in body and "header" in body:
        body = json.loads(body["body"])

    if body.get("status") != 0:
        raise RuntimeError(f"API 返回错误: {body.get('msg', 'unknown')}")

    return body["result"]


VEHICLE_TYPE_ID_BASE = {
    "C1": 0, "A1": 100000, "A2": 200000, "D": 300000,
}


def normalize_question(raw, subject, idx, vehicle_type="C1"):
    options = []
    for key in ["option1", "option2", "option3", "option4"]:
        val = raw.get(key)
        if val:
            options.append(val)

    answer = raw.get("answer", "")
    if not options:
        q_type = "judge"
    elif "," in answer:
        q_type = "multi"
    else:
        q_type = "single"

    base = VEHICLE_TYPE_ID_BASE.get(vehicle_type, 0)
    return {
        "id": base + subject * 10000 + idx,
        "subject": subject,
        "category": raw.get("chapter", "未分类"),
        "type": q_type,
        "question": raw.get("question", ""),
        "options": options,
        "answer": answer,
        "explanation": raw.get("explain", ""),
        "image": raw.get("pic") or None,
        "vehicle_type": raw.get("type", vehicle_type),
    }


def fetch_subject(subject, cookie, vehicle_type="C1"):
    label = "一" if subject == 1 else "四"
    print(f"\n{'='*60}")
    print(f"  [{vehicle_type}] 开始拉取科目{label}题库...")
    print(f"{'='*60}")

    first_page = fetch_page(subject, 1, cookie, vehicle_type)
    total = first_page["total"]
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    print(f"  共 {total} 题，分 {total_pages} 页拉取\n")

    all_questions = []
    idx = 1

    for page in range(1, total_pages + 1):
        result = first_page if page == 1 else None

        if result is None:
            time.sleep(1.5)
            for attempt in range(3):
                try:
                    result = fetch_page(subject, page, cookie, vehicle_type)
                    break
                except Exception as e:
                    if attempt < 2:
                        wait = (attempt + 1) * 3
                        print(f"  [重试] 第 {page} 页失败: {e}，{wait}s 后重试...")
                        time.sleep(wait)
                    else:
                        print(f"  [跳过] 第 {page} 页 3 次尝试均失败: {e}")

        if result is None:
            continue

        page_list = result.get("list", [])
        for raw in page_list:
            all_questions.append(normalize_question(raw, subject, idx, vehicle_type))
            idx += 1

        print(f"  [{page}/{total_pages}] +{len(page_list)} 题  (累计 {len(all_questions)})")

    print(f"\n  [{vehicle_type}] 科目{label}完成: 共获取 {len(all_questions)}/{total} 题")
    return all_questions


def save_questions(questions, subject, vehicle_type="C1"):
    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, f"{vehicle_type.lower()}_subject{subject}.json")

    categories = {}
    type_counts = {"single": 0, "judge": 0, "multi": 0}
    for q in questions:
        categories[q["category"]] = categories.get(q["category"], 0) + 1
        type_counts[q["type"]] = type_counts.get(q["type"], 0) + 1

    output = {
        "version": time.strftime("%Y.%m"),
        "last_updated": time.strftime("%Y-%m-%d"),
        "subject": subject,
        "vehicle_type": vehicle_type,
        "total": len(questions),
        "type_counts": type_counts,
        "categories": categories,
        "questions": questions,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_mb = os.path.getsize(filepath) / 1024 / 1024
    print(f"\n  已保存: {filepath} ({size_mb:.1f} MB)")
    print(f"  题型: 单选 {type_counts['single']} / 判断 {type_counts['judge']} / 多选 {type_counts['multi']}")
    print(f"  分类:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {count} 题")


def main():
    parser = argparse.ArgumentParser(description="拉取驾考题库数据")
    parser.add_argument(
        "--subject", type=int, choices=[1, 4], action="append",
        help="指定科目（可多次使用），默认拉取全部",
    )
    parser.add_argument(
        "--type", type=str, action="append", dest="vehicle_types",
        help="车型（如 C1, A1, A2, D），可多次指定，默认 C1",
    )
    args = parser.parse_args()

    subjects = args.subject if args.subject else [1, 4]
    vehicle_types = args.vehicle_types if args.vehicle_types else ["C1"]
    cookie = load_cookies()

    print("驾考题库数据导入工具")
    print(f"目标车型: {', '.join(vehicle_types)}")
    print(f"目标科目: {', '.join('科目一' if s==1 else '科目四' for s in subjects)}")

    for vtype in vehicle_types:
        for subj in subjects:
            questions = fetch_subject(subj, cookie, vtype)
            if questions:
                save_questions(questions, subj, vtype)
            else:
                label = '一' if subj == 1 else '四'
                print(f"\n  [WARNING] [{vtype}] 科目{label}未获取到任何题目")

    print(f"\n{'='*60}")
    print("  全部完成!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
