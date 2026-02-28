#!/usr/bin/env python3
"""
驾考练习出题引擎。供 Agent 调用来获取题目、验证答案。

用法:
  python scripts/quiz.py vtypes
  python scripts/quiz.py random --subject 1 --vtype c1 [--count 5] [--category 交通信号]
  python scripts/quiz.py sequential --subject 1 --vtype c1 [--count 5] [--reset]
  python scripts/quiz.py exam --subject 1 --vtype c1
  python scripts/quiz.py check --id 10001 --answer B
  python scripts/quiz.py categories --subject 1 --vtype c1
  python scripts/quiz.py stats
  python scripts/quiz.py wrong [--subject 1] [--count 10]
  python scripts/quiz.py favorite --id 10001
  python scripts/quiz.py unfavorite --id 10001
  python scripts/quiz.py favorites [--subject 1] [--count 10]
  python scripts/quiz.py top500 --subject 1 --vtype c1 [--count 5]
  python scripts/quiz.py topics --subject 1 --vtype c1
  python scripts/quiz.py topic-practice --subject 1 --vtype c1 --topic 灯光使用 [--count 5]
  python scripts/quiz.py hard --subject 1 --vtype c1 [--count 10]
"""

import argparse
import datetime
import json
import os
import random
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROGRESS_FILE = os.path.join(BASE_DIR, "progress.json")

VTYPE_ALIAS = {
    "a1": "a1", "a3": "a1", "b1": "a1",
    "a2": "a2", "b2": "a2",
    "c1": "c1", "c2": "c1", "c3": "c1",
    "d": "d",  "e": "d",   "f": "d",
}

VTYPE_LABELS = {
    "c1": {"name": "小车 (C1/C2/C3)", "types": ["C1", "C2", "C3"]},
    "a1": {"name": "客车 (A1/A3/B1)", "types": ["A1", "A3", "B1"]},
    "a2": {"name": "货车 (A2/B2)", "types": ["A2", "B2"]},
    "d":  {"name": "摩托车 (D/E/F)", "types": ["D", "E", "F"]},
}


# ---------------------------------------------------------------------------
# 专项标签定义（关键词 → 标签）
# ---------------------------------------------------------------------------

TOPIC_RULES = {
    "交通标志": r"标志|标识|这个标志",
    "交通标线": r"标线|虚线|实线|导向线|路面标记",
    "交通信号灯": r"信号灯|红灯|绿灯|黄灯|闪光警告",
    "灯光使用": r"灯光|远光|近光|雾灯|转向灯|危险报警|示廓灯",
    "罚款金额": r"罚款|处\d+元|元以[上下]罚款",
    "记分规则": r"扣\d+分|记\d+分|一次记|记分",
    "让行规则": r"让行|让路|先行|优先通行|礼让",
    "车速规定": r"最高速度|最低速度|时速|限速|超速|车速",
    "安全车距": r"车距|跟车距离|保持距离|安全距离",
    "超车规定": r"超车|超越|借道超",
    "停车规定": r"停车|停放|泊车|禁停|临时停车",
    "掉头转弯": r"掉头|调头|转弯|左转|右转",
    "高速公路": r"高速公路|高速路|匝道|加速车道|减速车道|应急车道",
    "安全带使用": r"安全带|系.*带",
    "酒驾醉驾": r"饮酒|醉酒|酒后|醉驾|酒驾",
    "肇事逃逸": r"逃逸|肇事逃",
    "事故处理": r"事故|碰撞|追尾|刮擦|事故现场",
    "恶劣天气": r"雨天|雪天|雾天|冰雪|暴风|大风|泥泞|涉水|湿滑",
    "紧急避险": r"爆胎|制动失灵|转向失控|起火|自燃|紧急制动|紧急避险",
    "伤员急救": r"急救|伤员|止血|骨折|人工呼吸|心肺复苏",
    "危化品运输": r"危险品|危化品|爆炸品|易燃|有毒|腐蚀",
}

_compiled_topics = {name: re.compile(pattern) for name, pattern in TOPIC_RULES.items()}


def get_question_topics(q):
    """返回一道题匹配的所有专项标签"""
    text = q["question"] + " ".join(q.get("options", [])) + q.get("explanation", "")
    return [name for name, pat in _compiled_topics.items() if pat.search(text)]


# ---------------------------------------------------------------------------
# 口诀数据
# ---------------------------------------------------------------------------

MNEMONICS_FILE = os.path.join(DATA_DIR, "mnemonics.json")
_mnemonics_cache = None


def load_mnemonics():
    global _mnemonics_cache
    if _mnemonics_cache is not None:
        return _mnemonics_cache
    if os.path.exists(MNEMONICS_FILE):
        with open(MNEMONICS_FILE, "r", encoding="utf-8") as f:
            _mnemonics_cache = json.load(f)
    else:
        _mnemonics_cache = {}
    return _mnemonics_cache


def get_mnemonics_for_question(q):
    """根据题目的专项标签，返回相关的记忆口诀"""
    topics = get_question_topics(q)
    mnemonics = load_mnemonics()
    result = []
    seen = set()
    for topic in topics:
        for m in mnemonics.get(topic, []):
            key = m["title"]
            if key not in seen:
                seen.add(key)
                result.append(m)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_vtype(raw):
    key = raw.strip().lower()
    if key not in VTYPE_ALIAS:
        print(json.dumps({"error": f"不支持的车型: {raw}，可选: {', '.join(sorted(VTYPE_ALIAS.keys()))}"}, ensure_ascii=False))
        sys.exit(1)
    return VTYPE_ALIAS[key]


def load_questions(subject, vtype="c1"):
    filepath = os.path.join(DATA_DIR, f"{vtype}_subject{subject}.json")
    if not os.path.exists(filepath):
        print(json.dumps({
            "error": f"题库文件不存在: {vtype}_subject{subject}.json",
            "hint": "请先运行 import_questions.py 导入对应车型题库",
        }, ensure_ascii=False))
        sys.exit(1)
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["questions"]


def find_question_by_id(qid):
    for vtype in VTYPE_LABELS:
        for subj in [1, 4]:
            filepath = os.path.join(DATA_DIR, f"{vtype}_subject{subj}.json")
            if not os.path.exists(filepath):
                continue
            questions = load_questions(subj, vtype)
            for q in questions:
                if q["id"] == qid:
                    return q
    return None


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return _default_progress()


def _default_progress():
    return {
        "total_answered": 0,
        "total_correct": 0,
        "categories": {},
        "wrong_questions": [],
        "favorites": [],
        "sequential_pos": {},
        "question_stats": {},
        "mock_exams": [],
    }


def save_progress(progress):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def ensure_fields(progress):
    """兼容旧版 progress.json，补齐新字段"""
    for key, default in [("favorites", []), ("sequential_pos", {}), ("question_stats", {})]:
        if key not in progress:
            progress[key] = default
    return progress


def format_question(q, include_topics=False):
    out = {
        "id": q["id"],
        "subject": q["subject"],
        "category": q["category"],
        "type": q["type"],
        "question": q["question"],
        "options": q["options"],
        "image": q.get("image"),
    }
    if include_topics:
        out["topics"] = get_question_topics(q)
    return out


def output_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_vtypes(_args):
    result = []
    for vtype, info in VTYPE_LABELS.items():
        entry = {"vtype": vtype, "name": info["name"], "covers": info["types"]}
        for subj in [1, 4]:
            filepath = os.path.join(DATA_DIR, f"{vtype}_subject{subj}.json")
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry[f"subject{subj}"] = data["total"]
            else:
                entry[f"subject{subj}"] = 0
        result.append(entry)
    output_json({"vehicle_types": result})


def cmd_random(args):
    vtype = resolve_vtype(args.vtype)
    questions = load_questions(args.subject, vtype)

    if args.category:
        questions = [q for q in questions if q["category"] == args.category]
        if not questions:
            output_json({"error": f"未找到分类: {args.category}"})
            return

    if args.exclude_done:
        progress = ensure_fields(load_progress())
        done_ids = set()
        for cat_data in progress.get("categories", {}).values():
            done_ids.update(cat_data.get("answered_ids", []))
        questions = [q for q in questions if q["id"] not in done_ids]

    count = min(args.count, len(questions))
    selected = random.sample(questions, count)
    output_json({
        "mode": "random",
        "vehicle_type": vtype,
        "subject": args.subject,
        "category": args.category,
        "total_available": len(questions),
        "count": count,
        "questions": [format_question(q) for q in selected],
    })


def cmd_sequential(args):
    """顺序练习：按题号顺序出题，支持断点续练"""
    vtype = resolve_vtype(args.vtype)
    questions = load_questions(args.subject, vtype)
    progress = ensure_fields(load_progress())

    pos_key = f"{vtype}_subject{args.subject}"

    if args.reset:
        progress["sequential_pos"][pos_key] = 0
        save_progress(progress)
        output_json({"message": f"已重置 {pos_key} 的顺序练习进度", "position": 0, "total": len(questions)})
        return

    current_pos = progress["sequential_pos"].get(pos_key, 0)
    total = len(questions)

    if current_pos >= total:
        output_json({
            "message": "已完成全部题目!",
            "position": current_pos,
            "total": total,
            "hint": "使用 --reset 可从头开始",
        })
        return

    end_pos = min(current_pos + args.count, total)
    selected = questions[current_pos:end_pos]

    progress["sequential_pos"][pos_key] = end_pos
    save_progress(progress)

    output_json({
        "mode": "sequential",
        "vehicle_type": vtype,
        "subject": args.subject,
        "position": current_pos + 1,
        "end_position": end_pos,
        "total": total,
        "remaining": total - end_pos,
        "progress_pct": f"{end_pos / total * 100:.1f}%",
        "count": len(selected),
        "questions": [format_question(q) for q in selected],
    })


def cmd_exam(args):
    vtype = resolve_vtype(args.vtype)
    questions = load_questions(args.subject, vtype)
    exam_count = 100 if args.subject == 1 else 50

    if len(questions) < exam_count:
        exam_count = len(questions)

    selected = random.sample(questions, exam_count)
    output_json({
        "mode": "exam",
        "vehicle_type": vtype,
        "subject": args.subject,
        "total_questions": exam_count,
        "pass_score": 90,
        "time_limit_minutes": 45 if args.subject == 1 else 30,
        "questions": [format_question(q) for q in selected],
    })


def cmd_check(args):
    q = find_question_by_id(args.id)
    if not q:
        output_json({"error": f"未找到题目 ID: {args.id}"})
        return

    user_answer = args.answer.strip().upper()
    correct_answer = q["answer"].strip().upper()

    if q["type"] == "judge":
        normalize_map = {"正确": "对", "错误": "错", "TRUE": "对", "FALSE": "错", "RIGHT": "对", "WRONG": "错"}
        user_normalized = user_answer
        for k, v in normalize_map.items():
            user_normalized = user_normalized.replace(k, v)
        is_correct = user_normalized == correct_answer
    else:
        is_correct = user_answer == correct_answer

    progress = ensure_fields(load_progress())
    progress["total_answered"] += 1
    cat = q["category"]
    if cat not in progress["categories"]:
        progress["categories"][cat] = {"answered": 0, "correct": 0, "answered_ids": []}
    progress["categories"][cat]["answered"] += 1
    progress["categories"][cat]["answered_ids"].append(q["id"])

    if is_correct:
        progress["total_correct"] += 1
        progress["categories"][cat]["correct"] += 1
        if q["id"] in progress["wrong_questions"]:
            progress["wrong_questions"].remove(q["id"])
    else:
        if q["id"] not in progress["wrong_questions"]:
            progress["wrong_questions"].append(q["id"])

    qid_str = str(q["id"])
    if qid_str not in progress["question_stats"]:
        progress["question_stats"][qid_str] = {"attempts": 0, "correct": 0}
    progress["question_stats"][qid_str]["attempts"] += 1
    if is_correct:
        progress["question_stats"][qid_str]["correct"] += 1

    save_progress(progress)

    qs = progress["question_stats"][qid_str]
    error_rate = f"{(1 - qs['correct']/qs['attempts'])*100:.0f}%" if qs["attempts"] > 0 else "N/A"

    result = {
        "question_id": q["id"],
        "correct": is_correct,
        "user_answer": args.answer,
        "correct_answer": q["answer"],
        "explanation": q["explanation"],
        "category": q["category"],
        "topics": get_question_topics(q),
        "error_rate": error_rate,
        "attempts": qs["attempts"],
    }

    mnemonics = get_mnemonics_for_question(q)
    if mnemonics:
        result["mnemonics"] = mnemonics

    output_json(result)


def cmd_categories(args):
    vtype = resolve_vtype(args.vtype)
    questions = load_questions(args.subject, vtype)
    categories = {}
    for q in questions:
        cat = q["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "types": {"single": 0, "judge": 0, "multi": 0}}
        categories[cat]["total"] += 1
        categories[cat]["types"][q["type"]] += 1

    progress = ensure_fields(load_progress())

    result = []
    for cat, info in sorted(categories.items(), key=lambda x: -x[1]["total"]):
        p = progress.get("categories", {}).get(cat, {})
        result.append({
            "name": cat,
            "total": info["total"],
            "types": info["types"],
            "answered": p.get("answered", 0),
            "correct": p.get("correct", 0),
            "accuracy": f"{p.get('correct',0)/p['answered']*100:.0f}%" if p.get("answered", 0) > 0 else "未练习",
        })

    output_json({"vehicle_type": vtype, "subject": args.subject, "categories": result})


def cmd_stats(_args):
    progress = ensure_fields(load_progress())

    accuracy = 0
    if progress["total_answered"] > 0:
        accuracy = progress["total_correct"] / progress["total_answered"] * 100

    weak_categories = []
    for cat, data in progress.get("categories", {}).items():
        if data["answered"] >= 5:
            cat_acc = data["correct"] / data["answered"] * 100
            if cat_acc < 80:
                weak_categories.append({"name": cat, "accuracy": f"{cat_acc:.0f}%", "answered": data["answered"]})
    weak_categories.sort(key=lambda x: float(x["accuracy"].rstrip("%")))

    seq_progress = {}
    for key, pos in progress.get("sequential_pos", {}).items():
        parts = key.split("_subject")
        if len(parts) == 2:
            vtype, subj_str = parts
            filepath = os.path.join(DATA_DIR, f"{key}.json")
            total = 0
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    total = json.load(f).get("total", 0)
            seq_progress[key] = {
                "position": pos,
                "total": total,
                "progress": f"{pos/total*100:.1f}%" if total > 0 else "0%",
            }

    output_json({
        "total_answered": progress["total_answered"],
        "total_correct": progress["total_correct"],
        "accuracy": f"{accuracy:.1f}%",
        "wrong_count": len(progress["wrong_questions"]),
        "favorites_count": len(progress.get("favorites", [])),
        "weak_categories": weak_categories[:5],
        "sequential_progress": seq_progress,
        "mock_exams": progress.get("mock_exams", [])[-5:],
    })


def cmd_wrong(args):
    progress = ensure_fields(load_progress())
    wrong_ids = set(progress.get("wrong_questions", []))

    if not wrong_ids:
        output_json({"message": "没有错题记录，继续保持!", "count": 0})
        return

    wrong_questions = []
    for vtype in VTYPE_LABELS:
        subjects = [args.subject] if args.subject else [1, 4]
        for subj in subjects:
            filepath = os.path.join(DATA_DIR, f"{vtype}_subject{subj}.json")
            if not os.path.exists(filepath):
                continue
            for q in load_questions(subj, vtype):
                if q["id"] in wrong_ids:
                    wrong_questions.append(q)

    if args.count and len(wrong_questions) > args.count:
        wrong_questions = random.sample(wrong_questions, args.count)

    output_json({
        "mode": "wrong_review",
        "total_wrong": len(wrong_ids),
        "showing": len(wrong_questions),
        "questions": [format_question(q) for q in wrong_questions],
    })


def cmd_favorite(args):
    progress = ensure_fields(load_progress())
    qid = args.id

    q = find_question_by_id(qid)
    if not q:
        output_json({"error": f"未找到题目 ID: {qid}"})
        return

    if qid not in progress["favorites"]:
        progress["favorites"].append(qid)
        save_progress(progress)
        output_json({"action": "favorited", "question_id": qid, "total_favorites": len(progress["favorites"])})
    else:
        output_json({"action": "already_favorited", "question_id": qid, "total_favorites": len(progress["favorites"])})


def cmd_unfavorite(args):
    progress = ensure_fields(load_progress())
    qid = args.id

    if qid in progress["favorites"]:
        progress["favorites"].remove(qid)
        save_progress(progress)
        output_json({"action": "unfavorited", "question_id": qid, "total_favorites": len(progress["favorites"])})
    else:
        output_json({"action": "not_in_favorites", "question_id": qid})


def cmd_favorites(args):
    progress = ensure_fields(load_progress())
    fav_ids = set(progress.get("favorites", []))

    if not fav_ids:
        output_json({"message": "没有收藏的题目", "count": 0})
        return

    fav_questions = []
    for vtype in VTYPE_LABELS:
        subjects = [args.subject] if args.subject else [1, 4]
        for subj in subjects:
            filepath = os.path.join(DATA_DIR, f"{vtype}_subject{subj}.json")
            if not os.path.exists(filepath):
                continue
            for q in load_questions(subj, vtype):
                if q["id"] in fav_ids:
                    fav_questions.append(q)

    if args.count and len(fav_questions) > args.count:
        fav_questions = random.sample(fav_questions, args.count)

    output_json({
        "mode": "favorites",
        "total_favorites": len(fav_ids),
        "showing": len(fav_questions),
        "questions": [format_question(q) for q in fav_questions],
    })


def cmd_top500(args):
    """精选题模式：基于易错率和分类均衡抽取高价值题目"""
    vtype = resolve_vtype(args.vtype)
    questions = load_questions(args.subject, vtype)
    progress = ensure_fields(load_progress())

    wrong_ids = set(progress.get("wrong_questions", []))
    answered_ids = set()
    for cat_data in progress.get("categories", {}).values():
        answered_ids.update(cat_data.get("answered_ids", []))

    wrong_pool = []
    unanswered_pool = []
    correct_pool = []

    for q in questions:
        qid = q["id"]
        if qid in wrong_ids:
            wrong_pool.append(q)
        elif qid not in answered_ids:
            unanswered_pool.append(q)
        else:
            correct_pool.append(q)

    target = 500
    selected = []

    # 优先纳入全部错题
    selected.extend(wrong_pool)

    # 从未做过的题中按分类均衡抽取
    remaining = target - len(selected)
    if remaining > 0 and unanswered_pool:
        by_cat = {}
        for q in unanswered_pool:
            by_cat.setdefault(q["category"], []).append(q)

        per_cat = max(1, remaining // len(by_cat)) if by_cat else 0
        for cat, cat_qs in by_cat.items():
            take = min(per_cat, len(cat_qs))
            selected.extend(random.sample(cat_qs, take))

    # 如果还不够，从已答对但随机的题中补充
    remaining = target - len(selected)
    if remaining > 0 and correct_pool:
        take = min(remaining, len(correct_pool))
        selected.extend(random.sample(correct_pool, take))

    selected = selected[:target]
    random.shuffle(selected)

    count = min(args.count, len(selected))
    batch = selected[:count]

    output_json({
        "mode": "top500",
        "vehicle_type": vtype,
        "subject": args.subject,
        "total_selected": len(selected),
        "composition": {
            "wrong": len(wrong_pool),
            "unanswered": len([q for q in selected if q["id"] not in answered_ids and q["id"] not in wrong_ids]),
            "reviewed": len([q for q in selected if q["id"] in answered_ids and q["id"] not in wrong_ids]),
        },
        "count": count,
        "questions": [format_question(q) for q in batch],
    })


def cmd_topics(args):
    """列出所有专项标签及各标签的题目数"""
    vtype = resolve_vtype(args.vtype)
    questions = load_questions(args.subject, vtype)
    progress = ensure_fields(load_progress())

    topic_counts = {}
    for q in questions:
        for t in get_question_topics(q):
            if t not in topic_counts:
                topic_counts[t] = {"total": 0, "ids": []}
            topic_counts[t]["total"] += 1
            topic_counts[t]["ids"].append(q["id"])

    result = []
    for name, info in sorted(topic_counts.items(), key=lambda x: -x[1]["total"]):
        answered_ids = set()
        for cat_data in progress.get("categories", {}).values():
            answered_ids.update(cat_data.get("answered_ids", []))
        done = len(set(info["ids"]) & answered_ids)
        wrong = len(set(info["ids"]) & set(progress.get("wrong_questions", [])))
        result.append({
            "topic": name,
            "total": info["total"],
            "answered": done,
            "wrong": wrong,
            "progress": f"{done/info['total']*100:.0f}%" if info["total"] > 0 else "0%",
        })

    # 附上是否有口诀
    mnemonics = load_mnemonics()
    for item in result:
        item["has_mnemonic"] = item["topic"] in mnemonics or any(
            k for k in mnemonics if k in item["topic"] or item["topic"] in k
        )

    output_json({"vehicle_type": vtype, "subject": args.subject, "topics": result})


def cmd_topic_practice(args):
    """按专项标签出题"""
    vtype = resolve_vtype(args.vtype)
    questions = load_questions(args.subject, vtype)

    matched = [q for q in questions if args.topic in get_question_topics(q)]
    if not matched:
        output_json({"error": f"未找到专项: {args.topic}，请用 topics 命令查看可用专项"})
        return

    count = min(args.count, len(matched))
    selected = random.sample(matched, count)
    output_json({
        "mode": "topic_practice",
        "vehicle_type": vtype,
        "subject": args.subject,
        "topic": args.topic,
        "total_available": len(matched),
        "count": count,
        "questions": [format_question(q, include_topics=True) for q in selected],
    })


def cmd_hard(args):
    """按易错率排序出题：优先出用户做错率高的题"""
    vtype = resolve_vtype(args.vtype)
    questions = load_questions(args.subject, vtype)
    progress = ensure_fields(load_progress())
    q_stats = progress.get("question_stats", {})

    scored = []
    for q in questions:
        qid_str = str(q["id"])
        stats = q_stats.get(qid_str)
        if stats and stats["attempts"] > 0:
            error_rate = 1 - stats["correct"] / stats["attempts"]
            scored.append((q, error_rate, stats["attempts"]))

    if not scored:
        output_json({
            "message": "还没有做题记录，无法计算易错率。请先做一些题目!",
            "hint": "建议先用 sequential 或 random 模式做一轮题",
        })
        return

    scored.sort(key=lambda x: (-x[1], -x[2]))

    count = min(args.count, len(scored))
    selected = scored[:count]

    output_json({
        "mode": "hard",
        "vehicle_type": vtype,
        "subject": args.subject,
        "total_with_stats": len(scored),
        "count": count,
        "questions": [
            {
                **format_question(q, include_topics=True),
                "error_rate": f"{er*100:.0f}%",
                "attempts": att,
            }
            for q, er, att in selected
        ],
    })


def cmd_record_exam(args):
    vtype = resolve_vtype(args.vtype)
    progress = ensure_fields(load_progress())
    progress["mock_exams"].append({
        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "vehicle_type": vtype,
        "subject": args.subject,
        "score": args.score,
        "total": args.total,
        "passed": args.score >= 90,
    })
    save_progress(progress)
    output_json({"recorded": True, "passed": args.score >= 90})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def add_vtype_arg(parser):
    parser.add_argument(
        "--vtype", type=str, default="c1",
        help="车型: c1(小车) a1(客车) a2(货车) d(摩托车)",
    )


def main():
    parser = argparse.ArgumentParser(description="驾考练习出题引擎")
    sub = parser.add_subparsers(dest="command", help="可用命令")

    sub.add_parser("vtypes", help="列出可用车型及题库状态")

    p_random = sub.add_parser("random", help="随机出题")
    p_random.add_argument("--subject", type=int, choices=[1, 4], required=True)
    p_random.add_argument("--count", type=int, default=5)
    p_random.add_argument("--category", type=str, default=None)
    p_random.add_argument("--exclude-done", action="store_true")
    add_vtype_arg(p_random)

    p_seq = sub.add_parser("sequential", help="顺序练习（断点续练）")
    p_seq.add_argument("--subject", type=int, choices=[1, 4], required=True)
    p_seq.add_argument("--count", type=int, default=5)
    p_seq.add_argument("--reset", action="store_true", help="重置进度从头开始")
    add_vtype_arg(p_seq)

    p_exam = sub.add_parser("exam", help="生成模拟考试")
    p_exam.add_argument("--subject", type=int, choices=[1, 4], required=True)
    add_vtype_arg(p_exam)

    p_check = sub.add_parser("check", help="验证答案")
    p_check.add_argument("--id", type=int, required=True)
    p_check.add_argument("--answer", type=str, required=True)

    p_cat = sub.add_parser("categories", help="列出题目分类")
    p_cat.add_argument("--subject", type=int, choices=[1, 4], required=True)
    add_vtype_arg(p_cat)

    sub.add_parser("stats", help="查看练习统计")

    p_wrong = sub.add_parser("wrong", help="获取错题")
    p_wrong.add_argument("--subject", type=int, choices=[1, 4], default=None)
    p_wrong.add_argument("--count", type=int, default=None)

    p_fav = sub.add_parser("favorite", help="收藏题目")
    p_fav.add_argument("--id", type=int, required=True)

    p_unfav = sub.add_parser("unfavorite", help="取消收藏")
    p_unfav.add_argument("--id", type=int, required=True)

    p_favs = sub.add_parser("favorites", help="查看收藏题目")
    p_favs.add_argument("--subject", type=int, choices=[1, 4], default=None)
    p_favs.add_argument("--count", type=int, default=None)

    p_top = sub.add_parser("top500", help="精选500题")
    p_top.add_argument("--subject", type=int, choices=[1, 4], required=True)
    p_top.add_argument("--count", type=int, default=5)
    add_vtype_arg(p_top)

    p_topics = sub.add_parser("topics", help="列出专项标签")
    p_topics.add_argument("--subject", type=int, choices=[1, 4], required=True)
    add_vtype_arg(p_topics)

    p_tp = sub.add_parser("topic-practice", help="按专项标签出题")
    p_tp.add_argument("--subject", type=int, choices=[1, 4], required=True)
    p_tp.add_argument("--topic", type=str, required=True)
    p_tp.add_argument("--count", type=int, default=5)
    add_vtype_arg(p_tp)

    p_hard = sub.add_parser("hard", help="按易错率出题")
    p_hard.add_argument("--subject", type=int, choices=[1, 4], required=True)
    p_hard.add_argument("--count", type=int, default=10)
    add_vtype_arg(p_hard)

    p_rec = sub.add_parser("record-exam", help="记录模拟考试成绩")
    p_rec.add_argument("--subject", type=int, choices=[1, 4], required=True)
    p_rec.add_argument("--score", type=int, required=True)
    p_rec.add_argument("--total", type=int, required=True)
    add_vtype_arg(p_rec)

    args = parser.parse_args()

    commands = {
        "vtypes": cmd_vtypes,
        "random": cmd_random,
        "sequential": cmd_sequential,
        "exam": cmd_exam,
        "check": cmd_check,
        "categories": cmd_categories,
        "stats": cmd_stats,
        "wrong": cmd_wrong,
        "favorite": cmd_favorite,
        "unfavorite": cmd_unfavorite,
        "favorites": cmd_favorites,
        "top500": cmd_top500,
        "topics": cmd_topics,
        "topic-practice": cmd_topic_practice,
        "hard": cmd_hard,
        "record-exam": cmd_record_exam,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
