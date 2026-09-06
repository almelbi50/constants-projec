#!/usr/bin/env python3
"""
publish_wordpress.py
=====================
يرسل مسوّدة مقالة {symbol}.md (المُولَّدة عبر generate_article.py) إلى
phy-lab.com كمسودة (draft) عبر WordPress REST API — لا يُنشر المقال
فعليًا؛ المراجعة والنشر النهائي يتمّان يدويًا من لوحة تحكم WordPress
(القسم 23 من قواعد المشروع: Human Review قبل Publish).

سكربت عام (generic) وفق القسم 24: لا يحتوي على أي اسم ثابت مكتوب صراحة
في الكود، يعمل على أي رمز (symbol) دون تعديل.

قيود إلزامية مطبَّقة هنا:
    * القسم 21 — بيانات الدخول (WP_USERNAME / WP_APP_PASSWORD) تُقرأ فقط
      من متغيرات البيئة، ولا تُقبل كوسيط سطر أوامر ولا تُسجَّل في أي log.
    * القسم 23 — الحالة المُرسَلة دائمًا draft أو pending فقط؛ لا يوجد
      خيار publish في هذا السكربت إطلاقًا (تطبيق للقاعدة على مستوى الكود).
    * القسم 20 — العملية idempotent: البحث عن مقال موجود بنفس الـslug
      وتحديثه (PUT) بدل إنشاء نسخة مكررة عند إعادة تشغيل الـworkflow.

الاستخدام:
    export WP_USERNAME=...
    export WP_APP_PASSWORD=...
    python3 scripts/publish_wordpress.py --symbol h
    python3 scripts/publish_wordpress.py --symbol h --dry-run

exit codes:
    0 -> نجاح (إنشاء أو تحديث المسودة، أو dry-run ناجح).
    1 -> خطأ في المدخلات (المقالة غير موجودة، frontmatter تالف).
    2 -> خطأ اتصال/استجابة من WordPress REST API.
    3 -> بيانات الدخول غير متوفرة (وغير dry-run).
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import markdown as md
except ImportError:  # pragma: no cover
    print(
        "الحزمة markdown غير مثبتة. ثبّتها عبر: "
        "pip install markdown --break-system-packages",
        file=sys.stderr,
    )
    sys.exit(2)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("publish_wordpress")

DEFAULT_SITE_URL = "https://phy-lab.com"
DEFAULT_CATEGORY_NAME = "ثوابت فيزيائية"
DEFAULT_CATEGORY_SLUG = "physical-constants"


def parse_article(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError(f"تعذّر تحليل frontmatter في {path}")
    fm_block, body = m.group(1), m.group(2)
    frontmatter: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        frontmatter[key.strip()] = value.strip().strip('"')
    return frontmatter, body.strip()


def wp_request(
    site_url: str,
    path: str,
    username: str,
    app_password: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: int = 60,
) -> Any:
    url = f"{site_url.rstrip('/')}/wp-json/wp/v2/{path}"
    token = base64.b64encode(f"{username}:{app_password}".encode("utf-8")).decode("ascii")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"WordPress REST API أعادت خطأ HTTP {exc.code} على {path}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"تعذّر الاتصال بـ WordPress ({url}): {exc.reason}") from exc
    return json.loads(raw) if raw else None


def get_or_create_category(
    site_url: str, username: str, app_password: str, name: str, slug: str
) -> int:
    existing = wp_request(
        site_url, f"categories?slug={slug}", username, app_password, method="GET"
    )
    if existing:
        return existing[0]["id"]
    created = wp_request(
        site_url,
        "categories",
        username,
        app_password,
        method="POST",
        body={"name": name, "slug": slug},
    )
    return created["id"]


def find_existing_post(
    site_url: str, username: str, app_password: str, slug: str
) -> int | None:
    existing = wp_request(
        site_url,
        f"posts?slug={slug}&status=draft,publish,pending,future,private",
        username,
        app_password,
        method="GET",
    )
    if existing:
        return existing[0]["id"]
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--articles-dir", type=Path, default=Path("articles"))
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL)
    parser.add_argument("--category-name", default=DEFAULT_CATEGORY_NAME)
    parser.add_argument("--category-slug", default=DEFAULT_CATEGORY_SLUG)
    parser.add_argument("--status", default="draft", choices=["draft", "pending"])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="يبني العنوان ومحتوى HTML ويطبعهما دون إرسال أي طلب فعلي لـWordPress",
    )
    args = parser.parse_args(argv)

    article_path = args.articles_dir / f"{args.symbol}.md"
    if not article_path.is_file():
        logger.error("ملف المقالة غير موجود: %s", article_path)
        return 1

    try:
        frontmatter, body = parse_article(article_path)
    except ValueError as exc:
        logger.error(str(exc))
        return 1

    if frontmatter.get("review_status") != "PENDING_HUMAN_REVIEW":
        logger.warning(
            "review_status = %s (متوقَّع PENDING_HUMAN_REVIEW) — سيُتابَع الإرسال كمسودة على أي حال.",
            frontmatter.get("review_status"),
        )

    name_ar = frontmatter.get("name_ar", args.symbol)
    symbol = frontmatter.get("symbol", args.symbol)
    title = f"{name_ar} ({symbol})"
    slug = f"physical-constant-{symbol}".lower()
    html_body = md.markdown(body, extensions=["tables", "fenced_code"])

    if args.dry_run:
        print(f"=== TITLE ===\n{title}\n")
        print(f"=== SLUG ===\n{slug}\n")
        print(f"=== CATEGORY ===\n{args.category_name} ({args.category_slug})\n")
        print(f"=== HTML BODY (excerpt) ===\n{html_body[:500]}...\n")
        print(f"=== (dry-run: لم يُرسَل أي طلب إلى {args.site_url}) ===")
        return 0

    import os

    username = os.environ.get("WP_USERNAME")
    app_password = os.environ.get("WP_APP_PASSWORD")
    if not username or not app_password:
        logger.error(
            "متغيرا البيئة WP_USERNAME و WP_APP_PASSWORD غير مضبوطين. اضبطهما أو استخدم "
            "--dry-run للمعاينة (القسم 21 — لا بيانات دخول داخل الكود)."
        )
        return 3

    try:
        category_id = get_or_create_category(
            args.site_url, username, app_password, args.category_name, args.category_slug
        )
        existing_id = find_existing_post(args.site_url, username, app_password, slug)
        payload = {
            "title": title,
            "slug": slug,
            "status": args.status,
            "categories": [category_id],
            "content": html_body,
        }
        if existing_id:
            result = wp_request(
                args.site_url,
                f"posts/{existing_id}",
                username,
                app_password,
                method="POST",
                body=payload,
            )
            logger.info(
                "تم تحديث المسودة الموجودة على WordPress: post_id=%s status=%s",
                result["id"],
                result["status"],
            )
        else:
            result = wp_request(
                args.site_url,
                "posts",
                username,
                app_password,
                method="POST",
                body=payload,
            )
            logger.info(
                "تم إنشاء مسودة جديدة على WordPress: post_id=%s status=%s",
                result["id"],
                result["status"],
            )
    except RuntimeError as exc:
        logger.error(str(exc))
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())

