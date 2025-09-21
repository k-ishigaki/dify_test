#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import textile
from pathlib import Path

def convert_textile_to_html(input_file: str, output_file: str = None):
    # 入力ファイルを読む
    input_path = Path(input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"入力ファイルが存在しません: {input_file}")

    with input_path.open("r", encoding="utf-8") as f:
        textile_text = f.read()

    # Textile → HTML 変換
    html_body = textile.textile(textile_text)

    # HTMLファイルのひな型に埋め込む
    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>{input_path.stem}</title>
</head>
<body>
{html_body}
</body>
</html>"""

    # 出力ファイルの決定
    if output_file is None:
        output_file = input_path.with_suffix(".html")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"変換完了: {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python convert.py input.textile [output.html]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    convert_textile_to_html(input_file, output_file)
