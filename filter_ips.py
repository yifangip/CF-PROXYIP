import re
import os
import requests
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ------------------------- 配置区 -------------------------
MAX_PER_COUNTRY = int(os.getenv("MAX_PER_COUNTRY", 3))  # 每个国家最大条数
IP_URL = "https://zip.cm.edu.kg/all.txt"               # 远程 IP 列表
CHECK_API = "https://check.proxyip.cmliussss.net/check?proxyip={}"  # 验证 API
MAX_THREADS = 20                                      # 并发线程数

# ------------------------- 缓存 -------------------------
verified_cache = {}  # {ip_port: True/False}


# ------------------------- 函数定义 -------------------------
def check_proxy(ip_port):
    """验证代理是否有效，返回 True 表示有效，使用缓存加速"""
    if ip_port in verified_cache:
        return verified_cache[ip_port]

    url = CHECK_API.format(ip_port)
    try:
        resp = requests.get(url, timeout=6)
        data = resp.json()
        valid = isinstance(data, dict) and data.get("proxyIP") != "-1"
        verified_cache[ip_port] = valid
        if valid:
            print(f"[✅ 有效] {ip_port}")
        else:
            print(f"[❌ 无效] {ip_port}")
        return valid
    except Exception as e:
        print(f"[⚠️ 验证失败] {ip_port} -> {e}")
        verified_cache[ip_port] = False
        return False


def validate_ips_multithread(ip_list):
    """多线程验证 IP 列表，返回有效 IP"""
    valid_ips = []
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(check_proxy, ip): ip for ip in ip_list}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                if future.result():
                    valid_ips.append(ip)
            except Exception as e:
                print(f"[线程错误] {ip} -> {e}")
    return valid_ips


def filter_ips(input_data, max_per_country=MAX_PER_COUNTRY):
    """按国家筛选 IP，每个国家最多 max_per_country 条，有效性验证"""
    lines = input_data.strip().split('\n')

    # 解析每行 IP 与国家
    parsed_data = []
    for line in lines:
        line = line.strip()
        if not line or ':443#' not in line:
            continue
        match = re.search(r'#([A-Z]{2})$', line)
        if not match:
            continue
        country = match.group(1)
        ip_port = line.split('#')[0]
        parsed_data.append((country, ip_port, line))

    # 按国家分组
    grouped = defaultdict(list)
    for country, ip_port, line in parsed_data:
        grouped[country].append((ip_port, line))

    result = []

    # 对每个国家依次验证 IP
    for country in sorted(grouped.keys()):
        candidates = grouped[country]
        print(f"\n🌍 验证 {country} 的 IP，目标数量: {max_per_country}")
        valid_lines = []

        index = 0
        while len(valid_lines) < max_per_country and index < len(candidates):
            batch = candidates[index:index + MAX_THREADS]
            ip_ports = [ip for ip, _ in batch]
            valid_ips = validate_ips_multithread(ip_ports)

            # 严格限制数量
            for ip, line in batch:
                if ip in valid_ips:
                    if len(valid_lines) < max_per_country:
                        valid_lines.append(line)
                    else:
                        break  # 达到上限
            index += MAX_THREADS

        result.extend(valid_lines)
        print(f"✅ {country} 有效 IP 数量: {len(valid_lines)} / {max_per_country}")

    return '\n'.join(result)


# ------------------------- 主执行逻辑 -------------------------
if __name__ == "__main__":
    output_file = "filtered_ips.txt"

    try:
        response = requests.get(IP_URL, timeout=15)
        response.raise_for_status()
        input_data = response.text
    except Exception as e:
        print(f"无法获取远程 IP 列表: {e}")
        exit(1)

    output_data = filter_ips(input_data)

    if output_data.strip():
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output_data)
        print(f"\n✅ 已生成 {output_file} 文件，共 {len(output_data.splitlines())} 条有效代理。")
    else:
        print("\n⚠️ 没有找到任何有效代理 IP。")
