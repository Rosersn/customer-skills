#!/usr/bin/env python3
"""
校验题库数据完整性和格式。

用法:
  python scripts/validate_questions.py                    # 校验所有已有题库
  python scripts/validate_questions.py --vtype c1         # 仅校验指定车型
  python scripts/validate_questions.py --vtype a1 --subject 1
"""

import argparse
import glob
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

REQUIRED_FIELDS = {"id", "subject", "category", "type", "question", "options", "answer", "explanation"}
VALID_TYPES = {"single", "judge", "multi"}
VTYPES = ["c1", "a1", "a2", "d"]
VTYPE_NAMES = {"c1": "小车", "a1": "客车", "a2": "货车", "d": "摩托车"}


def validate_file(filepath):
    basename = os.path.basename(filepath)
    if not os.path.exists(filepath):
        print(f"[SKIP] {basename} 不存在")
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    questions = data.get("questions", [])
    errors = []
    warnings = []
    ids_seen = set()

    for i, q in enumerate(questions):
        prefix = f"[#{q.get('id', f'index={i}')}]"

        missing = REQUIRED_FIELDS - set(q.keys())
        if missing:
            errors.append(f"{prefix} 缺少字段: {missing}")

        if q.get("id") in ids_seen:
            errors.append(f"{prefix} ID 重复")
        ids_seen.add(q.get("id"))

        if q.get("type") not in VALID_TYPES:
            errors.append(f"{prefix} 无效题型: {q.get('type')}")

        if q.get("type") == "judge" and q.get("options"):
            warnings.append(f"{prefix} 判断题不应有选项")

        if q.get("type") in ("single", "multi") and not q.get("options"):
            errors.append(f"{prefix} 选择题缺少选项")

        if not q.get("question", "").strip():
            errors.append(f"{prefix} 题目内容为空")

        if not q.get("answer", "").strip():
            errors.append(f"{prefix} 答案为空")

        if not q.get("explanation", "").strip():
            warnings.append(f"{prefix} 缺少解析")

    print(f"\n{basename} 校验结果:")
    print(f"  总题数: {len(questions)}")
    print(f"  声明题数: {data.get('total', '未声明')}")
    print(f"  分类数: {len(data.get('categories', {}))}")

    if errors:
        print(f"\n  错误 ({len(errors)}):")
        for e in errors[:20]:
            print(f"    - {e}")
        if len(errors) > 20:
            print(f"    ... 还有 {len(errors)-20} 个错误")
    else:
        print(f"  错误: 无")

    if warnings:
        print(f"\n  警告 ({len(warnings)}):")
        for w in warnings[:10]:
            print(f"    - {w}")
        if len(warnings) > 10:
            print(f"    ... 还有 {len(warnings)-10} 个警告")

    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(description="校验题库数据")
    parser.add_argument("--vtype", type=str, action="append", help="指定车型")
    parser.add_argument("--subject", type=int, choices=[1, 4], action="append")
    args = parser.parse_args()

    vtypes = args.vtype if args.vtype else VTYPES
    subjects = args.subject if args.subject else [1, 4]

    all_ok = True
    found_any = False

    for vtype in vtypes:
        for subj in subjects:
            filepath = os.path.join(DATA_DIR, f"{vtype}_subject{subj}.json")
            if not os.path.exists(filepath):
                continue
            found_any = True
            result = validate_file(filepath)
            if result is False:
                all_ok = False

    if not found_any:
        print("未找到任何题库文件")
        sys.exit(1)

    if all_ok:
        print("\n校验通过!")
    else:
        print("\n存在错误，请修复后重新校验")
        sys.exit(1)


if __name__ == "__main__":
    main()
