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
MAX_THREADS = 3                                        # 每批次并发线程数（调低以防并发过多）

# ------------------------- 缓存 & 锁 -------------------------
verified_cache = {}
lock = threading.Lock()  # 用于多线程安全输出和列表操作

def check_proxy(ip_port, stop_flag):
    """验证代理是否有效，并返回 (是否有效, 延迟ms)。如果 stop_flag 被设置则尽快返回。"""
    # 尽早退出以减少无谓请求
    if stop_flag.is_set():
        return False, -1

    if ip_port in verified_cache:
        return verified_cache[ip_port]

    url = CHECK_API.format(ip_port)
    try:
        resp = requests.get(url, timeout=10)  # 增加了超时时间
        data = resp.json()

        valid = (
            isinstance(data, dict)
            and data.get("success") is True
            and str(data.get("proxyIP")) != "-1"
        )
        delay = data.get("responseTime", -1)
        verified_cache[ip_port] = (valid, delay)

        with lock:
            status = "✅ 有效" if valid else "❌ 无效"
            if not stop_flag.is_set():
                print(f"[{status}] {ip_port}  延迟: {delay}ms")

        return valid, delay
    except Exception as e:
        with lock:
            print(f"[⚠️ 验证失败] {ip_port} -> {e}")
        verified_cache[ip_port] = (False, -1)
        return False, -1


def validate_batch(ip_batch, stop_flag):
    """
    对一小批 ip（原始行，如 '1.2.3.4:443#CC'）并发验证，返回本批次中按出现顺序的有效行（已附带延迟）。
    不会返回超过 remaining_quota（外部控制）。
    """
    ip_ports = [line.split('#')[0] for line in ip_batch]
    valid_lines = []
    with ThreadPoolExecutor(max_workers=min(MAX_THREADS, len(ip_ports))) as executor:
        futures = {executor.submit(check_proxy, ip, stop_flag): ip for ip in ip_ports}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                valid, delay = future.result()
                if valid:
                    # 找到对应的原始行（保持原始顺序以便后面截取）
                    for line in ip_batch:
                        if line.startswith(ip):
                            valid_lines.append(f"{line}  # 延迟:{delay}ms")
                            break
                # 如果 stop_flag 已经被设定，则我们可以尽早返回
                if stop_flag.is_set():
                    break
            except Exception as e:
                with lock:
                    print(f"[线程错误] {ip} -> {e}")
    return valid_lines


def validate_country(country, ip_lines, max_per_country):
    """逐批次验证某个国家的 IP，严格控制最多 max_per_country 条有效 IP"""
    print(f"\n🌍 验证 {country} 的 IP，目标数量: {max_per_country}")

    valid_results = []
    stop_flag = threading.Event()
    index = 0
    total = len(ip_lines)

    while len(valid_results) < max_per_country and index < total:
        batch = ip_lines[index:index + MAX_THREADS]
        valid_batch = validate_batch(batch, stop_flag)

        for line in valid_batch:
            if len(valid_results) < max_per_country:
                valid_results.append(line)
                if len(valid_results) >= max_per_country:
                    stop_flag.set()  # 达到目标数量后停止
                    break

        # 如果已经达到目标数量，就退出
        if stop_flag.is_set():
            break

        index += MAX_THREADS

    print(f"✅ {country} 有效 IP 数量: {len(valid_results)} / {max_per_country}")
    return valid_results



def filter_ips(input_data, max_per_country=MAX_PER_COUNTRY):
    """主流程：按国家分组并逐国家验证"""
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
