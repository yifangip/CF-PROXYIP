#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, requests, time, traceback
from datetime import datetime
from collections import defaultdict

# ==============================
# 🔧 环境变量检测
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
# 📄 读取本地 TXT 文件
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
                ip = ip.split(":")[0].strip()
                country = country.strip().upper()
                data.append({"ip": ip, "country": country})
            except:
                continue
    return data

# ==============================
# ☁️ Cloudflare DNS 操作（分页获取全部记录）
# ==============================
def get_all_dns_records():
    records = []
    page = 1
    per_page = 100
    while True:
        url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records?type=A&page={page}&per_page={per_page}'
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            resp_json = resp.json()
            result = resp_json.get('result', [])
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
    count = 0
    for r in records:
        url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{r["id"]}'
        try:
            resp = requests.delete(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                count += 1
            time.sleep(0.05)
        except:
            pass
    return count

def create_records(name, ips):
    added = 0
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'
    for ip in ips:
        data = {'type':'A', 'name':name, 'content':ip, 'ttl':1}
        try:
            resp = requests.post(url, headers=HEADERS, json=data, timeout=10).json()
            if resp.get('success', False) or any(err.get('code')==81058 for err in resp.get('errors',[])):
                added += 1
            time.sleep(0.05)
        except:
            pass
    return added

# ==============================
# 📢 Telegram 推送
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
# 🧹 删除旧日志文件，只保留最新
# ==============================
def cleanup_old_logs():
    for file in os.listdir('.'):
        if file.startswith("PROXYIP_") and file.endswith(".txt"):
            try:
                os.remove(file)
                print(f"已删除旧日志: {file}")
            except:
                pass

# ==============================
# 🔄 按国家全量同步
# ==============================
def sync_country_records(country, ips, managed_records):
    name = f"{CF_BASE_NAME}_{country}"
    old_records = [r for r in managed_records if r["name"] == name]
    deleted_count = delete_records(old_records) if old_records else 0
    added_count = create_records(name, ips)
    return deleted_count, added_count

# ==============================
# 🚀 主逻辑
# ==============================
def main():
    proxy_data = fetch_proxy_data()
    if not proxy_data:
        send_tg_message("❌ TXT 文件为空或不存在，Cloudflare 同步失败")
        return

    # 删除旧日志
    cleanup_old_logs()

    existing_records = get_all_dns_records()
    managed_records = [r for r in existing_records if r["name"].startswith(f"{CF_BASE_NAME}_")]

    # 按国家分组
    country_groups = defaultdict(list)
    for e in proxy_data:
        country_groups[e["country"]].append(e["ip"])

    summary = []
    for country, ips in country_groups.items():
        deleted, added = sync_country_records(country, ips, managed_records)
        summary.append(f"🌍 {country}: 删除 {deleted} 条，新增 {added} 条")
        summary.append("IPs:")
        for ip in ips:
            summary.append(f" - {ip}")

    # Telegram 汇总
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tg_text = f"📢 *Cloudflare DNS 同步汇总*\n🕒 {now}\n\n" + "\n".join(summary)
    send_tg_message(tg_text)

    # 生成日志文件
    log_path = f"PROXYIP_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(tg_text)
    send_tg_file(log_path, caption="📄 同步日志（含详细记录）")
    send_tg_message("✅ 本次 Cloudflare 同步任务已完成 ✅")

if __name__ == '__main__':
    main()
