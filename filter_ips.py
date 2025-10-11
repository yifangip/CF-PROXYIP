import re
import os
import requests
from collections import defaultdict

# 从环境变量获取最大条数，默认3条
MAX_PER_COUNTRY = int(os.getenv("MAX_PER_COUNTRY", 3))

# 远程 IP 列表 URL
IP_URL = "https://zip.cm.edu.kg/all.txt"

def filter_ips(input_data, max_per_country=MAX_PER_COUNTRY):
    lines = input_data.strip().split('\n')
    country_map = defaultdict(list)

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if ':443#' not in line:
            continue

        match = re.search(r'#([A-Z]{2})$', line)
        if not match:
            continue
        country = match.group(1)

        if len(country_map[country]) < max_per_country:
            country_map[country].append(line)

    sorted_countries = sorted(country_map.keys())
    result = []
    for country in sorted_countries:
        result.extend(country_map[country])

    return '\n'.join(result)

if __name__ == "__main__":
    output_file = "filtered_ips.txt"

    try:
        response = requests.get(IP_URL, timeout=10)
        response.raise_for_status()
        input_data = response.text
    except Exception as e:
        print(f"无法获取远程 IP 列表: {e}")
        exit(1)

    output_data = filter_ips(input_data)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_data)

    print(f"已生成 {output_file} 文件")
