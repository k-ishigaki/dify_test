#!/usr/bin/env python3
import sys, re

DELIM = "---DIFY-CHUNK---"
PAT = re.compile(r'^#{1,3}\s')  # 見出しレベル1～3

for line in sys.stdin:
    if PAT.match(line) and not line.startswith(DELIM):
        sys.stdout.write(DELIM + line)
    else:
        sys.stdout.write(line)
