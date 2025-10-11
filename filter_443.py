#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests

# ---------------- 配置区 ----------------
INPUT_URL = "https://zip.cm.edu.kg/all.txt"   # 远程文件 URL
OUTPUT_FILE = "proxyip_443_sorted.txt"       # 输出文件路径
MAX_PER_COUNTRY = int(os.getenv("MAX_PER_COUNTRY", 10))  # 每个国家最多保留条数，默认 10
# ---------------------------------------

def main():
    try:
        resp = requests.get(INPUT_URL, timeout=30)
        resp.raise_for_status()
        lines = resp.text.splitlines()
    except Exception as e:
        print(f"下载文件失败: {e}")
        return

    country_map = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if ":443#" not in line:
            continue  # 只保留 443 端口

        parts = line.split("#")
        if len(parts) != 2:
            continue

        ip_part, country = parts
        if country not in country_map:
            country_map[country] = []

        if len(country_map[country]) < MAX_PER_COUNTRY:
            country_map[country].append(line)

    # 按国家代码排序，并按原顺序输出每个国家的条目
    result = []
    for country in sorted(country_map.keys()):
        result.extend(country_map[country])

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(result))

    print(f"筛选完成，结果已写入 {OUTPUT_FILE}（每个国家最多 {MAX_PER_COUNTRY} 条，按国家排序）")

if __name__ == "__main__":
    main()
