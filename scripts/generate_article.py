#!/usr/bin/env python3
"""
generate_article.py
====================
توليد مسوّدة مقالة عربية لثابت فيزيائي واحد من /constants/{symbol}.json
باستخدام GLM API (Zhipu AI — open.bigmodel.cn)، وفق قواعد المشروع.

هذا سكربت عام (generic) وفق القسم 24: لا يحتوي على أي اسم ثابت مكتوب
صراحة في الكود، ويعمل على أي رمز (symbol) موجود في /constants دون تعديل.

قيود إلزامية مطبَّقة هنا (راجع PROJECT_RULES.md):
    * القسم 4  — لا تخمين: يُطلب من النموذج التصريح بعدم توفر أي معلومة
      غير واردة في البيانات المرفقة بدل اختلاقها.
    * القسم 6-ب — لا تُحوَّل value/exponent إلى float عند القراءة؛ تُمرَّر
      كنصوص كما هي إلى النموذج ويُستخدم decimal.Decimal فقط للعرض المنسّق.
    * القسم 7-ب — يميّز صراحة بين defined_exact و measured في الـ prompt.
    * القسم 12 — التجارب المرتبطة تُذكر بالاسم فقط (بلا تفاصيل مخبرية).
    * القسم 13 — ممنوع اختلاق قيمة/تاريخ/عالم/تجربة/DOI/رابط.
    * القسم 15-ب — يستورد الترجمات المعتمدة حصرًا من glossary.json.
    * القسم 21 — مفتاح API يُقرأ فقط من متغير البيئة GLM_API_KEY، ولا
      يُقبل كوسيط سطر أوامر (CLI) تفاديًا لتسريبه عبر history/العمليات.
    * القسم 23 — المخرج مسوّدة دائمًا (review_status: PENDING_HUMAN_REVIEW)
      ولا يوجد أي مسار نشر تلقائي في هذا السكربت.
    * القسم 29 — الأسلوب: عربي واضح دقيق أكاديمي، بلا مبالغة أو حشو.

بيانات الـ frontmatter (الحالة، الرموز، الوحدات...) تُبنى آليًا من سجل
الثابت نفسه في هذا السكربت — وليس من مخرجات النموذج — لتفادي أي احتمال
لتلوّث الحقول البنيوية بهلوسة النموذج اللغوي.

الاستخدام:
    export GLM_API_KEY=...
    python3 scripts/generate_article.py --symbol h
    python3 scripts/generate_article.py --symbol h --dry-run   # بلا استدعاء API فعلي

exit codes:
    0 -> نجاح (أو dry-run ناجح).
    1 -> خطأ في المدخلات (ثابت/مسرد غير موجود، ملف مقالة موجود بلا --force).
    2 -> خطأ اتصال/استجابة من GLM API.
    3 -> مفتاح API غير متوفر (وغير dry-run).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-5.3-flash"
DEFAULT_TIMEOUT = 90

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("generate_article")


# --------------------------------------------------------------------------
# تحميل المدخلات
# --------------------------------------------------------------------------

def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON تالف في {path}: {exc}") from exc


def load_constant(constants_dir: Path, symbol: str) -> dict[str, Any]:
    path = constants_dir / f"{symbol}.json"
    if not path.is_file():
        raise FileNotFoundError(f"لا يوجد سجل ثابت للرمز '{symbol}' في {path}")
    return load_json(path)


def load_glossary(glossary_path: Path) -> list[dict[str, Any]]:
    if not glossary_path.is_file():
        raise FileNotFoundError(
            f"glossary.json غير موجود في {glossary_path} — مطلوب وفق القسم 15-ب "
            "قبل تشغيل أي سكربت توليد محتوى."
        )
    data = load_json(glossary_path)
    return data.get("terms", [])


def load_source(sources_dir: Path, source_id: str) -> dict[str, Any] | None:
    path = sources_dir / f"{source_id}.json"
    if not path.is_file():
        logger.warning("سجل المصدر '%s' غير موجود في %s — سيُتجاهل الاستشهاد.", source_id, path)
        return None
    return load_json(path)


def load_related_experiments(experiments_dir: Path, symbol: str) -> list[dict[str, Any]]:
    """
    يعيد قائمة التجارب المرتبطة بالرمز (اسم + نوع العلاقة فقط)، وفق نموذج
    العلاقة many-to-many في القسم 11-ب. لا تفاصيل مخبرية تُمرَّر (القسم 12).
    يعيد قائمة فارغة بأمان إذا كان المجلد غير موجود بعد (لا تجارب مبنية حتى الآن).
    """
    if not experiments_dir.is_dir():
        return []
    related: list[dict[str, Any]] = []
    for path in sorted(experiments_dir.glob("*.json")):
        try:
            exp = load_json(path)
        except ValueError as exc:
            logger.warning("تخطي ملف تجربة تالف %s: %s", path, exc)
            continue
        if symbol in exp.get("relates_to", []):
            related.append(
                {
                    "experiment_id": exp.get("experiment_id", path.stem),
                    "name_ar": exp.get("name_ar"),
                    "name_en": exp.get("name_en"),
                    "relation_type": exp.get("relation_type"),
                }
            )
    return related


# --------------------------------------------------------------------------
# تنسيق العرض (بدون float — القسم 6-ب)
# --------------------------------------------------------------------------

def format_value_display(value: str, exponent: int) -> str:
    """
    يبني نصًا للعرض من value/exponent كنصوص، عبر Decimal فقط لحظة العرض
    (وليس عند التخزين أو النقل)، حفاظًا على الأرقام المعنوية الأصلية.
    """
    mantissa = Decimal(value)
    if exponent == 0:
        return str(mantissa)
    return f"{mantissa} × 10^{exponent}"


# --------------------------------------------------------------------------
# بناء الـ prompt
# --------------------------------------------------------------------------

def build_system_prompt(glossary_terms: list[dict[str, Any]]) -> str:
    glossary_lines = "\n".join(
        f"- {t['term_en']} → {t['term_ar']}"
        + (f" ({t['notes_ar']})" if t.get("notes_ar") else "")
        for t in glossary_terms
    )
    return f"""أنت محرر علمي متخصص في المترولوجيا والفيزياء، تكتب بالعربية الفصحى
الأكاديمية لمشروع "Physics Constants of the Week". يجب الالتزام الصارم
بما يلي دون استثناء:

1. استخدم فقط البيانات الواردة في رسالة المستخدم. ممنوع منعًا باتًا اختلاق
   أي قيمة عددية، تاريخ، اسم عالم، تجربة، ورقة علمية، DOI، أو رابط لم يرد
   صراحة في البيانات المرفقة. إن كانت معلومة مفيدة غير متوفرة في البيانات،
   صرّح بذلك بعبارة مثل "غير متوفر في البيانات الحالية" بدل التخمين أو
   الاعتماد على معرفتك العامة.
2. ميّز بوضوح بين القيمة المحددة بالتعريف (defined_exact) والقيمة المقاسة
   (measured) بحسب حقل definitional_status المرفق. لا تصف قيمة measured
   بأنها "دقيقة تمامًا"، ولا تُسقط عدم اليقين المرتبط بها.
3. اذكر حالة التحقق (verification_status) كما وردت حرفيًا، ولا تدّعي أن
   السجل "موثّق نهائيًا" أو "VERIFIED" إذا لم تكن هذه هي القيمة الفعلية
   المرفقة — بل صِف الحالة كما هي (مثال: قيد التحقق/VALIDATING).
4. عند ذكر أي تجربة مرتبطة: اذكر اسمها فقط كما ورد، دون تفاصيل مخبرية أو
   خطوات إجرائية — تفاصيل التجربة تخص صفحتها المتخصصة لا مقال الثابت.
5. لأي مصطلح مترولوجي له مقابل في المسرد أدناه، استخدم الترجمة المعتمدة
   حرفيًا ولا تخترع ترجمة بديلة:
{glossary_lines}
6. الأسلوب: عربي واضح، دقيق، أكاديمي، منظم، مختصر عند عدم الحاجة للتوسع.
   تجنّب المبالغة واللغة التسويقية والادعاءات المطلقة والحشو وتكرار المعلومة.
7. أخرج المحتوى كنص Markdown لجسم المقالة فقط (بدون YAML frontmatter وبدون
   عنوان H1 مكرر لاسم الملف) — الأقسام المتوقعة: تعريف موجز، الوضع
   المترولوجي (exact/measured وحالة التحقق)، القيمة والوحدة وعدم اليقين إن
   وجد، الصيغة البعدية، سلسلة القيم عبر إصدارات CODATA إن توفرت في
   history، التجارب ذات الصلة (أسماء فقط) إن وُجدت، والمصدر المرجعي."""


def build_user_prompt(
    record: dict[str, Any],
    source: dict[str, Any] | None,
    experiments: list[dict[str, Any]],
) -> str:
    payload: dict[str, Any] = {
        "constant_record": record,
        "value_display_note": format_value_display(record["value"], record["exponent"]),
        "source_ref_full": source,
        "related_experiments": experiments,
    }
    return (
        "اكتب مسوّدة مقالة عن الثابت الفيزيائي التالي بالاعتماد حصرًا على "
        "البيانات المنظمة أدناه (JSON). لا تستخدم أي معلومة من خارج هذا "
        "الكائن:\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    )


# --------------------------------------------------------------------------
# استدعاء GLM API
# --------------------------------------------------------------------------

def call_glm(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str,
    base_url: str,
    temperature: float,
    timeout: int,
) -> str:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    req = urllib.request.Request(
        base_url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GLM API أعادت خطأ HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"تعذّر الاتصال بـ GLM API ({base_url}): {exc.reason}") from exc

    data = json.loads(raw)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"استجابة GLM API غير متوقعة الشكل: {raw[:500]}") from exc


# --------------------------------------------------------------------------
# بناء frontmatter آليًا من سجل الثابت (وليس من مخرجات النموذج)
# --------------------------------------------------------------------------

def build_frontmatter(
    record: dict[str, Any],
    model: str,
    base_url: str,
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        f"symbol: \"{record['symbol']}\"",
        f"name_ar: \"{record['name_ar']}\"",
        f"name_en: \"{record['name_en']}\"",
        f"unit: \"{record['unit']}\"",
        f"dimensional_formula: \"{record['dimensional_formula']}\"",
        f"definitional_status: \"{record['definitional_status']}\"",
        f"codata_version: \"{record['codata_version']}\"",
        f"verification_status: \"{record['verification_status']}\"",
        f"source_id: \"{record['source_ref']['source_id']}\"",
        "review_status: \"PENDING_HUMAN_REVIEW\"",
        f"generated_by: \"{model} ({base_url})\"",
        f"generated_at: \"{generated_at}\"",
        "---",
        "",
    ]
    return "\n".join(lines)


def write_article(articles_dir: Path, symbol: str, content: str, force: bool) -> Path:
    articles_dir.mkdir(parents=True, exist_ok=True)
    path = articles_dir / f"{symbol}.md"
    if path.is_file() and not force:
        raise FileExistsError(
            f"المقالة {path} موجودة مسبقًا. استخدم --force لاستبدالها عمدًا "
            "(القسم 15 — لا تكرار للبيانات دون قرار صريح)."
        )
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="رمز الثابت، مثل h أو G أو alpha")
    parser.add_argument("--constants-dir", type=Path, default=Path("constants"))
    parser.add_argument("--sources-dir", type=Path, default=Path("sources"))
    parser.add_argument("--experiments-dir", type=Path, default=Path("experiments"))
    parser.add_argument("--glossary", type=Path, default=Path("glossary.json"))
    parser.add_argument("--articles-dir", type=Path, default=Path("articles"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--force", action="store_true", help="استبدال مقالة موجودة عمدًا")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="يبني الـ prompt ويطبعه دون استدعاء GLM API فعليًا ودون حاجة لمفتاح",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        record = load_constant(args.constants_dir, args.symbol)
        glossary_terms = load_glossary(args.glossary)
    except (FileNotFoundError, ValueError) as exc:
        logger.error(str(exc))
        return 1

    source = load_source(args.sources_dir, record["source_ref"]["source_id"])
    experiments = load_related_experiments(args.experiments_dir, args.symbol)

    system_prompt = build_system_prompt(glossary_terms)
    user_prompt = build_user_prompt(record, source, experiments)

    if args.dry_run:
        print("=== SYSTEM PROMPT ===\n")
        print(system_prompt)
        print("\n=== USER PROMPT ===\n")
        print(user_prompt)
        print(
            f"\n=== (dry-run: لم يُستدعَ GLM API — model={args.model}, "
            f"base_url={args.base_url}) ==="
        )
        return 0

    import os

    api_key = os.environ.get("GLM_API_KEY")
    if not api_key:
        logger.error(
            "متغير البيئة GLM_API_KEY غير مضبوط. اضبطه أو استخدم --dry-run "
            "للمعاينة بدون استدعاء فعلي (القسم 21 — لا مفاتيح داخل الكود)."
        )
        return 3

    try:
        body = call_glm(
            system_prompt,
            user_prompt,
            api_key,
            args.model,
            args.base_url,
            args.temperature,
            args.timeout,
        )
    except RuntimeError as exc:
        logger.error(str(exc))
        return 2

    frontmatter = build_frontmatter(record, args.model, args.base_url)
    content = frontmatter + body.strip() + "\n"

    try:
        path = write_article(args.articles_dir, args.symbol, content, args.force)
    except FileExistsError as exc:
        logger.error(str(exc))
        return 1

    logger.info("تم إنشاء مسوّدة: %s (review_status=PENDING_HUMAN_REVIEW)", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
