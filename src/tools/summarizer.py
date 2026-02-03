# summarize_unstructured_elements.py
import os
import time
from dataclasses import dataclass
from typing import List, Optional

from openai import OpenAI, BadRequestError
import tiktoken

from unstructured.documents.elements import Element, Text, Title, NarrativeText, ListItem, Table

@dataclass
class SummaryResult:
    summary: str
    rounds: int
    steps: List[str]  # intermediate summaries

def _with_retries(fn):
    def wrapped(*args, **kwargs):
        delay = 1.0
        for attempt in range(3):
            try:
                return fn(*args, **kwargs)
            except Exception:
                if attempt == 3 - 1:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 8)
    return wrapped

class Summarizer():
    """
    Summarizer configuration class.
    Contains model settings and token limits.
    """
    def __init__(self, apikey, model: str = "gpt-4.1-nano-2025-04-14", chunk_tokens: int = 4000, target_summary_tokens: int = 2000,
                 overlap_elems: int = 2, temperature: float = 0.2, max_rounds: int = 6, optional_prompt: Optional[str] = ''):
        self.model = model
        self.chunk_tokens = chunk_tokens
        self.target_summary_tokens = target_summary_tokens
        self.overlap_elems = overlap_elems
        self.temperature = temperature
        self.max_rounds = max_rounds
        self.client = OpenAI(api_key=apikey)
        self.ENC = self.get_encoding()
        self.optional_prompt = optional_prompt

    # =========================
    # Tokenization
    # =========================
    def get_encoding(self):
        try:
            return tiktoken.encoding_for_model(self.model)
        except Exception:
            return tiktoken.get_encoding("cl100k_base")

    def tok_count(self, text: str) -> int:
        return len(self.ENC.encode(text or ""))

    # =========================
    # Element rendering
    # =========================
    @staticmethod
    def safe_text(el: Element) -> str:
        return (getattr(el, "text", None) or "").strip()

    @staticmethod
    def render_element(el: Element) -> str:
        if isinstance(el, Title):
            return f"[TITLE] {Summarizer.safe_text(el)}"
        if isinstance(el, NarrativeText):
            return f"[NARRATIVE] {Summarizer.safe_text(el)}"
        if isinstance(el, ListItem):
            return f"[LIST] - {Summarizer.safe_text(el)}"
        if isinstance(el, Table):
            return f"[TABLE] {Summarizer.safe_text(el)}"
        # default: plain Text or unknown subclass
        return f"[TEXT] {Summarizer.safe_text(el)}"

    def render_elements(self, elements: List[List[Element]]) -> List[str]:
        rendered_elements = []
        # List of elements should chunked by 5 elements with 2 overlap
        for el in elements: # type: List[Element]
            rendered = [Summarizer.render_element(e) for e in el]
            # join rendered elements into a single string
            rendered = [r for r in rendered if r.strip()]  # filter out empty strings
            if not rendered:
                continue
            joined_text = "\n".join(rendered)
            # append to lists
            rendered_elements.append(joined_text)

        return rendered_elements

    def _hard_split_by_tokens_with_sep(self, text: str, max_tokens: int) -> List[str]:
        # seperate text into chunks of max_tokens, preserving element boundaries
        ids = self.ENC.encode(text)
        out = []
        k = 0
        while k < len(ids):
            if k + max_tokens >= len(ids):
                out.append(self.ENC.decode(ids[k:]))
                break
            # find the last line(.\n or \n) change before max_tokens
            last_space = k + max_tokens
            while last_space > k and ids[last_space] not in (self.ENC.encode("\n\n") + self.ENC.encode(".\n\n")):
                last_space -= 1
            if last_space <= k:  # no space found, just split at max_tokens
                last_space = k + max_tokens
            # append the chunk
            out.append(self.ENC.decode(ids[k:last_space]))
            k = last_space
        return out

    # =========================
    # Chunking by element boundaries
    # =========================
    def chunk_elements(self,
        elements: List[str],
    ) -> List[str]:
        """
        Build chunks that fit within token budget, never splitting an element.
        Uses element overlap instead of token overlap to preserve structure.
        """
        max_tokens = self.chunk_tokens
        overlap_elems = self.overlap_elems
        length_elements = [self.tok_count(el) for el in elements]

        chunks: List[str] = []
        cur: List[str] = []
        cur_tokens = 0
        for i, (r, t) in enumerate(zip(elements, length_elements)):
            # group 5 elements into 1 text while overlap 2 elements.
            # if single element is too big, do not group it.
            if t > max_tokens:
                # flush current
                if cur:
                    chunks.append("\n\n".join(cur))
                    cur, cur_tokens = [], 0
                # split the big r by tokens
                chunks.append(r)
                continue

            if cur_tokens + t > max_tokens and cur:
                # flush with overlap
                chunks.append("\n\n".join(cur))
                if overlap_elems > 0:
                    cur = cur[-overlap_elems:]
                    cur_tokens = sum(self.tok_count(x) for x in cur)
                else:
                    cur, cur_tokens = [], 0

            cur.append(r)
            cur_tokens += t

        if cur:
            chunks.append("\n\n".join(cur))

        return [c for c in chunks if c.strip()]

    @_with_retries
    def summarize_once(self, text: str, target_summary_tokens:Optional[int]=None) -> str:
        """
        Summarize a single chunk.
        The prompt explains the element tags so the model knows how to treat tables vs prose.
        """
        max_output_tokens = target_summary_tokens or self.target_summary_tokens
        instructions = ("당신은 원문 의미와 흐름을 충실히 반영하는 정확한 요약자입니다. "
                "입력은 [TITLE], [TEXT], [NARRATIVE], [LIST], [TABLE](HTML 또는 텍스트)로 태그된 줄로 구성됩니다. "
                "원문의 논리 구조와 맥락을 해치지 않으면서 핵심 포인트를 간결하게 추출하십시오. "
                "모든 내용은 원문 흐름 순서에 맞게 요약하여, 독자가 맥락을 잃지 않도록 하십시오. "
                "[TABLE]은 셀 내용을 그대로 복사하지 말고, 데이터가 보여주는 주요 결론(지표, 추세, 극값, 변화량, 주목할 비교점)을 설명하십시오. "
                "최근 시점의 변화, 최신 수치, 추세 전환점에는 가중치를 두고 명확히 드러내십시오. "
                "중요한 이름, 날짜, 숫자는 반드시 보존하고, 의미 왜곡 없이 전달하십시오. "
                "문맥 이해에 도움이 되면 불릿 포인트를 사용하되, 그렇지 않으면 간결하고 명확한 문장을 사용하십시오. "
                "반복된 내용은 제거하고, 더 이상 요약할 것이 없을 경우 핵심만 남기십시오. "
                "특히 시계열 데이터나 진행 과정이 있는 경우, 과거 대비 변화 방향과 그 의미를 반드시 언급하십시오.\n") + self.optional_prompt
        try:
            resp = self.client.responses.create(
            model=self.model,
            temperature=self.temperature,
            max_output_tokens=max_output_tokens,
            instructions=instructions,
            input=f"{text}",
            )
        except BadRequestError:
            resp = self.client.responses.create(
            model=self.model,
            max_output_tokens=max_output_tokens,
            instructions=instructions,
            input=f"{text}",
            )
        return resp.output_text.strip()

    # =========================
    # Recursive summarization
    # =========================
    def run(self,
        elements: List[List[Element]],
        target_summary_tokens: Optional[int] = None,
    ) -> SummaryResult:
        """
        Recursive_summarize_elements
        Repeatedly:
          1) Pack elements into token-bounded chunks (by element boundaries)
          2) Summarize each chunk
          3) Concatenate summaries and loop
        Stops when one summary remains or token budget small enough for a final pass.
        """
        target_summary_tokens = target_summary_tokens or self.target_summary_tokens
        chunk_tokens = self.chunk_tokens
        max_rounds = self.max_rounds
        steps: List[str] = []
        rounds = 0

        rendered_elements = self.render_elements(elements)
        # First pass: element-aware chunks
        chunks = self.chunk_elements(rendered_elements)

        while rounds < max_rounds:
            print(f"Round {rounds + 1}: {len(chunks)} chunks, {sum(self.tok_count(c) for c in chunks)} tokens")
            rounds += 1

            # If we already have a single chunk, just summarize it and finish
            if len(chunks) == 1 and self.tok_count(chunks[0]) <= chunk_tokens:
                final = self.summarize_once(chunks[0], target_summary_tokens)
                steps.append(final)
                return SummaryResult(summary=final, rounds=rounds, steps=steps)
            elif len(chunks) == 1 and self.tok_count(chunks[0]) > chunk_tokens:
                # If the first chunk is too big, split it by tokens
                chunks = self._hard_split_by_tokens_with_sep(chunks[0], chunk_tokens)

            # Summarize each chunk
            chunk_summaries = [self.summarize_once(c) for c in chunks]
            combined = "\n\n".join(chunk_summaries)
            steps.append(combined)

            # If combined fits, polish once and return; else, treat the combined as a new single chunk
            if self.tok_count(combined) <= chunk_tokens:
                final = self.summarize_once(combined, target_summary_tokens)
                steps.append(final)
                return SummaryResult(summary=final, rounds=rounds + 1, steps=steps)

            chunks = self._hard_split_by_tokens_with_sep(combined, chunk_tokens)  # continue compressing

        # Fallback: return last combined
        return SummaryResult(summary="\n\n".join(chunks), rounds=rounds, steps=steps)

    def run_text(self,
                 text: str,
                 target_summary_tokens:Optional[int]=None
                 ) -> SummaryResult:
        """
        Run summarization on a single text input.
        This is a convenience method to avoid manual element partitioning.
        """
        elements = [Text(text=text)]
        return self.run([elements], target_summary_tokens=target_summary_tokens)

if __name__ == "__main__":
    """
    Example:
        from unstructured.partition.html import partition_html
        elements = partition_html(text=open("page.html","r",encoding="utf-8").read(), xml_keep_tags=True)
        result = run(elements)
        print(result.summary)
    """
    print("Import this module and call run(elements).")
