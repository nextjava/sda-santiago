#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
제주대회 공식 사이트(jeju.kuc.or.kr) 크롤러 — 교회별 연혁·설립연도 수집 시도.

배경/한계(2026-06 정찰로 확인):
  - jeju.kuc.or.kr 은 WordPress + mangboard(JS 게시판) 구조.
  - WP REST(wp-json/wp/v2/pages)로 받을 수 있는 건 정적 페이지(대회소개·사명·부서·교회목록)뿐이며
    설립연도/연혁/외부 교회 홈페이지 링크는 들어있지 않다(19xx년 0건).
  - '교회 웹사이트' 보드는 mangboard AJAX(admin-ajax.php, nonce/세션 의존)로만 로드되어
    서버측 정적 수집이 막혀 있다(직접 호출 시 500).
  => 따라서 이 사이트만으로는 설립연도를 채울 수 없음을 '미발견'으로 명확히 기록한다.

정책: robots.txt Content-Signal(search=yes, ai-train=no) 준수 — AI 학습용 아님, 연구/순례 콘텐츠.
      저속(요청 간 1초)·브라우저 UA 명시.

사용:
  python3 scripts/crawl_jeju_churches.py            # 전체 실행
  python3 scripts/crawl_jeju_churches.py --dry-run  # Stage 1만(페이지/링크 수집)
"""
import json, re, sys, time, html, os
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

BASE = "https://jeju.kuc.or.kr"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(HERE, "data", "원문기사", "제주대회사이트")
OUT_DIR = os.path.join(HERE, "data", "crawl")

# 제주대회 11개 교회(재림마을 주소록 기준). 알려진 자체 홈페이지가 있으면 seed로.
CHURCHES = [
    ("성산교회", None),
    ("표선교회", None),
    ("지도자훈련원교회", None),
    ("서귀포교회", "https://cafe.naver.com/kleim"),  # 주소록에 표기된 유일한 자체 사이트(네이버 카페)
    ("신서귀포교회", None),
    ("모슬포교회", None),
    ("한림교회", None),
    ("곽지교회", None),
    ("제주국제교회", None),
    ("제주중앙교회", None),
    ("함덕교회", None),
]
YEAR_RE = re.compile(r'1[89]\d\d\s*년')
FOUND_KEYWORDS = ("설립", "창립", "개척", "헌당", "시작", "연혁")


def fetch(url, timeout=25):
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=timeout) as r:
            raw = r.read()
        for enc in ("utf-8", "euc-kr", "cp949"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "ignore")
    except (URLError, HTTPError, Exception) as e:  # noqa
        print(f"   ! fetch 실패: {url} ({e})")
        return None


def strip_html(s):
    s = re.sub(r'(?is)<(script|style).*?</\1>', ' ', s)
    s = re.sub(r'<[^>]+>', ' ', s)
    return html.unescape(re.sub(r'\s+', ' ', s)).strip()


def stage1_wp_pages():
    """WP REST 정적 페이지 수집 + 외부 교회 URL 추출."""
    print("== Stage 1: WP REST pages ==")
    url = f"{BASE}/wp-json/wp/v2/pages?per_page=100&_fields=id,slug,title,link,content"
    txt = fetch(url)
    church_urls, all_text = {}, ""
    if not txt:
        return church_urls, all_text
    pages = json.loads(txt)
    os.makedirs(RAW_DIR, exist_ok=True)
    for p in pages:
        title = html.unescape(p.get("title", {}).get("rendered", ""))
        body = strip_html(p.get("content", {}).get("rendered", ""))
        all_text += f"\n\n# {title}\n{body}"
        if len(body) > 40:  # 알맹이 있는 페이지만 보관
            fn = os.path.join(RAW_DIR, f"{p['slug']}.txt")
            with open(fn, "w") as f:
                f.write(f"TITLE: {title}\nURL: {p.get('link')}\n{'='*50}\n{body}")
        # 외부(개별 교회) 홈페이지 링크 후보
        for m in re.finditer(r'https?://[^\s"\'<)]+', p.get("content", {}).get("rendered", "")):
            u = m.group(0)
            if not re.search(r'(jeju\.kuc|kuc\.or|adventist\.|wordpress|mangboard|w\.org|youtube|facebook|instagram)', u):
                church_urls.setdefault(u, "wp-page")
    print(f"   페이지 {len(pages)}건 수집, 알맹이 페이지 저장 완료")
    print(f"   설립연도(19xx년) 발견: {sorted(set(YEAR_RE.findall(all_text)))}")
    print(f"   외부 교회 URL 후보: {list(church_urls) or '없음'}")
    return church_urls, all_text


def scan_history(name, url):
    """개별 교회 홈페이지에서 연혁/설립연도 추출 시도."""
    txt = fetch(url)
    if not txt:
        return {"교회": name, "설립연도": "미발견", "근거": "사이트 접근 실패/없음", "출처": url}
    body = strip_html(txt)
    years = YEAR_RE.findall(body)
    has_kw = [k for k in FOUND_KEYWORDS if k in body]
    if years and has_kw:
        # 연도 주변 문장 근거
        m = re.search(r'[^.。]{0,60}1[89]\d\d\s*년[^.。]{0,60}', body)
        return {"교회": name, "설립연도": sorted(set(years))[0], "근거": (m.group(0).strip() if m else "")[:140], "출처": url}
    return {"교회": name, "설립연도": "미발견", "근거": f"연혁/연도 미게재(키워드 {has_kw or '없음'})", "출처": url}


def main():
    dry = "--dry-run" in sys.argv
    os.makedirs(OUT_DIR, exist_ok=True)
    church_urls, _ = stage1_wp_pages()

    # seed 홈페이지(주소록) 합치기
    seeds = {u: f"seed:{n}" for n, u in CHURCHES if u}
    for u, tag in seeds.items():
        church_urls.setdefault(u, tag)
    with open(os.path.join(OUT_DIR, "제주대회_교회링크.json"), "w") as f:
        json.dump(church_urls, f, ensure_ascii=False, indent=2)

    if dry:
        print("\n[--dry-run] Stage 1 종료. 교회링크:", church_urls or "없음")
        return

    print("\n== Stage 2: 개별 교회 홈페이지 연혁 추출 ==")
    results = []
    for name, url in CHURCHES:
        if not url:
            results.append({"교회": name, "설립연도": "미발견",
                            "근거": "제주대회 사이트에 자체 홈페이지 링크 없음", "출처": ""})
            continue
        print(f"   - {name}: {url}")
        results.append(scan_history(name, url))
        time.sleep(1)  # 저속

    with open(os.path.join(OUT_DIR, "연혁수집결과.json"), "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n===== 결과 요약 =====")
    print(f"{'교회':<14}{'설립연도':<10}근거")
    for r in results:
        print(f"{r['교회']:<14}{r['설립연도']:<10}{r['근거'][:60]}")
    found = [r for r in results if r["설립연도"] != "미발견"]
    print(f"\n설립연도 확보: {len(found)}/{len(results)}건")


if __name__ == "__main__":
    main()
