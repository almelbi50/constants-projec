#!/usr/bin/env python3
"""
validate_schema.py
====================
التحقق من أن كل ملف في /constants/*.json مطابق لـ /schemas/constant.schema.json.

هذا سكربت عام (generic) وفق القسم 24 من قواعد المشروع: لا يحتوي على أي اسم ثابت
مكتوب صراحة في الكود (hard-coded)، ويعمل تلقائيًا على أي عدد من الثوابت دون تعديل.

الاستخدام:
    python3 scripts/validate_schema.py
    python3 scripts/validate_schema.py --constants-dir /path/to/constants \
                                        --schema /path/to/constant.schema.json

مخرجات الخروج (exit codes) لأغراض CI (القسم 19-ب، بند 5):
    0  -> كل الملفات صالحة.
    1  -> يوجد ملف واحد على الأقل غير مطابق للـ schema (فشل يمنع الدمج).
    2  -> خطأ تشغيلي (مسار غير موجود، JSON تالف، إلخ).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Iterator

try:
    import jsonschema
except ImportError:  # pragma: no cover
    print(
        "الحزمة jsonschema غير مثبتة. ثبّتها عبر: "
        "pip install jsonschema --break-system-packages",
        file=sys.stderr,
    )
    sys.exit(2)


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger("validate_schema")


def load_json(path: Path) -> dict:
    """تحميل ملف JSON مع رسائل خطأ واضحة عند التلف."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON تالف في {path}: {exc}") from exc


def iter_constant_files(constants_dir: Path) -> Iterator[Path]:
    """
    يعيد كل ملفات /constants/*.json القابلة للتحقق، باستثناء ملفات التخطيط
    التي تبدأ بشرطة سفلية (_) مثل _build_queue.json، لأنها ليست سجلات ثابت
    نهائية بصيغة constant.schema.json (انظر ملاحظة _build_queue.json نفسه).
    """
    for path in sorted(constants_dir.glob("*.json")):
        if path.name.startswith("_"):
            logger.info("تخطي ملف تخطيط غير خاضع للـ schema: %s", path.name)
            continue
        yield path


def validate_all(constants_dir: Path, schema_path: Path) -> tuple[int, int]:
    """
    يتحقق من كل الملفات. يعيد (عدد الناجح, عدد الفاشل).
    لا يتوقف عند أول خطأ — يجمع كل الأخطاء لعرضها دفعة واحدة، لأن ذلك
    أفيد لمطوّر يصلح عدة ملفات في نفس الـ PR.
    """
    schema = load_json(schema_path)
    passed = 0
    failed = 0

    for const_file in iter_constant_files(constants_dir):
        try:
            data = load_json(const_file)
        except ValueError as exc:
            logger.error("✗ %s — %s", const_file.name, exc)
            failed += 1
            continue

        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: e.path)

        if errors:
            failed += 1
            logger.error("✗ %s — %d خطأ/أخطاء:", const_file.name, len(errors))
            for err in errors:
                location = "/".join(str(p) for p in err.path) or "(الجذر)"
                logger.error("    - في %s: %s", location, err.message)
        else:
            passed += 1
            logger.info("✓ %s", const_file.name)

    return passed, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--constants-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "constants",
        help="مسار مجلد /constants (افتراضيًا: ../constants نسبة لهذا السكربت)",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "schemas"
        / "constant.schema.json",
        help="مسار constant.schema.json",
    )
    args = parser.parse_args()

    if not args.constants_dir.is_dir():
        logger.error("مجلد الثوابت غير موجود: %s", args.constants_dir)
        return 2
    if not args.schema.is_file():
        logger.error("ملف الـ schema غير موجود: %s", args.schema)
        return 2

    passed, failed = validate_all(args.constants_dir, args.schema)
    total = passed + failed

    logger.info("—" * 40)
    logger.info("النتيجة: %d/%d ملفًا صالحًا", passed, total)

    if failed:
        logger.error(
            "فشل التحقق. وفق القسم 19-ب: لا يُسمح بالدمج حتى تصحيح كل الأخطاء أعلاه."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
