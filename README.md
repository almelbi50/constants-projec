# Physics Constants of the Week — قاعدة معرفية للثوابت الفيزيائية

مستودع بيانات منظمة للثوابت الفيزيائية الأساسية (CODATA)، مبني وفق
[قواعد المشروع](./PROJECT_RULES.md) — راجعها قبل أي تعديل.

## بنية المستودع

```text
/constants/{symbol}.json      ← سجلات الثوابت (19 حاليًا) — مصدر الحقيقة
/constants/_build_queue.json  ← خطة الوكيل لبناء الثوابت (ليس سجل schema)
/sources/{id}.json            ← بيانات مصدر CODATA + snapshot + hash
/sources/snapshots/*.txt      ← نسخ نصية مؤرشفة من ملفات NIST الرسمية
/schemas/constant.schema.json ← الـ JSON Schema الملزمة لكل سجل ثابت
/scripts/
    validate_schema.py        ← تحقق كل سجل مقابل الـ schema
    validate_consistency.py   ← تحقق تناسقي رياضي بين الثوابت (القسم 9-ب)
/.github/workflows/validate.yml ← CI: يشغّل السكربتين أعلاه على كل PR
```

## الثوابت المبنية حاليًا (19)

| المجموعة | الرموز |
|---|---|
| exact (معرَّف) | `c` `h` `e` `k_B` `N_A` `hbar` `K_J` `R_K` `Phi_0` `R` `F` `sigma` |
| measured (مقيس) | `R_inf` `alpha` `mu_0` `epsilon_0` `m_e` `m_p` `G` |

انظر `constants/_build_queue.json` للترتيب الكامل من الأسهل إلى الأصعب،
ولمنطق كل قرار ترتيب.

## تشغيل التحقق محليًا

```bash
pip install jsonschema --break-system-packages

python3 scripts/validate_schema.py
python3 scripts/validate_consistency.py --n-sigma 3
```

كلا السكربتين يعيدان exit code غير صفري عند الفشل — مناسبان مباشرة لـ CI.

## حالة الابتلاع (Ingestion) — ملاحظة صريحة

كل `archive_hash_sha256` في `/sources/*.json` هو حاليًا **hash لملف نصي
مستخرَج (snapshot)**، وليس hash للبايتات الخام لملف PDF الأصلي من NIST.
سكربت `ingest_codata.py` (لم يُبنَ بعد) يجب أن يُشغَّل في بيئة CI تملك
وصولًا مباشرًا لنطاق `physics.nist.gov`/`nist.gov` لتنزيل الملف الخام
وحساب hash حقيقي بديل، قبل أن تتحول أي `verification_status` إلى `VERIFIED`
نهائيًا (وفق القسم 5-ب و31 من قواعد المشروع).

## الخطوات التالية المخطَّطة

1. إضافة علاقة `σ = π²k_B⁴/(60ħ³c²)` إلى `RELATIONS` في
   `validate_consistency.py`.
2. بناء `ingest_codata.py` الفعلي (يحتاج بيئة بوصول شبكي لـ nist.gov).
3. بناء `validate_dimensions.py` (تحقق آلي بعدي، القسم 9).
4. التوسع لمجموعة الثوابت متوسطة الصعوبة: `a_0`, `E_h`, `mu_B`, `mu_N`,
   `lambda_C`, `mu_p`.
