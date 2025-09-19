# -*- coding: utf-8 -*-
"""
PDF → (chapter/page images) → GPT interpretation (markdown)
----------------------------------------------------------
Usage:
  from pdf_parser import PDFParser
  parser = PDFParser(api_key='your_api_key', model='gpt-4o-mini')
  parser.parse_pdf('document.pdf', 'output_dir')
"""

import configparser
import os
import io
import re
import base64
import argparse
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

import fitz  # PyMuPDF
from pdf2image import convert_from_path
from PIL import Image
from pydantic import BaseModel

# OpenAI API
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


@dataclass
class Chapter:
    title: str
    start_page: int
    end_page: int = None
    pages: List[int] = field(default_factory=list)

class OCRdata(BaseModel):
    text: str
    reasoning: str

class PDFParser:
    """PDF 파서 클래스 - PDF를 챕터/페이지 이미지로 변환하고 GPT를 통해 마크다운으로 해석"""

    CHAPTER_REGEXES = [
        # Korean common patterns
        r"^제?\s*[0-9一二三四五六七八九十ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*장\b",
        r"^\s*[0-9]+\s*장\b",
        r"^\s*부록\b",
        r"^\s*요약\b",
        r"^\s*목차\b",
        # English common patterns
        r"^\s*chapter\s+[0-9ivx]+\b",
        r"^\s*appendix\b",
        r"^\s*contents\b",
        r"^\s*summary\b",
        # Numeric heading styles
        r"^\s*[0-9]+\.\s+[^\n]{1,80}$",
        r"^\s*[Ⅰ-Ⅹ]+\.\s+[^\n]{1,80}$",
    ]

    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini", dpi: int = 200, max_width: int = 1280):
        """
        PDF 파서 초기화

        Args:
            api_key: OpenAI API 키 (None이면 config.ini에서 읽음)
            model: 사용할 GPT 모델
            dpi: 이미지 렌더링 DPI
            max_width: 이미지 최대 너비
        """
        if api_key is None:
            config_file = "D:/config.ini"
            config = configparser.ConfigParser()
            config.read(config_file)
            api_key = config.get("openai", "API_KEY")

        self.api_key = api_key
        self.model = model
        self.dpi = dpi
        self.max_width = max_width if max_width > 0 else None
        self.chapter_regexes = [re.compile(pat, re.IGNORECASE) for pat in self.CHAPTER_REGEXES]

    def ensure_dir(self, path: str, remove_if_exists: bool = False):
        """디렉토리 생성"""
        if remove_if_exists and os.path.exists(path):
            import shutil
            shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)

    def guess_chapters(self, doc) -> List[Chapter]:
        """목차 감지 - PyMuPDF 북마크 또는 정규식 휴리스틱 사용"""
        chapters: List[Chapter] = []

        # 1) Table of Contents via PyMuPDF
        toc = []
        try:
            toc = doc.get_toc(simple=True) or []
        except Exception:
            toc = []

        flat = []
        for item in toc:
            if not item or len(item) < 3:
                continue
            level, title, page = item[0], str(item[1]).strip(), int(item[2])
            page_index = max(0, page - 1)
            flat.append((title, page_index, level))

        if flat:
            # Use top-level entries as chapters
            level_threshold = min(lvl for _, _, lvl in flat)
            for title, pnum, lvl in flat:
                if lvl == level_threshold:
                    chapters.append(Chapter(title=title, start_page=pnum))

            # Close chapter ranges
            for i in range(len(chapters)):
                if i < len(chapters) - 1:
                    chapters[i].end_page = chapters[i + 1].start_page - 1
                else:
                    chapters[i].end_page = doc.page_count - 1

            for ch in chapters:
                ch.pages = list(range(ch.start_page, ch.end_page + 1))
            return chapters

        # 2) Heuristic via per-page text and regexes
        per_page_texts: List[str] = []
        for i in range(doc.page_count):
            try:
                page = doc.load_page(i)
                txt = page.get_text() or ""
            except Exception:
                txt = ""
            txt = re.sub(r"[ \t]+", " ", txt).strip()
            per_page_texts.append(txt)

        candidate_starts: List[Tuple[int, str]] = []
        for i, txt in enumerate(per_page_texts):
            head = "\n".join(txt.splitlines()[:12])
            for line in head.splitlines():
                s = line.strip()
                if not s:
                    continue
                for pat in self.chapter_regexes:
                    if pat.search(s):
                        candidate_starts.append((i, s))
                        break
                else:
                    if len(s) <= 80 and s.upper() == s and re.search(r"[A-Z가-힣0-9]", s):
                        candidate_starts.append((i, s))
                        break

        # Deduplicate close hits
        filtered: List[Tuple[int, str]] = []
        seen_pages = set()
        for p, t in sorted(candidate_starts, key=lambda x: x[0]):
            if any(abs(p - sp) <= 1 for sp in seen_pages):
                continue
            seen_pages.add(p)
            filtered.append((p, t))

        if not filtered:
            chapters = [
                Chapter(title="Document", start_page=0, end_page=doc.page_count - 1, pages=list(range(doc.page_count)))]
            return chapters

        for p, t in filtered:
            title = re.sub(r"\s+", " ", t).strip()
            chapters.append(Chapter(title=title, start_page=p))

        for i in range(len(chapters)):
            if i < len(chapters) - 1:
                chapters[i].end_page = chapters[i + 1].start_page - 1
            else:
                chapters[i].end_page = doc.page_count - 1

        for ch in chapters:
            ch.pages = list(range(ch.start_page, ch.end_page + 1))

        return chapters

    def pil_to_base64(self, img: Image.Image, fmt: str = "PNG") -> str:
        """PIL 이미지를 base64 문자열로 변환"""
        if self.max_width and img.width > self.max_width:
            ratio = self.max_width / float(img.width)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format=fmt, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/{fmt.lower()};base64,{b64}"

    def render_pages_to_images(self, pdf_path: str, page_numbers: List[int]) -> List[Image.Image]:
        """특정 페이지들을 PIL 이미지로 렌더링"""
        if not page_numbers:
            return []

        first_page = min(page_numbers) + 1
        last_page = max(page_numbers) + 1
        all_imgs = convert_from_path(pdf_path, dpi=self.dpi, first_page=first_page, last_page=last_page, poppler_path='C:/poppler/Library/bin')

        page_set = set(page_numbers)
        imgs = []
        for idx, pil in enumerate(all_imgs, start=first_page - 1):
            if idx in page_set:
                imgs.append(pil.convert("RGB"))
        return imgs

    def build_prompt_chapter(self, chapter_title: str) -> str:
        """챕터 분석용 프롬프트 생성"""
        return f"""
        당신은 전문 리포트/IR 문서를 해석하는 분석가입니다.
        다음 이미지는 문서의 한 '장(챕터)'를 구성하는 페이지들입니다.
        다음 지침에 따라 **한국어**로 해석본을 작성하세요.
        
        [목표]
        - 핵심 개요 → 불릿
        - 주요 수치/지표 → **마크다운 테이블**(표준화된 컬럼명 활용)
        - 그래프/표가 암시하는 인사이트 → 2~4문장
        - 주석/주의사항(출처, 단위, 시점)
        
        [출력 형식]
        ## 1) 핵심 요약
        - (요점 3~5개)
        
        ## 2) 주요 수치 표
        - 필요 시 여러 표를 사용해도 좋음
        - 가능한 컬럼 예: 항목 | 기간 | 값 | 단위 | 전년동기대비(%) | 전분기대비(%)
        | 항목 | 기간 | 값 | 단위 | 전년동기대비(%) | 전분기대비(%) |
        |---|---:|---:|---|---:|---:|
        | 예시 | 2025 Q2 | 123 | 억원 | 5.2 | 1.1 |
        
        ## 3) 그래프/도표 해석
        - 수치 추세/전환점/리스크 등 2~4문장
        
        ## 4) 용어 및 주석
        - 약어 해설, 출처, 단위(억원/백만원/%) 명시 (억원은 1E8원, 백만원은 1E6원에 해당)
        
        [원칙]
        - 추정/해석은 근거를 간단히 표기
        - 불명확한 부분은 '추정'으로 명시
        """.strip()

    def build_prompt_page(self, page_number: int, rough_text: str) -> str:
        """페이지 분석용 프롬프트 생성"""
        return f"""
        당신은 전문 리포트/IR 문서를 페이지 단위로 해석하는 분석가입니다.
        PDF에서 텍스트를 추출했으나 레이아웃이 엉망입니다. 이미지 기반 해석이 필요합니다.
        아래 이미지는 문서의 단일 페이지입니다. **한국어**로 간결하지만 핵심을 놓치지 않는 요약을 작성하세요.
        
        [추출 텍스트]
        {rough_text}
        
        [출력 형식]
        # p{page_number:03d} 요약
        
        ## 1) 핵심 요약
        - (요점 3~5개)
        
        ## 2) 주요 수치 표
        - 필요 시 여러 표를 사용해도 좋음
        - 가능한 컬럼 예: 항목 | 기간 | 값 | 단위 | 전년동기대비(%) | 전분기대비(%)
        | 항목 | 기간 | 값 | 단위 | 전년동기대비(%) | 전분기대비(%) |
        |---|---:|---:|---|---:|---:|
        | 예시 | 2025 Q2 | 123 | 억원 | 5.2 | 1.1 |
        
        ## 3) 그래프/도표 해석
        - 수치 추세/전환점/리스크
        
        ## 4) 용어 및 주석
        - 약어 해설, 출처, 단위(억원/백만원/%) 명시 (억원은 1E8원, 백만원은 1E6원에 해당)
        
        [원칙]
        - 추정/해석은 근거를 간단히 표기
        - 불명확한 부분은 '추정'으로 명시
        """.strip()

    def chat_with_gpt(self, images_b64: List[str], prompt_text: str, temperature: float = 0.2,
                      max_tokens: int = 1200, ocr_mode: bool = False) -> str:
        """GPT API 호출"""
        if OpenAI is None:
            raise RuntimeError("openai package not available. Please `pip install openai` and try again.")

        client = OpenAI(api_key=self.api_key)
        content = [{"type": "text", "text": prompt_text}]
        for b64 in images_b64:
            content.append({"type": "image_url", "image_url": {"url": b64}})

        if ocr_mode:
            resp = client.chat.completions.parse(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                response_format=OCRdata,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.parsed.text.strip()
        else:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()

    def save_markdown(self, path: str, text: str):
        """마크다운 파일 저장"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def sanitize_title(self, s: str) -> str:
        """파일명용 제목 정리"""
        s = re.sub(r"[^\w가-힣\- _\.\(\)]", "_", s)
        s = re.sub(r"\s+", "_", s).strip("_")
        return s[:80] if len(s) > 80 else s

    def parse_pdf(self, pdf_path: str,
                  out_dir: str,
                  generate_chapter_summaries: bool = False,
                  generate_page_summaries: bool = True,
                  max_images_per_chapter: int = 8,
                  start_page: int = None,
                  end_page: int = None,
                  max_pages: int = 0,
                  dry_run: bool = False):
        """
        PDF 파싱 메인 메소드

        Args:
            pdf_path: PDF 파일 경로
            out_dir: 출력 디렉토리
            generate_chapter_summaries: 챕터별 요약 생성 여부
            generate_page_summaries: 페이지별 요약 생성 여부
            max_images_per_chapter: 챕터당 최대 이미지 수
            max_pages: 페이지별 요약 최대 페이지 수 (0=전체)
            dry_run: 실제 GPT 호출 없이 테스트
        """
        # 출력 디렉토리 설정
        self.ensure_dir(out_dir)
        img_root = os.path.join(out_dir, "images")
        md_root = os.path.join(out_dir, "markdown")
        self.ensure_dir(img_root, True)
        self.ensure_dir(md_root, True)

        # PDF 열기
        doc = fitz.open(pdf_path)
        total_pages = doc.page_count

        if start_page:
            start_page -= 1
        if end_page:
            end_page -= 1

        # 챕터별 요약 생성
        if generate_chapter_summaries:
            # 챕터 감지
            chapters = self.guess_chapters(doc)
            if not chapters:
                chapters = [
                    Chapter(title="Document", start_page=0, end_page=total_pages - 1, pages=list(range(total_pages)))]

            # TOC 저장
            toc_lines = ["# Chapter Detection", "", "| # | Title | Start | End | Pages |", "|---:|---|---:|---:|---|"]
            for i, ch in enumerate(chapters, 1):
                toc_lines.append(f"| {i} | {ch.title} | {ch.start_page + 1} | {ch.end_page + 1} | {len(ch.pages)} |")
            self.save_markdown(os.path.join(out_dir, "README.md"), "\n".join(toc_lines))

            print(f"Detected {len(chapters)} chapter(s).")

            self._generate_chapter_summaries(pdf_path, chapters, img_root, md_root, max_images_per_chapter, dry_run)

        # 페이지별 요약 생성
        if generate_page_summaries:
            self._generate_page_summaries(pdf_path, doc, img_root, md_root, total_pages, start_page, end_page, max_pages, dry_run)

        doc.close()

        '''self.consolidate_markdown(
            out_dir=out_dir,
            include_chapters=generate_chapter_summaries,
            include_pages=generate_page_summaries,
            output_filename="summary.md"
        )'''

        print("Done.")

    def _generate_chapter_summaries(self, pdf_path: str, chapters: List[Chapter], img_root: str, md_root: str,
                                    max_images_per_chapter: int, dry_run: bool):
        """챕터별 요약 생성"""
        print("Generating chapter-level summaries...")
        for idx, ch in enumerate(chapters, 1):
            ch_dir = os.path.join(img_root, f"{idx:02d}_{self.sanitize_title(ch.title) or 'Chapter'}")
            self.ensure_dir(ch_dir)
            print(f"[Chapter {idx}/{len(chapters)}] {ch.title} (pages {ch.start_page + 1}-{ch.end_page + 1})")

            # 이미지 렌더링
            imgs = self.render_pages_to_images(pdf_path, ch.pages)
            image_paths = []
            for j, img in enumerate(imgs, 1):
                out_path = os.path.join(ch_dir, f"p{ch.pages[j - 1] + 1:03d}.png")
                save_img = img
                if self.max_width and img.width > self.max_width:
                    ratio = self.max_width / float(img.width)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    save_img = img.resize(new_size, Image.LANCZOS)
                save_img.save(out_path, format="PNG", optimize=True)
                image_paths.append(out_path)

            if dry_run:
                print("  - Dry run: skipped GPT interpretation for chapter.")
                continue

            # GPT 분석
            limited = image_paths[:max_images_per_chapter]
            images_b64 = []
            for p in limited:
                pil = Image.open(p).convert("RGB")
                images_b64.append(self.pil_to_base64(pil, fmt="PNG"))

            prompt_text = self.build_prompt_chapter(ch.title)

            try:
                md = self.chat_with_gpt(images_b64=images_b64, prompt_text=prompt_text, max_tokens=1200)
            except Exception as e:
                md = f"# {ch.title}\n\n> GPT 호출 중 오류 발생: {e}\n"

            md_path = os.path.join(md_root, f"{idx:02d}_{self.sanitize_title(ch.title) or 'Chapter'}.md")
            self.save_markdown(md_path, md)
            print(f"  - Saved: {md_path}")

    def _generate_page_summaries(self,
                                 pdf_path: str,
                                 doc,
                                 img_root: str,
                                 md_root: str,
                                 total_pages: int,
                                 start_page: int,
                                 end_page: int,
                                 max_pages: int,
                                 dry_run: bool):
        """페이지별 요약 생성"""
        print("Generating page-level summaries...")
        # 처리할 페이지 결정
        page_indices = list(range(total_pages))[start_page:end_page]
        if max_pages and max_pages > 0:
            page_indices = page_indices[:max_pages]

        # 이미지 렌더링
        imgs = self.render_pages_to_images(pdf_path, page_indices)
        img_map = dict(zip(page_indices, imgs))

        for pidx in page_indices:
            page_no_human = pidx + 1
            img = img_map[pidx]
            out_img_path = os.path.join(img_root, f"p{page_no_human:03d}.png")

            save_img = img
            if self.max_width and img.width > self.max_width:
                ratio = self.max_width / float(img.width)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                save_img = img.resize(new_size, Image.LANCZOS)
            save_img.save(out_img_path, format="PNG", optimize=True)

            if dry_run:
                print(f"  - [Dry] p{page_no_human:03d}")
                continue

            # GPT 분석
            pil = Image.open(out_img_path).convert("RGB")
            b64 = self.pil_to_base64(pil, fmt="PNG")
            rough_text = doc.load_page(pidx).get_text("text") or ""
            rough_text = re.sub(r"\s+", " ", rough_text).strip()

            if len(rough_text) < 25:
                # 이미지로만 구성되었을 가능성을 염두하여, GPT 호출
                rough_text = self.chat_with_gpt(images_b64=[b64],
                    prompt_text="""이미지에 있는 텍스트를 음역해 주세요.
                     텍스트가 잘 읽히지 않으면, 이미지를 먼저 보정한 후에 텍스트를 추측해 보세요.
                     이미지의 대비를 높이거나, 회전시키거나, 기울기 또는 원근 보정을 적용하여 더 쉽게 읽을 수도 있습니다.
                     단어의 의미를 통해 추측을 수정하기 전에, 이미지에 있는 글자들을 최대한 정확하게 읽었는지 확인하세요."""
                                                )
                if len(rough_text) < 25:
                    continue

            prompt_text = self.build_prompt_page(page_no_human, rough_text)

            try:
                md = self.chat_with_gpt(images_b64=[b64], prompt_text=prompt_text, max_tokens=700)
            except Exception as e:
                md = f"# p{page_no_human:03d} 요약\n\n> GPT 호출 중 오류 발생: {e}\n"

            md_path = os.path.join(md_root, f"p{page_no_human:03d}.md")
            self.save_markdown(md_path, md)
            print(f"  - Saved page summary: {md_path}")

    def consolidate_markdown(self, out_dir: str,
                             include_chapters: bool = True,
                             include_pages: bool = True,
                             output_filename: str = "consolidated_summary.md") -> str:
        """
        생성된 마크다운 파일들을 하나의 통합 문서로 취합

        Args:
            out_dir: 출력 디렉토리 (parse_pdf에서 사용한 동일한 디렉토리)
            include_chapters: 챕터별 요약 포함 여부
            include_pages: 페이지별 요약 포함 여부
            output_filename: 통합 파일명

        Returns:
            str: 생성된 통합 파일의 경로
        """
        import glob
        from datetime import datetime

        consolidated_content = []

        # 헤더 추가
        consolidated_content.append("# PDF 분석 통합 보고서")
        consolidated_content.append(f"생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        consolidated_content.append("")

        # 목차 읽기 (README.md가 있다면)
        readme_path = os.path.join(out_dir, "README.md")
        if os.path.exists(readme_path):
            with open(readme_path, "r", encoding="utf-8") as f:
                toc_content = f.read()
            consolidated_content.append("## 문서 구조")
            consolidated_content.append(toc_content)
            consolidated_content.append("")

        # 챕터별 요약 통합
        if include_chapters:
            md_root = os.path.join(out_dir, "markdown")
            if os.path.exists(md_root):
                consolidated_content.append("# 챕터별 분석")
                consolidated_content.append("")

                chapter_files = sorted(glob.glob(os.path.join(md_root, "*.md")))
                for i, file_path in enumerate(chapter_files, 1):
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()

                    # 파일명에서 챕터 정보 추출
                    filename = os.path.basename(file_path)
                    chapter_name = filename.replace(".md", "").replace("_", " ")

                    consolidated_content.append(f"## 챕터 {i}: {chapter_name}")
                    consolidated_content.append("")
                    consolidated_content.append(content)
                    consolidated_content.append("")
                    consolidated_content.append("---")
                    consolidated_content.append("")

        # 페이지별 요약 통합
        if include_pages:
            md_pages_root = os.path.join(out_dir, "markdown_pages")
            if os.path.exists(md_pages_root):
                consolidated_content.append("# 페이지별 상세 분석")
                consolidated_content.append("")

                page_files = sorted(glob.glob(os.path.join(md_pages_root, "*.md")))

                # 페이지를 그룹으로 나누어 표시 (10페이지씩)
                pages_per_group = 10
                for group_start in range(0, len(page_files), pages_per_group):
                    group_end = min(group_start + pages_per_group, len(page_files))
                    group_files = page_files[group_start:group_end]

                    # 그룹 헤더
                    start_page = group_start + 1
                    end_page = group_end
                    consolidated_content.append(f"## 페이지 {start_page}-{end_page}")
                    consolidated_content.append("")

                    for file_path in group_files:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read().strip()

                        consolidated_content.append(content)
                        consolidated_content.append("")

                    consolidated_content.append("---")
                    consolidated_content.append("")

        # 통합 파일 저장
        consolidated_path = os.path.join(out_dir, output_filename)
        final_content = "\n".join(consolidated_content)
        self.save_markdown(consolidated_path, final_content)

        print(f"통합 마크다운 파일 생성 완료: {consolidated_path}")
        return consolidated_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDF → chapter/page images → GPT interpretation (markdown).")
    parser.add_argument("--pdf", default='A381970_IR.pdf', help="Path to PDF file")
    parser.add_argument("--out", default='./out', help="Output directory")
    parser.add_argument("--model", default="gpt-4o-mini", help="OpenAI model")
    parser.add_argument("--dpi", type=int, default=200, help="Rendering DPI")
    parser.add_argument("--max-width", type=int, default=1280, help="Max image width")
    parser.add_argument("--max-images-per-chapter", type=int, default=8, help="Max images per chapter")
    parser.add_argument("--dry-run", action="store_true", help="Skip GPT calls")
    parser.add_argument("--per-page-summaries", default=True, action="store_true", help="Generate page summaries")
    parser.add_argument("--no-chapter-summaries", default=True, action="store_true", help="Skip chapter summaries")
    parser.add_argument("--max-pages", type=int, default=4, help="Max pages for page summaries")

    args = parser.parse_args()

    pdf_parser = PDFParser(
        model=args.model,
        dpi=args.dpi,
        max_width=args.max_width
    )

    pdf_parser.parse_pdf(
        pdf_path=args.pdf,
        out_dir=args.out,
        generate_chapter_summaries=not args.no_chapter_summaries,
        generate_page_summaries=args.per_page_summaries,
        max_images_per_chapter=args.max_images_per_chapter,
        start_page=12,
        end_page=26,
        max_pages=3,
        dry_run=args.dry_run
    )

    a = 1
