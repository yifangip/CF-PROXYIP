import re
import os
from collections import defaultdict

# 从环境变量获取最大条数，默认3条
MAX_PER_COUNTRY = int(os.getenv("MAX_PER_COUNTRY", 3))

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
    # 测试用数据
    input_data = """103.146.119.108:443#NL
104.234.36.246:443#US
123.234.56.78:443#US
192.168.1.1:443#IN
203.0.113.5:443#US"""
    
    output = filter_ips(input_data)
    print(output)
