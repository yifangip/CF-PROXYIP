#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import os
import time
import traceback
from datetime import datetime
from collections import defaultdict
import sys

# ==============================
# 🔧 环境变量检测
# ==============================
REQUIRED_ENV_VARS = ["CF_API_TOKEN", "CF_ZONE_ID", "BOT_TOKEN", "CHAT_ID"]
missing_vars = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if missing_vars:
    print(f"❌ 缺少环境变量: {', '.join(missing_vars)}")
    print("请先设置以上环境变量后再运行。")
    sys.exit(1)

CF_API_TOKEN = os.environ["CF_API_TOKEN"]
CF_ZONE_ID = os.environ["CF_ZONE_ID"]
CF_BASE_NAME = "proxyip"

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

headers = {
    'Authorization': f'Bearer {CF_API_TOKEN}',
    'Content-Type': 'application/json'
}

# ==============================
# 🛰 获取 TXT 数据
# ==============================
def fetch_proxy_data():
    url = "https://raw.githubusercontent.com/yifangip/CF-PROXYIP/main/proxyip_443_sorted.txt"
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        lines = response.text.splitlines()

        proxy_data = []
        for line in lines:
            line = line.strip()
            if not line or ":" not in line or "#" not in line:
                continue
            try:
                ip_port, country = line.split("#")
                ip = ip_port.split(":")[0].strip()
                country = country.strip().upper()
                if ip and country:
                    proxy_data.append({
                        "ip": ip,
                        "country": country
                    })
            except:
                continue
        return proxy_data
    except Exception as e:
        traceback.print_exc()
        print(f"❌ 获取代理数据失败: {e}")
        return []

# ==============================
# ☁️ Cloudflare DNS 操作
# ==============================
def get_dns_records():
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records?type=A'
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get('result', [])
    except Exception as e:
        traceback.print_exc()
        print("❌ 获取 DNS 记录失败")
        return []

def create_record(name, ip):
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'
    data = {'type': 'A', 'name': name, 'content': ip, 'ttl': 1}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=15)
        resp_json = response.json()
        if response.status_code in [200, 201] and resp_json.get('success', False):
            return True
        # 处理已存在的情况
        if any(err.get('code') == 81058 for err in resp_json.get('errors', [])):
            return True
        return False
    except Exception as e:
        traceback.print_exc()
        return False

def bulk_delete(records_to_delete):
    deleted_count = 0
    for record in records_to_delete:
        url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record["id"]}'
        try:
            response = requests.delete(url, headers=headers, timeout=15)
            if response.status_code == 200:
                deleted_count += 1
            time.sleep(0.2)
        except:
            pass
    return deleted_count

# ==============================
# 📢 Telegram 推送
# ==============================
def send_tg_message(text):
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        resp = requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage', json=data, timeout=15)
        if resp.status_code != 200:
            print(f"⚠️ Telegram 推送失败: {resp.text}")
        time.sleep(1)
    except Exception as e:
        print(f"❌ Telegram 网络异常: {e}")

def send_tg_file(file_path, caption="同步日志文件"):
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                data={"chat_id": CHAT_ID, "caption": caption},
                files={"document": f},
                timeout=60
            )
        if resp.status_code != 200:
            print(f"⚠️ 文件上传失败: {resp.text}")
    except Exception as e:
        print(f"❌ 上传文件异常: {e}")

# ==============================
# 🔄 按国家全量同步
# ==============================
def sync_country_records(country, ips, managed_records):
    record_name = f"{CF_BASE_NAME}_{country}"

    # 删除旧记录
    old_records = [r for r in managed_records if r["name"] == record_name]
    deleted_count = bulk_delete(old_records) if old_records else 0

    # 添加新记录
    added_count = 0
    for ip in ips:
        if create_record(record_name, ip):
            added_count += 1
        time.sleep(0.2)

    return deleted_count, added_count

# ==============================
# 🚀 主逻辑
# ==============================
def main():
    proxy_data = fetch_proxy_data()
    if not proxy_data:
        warn_text = f"⚠️ Cloudflare 同步失败：TXT 文件为空或下载失败\n> 时间：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        print(warn_text)
        send_tg_message(warn_text)
        return

    existing_records = get_dns_records()
    managed_records = [r for r in existing_records if r["name"].startswith(f"{CF_BASE_NAME}_")]

    # 按国家分组
    country_groups = defaultdict(list)
    for entry in proxy_data:
        country_groups[entry["country"]].append(entry["ip"])

    # 汇总每个国家同步结果
    summary = []
    for country, ips in country_groups.items():
        deleted_count, added_count = sync_country_records(country, ips, managed_records)
        summary.append(f"🌍 {country}: 删除 {deleted_count} 条，新增 {added_count} 条")
        print(summary[-1])

    # Telegram 汇总消息
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tg_text = f"📢 *Cloudflare DNS 同步汇总*\n🕒 更新时间：`{now}`\n\n" + "\n".join(summary)
    send_tg_message(tg_text)

    # 生成详细日志文件
    log_path = f"PROXYIP_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("📜 Cloudflare DNS 同步日志\n")
        f.write(f"更新时间：{now}\n")
        f.write("-" * 60 + "\n")
        for line in summary:
            f.write(line + "\n")
        f.write("-" * 60 + "\n")
    send_tg_file(log_path, caption="📄 同步日志（含详细记录）")
    send_tg_message("✅ 本次 Cloudflare 同步任务已完成 ✅")

if __name__ == '__main__':
    main()
