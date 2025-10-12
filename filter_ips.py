import re
import os
import requests
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ------------------------- 配置区 -------------------------
MAX_PER_COUNTRY = int(os.getenv("MAX_PER_COUNTRY", 5))  # 每个国家最大条数
IP_URL = "https://zip.cm.edu.kg/all.txt"                # 远程 IP 列表
CHECK_API = "https://check.proxyip.cmliussss.net/check?proxyip={}"  # 验证 API
MAX_THREADS = MAX_PER_COUNTRY  # 每批次线程数

# ------------------------- 缓存 -------------------------
verified_cache = {}  # {ip_port: (valid, responseTime)}

# ------------------------- 验证函数 -------------------------
def check_proxy(ip_port):
    """验证代理是否有效，并返回 (是否有效, responseTime)"""
    if ip_port in verified_cache:
        return verified_cache[ip_port]

    url = CHECK_API.format(ip_port)
    try:
        resp = requests.get(url, timeout=6)
        data = resp.json()

        # 严格判断是否有效
        valid = (
            isinstance(data, dict)
            and data.get("success") is True
            and str(data.get("proxyIP")) != "-1"
        )
        response_time = data.get("responseTime", -1)
        verified_cache[ip_port] = (valid, response_time)

        if valid:
            print(f"[✅ 有效] {ip_port}  延迟: {response_time}ms")
        else:
            print(f"[❌ 无效] {ip_port}  延迟: {response_time}ms")

        return valid, response_time

    except Exception as e:
        print(f"[⚠️ 验证失败] {ip_port} -> {e}")
        verified_cache[ip_port] = (False, -1)
        return False, -1


def validate_batch(ip_lines, max_workers):
    """多线程验证批次 IP，返回有效 IP 列表"""
    ip_ports = [ip.split('#')[0] for ip in ip_lines]
    valid_ips = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_proxy, ip): ip for ip in ip_ports}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                valid, response_time = future.result()
                if valid:
                    # 找到对应的原始行
                    for line in ip_lines:
                        if line.startswith(ip):
                            valid_ips.append(f"{line}  # 延迟: {response_time}ms")
                            break
            except Exception as e:
                print(f"[线程错误] {ip} -> {e}")
    return valid_ips


def filter_ips(input_data, max_per_country=MAX_PER_COUNTRY):
    """按国家筛选 IP，每个国家严格 max_per_country 条有效 IP"""
    lines = input_data.strip().split('\n')
    country_map = defaultdict(list)

    # 按国家分组
    for line in lines:
        line = line.strip()
        if not line or ':443#' not in line:
            continue
        match = re.search(r'#([A-Z]{2})$', line)
        if not match:
            continue
        country = match.group(1)
        country_map[country].append(line)

    result = []

    # 逐国家验证
    for country in sorted(country_map.keys()):
        candidates = country_map[country]
        print(f"\n🌍 验证 {country} 的 IP，目标数量: {max_per_country}")

        valid_lines = []
        index = 0

        # 限制每个国家的有效 IP 数量
        while len(valid_lines) < max_per_country and index < len(candidates):
            batch = candidates[index:index + MAX_THREADS]
            valid_batch = validate_batch(batch, MAX_THREADS)

            # 按顺序添加到有效列表，严格控制数量
            for line in valid_batch:
                if len(valid_lines) < max_per_country:
                    valid_lines.append(line)
                else:
                    break

            index += MAX_THREADS

        print(f"✅ {country} 有效 IP 数量: {len(valid_lines)} / {max_per_country}")
        result.extend(valid_lines)

    return '\n'.join(result)


# ------------------------- 主逻辑 -------------------------
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
