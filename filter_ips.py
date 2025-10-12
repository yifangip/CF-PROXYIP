import re
import os
import requests
from collections import defaultdict

# 每个国家最大条数，默认3条，可通过环境变量修改
MAX_PER_COUNTRY = int(os.getenv("MAX_PER_COUNTRY", 3))

# 远程 IP 列表 URL
IP_URL = "https://zip.cm.edu.kg/all.txt"
CHECK_API = "https://check.proxyip.cmliussss.net/check?proxyip={}"

def check_ip_latency(ip_port):
    """检查 IP 的延迟"""
    try:
        # 访问 API 进行验证
        response = requests.get(CHECK_API.format(ip_port), timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("success"):
            return data["responseTime"], data["colo"]
        else:
            return None, None
    except Exception as e:
        print(f"检查 {ip_port} 时发生错误: {e}")
        return None, None

def filter_ips(input_data, max_per_country=MAX_PER_COUNTRY):
    """过滤并检查 IP 列表，返回符合要求的 IP"""
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

        # 获取 IP 和端口
        ip_port = line.split(':')[0] + ':' + line.split(':')[1]

        # 检查 IP 延迟
        latency, colo = check_ip_latency(ip_port)
        
        # 如果没有有效延迟，跳过此 IP
        if latency is None:
            continue

        # 如果延迟有效并且该国家的 IP 还没有达到最大数量，加入该国家的 IP 列表
        if len(country_map[country]) < max_per_country:
            line_with_latency = f"{line.split(':')[0]}:{line.split(':')[1]}#{country}#延迟:{latency}ms"
            country_map[country].append(line_with_latency)

    # 对国家进行排序并合并结果
    sorted_countries = sorted(country_map.keys())
    result = []
    for country in sorted_countries:
        result.extend(country_map[country])

    return '\n'.join(result)

if __name__ == "__main__":
    output_file = "filtered_ips_with_latency.txt"

    try:
        response = requests.get(IP_URL, timeout=15)
        response.raise_for_status()
        input_data = response.text
    except Exception as e:
        print(f"无法获取远程 IP 列表: {e}")
        exit(1)

    output_data = filter_ips(input_data)

    # 将结果写入文件
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_data)

    print(f"已生成 {output_file} 文件")
