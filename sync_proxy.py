#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, requests, time
from datetime import datetime
from collections import defaultdict

# ==============================
# 环境变量
# ==============================
REQUIRED_ENV_VARS = ["CF_API_TOKEN", "CF_ZONE_ID", "BOT_TOKEN", "CHAT_ID"]
for v in REQUIRED_ENV_VARS:
    if v not in os.environ:
        print(f"❌ 缺少环境变量: {v}")
        exit(1)

CF_API_TOKEN = os.environ["CF_API_TOKEN"]
CF_ZONE_ID = os.environ["CF_ZONE_ID"]
CF_BASE_NAME = os.getenv("CF_BASE_NAME", "proxyip")
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
TXT_FILE = os.getenv("TXT_FILE", "proxyip_443_sorted.txt")

HEADERS = {'Authorization': f'Bearer {CF_API_TOKEN}', 'Content-Type': 'application/json'}

# ==============================
# 读取 TXT 文件
# ==============================
def fetch_proxy_data():
    if not os.path.exists(TXT_FILE):
        print(f"❌ TXT 文件不存在: {TXT_FILE}")
        return []
    data = []
    with open(TXT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line or "#" not in line:
                continue
            try:
                ip, country = line.split("#")
                ip = ip.split(":")[0].strip()   # 只取 IP
                country = country.strip().upper()
                data.append({"ip": ip, "country": country})
            except:
                continue
    return data

# ==============================
# Cloudflare DNS
# ==============================
def get_all_dns_records():
    records = []
    page = 1
    per_page = 100
    while True:
        url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records?type=A&page={page}&per_page={per_page}'
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15).json()
            result = resp.get('result', [])
            if not result:
                break
            records.extend(result)
            if len(result) < per_page:
                break
            page += 1
        except:
            break
    return records

def delete_records(records):
    deleted_ips = []
    for r in records:
        url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{r["id"]}'
        try:
            requests.delete(url, headers=HEADERS, timeout=10)
            deleted_ips.append(r["content"])
            time.sleep(0.05)
        except:
            pass
    return deleted_ips

def create_records(name, ips):
    created_ips = []
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'
    for ip in ips:
        data = {'type':'A', 'name':name, 'content':ip, 'ttl':1}
        try:
            resp = requests.post(url, headers=HEADERS, json=data, timeout=10).json()
            if resp.get('success', False):
                created_ips.append(ip)
            time.sleep(0.05)
        except:
            pass
    return created_ips

# ==============================
# Telegram
# ==============================
def send_tg_message(text):
    try:
        requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
                      timeout=10)
        time.sleep(0.5)
    except:
        pass

def send_tg_file(file_path, caption="同步日志文件"):
    try:
        with open(file_path, "rb") as f:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                          data={"chat_id": CHAT_ID, "caption": caption},
                          files={"document": f},
                          timeout=30)
    except:
        pass

# ==============================
# 删除旧日志
# ==============================
def cleanup_old_logs():
    for file in os.listdir('.'):
        if file.startswith("PROXYIP_") and file.endswith(".txt"):
            try:
                os.remove(file)
            except:
                pass

# ==============================
# 同步单个国家
# ==============================
def sync_country_records(country, ips, managed_records):
    name = f"{CF_BASE_NAME}_{country}"
    # 删除该国家所有旧记录
    old_records = [r for r in managed_records if r["name"].lower() == name.lower()]
    deleted_ips = delete_records(old_records)

    # 添加新记录
    created_ips = create_records(name, ips)

    # GitHub Actions 控制台日志显示每个 IP
    print(f"🌍 {country}: 删除 {len(deleted_ips)} 条，新增 {len(created_ips)} 条")
    if deleted_ips:
        print("  删除 IP:")
        for ip in deleted_ips:
            print(f"   - {ip}")
    if created_ips:
        print("  新增 IP:")
        for ip in created_ips:
            print(f"   + {ip}")

    return created_ips  # 只给 Telegram 使用新增 IP

# ==============================
# 主逻辑
# ==============================
def main():
    proxy_data = fetch_proxy_data()
    total_ips = len(proxy_data)
    if total_ips == 0:
        send_tg_message("❌ TXT 文件为空或不存在，Cloudflare 同步失败")
        return

    cleanup_old_logs()

    existing_records = get_all_dns_records()
    managed_records = [r for r in existing_records if r["name"].startswith(f"{CF_BASE_NAME}_")]

    # 按国家分组
    country_groups = defaultdict(list)
    for e in proxy_data:
        country_groups[e["country"]].append(e["ip"])

    created_ips_all = []
    for country, ips in country_groups.items():
        created_ips = sync_country_records(country, ips, managed_records)
        created_ips_all.extend(created_ips)

    # 日志文件只记录新增 IP
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = f"PROXYIP_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"📜 Cloudflare DNS 同步日志\n🕒 {now}\n\n")
        f.write(f"总共获取 IP 数量：{total_ips}\n")
        f.write(f"新增 IP 数量：{len(created_ips_all)}\n")
        if created_ips_all:
            f.write("新增 IP 列表:\n")
            for ip in created_ips_all:
                f.write(f"- {ip}\n")

    # Telegram 推送简洁汇总
    tg_text = f"📢 Cloudflare DNS 同步汇总\n🕒 {now}\n\n🌍 总共获取 IP：{total_ips}\n📄 日志文件已上传"
    send_tg_message(tg_text)
    send_tg_file(log_path, caption="📄 同步日志（只含新增记录）")

if __name__ == '__main__':
    main()
