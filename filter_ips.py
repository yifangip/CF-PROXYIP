import re
import os
import requests
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ------------------------- 配置区 -------------------------
MAX_PER_COUNTRY = int(os.getenv("MAX_PER_COUNTRY", 2))  # 每个国家最大条数
IP_URL = "https://zip.cm.edu.kg/all.txt"                # 远程 IP 列表
CHECK_API = "https://check.proxyip.cmliussss.net/check?proxyip={}"  # 验证 API
MAX_THREADS = 5                                        # 每批次线程数

# ------------------------- 缓存 -------------------------
verified_cache = {}
lock = threading.Lock()  # 用于多线程安全操作

def check_proxy(ip_port, stop_flag):
    """验证代理是否有效，并返回 (是否有效, 延迟ms)"""
    if stop_flag.is_set():  # 如果其他线程已找到足够数量，立即退出
        return False, -1

    if ip_port in verified_cache:
        return verified_cache[ip_port]

    url = CHECK_API.format(ip_port)
    try:
        resp = requests.get(url, timeout=6)
        data = resp.json()

        valid = (
            isinstance(data, dict)
            and data.get("success") is True
            and str(data.get("proxyIP")) != "-1"
        )
        delay = data.get("responseTime", -1)

        verified_cache[ip_port] = (valid, delay)

        # 打印时加锁，防止输出交错
        with lock:
            if not stop_flag.is_set():
                status = "✅ 有效" if valid else "❌ 无效"
                print(f"[{status}] {ip_port}  延迟: {delay}ms")

        return valid, delay
    except Exception as e:
        with lock:
            print(f"[⚠️ 验证失败] {ip_port} -> {e}")
        verified_cache[ip_port] = (False, -1)
        return False, -1


def validate_country(country, ip_lines, max_per_country):
    """验证某个国家的 IP，严格限制数量"""
    print(f"\n🌍 验证 {country} 的 IP，目标数量: {max_per_country}")

    valid_ips = []
    stop_flag = threading.Event()  # 当找到足够的IP后触发

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(check_proxy, ip.split('#')[0], stop_flag): ip for ip in ip_lines}

        for future in as_completed(futures):
            ip = futures[future]
            try:
                valid, delay = future.result()
                if valid:
                    with lock:
                        if len(valid_ips) < max_per_country:
                            valid_ips.append(f"{ip}#延迟:{delay}ms")
                            if len(valid_ips) >= max_per_country:
                                stop_flag.set()  # 达到目标后通知其他线程停止
            except Exception as e:
                print(f"[线程错误] {ip} -> {e}")

    print(f"✅ {country} 有效 IP 数量: {len(valid_ips)} / {max_per_country}")
    return valid_ips


def filter_ips(input_data, max_per_country=MAX_PER_COUNTRY):
    """按国家筛选 IP，每个国家严格 max_per_country 条"""
    lines = input_data.strip().split('\n')
    country_map = defaultdict(list)

    for line in lines:
        line = line.strip()
        if not line or ':443#' not in line:
            continue
        match = re.search(r'#([A-Z]{2})$', line)
        if match:
            country = match.group(1)
            country_map[country].append(line)

    result = []
    for country in sorted(country_map.keys()):
        valid = validate_country(country, country_map[country], max_per_country)
        result.extend(valid)
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
