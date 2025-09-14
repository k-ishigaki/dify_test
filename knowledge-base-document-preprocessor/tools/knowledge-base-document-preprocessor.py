from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

import io
import os
import re
import tempfile
from typing import Any, Generator, Iterable, Tuple

from markitdown import MarkItDown


DELIM = "---DIFY-CHUNK---"


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


def _format_datapath_marker(segments: list[str]) -> str:
    """
    data-path マーカーを生成する。
    形式: { data-path = "H1" > "H2" > ... }
    引用符や制御文字を簡易サニタイズする。
    """
    def sanitize(s: str) -> str:
        # バックスラッシュと二重引用符をエスケープし、前後空白を除去
        s = s.replace("\\", "\\\\").replace('"', '\\"').strip()
        return s

    joined = " > ".join(f'"{sanitize(x)}"' for x in segments)
    # セグメントが空の場合は空の右辺を維持（= の後は空）
    return f"{{ data-path = {joined} }}"


def _split_and_prefix(lines: Iterable[str], max_chunk_length: int, split_max_level: int) -> Iterable[str]:
    """
    1パスで分割とプレフィックス付与を実施する。
    - チャンク先頭: 先頭チャンクは `{ data-path = ... }`、以降は
      `---DIFY-CHUNK---{ data-path = ... }` を行頭に付与し、そのまま1行目に
      連結する（改行・空白は挟まない）。
    - 分割ポリシー: 見出し(<= split_max_level) > 空行 > 改行（長さ超過）
    - 長さ計算: チャンク1行目にはプレフィックス長も含めてカウントする。
    """
    heading_re = re.compile(r'^(#{1,6})\s+(.*)')
    path_stack: list[str] = []

    buffer: list[str] = []
    buffer_chars = 0
    last_blank_idx = -1
    is_first_chunk = True
    current_prefix = ""

    def compute_prefix_for_first_line(first_line: str, is_first: bool) -> str:
        m = heading_re.match(first_line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            tmp_stack = path_stack[: level - 1] + [title]
            dp_marker = _format_datapath_marker(tmp_stack)
        else:
            dp_marker = _format_datapath_marker(path_stack)
        if is_first:
            return dp_marker
        return f"{DELIM}{dp_marker}"

    def emit_chunk(lines_chunk: list[str], prefix: str) -> Iterable[str]:
        if not lines_chunk:
            return
        # 1行目にプレフィックスを結合
        first = lines_chunk[0]
        yield f"{prefix}{first}"
        for l in lines_chunk[1:]:
            yield l

    for line in lines:
        m_head = heading_re.match(line)
        # 見出しが分割対象かつバッファに内容があれば、現在のチャンクを出力して新チャンク開始
        if m_head and len(m_head.group(1)) <= split_max_level and buffer:
            for out in emit_chunk(buffer, current_prefix):
                yield out
            buffer = []
            buffer_chars = 0
            last_blank_idx = -1
            is_first_chunk = False
            # 新チャンク開始
            current_prefix = compute_prefix_for_first_line(line, is_first_chunk)
            buffer.append(line)
            # 長さはプレフィックス長 + 1行目
            buffer_chars = len(current_prefix) + len(line)
            # 見出しに応じてスタック更新
            level = len(m_head.group(1))
            title = m_head.group(2).strip()
            path_stack = path_stack[: level - 1] + [title]
            continue

        # ここまで来たら通常の追記
        if not buffer:
            # 新チャンク開始
            current_prefix = compute_prefix_for_first_line(line, is_first_chunk)
            buffer.append(line)
            buffer_chars = len(current_prefix) + len(line)
        else:
            buffer.append(line)
            buffer_chars += len(line)

        # 見出しはスタックを更新（split_max_level 超でも更新）
        if m_head:
            level = len(m_head.group(1))
            title = m_head.group(2).strip()
            path_stack = path_stack[: level - 1] + [title]

        # 空行の位置を記録
        if line.strip() == "":
            last_blank_idx = len(buffer) - 1

        # 長さオーバーなら分割
        if buffer_chars >= max_chunk_length:
            cut_idx = last_blank_idx if last_blank_idx != -1 else len(buffer) - 1
            left = buffer[:cut_idx + 1]
            right = buffer[cut_idx + 1:]
            # 左チャンク出力
            for out in emit_chunk(left, current_prefix):
                yield out
            # 右チャンクを新しいチャンクとしてセット
            buffer = right
            is_first_chunk = False
            if buffer:
                current_prefix = compute_prefix_for_first_line(buffer[0], is_first_chunk)
                buffer_chars = len(current_prefix) + sum(len(x) for x in buffer)
                # 空行の再計算
                last_blank_idx = -1
                for i, l in enumerate(buffer):
                    if l.strip() == "":
                        last_blank_idx = i
            else:
                buffer_chars = 0
                last_blank_idx = -1

    # 残りを出力
    if buffer:
        for out in emit_chunk(buffer, current_prefix):
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
