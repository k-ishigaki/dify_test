import re, sys

path_stack = []

for line in sys.stdin:
    m = re.match(r'^(#+)\s+(.*)', line)
    if m:
        level = len(m.group(1))
        title = m.group(2).strip()

        # 階層調整
        path_stack = path_stack[:level-1]
        path_stack.append(title)

        data_path = " > ".join(path_stack)
        # 見出し行に属性を追加
        line = f"{m.group(1)} {title} {{data-path=\"{data_path}\"}}\n"

    sys.stdout.write(line)
