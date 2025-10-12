#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os
import time
import requests
from collections import defaultdict

# 配置
MAX_PER_COUNTRY = int(os.getenv("MAX_PER_COUNTRY", 3))  # 每个国家最大条数
IP_LIST_URL = "https://zip.cm.edu.kg/all.txt"
LOCAL_IP_FILE = "all.txt"  # 下载后的本地文件
OUTPUT_FILE = "filtered_ips_with_latency.txt"
CHECK_API = "https://check.proxyip.cmliussss.net/check?proxyip={}"  # 请确认该 API 可用

# 检查并下载远程 IP 列表到本地
def download_ip_list(url=IP_LIST_URL, dest=LOCAL_IP_FILE, timeout=20):
    print(f"下载远程 IP 列表：{url} -> {dest}")
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        with open(dest, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"下载完成，已保存到 {dest}，文件大小 {len(r.text)} 字节")
        return True
    except Exception as e:
        print(f"下载失败: {e}")
        return False

# 使用 API 检测单个 ip:port 的延迟，带重试与指数退避
def check_ip_latency(ip_port, retries=3, initial_delay=1, timeout=10):
    delay = initial_delay
    for attempt in range(1, retries + 1):
        try:
            url = CHECK_API.format(ip_port)
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if data.get("success") and "responseTime" in data:
                return int(data["responseTime"])
            else:
                # API 返回不成功，也视为该 IP 无效
                return None
        except requests.exceptions.RequestException as e:
            # 打印错误并在重试前等待（指数退避）
            print(f"检测 {ip_port} 失败 (尝试 {attempt}/{retries})，错误: {e}")
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
            else:
                return None
        except ValueError:
            # JSON decode 错误
            print(f"检测 {ip_port} 返回非 JSON 内容，略过")
            return None

# 读取本地文件并逐行处理；只保留格式正确且检测成功的 IP
def filter_and_check(local_file=LOCAL_IP_FILE, max_per_country=MAX_PER_COUNTRY):
    if not os.path.exists(local_file):
        raise FileNotFoundError(f"{local_file} 不存在，请先下载或指定正确路径")

    country_count = defaultdict(int)
    results = []

    with open(local_file, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue

            # 跳过含有星号掩码或明显不完整的行
            if "***" in line or "..." in line:
                # 如果你想记录被跳过的行可以在此处打印或写入日志
                # print(f"跳过被掩码或不完整的行: {line}")
                continue

            # 只处理 :443#XX 这类格式
            if ':443#' not in line:
                continue

            # 提取国家码（行尾两个大写字母）
            m = re.search(r'#([A-Z]{2})$', line)
            if not m:
                continue
            country = m.group(1)

            # 如果该国家已经达到了上限，直接跳过该行
            if country_count[country] >= max_per_country:
                continue

            # 获取 ip:port（仅取前两个冒号分割部分，以防额外字段）
            parts = line.split(':')
            if len(parts) < 2:
                continue
            ip = parts[0]
            port_and_rest = parts[1]
            # port 可能包含 #，所以取 split('#')[0]
            port = port_and_rest.split('#')[0]
            ip_port = f"{ip}:{port}"

            # 调用检测 API（只有检测成功才记录）
            latency = check_ip_latency(ip_port)
            if latency is None:
                # 检测失败（无延迟或 API 不成功），跳过该 IP
                continue

            # 记录并计数
            formatted = f"{ip_port}#{country}#延迟:{latency}ms"
            results.append(formatted)
            country_count[country] += 1

            print(f"通过: {formatted} （国家 {country} 已有 {country_count[country]}/{max_per_country}）")

            # 若所有国家都已达到上限，可提前停止 —— 但我们没有事先知道有哪些国家在列表中
            # 因此继续遍历文件，直到文件结束或每个国家都尽可能达到上限

    return results

def main():
    # 1. 下载远程列表到本地（如果已经有本地文件也可以跳过这一步）
    if not os.path.exists(LOCAL_IP_FILE):
        ok = download_ip_list()
        if not ok:
            print("无法下载远程 IP 列表，退出")
            return

    # 2. 处理并检测
    try:
        results = filter_and_check()
    except Exception as e:
        print(f"处理出错: {e}")
        return

    # 3. 写入输出文件
    if results:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
            out.write("\n".join(results))
        print(f"已生成 {OUTPUT_FILE}，共 {len(results)} 条")
    else:
        print("没有检测到有效 IP，未生成输出文件。")

if __name__ == "__main__":
    main()
