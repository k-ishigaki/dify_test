from collections.abc import Generator, Iterable
from typing import Any

import io
import json
import os
import re
import tempfile

import logging

from dify_plugin import Tool
from dify_plugin.config.logger_format import plugin_logger_handler
from dify_plugin.entities.tool import ToolInvokeMessage
from markitdown import MarkItDown


DELIM = "---DIFY-CHUNK---"
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)")


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if plugin_logger_handler not in logger.handlers:
    logger.addHandler(plugin_logger_handler)


def _split_table_row(line: str) -> list[str]:
    """Markdown の表行をセルごとのリストに分解する。"""
    stripped = line.strip()
    if not stripped:
        return []
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


_ALIGN_CELL_PATTERN = re.compile(r"^:?-{3,}:?$")


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 1


def _is_table_header(line: str) -> bool:
    return len(_split_table_row(line)) >= 2


def _is_alignment_line(line: str, expected_cols: int) -> bool:
    if not _is_table_row(line):
        return False
    cells = _split_table_row(line)
    if len(cells) != expected_cols:
        return False
    return all(_ALIGN_CELL_PATTERN.match(cell.replace(" ", "")) for cell in cells)


def _normalize_markdown_tables(md_text: str) -> str:
    """Markdown の表を JSON 行のコードブロックに正規化する。"""
    lines = md_text.splitlines()
    result: list[str] = []
    in_code_block = False
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            result.append(line)
            i += 1
            continue

        if not in_code_block and _is_table_row(line) and _is_table_header(line):
            header_cells = _split_table_row(line)
            if header_cells and i + 1 < len(lines) and _is_alignment_line(lines[i + 1], len(header_cells)):
                data_rows: list[list[str]] = []
                j = i + 2
                while j < len(lines):
                    candidate = lines[j]
                    if candidate.strip() == "":
                        break
                    if not _is_table_row(candidate):
                        break
                    row_cells = _split_table_row(candidate)
                    if len(row_cells) != len(header_cells):
                        break
                    data_rows.append(row_cells)
                    j += 1

                if data_rows:
                    result.append("```json")
                    for row in data_rows:
                        obj = {header_cells[idx]: row[idx] for idx in range(len(header_cells))}
                        result.append(json.dumps(obj, ensure_ascii=False))
                    result.append("```")
                    i = j
                    continue

        result.append(line)
        i += 1

    normalized = "\n".join(result)
    if md_text.endswith("\n"):
        normalized += "\n"
    return normalized


def _convert_to_markdown_bytes(in_bytes: bytes, filename_hint: str | None = None) -> str:
    """
    markitdown はパス文字列入力が安定しているため、一旦 temp に落としてから convert します。
    返り値は Markdown テキスト（str）。
    """
    suffix = ""
    if filename_hint and "." in filename_hint:
        suffix = os.path.splitext(filename_hint)[1]

    fd, tmp_in = tempfile.mkstemp(suffix=suffix or ".bin", prefix="kb_src_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(in_bytes)
        md = MarkItDown()
        res = md.convert(tmp_in)
        return res.markdown if hasattr(res, "text") else str(res)
    finally:
        try:
            os.remove(tmp_in)
        except OSError:
            pass


class DataPathTracker:
    """Track heading stack and format the current data-path marker."""

    def __init__(self) -> None:
        self._segments: list[str] = []

    def current_marker(self, first_line: str | None = None) -> str:
        """現在のスタックとチャンク先頭行を反映した data-path を返す。"""
        segments = self._segments[:]
        if first_line:
            match = HEADING_PATTERN.match(first_line)
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                segments = segments[: level - 1] + [title]

        def sanitize(text: str) -> str:
            return text.replace("\\", "\\\\").replace('"', '\\"').strip()

        joined = " > ".join(f'"{sanitize(segment)}"' for segment in segments)
        return f"{{ data-path = {joined} }}"

    def ingest_line(self, line: str) -> None:
        """行が見出しならスタックを更新する。"""
        match = HEADING_PATTERN.match(line)
        if not match:
            return
        level = len(match.group(1))
        title = match.group(2).strip()
        self._segments = self._segments[: level - 1] + [title]

def _split_and_prefix(lines: Iterable[str], max_chunk_length: int, split_max_level: int) -> Iterable[str]:
    """
    1パスで分割とマーカー付与を実施する。
    - チャンク先頭: data-path マーカーを独立行として出力する。
    - チャンク終端: 次チャンクが続く場合は最終行として `---DIFY-CHUNK---` を追加する。
    - 分割ポリシー: 見出し(<= split_max_level) > 空行 > 非インデント行 > 改行（長さ超過）
    - 長さ計算: チャンク1行目には data-path マーカー長も含めてカウントする。
    """

    tracker = DataPathTracker()

    lines_list = list(lines)
    total_lines = len(lines_list)

    chunk_lines: list[str] = []
    chunk_marker = ""
    chunk_content_chars = 0
    last_blank_idx = -1
    last_heading_idx = -1
    last_nonindent_idx = -1

    def emit_chunk(marker: str, lines_chunk: list[str], add_delimiter: bool) -> Iterable[str]:
        """チャンクを吐き出し、必要なら区切りマーカーも追加する。"""
        if not lines_chunk:
            return
        yield f"{marker}\n"
        for chunk_line in lines_chunk:
            yield chunk_line
            tracker.ingest_line(chunk_line)
        if add_delimiter:
            yield f"{DELIM}\n"

    def reset_chunk_state() -> None:
        nonlocal chunk_lines, chunk_marker, chunk_content_chars, last_blank_idx, last_heading_idx, last_nonindent_idx
        chunk_lines = []
        chunk_marker = ""
        chunk_content_chars = 0
        last_blank_idx = -1
        last_heading_idx = -1
        last_nonindent_idx = -1

    def recompute_chunk_metadata() -> None:
        nonlocal chunk_marker, chunk_content_chars, last_blank_idx, last_heading_idx, last_nonindent_idx
        chunk_content_chars = sum(len(entry) for entry in chunk_lines)
        if not chunk_lines:
            chunk_marker = ""
            last_blank_idx = -1
            last_heading_idx = -1
            last_nonindent_idx = -1
            return
        chunk_marker = tracker.current_marker(chunk_lines[0])
        last_blank_idx = -1
        last_heading_idx = -1
        last_nonindent_idx = -1
        for idx, buf_line in enumerate(chunk_lines):
            if buf_line.strip() == "":
                last_blank_idx = idx
                continue
            if idx > 0:
                heading = HEADING_PATTERN.match(buf_line)
                if heading and len(heading.group(1)) <= split_max_level:
                    last_heading_idx = idx
                if buf_line and not buf_line[0].isspace():
                    last_nonindent_idx = idx

    for idx, line in enumerate(lines_list):
        heading_match = HEADING_PATTERN.match(line)
        if chunk_lines and heading_match and len(heading_match.group(1)) <= split_max_level:
            # 見出しで区切る条件を満たしたら現在のチャンクを確定させる
            for out in emit_chunk(chunk_marker, chunk_lines, add_delimiter=True):
                yield out
            reset_chunk_state()

        if not chunk_lines:
            # 新しいチャンクの開始時点で data-path を決定する
            chunk_marker = tracker.current_marker(line)
            chunk_content_chars = 0
            last_blank_idx = -1
            last_heading_idx = -1
            last_nonindent_idx = -1

        chunk_lines.append(line)
        chunk_content_chars += len(line)
        idx_in_chunk = len(chunk_lines) - 1
        if line.strip() == "":
            last_blank_idx = idx_in_chunk
        elif idx_in_chunk > 0:
            if heading_match and len(heading_match.group(1)) <= split_max_level:
                last_heading_idx = idx_in_chunk
            if line and not line[0].isspace():
                last_nonindent_idx = idx_in_chunk

        is_last_line = idx == total_lines - 1

        while chunk_lines:
            chunk_length = len(chunk_marker) + 1 + chunk_content_chars
            if chunk_length < max_chunk_length:
                break
            # 最大長を超えたので見出し→空行→インデント無し行の優先順でチャンクを分割する
            if last_heading_idx > 0:
                cut_idx = last_heading_idx - 1
            elif last_blank_idx != -1:
                cut_idx = last_blank_idx
            elif last_nonindent_idx > 0:
                cut_idx = last_nonindent_idx - 1
            else:
                cut_idx = len(chunk_lines) - 1
            left_lines = chunk_lines[: cut_idx + 1]
            right_lines = chunk_lines[cut_idx + 1 :]
            add_delimiter = bool(right_lines) or not is_last_line
            for out in emit_chunk(chunk_marker, left_lines, add_delimiter=add_delimiter):
                yield out
            chunk_lines = right_lines
            recompute_chunk_metadata()

    if chunk_lines:
        # 最後のチャンクを出力
        for out in emit_chunk(chunk_marker, chunk_lines, add_delimiter=False):
            yield out


class KnowledgeBaseDocumentPreprocessorTool(Tool):
    """
    Input parameters:
      - input_file: File  (必須)  ※ tool_parameters["input_file"] は File モデル
      - max_chunk_length: int (必須)
      - split_max_level: int (任意, default=3)
    Output:
      - BLOB (bytes) : text/plain を返却。meta に mime/filename を付与。
    """
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        file_obj = tool_parameters["input_file"]          # File モデル（.blob で bytes 取得）
        max_chunk_length = int(tool_parameters.get("max_chunk_length", 8000))
        split_max_level = int(tool_parameters.get("split_max_level", 3))

        # 1) 入力 bytes を取得
        in_bytes: bytes = file_obj.blob
        in_name = getattr(file_obj, "filename", None) or "input.bin"

        # 2) markitdown で Markdown テキストへ
        md_text: str = _convert_to_markdown_bytes(in_bytes, filename_hint=in_name)

        # 2.5) Markdown 表を JSON 行へ正規化
        md_text = _normalize_markdown_tables(md_text)

        # 3) 1パスで分割 + プレフィックス付与
        lines = io.StringIO(md_text).readlines()
        processed_iter = _split_and_prefix(
            lines,
            max_chunk_length=max_chunk_length,
            split_max_level=split_max_level,
        )

        # 4) 逐次書き出して bytes 化（UTF-8）
        #    大きな文字列連結は避け、temp を経由して BLOB を返却
        fd_out, out_path = tempfile.mkstemp(suffix=".md", prefix="kb_out_")
        os.close(fd_out)
        try:
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                for ln in processed_iter:
                    f.write(ln)
            with open(out_path, "rb") as f:
                out_bytes = f.read()
        finally:
            try:
                os.remove(out_path)
            except OSError:
                pass

        # 5) BLOB で返却（create_blob_message）
        #    meta に filename / mime_type 等を付けておくと後段で扱いやすい
        # 出力はプレーンテキストとして扱う（KB 側の不要な Markdown 分割を避ける）
        out_name = os.path.splitext(os.path.basename(in_name))[0] + ".txt"
        meta = {
            "mime_type": "text/plain",
            "filename": out_name,
        }
        yield self.create_blob_message(blob=out_bytes, meta=meta)
