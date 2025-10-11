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
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get('result', [])
    else:
        print('❌ 获取 DNS 记录失败:', response.text)
        return []

def record_exists(name, ip, existing_records):
    for record in existing_records:
        if record["name"] == name and record["content"] == ip:
            return True
    return False

# ==============================
# 🧱 创建与删除逻辑
# ==============================
def create_record_if_not_exists(name, cf_ip, existing_records):
    text = f"{name} → {cf_ip}"

    if record_exists(name, cf_ip, existing_records):
        return ("已存在", text)

    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'
    data = {'type': 'A', 'name': name, 'content': cf_ip, 'ttl': 1}

    try:
        response = requests.post(url, headers=headers, json=data, timeout=15)
        resp_json = response.json()

        if response.status_code in [200, 201] and resp_json.get('success', False):
            print(f"✅ 创建成功: {name} → {cf_ip}")
            return ("新增", text)
        else:
            # 81058 常见表示已存在
            if any(err.get('code') == 81058 for err in resp_json.get('errors', [])):
                print(f"ℹ️ 已存在（API反馈）: {name} → {cf_ip}")
                return ("已存在", text)
            err_msg = resp_json.get('errors') or resp_json.get('message') or "未知错误"
            print(f"❌ 创建失败: {name} → {cf_ip}")
            return ("失败", f"{text}（错误: {err_msg}）")
    except Exception as e:
        traceback.print_exc()
        return ("失败", f"{text}（网络异常: {e}）")

def bulk_delete(records_to_delete):
    messages = []
    for record in records_to_delete:
        url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record["id"]}'
        try:
            response = requests.delete(url, headers=headers, timeout=15)
            if response.status_code == 200:
                print(f"🗑 删除成功: {record['name']} → {record['content']}")
                messages.append(("删除", f"{record['name']} → {record['content']}"))
            else:
                print(f"⚠️ 删除失败: {record['name']} → {record['content']}")
                messages.append(("失败", f"{record['name']} → {record['content']}（删除失败）"))
        except Exception as e:
            traceback.print_exc()
            messages.append(("失败", f"{record['name']} → {record['content']}（网络异常: {e}）"))
    return messages

# ==============================
# 📢 Telegram 推送
# ==============================
def send_tg_message(text):
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        resp = requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage', json=data, timeout=15)
        if resp.status_code != 200:
            print(f"⚠️ Telegram 推送失败: {resp.text}")
        time.sleep(1.2)
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
# 📝 推送汇总 + 日志生成
# ==============================
def push_summary(statused_messages, proxy_data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_ips = len(proxy_data)
    country_count = defaultdict(int)
    for entry in proxy_data:
        country_count[entry["country"]] += 1

    tg_text = f"📢 *Cloudflare DNS 同步结果汇总*\n"
    tg_text += f"🕒 更新时间：`{now}`\n"
    tg_text += f"🌍 本次共同步 IP 数量：*{total_ips}*\n\n"
    tg_text += "🌎 各国家 IP 数量：\n"
    for country, count in sorted(country_count.items()):
        tg_text += f"• {country}：{count} 条\n"

    for i in range(0, len(tg_text), 3800):
        send_tg_message(tg_text[i:i + 3800])

    # 清除旧日志，仅保留最新
    for file in os.listdir('.'):
        if file.startswith("PROXYIP_") and file.endswith(".txt"):
            try:
                os.remove(file)
                print(f"🧹 已删除旧日志: {file}")
            except:
                pass

    log_path = f"PROXYIP_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("📜 Cloudflare DNS 同步日志\n")
        f.write(f"更新时间：{now}\n")
        f.write("-" * 60 + "\n")

        for status, text in statused_messages:
            f.write(f"{status:<6} | {text}\n")

        f.write("-" * 60 + "\n")
        f.write("（以上为本次同步的所有记录情况）\n")

    send_tg_file(log_path, caption="📄 同步日志（含详细记录）")
    send_tg_message("✅ 本次 Cloudflare 同步任务已完成 ✅")

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

    country_groups = defaultdict(list)
    for entry in proxy_data:
        country_groups[entry["country"]].append(entry["ip"])

    statused_messages = []

    for country, ips in country_groups.items():
        record_name = f"{CF_BASE_NAME}_{country}"
        for ip in ips:
            status, text = create_record_if_not_exists(record_name, ip, managed_records)
            statused_messages.append((status, text))
            time.sleep(0.2)

    csv_ips_set = {e["ip"] for e in proxy_data}
    records_to_delete = [r for r in managed_records if r["content"] not in csv_ips_set]
    if records_to_delete:
        statused_messages.extend(bulk_delete(records_to_delete))

    push_summary(statused_messages, proxy_data)

if __name__ == '__main__':
    main()
