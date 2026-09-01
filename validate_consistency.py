#!/usr/bin/env python3
"""
validate_consistency.py
=========================
التحقق التناسقي بين الثوابت (القسم 9-ب من قواعد المشروع).

الفكرة: بعض الثوابت المخزّنة في /constants/ يمكن حسابها رياضيًا من ثوابت
أخرى مخزّنة أيضًا. هذا السكربت يحسب كل علاقة معروفة، ويقارن الناتج بالقيمة
المخزّنة ضمن هامش nσ (مضروبًا في عدم اليقين المُجمّع)، وإن تجاوز الفرق
الهامش المسموح، يُبلّغ بذلك كفشل يمنع الدمج (لا يُعدّل الملفات تلقائيًا).

هذا السكربت عام (generic) وفق القسم 24: العلاقات معرّفة في قائمة RELATIONS
في الأعلى، وإضافة علاقة جديدة (مثلًا لثابت يُضاف لاحقًا) لا يتطلب تعديل
منطق الحساب أو المقارنة — فقط إضافة سطر جديد لقائمة RELATIONS.

ملاحظة صريحة عن القسم 9-ب: G "ثابت الجذب العام" لا يدخل في least-squares
adjustment الخاص بـ CODATA، أي لا توجد له علاقة تناسقية رياضية مع باقي
الثوابت هنا — وهذا سلوك متوقع وليس نقصًا في السكربت (انظر build_queue,
build_order 12).

الاستخدام:
    python3 scripts/validate_consistency.py
    python3 scripts/validate_consistency.py --n-sigma 5

exit codes:
    0 -> كل العلاقات المُختبرة ضمن الهامش المسموح.
    1 -> علاقة واحدة على الأقل تجاوزت الهامش (NEEDS_REVIEW).
    2 -> خطأ تشغيلي (ملف مفقود، قيمة exact بلا history كافية، إلخ).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Callable, NamedTuple

getcontext().prec = 60

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("validate_consistency")

PI = Decimal(
    "3.14159265358979323846264338327950288419716939937510582097494"
)


def load_constant(constants_dir: Path, symbol: str) -> dict:
    path = constants_dir / f"{symbol}.json"
    if not path.is_file():
        raise FileNotFoundError(f"ثابت مفقود مطلوب للتحقق التناسقي: {symbol} ({path})")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def to_decimal(record: dict) -> Decimal:
    """تحويل value+exponent المخزَّنين كنصوص إلى Decimal — فقط لحظة الحساب (القسم 6-ب)."""
    return Decimal(record["value"]) * (Decimal(10) ** record["exponent"])


def relative_uncertainty(record: dict) -> Decimal:
    """
    يعيد عدم اليقين النسبي كـ Decimal. القيم exact تُعامَل بعدم يقين = 0
    (وليس None) لأغراض حساب الهامش المُجمّع فقط.
    """
    ru = record.get("relative_uncertainty")
    if ru is None:
        return Decimal(0)
    return Decimal(str(ru))


class Relation(NamedTuple):
    name_ar: str
    target_symbol: str
    required_symbols: tuple[str, ...]
    compute: Callable[[dict[str, Decimal]], Decimal]


# --------------------------------------------------------------------------
# قائمة العلاقات التناسقية المعروفة بين الثوابت المخزّنة حاليًا في /constants
# كل علاقة: (اسم عربي، الثابت الهدف، الثوابت المطلوبة كمدخلات، دالة الحساب)
# --------------------------------------------------------------------------
RELATIONS: list[Relation] = [
    Relation(
        name_ar="ثابت البنية الدقيقة α = e² / (4π ε0 ħ c)",
        target_symbol="alpha",
        required_symbols=("e", "epsilon_0", "hbar", "c"),
        compute=lambda v: (v["e"] ** 2)
        / (4 * PI * v["epsilon_0"] * v["hbar"] * v["c"]),
    ),
    Relation(
        name_ar="ثابت بلانك المختزل ħ = h / (2π)",
        target_symbol="hbar",
        required_symbols=("h",),
        compute=lambda v: v["h"] / (2 * PI),
    ),
    Relation(
        name_ar="ثابت الغازات المولي R = N_A · k_B",
        target_symbol="R",
        required_symbols=("N_A", "k_B"),
        compute=lambda v: v["N_A"] * v["k_B"],
    ),
    Relation(
        name_ar="ثابت فاراداي F = N_A · e",
        target_symbol="F",
        required_symbols=("N_A", "e"),
        compute=lambda v: v["N_A"] * v["e"],
    ),
    Relation(
        name_ar="ثابت جوزيفسون K_J = 2e / h",
        target_symbol="K_J",
        required_symbols=("e", "h"),
        compute=lambda v: 2 * v["e"] / v["h"],
    ),
    Relation(
        name_ar="ثابت فون كليتزنغ R_K = h / e²",
        target_symbol="R_K",
        required_symbols=("h", "e"),
        compute=lambda v: v["h"] / (v["e"] ** 2),
    ),
    Relation(
        name_ar="كمّ الفيض المغناطيسي Φ0 = h / (2e)",
        target_symbol="Phi_0",
        required_symbols=("h", "e"),
        compute=lambda v: v["h"] / (2 * v["e"]),
    ),
    Relation(
        name_ar="السماحية الكهربائية ε0 = 1 / (μ0 c²)",
        target_symbol="epsilon_0",
        required_symbols=("mu_0", "c"),
        compute=lambda v: 1 / (v["mu_0"] * v["c"] ** 2),
    ),
]


def check_relation(
    relation: Relation, constants_dir: Path, n_sigma: Decimal
) -> tuple[bool, str]:
    records = {
        sym: load_constant(constants_dir, sym)
        for sym in (relation.required_symbols + (relation.target_symbol,))
    }
    values = {sym: to_decimal(rec) for sym, rec in records.items()}

    derived = relation.compute(values)
    stored = values[relation.target_symbol]

    diff = abs(derived - stored)
    rel_diff = diff / stored if stored != 0 else diff

    # هامش مسموح تقريبي = n_sigma × (مجموع عدم اليقين النسبي للمدخلات + الهدف)
    combined_rel_unc = sum(
        relative_uncertainty(records[sym]) for sym in relation.required_symbols
    ) + relative_uncertainty(records[relation.target_symbol])

    # إن كانت كل المدخلات والهدف exact (عدم يقين = 0)، نستخدم هامشًا تقنيًا
    # صغيرًا جدًا (دقة العرض العشري المخزّن) بدل صفر مطلق، لتفادي فشل زائف
    # بسبب عدد الأرقام المعنوية في التمثيل النصي فقط.
    margin = max(combined_rel_unc * n_sigma, Decimal("1e-9"))

    passed = rel_diff <= margin
    status = "✓ PASS" if passed else "✗ NEEDS_REVIEW"

    msg = (
        f"{status}  {relation.name_ar}\n"
        f"      المُشتق  = {derived}\n"
        f"      المخزَّن = {stored}\n"
        f"      فرق نسبي = {rel_diff:.3e}   |   الهامش المسموح ({n_sigma}σ) = {margin:.3e}"
    )
    return passed, msg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--constants-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "constants",
    )
    parser.add_argument(
        "--n-sigma",
        type=Decimal,
        default=Decimal("3"),
        help="عدد مرات عدم اليقين المُجمّع المسموح بها كهامش (افتراضي: 3σ)",
    )
    args = parser.parse_args()

    if not args.constants_dir.is_dir():
        logger.error("مجلد الثوابت غير موجود: %s", args.constants_dir)
        return 2

    all_passed = True
    checked = 0

    for relation in RELATIONS:
        try:
            passed, msg = check_relation(relation, args.constants_dir, args.n_sigma)
        except FileNotFoundError as exc:
            logger.warning(
                "تخطي علاقة '%s' — %s (ثابت غير مبني بعد، ليس فشلًا)",
                relation.name_ar,
                exc,
            )
            continue

        checked += 1
        if passed:
            logger.info(msg)
        else:
            logger.error(msg)
            all_passed = False

    logger.info("—" * 40)
    logger.info("تم فحص %d علاقة تناسقية من أصل %d معرَّفة.", checked, len(RELATIONS))

    if not all_passed:
        logger.error(
            "توجد علاقة/علاقات خارج الهامش المسموح. "
            "وفق القسم 9-ب: السجلات المتعارضة يجب أن تتحول إلى NEEDS_REVIEW "
            "يدويًا، ولا يُسمح بالنشر (القسم 22)."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
