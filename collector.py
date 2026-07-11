#!/usr/bin/env python3
"""Collect recent JWST galaxy papers from the arXiv Atom API."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ATOM = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_API = "https://export.arxiv.org/api/query"
DEFAULT_CONFIG = Path(__file__).with_name("config.json")


@dataclass(frozen=True)
class Paper:
    arxiv_id: str
    title: str
    abstract: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    published: datetime
    updated: datetime
    abs_url: str
    pdf_url: str


@dataclass(frozen=True)
class RankedPaper:
    paper: Paper
    score: int
    matches: tuple[str, ...]


def normalize_space(value: str) -> str:
    return " ".join(value.split())


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def base_arxiv_id(url_or_id: str) -> str:
    value = url_or_id.rstrip("/").split("/")[-1]
    return re.sub(r"v\d+$", "", value)


def parse_atom(payload: bytes) -> list[Paper]:
    root = ET.fromstring(payload)
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ATOM):
        raw_id = entry.findtext("atom:id", default="", namespaces=ATOM)
        if not raw_id:
            continue
        links = entry.findall("atom:link", ATOM)
        pdf_url = next(
            (link.get("href", "") for link in links if link.get("title") == "pdf"),
            f"https://arxiv.org/pdf/{base_arxiv_id(raw_id)}",
        )
        authors = tuple(
            normalize_space(node.findtext("atom:name", default="", namespaces=ATOM))
            for node in entry.findall("atom:author", ATOM)
        )
        categories = tuple(
            node.get("term", "") for node in entry.findall("atom:category", ATOM)
        )
        papers.append(
            Paper(
                arxiv_id=base_arxiv_id(raw_id),
                title=normalize_space(
                    entry.findtext("atom:title", default="", namespaces=ATOM)
                ),
                abstract=normalize_space(
                    entry.findtext("atom:summary", default="", namespaces=ATOM)
                ),
                authors=tuple(author for author in authors if author),
                categories=tuple(category for category in categories if category),
                published=parse_datetime(
                    entry.findtext("atom:published", default="", namespaces=ATOM)
                ),
                updated=parse_datetime(
                    entry.findtext("atom:updated", default="", namespaces=ATOM)
                ),
                abs_url=f"https://arxiv.org/abs/{base_arxiv_id(raw_id)}",
                pdf_url=pdf_url.replace("http://", "https://"),
            )
        )
    return papers


def term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term).replace(r"\ ", r"[\s-]+")
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def matched_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term_pattern(term).search(text)]


def rank_paper(paper: Paper, config: dict[str, Any]) -> RankedPaper | None:
    title = paper.title
    abstract = paper.abstract
    jwst_terms = config["jwst_terms"]
    galaxy_terms = config["galaxy_terms"]
    related_terms = config["related_terms"]

    jwst_title = matched_terms(title, jwst_terms)
    jwst_abstract = matched_terms(abstract, jwst_terms)
    galaxy_title = matched_terms(title, galaxy_terms)
    galaxy_abstract = matched_terms(abstract, galaxy_terms)
    related_title = matched_terms(title, related_terms)
    related_abstract = matched_terms(abstract, related_terms)

    if not (jwst_title or jwst_abstract):
        return None
    if not (galaxy_title or galaxy_abstract or related_title or related_abstract):
        return None

    score = 0
    score += 4 if jwst_title else 2
    score += 4 if galaxy_title else (2 if galaxy_abstract else 0)
    score += min(4, 2 * len(related_title))
    score += min(3, len(related_abstract))

    matches = tuple(
        dict.fromkeys(
            jwst_title
            + jwst_abstract
            + galaxy_title
            + galaxy_abstract
            + related_title
            + related_abstract
        )
    )
    if score < int(config["minimum_score"]):
        return None
    return RankedPaper(paper=paper, score=score, matches=matches)


def build_query(config: dict[str, Any]) -> str:
    categories = " OR ".join(f"cat:{value}" for value in config["categories"])
    terms = " OR ".join(
        f'all:"{value}"' if " " in value else f"all:{value}"
        for value in config["jwst_terms"]
    )
    return f"({categories}) AND ({terms})"


def fetch_papers(config: dict[str, Any]) -> list[Paper]:
    params = urllib.parse.urlencode(
        {
            "search_query": build_query(config),
            "start": 0,
            "max_results": int(config["max_results"]),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    email = config.get("contact_email", "replace-with-your-email@example.com")
    request = urllib.request.Request(
        f"{ARXIV_API}?{params}",
        headers={
            "User-Agent": f"jwst-galaxy-digest/1.0 (mailto:{email})",
            "Accept": "application/atom+xml",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return parse_atom(response.read())


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def markdown_report(items: list[RankedPaper], run_date: str) -> str:
    lines = [
        f"# JWST × Galaxy arXiv Daily — {run_date}",
        "",
        f"发现 **{len(items)}** 篇未推送过的相关论文。",
        "",
    ]
    if not items:
        lines += ["今天没有新的匹配论文。", ""]
    for index, item in enumerate(items, 1):
        paper = item.paper
        authors = ", ".join(paper.authors)
        lines += [
            f"## {index}. {html.escape(paper.title)}",
            "",
            f"- **相关度：** {item.score}",
            f"- **匹配词：** {', '.join(item.matches)}",
            f"- **作者：** {html.escape(authors)}",
            f"- **分类：** {', '.join(paper.categories)}",
            f"- **首次提交：** {paper.published.date().isoformat()}",
            f"- **链接：** [摘要]({paper.abs_url}) · [PDF]({paper.pdf_url})",
            "",
            paper.abstract,
            "",
        ]
    lines += [
        "---",
        "",
        "由 GitHub Actions 和 arXiv API 自动生成。相关度分数仅用于排序。",
        "",
    ]
    return "\n".join(lines)


def html_page(title: str, content: str, home_href: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light dark; --accent: #4d72b8; --muted: #667085; }}
    body {{ font: 16px/1.65 system-ui, -apple-system, sans-serif; max-width: 980px; margin: 0 auto; padding: 2rem 1rem 5rem; }}
    a {{ color: var(--accent); }}
    header {{ border-bottom: 1px solid #8885; margin-bottom: 2rem; }}
    nav {{ margin-bottom: 1rem; }}
    .paper {{ border: 1px solid #8885; border-radius: 12px; padding: 1rem 1.25rem; margin: 1.25rem 0; }}
    .meta {{ color: var(--muted); }}
    .score {{ display: inline-block; padding: .1rem .55rem; border-radius: 999px; background: #4d72b822; font-weight: 700; }}
    ul.index {{ list-style: none; padding: 0; }}
    ul.index li {{ border-bottom: 1px solid #8883; padding: .7rem 0; }}
    footer {{ color: var(--muted); border-top: 1px solid #8885; margin-top: 2rem; padding-top: 1rem; }}
  </style>
</head>
<body>
  <nav><a href="{html.escape(home_href, quote=True)}">总目录</a></nav>
  {content}
  <footer>由 GitHub Actions 和 arXiv API 自动生成。</footer>
</body>
</html>
"""


def daily_html_report(items: list[RankedPaper], run_date: str) -> str:
    blocks = [
        "<header>",
        f"<h1>JWST × Galaxy arXiv Daily — {html.escape(run_date)}</h1>",
        f"<p>发现 <strong>{len(items)}</strong> 篇未推送过的相关论文。</p>",
        "</header>",
    ]
    if not items:
        blocks.append("<p>今天没有新的匹配论文。</p>")
    for index, item in enumerate(items, 1):
        paper = item.paper
        title = html.escape(paper.title)
        authors = html.escape(", ".join(paper.authors))
        categories = html.escape(", ".join(paper.categories))
        matches = html.escape(", ".join(item.matches))
        abstract = html.escape(paper.abstract)
        blocks.extend(
            [
                '<article class="paper">',
                f"<h2>{index}. {title}</h2>",
                f'<p><span class="score">相关度 {item.score}</span></p>',
                f'<p class="meta"><strong>匹配词：</strong>{matches}<br>',
                f"<strong>作者：</strong>{authors}<br>",
                f"<strong>分类：</strong>{categories}<br>",
                f"<strong>首次提交：</strong>{paper.published.date().isoformat()}</p>",
                f'<p><a href="{html.escape(paper.abs_url, quote=True)}">arXiv 摘要</a> · '
                f'<a href="{html.escape(paper.pdf_url, quote=True)}">PDF</a></p>',
                f"<p>{abstract}</p>",
                "</article>",
            ]
        )
    return html_page(f"JWST Galaxy Daily {run_date}", "\n".join(blocks), "../../index.html")


def write_catalogs(report_root: Path, year: str, month: str) -> None:
    month_dir = report_root / year / month
    daily_pages = sorted(
        (path for path in month_dir.glob("????-??-??.html")), reverse=True
    )
    daily_links = "\n".join(
        f'<li><a href="{path.name}">{html.escape(path.stem)}</a></li>'
        for path in daily_pages
    ) or "<li>本月还没有日报。</li>"
    month_content = (
        f"<header><h1>{year} 年 {int(month)} 月日报目录</h1>"
        f"<p>共 {len(daily_pages)} 天。</p></header>"
        f'<ul class="index">{daily_links}</ul>'
    )
    (month_dir / "index.html").write_text(
        html_page(f"{year}-{month} 日报目录", month_content, "../../index.html"),
        encoding="utf-8",
    )

    year_dir = report_root / year
    month_dirs = sorted(
        (path for path in year_dir.iterdir() if path.is_dir() and re.fullmatch(r"\d{2}", path.name)),
        reverse=True,
    )
    month_links = []
    for path in month_dirs:
        count = len(list(path.glob("????-??-??.html")))
        month_links.append(
            f'<li><a href="{path.name}/index.html">{year} 年 {int(path.name)} 月</a> '
            f"— {count} 天</li>"
        )
    year_content = (
        f"<header><h1>{year} 年月度目录</h1></header>"
        f'<ul class="index">{"".join(month_links) or "<li>本年还没有月报。</li>"}</ul>'
    )
    (year_dir / "index.html").write_text(
        html_page(f"{year} 年月度目录", year_content, "../index.html"), encoding="utf-8"
    )

    year_dirs = sorted(
        (path for path in report_root.iterdir() if path.is_dir() and re.fullmatch(r"\d{4}", path.name)),
        reverse=True,
    )
    year_links = "".join(
        f'<li><a href="{path.name}/index.html">{path.name} 年</a></li>'
        for path in year_dirs
    ) or "<li>还没有日报。</li>"
    root_content = (
        "<header><h1>JWST × Galaxy arXiv 日报</h1>"
        "<p>按年份、月份浏览每日论文。</p></header>"
        f'<ul class="index">{year_links}</ul>'
    )
    (report_root / "index.html").write_text(
        html_page("JWST Galaxy arXiv 日报", root_content, "index.html"), encoding="utf-8"
    )


def write_csv(path: Path, items: list[RankedPaper]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "arxiv_id",
                "score",
                "title",
                "authors",
                "published",
                "updated",
                "categories",
                "matches",
                "abstract_url",
                "pdf_url",
                "abstract",
            ],
        )
        writer.writeheader()
        for item in items:
            paper = item.paper
            writer.writerow(
                {
                    "arxiv_id": paper.arxiv_id,
                    "score": item.score,
                    "title": paper.title,
                    "authors": "; ".join(paper.authors),
                    "published": paper.published.isoformat(),
                    "updated": paper.updated.isoformat(),
                    "categories": "; ".join(paper.categories),
                    "matches": "; ".join(item.matches),
                    "abstract_url": paper.abs_url,
                    "pdf_url": paper.pdf_url,
                    "abstract": paper.abstract,
                }
            )


def run(config_path: Path, dry_run: bool = False) -> int:
    config = load_json(config_path, None)
    if config is None:
        raise FileNotFoundError(f"Configuration not found: {config_path}")

    root = config_path.parent
    state_path = root / config["state_file"]
    report_dir = root / config["report_directory"]
    state = load_json(state_path, {"seen": {}, "last_successful_run": None})
    seen: dict[str, str] = state.get("seen", {})

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=int(config["lookback_days"]))
    # This is a "new paper" digest, so use the v1 submission date rather than
    # resurfacing an older paper whenever a revised version is uploaded.
    candidates = [paper for paper in fetch_papers(config) if paper.published >= cutoff]
    ranked = [item for paper in candidates if (item := rank_paper(paper, config))]
    new_items = [item for item in ranked if item.paper.arxiv_id not in seen]
    new_items.sort(key=lambda item: (-item.score, -item.paper.published.timestamp()))

    local_now = now.astimezone(ZoneInfo(config["timezone"]))
    run_date = local_now.date().isoformat()
    if dry_run:
        print(markdown_report(new_items, run_date))
        return 0

    daily_dir = report_dir / f"{local_now.year:04d}" / f"{local_now.month:02d}"
    daily_dir.mkdir(parents=True, exist_ok=True)
    (daily_dir / f"{run_date}.md").write_text(
        markdown_report(new_items, run_date), encoding="utf-8"
    )
    (daily_dir / f"{run_date}.html").write_text(
        daily_html_report(new_items, run_date), encoding="utf-8"
    )
    write_csv(daily_dir / f"{run_date}.csv", new_items)
    write_catalogs(report_dir, f"{local_now.year:04d}", f"{local_now.month:02d}")

    for item in new_items:
        seen[item.paper.arxiv_id] = local_now.isoformat()
    state["seen"] = seen
    state["last_successful_run"] = local_now.isoformat()
    save_json(state_path, state)
    print(f"Wrote {len(new_items)} new papers to {report_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--dry-run", action="store_true", help="print report without writing files"
    )
    args = parser.parse_args()
    try:
        return run(args.config.resolve(), args.dry_run)
    except Exception as exc:
        print(f"collector failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
