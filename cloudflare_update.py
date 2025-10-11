import os
import requests
from datetime import datetime

# ------------------------- 配置区 -------------------------
cf_tokens_str = os.getenv("CF_TOKENS", "").strip()
if not cf_tokens_str:
    raise Exception("环境变量 CF_TOKENS 未设置或为空")
api_tokens = [token.strip() for token in cf_tokens_str.split(",") if token.strip()]

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()
if not BOT_TOKEN or not CHAT_ID:
    raise Exception("Telegram BOT_TOKEN 或 CHAT_ID 未设置")

IP_LIST_URL = "https://raw.githubusercontent.com/fangovo/ip-fandai/refs/heads/main/proxyip_443_sorted.txt"

MAX_IPS_PER_SUBDOMAIN = 150  # 避免 Cloudflare 记录超限，每个子域名最多添加多少 IP

# ------------------------- Telegram 推送 -------------------------
def send_telegram_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"Telegram 推送失败: {response.status_code} {response.text}")
    else:
        print("Telegram 推送成功")

def send_telegram_file(file_path: str, ip_counts: dict, total_ips: int) -> None:
    """发送日志文件到 Telegram，文件提示在国家统计后显示"""
    stats_text = f"🌍 总共获取 IP：{total_ips}\n*🌎 各国家 IP 数量统计:*\n" + \
                 "\n".join([f"• {k.upper()}: `{v}` 条" for k, v in ip_counts.items()])
    caption = f"{stats_text}\n📄 日志文件已上传"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(file_path, "rb") as f:
        files = {"document": f}
        data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"}
        response = requests.post(url, files=files, data=data)
        if response.status_code != 200:
            print(f"Telegram 文件上传失败: {response.status_code} {response.text}")
        else:
            print("Telegram 文件上传成功")

# ------------------------- Cloudflare 函数 -------------------------
def fetch_zone_info(api_token: str) -> tuple:
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    response = requests.get("https://api.cloudflare.com/client/v4/zones", headers=headers)
    response.raise_for_status()
    zones = response.json().get("result", [])
    if not zones:
        raise Exception("未找到域区信息")
    return zones[0]["id"], zones[0]["name"]

def fetch_subdomain_configs(url: str):
    response = requests.get(url)
    response.raise_for_status()
    lines = response.text.strip().split('\n')

    configs, ip_counts, total_ips, log_entries = {}, {}, 0, []

    for line in lines:
        if not line.strip() or "#" not in line:
            continue
        ip_raw, country = line.strip().split("#", 1)
        ip = ip_raw.split(":")[0].strip()
        country = country.strip().lower()
        if not ip or not country:
            continue
        subdomain = f"proxyip_{country}"
        if subdomain not in configs:
            configs[subdomain] = {"v4": []}
        configs[subdomain]["v4"].append(ip)
        ip_counts[country] = ip_counts.get(country, 0) + 1
        total_ips += 1
        log_entries.append(f"{subdomain} → {ip}")

    return configs, ip_counts, total_ips, log_entries

def update_dns_record(api_token, zone_id, subdomain, domain, dns_type, operation, ip_list=None):
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    full_name = domain if subdomain == "@" else f"{subdomain}.{domain}"

    if operation == "delete":
        while True:
            query_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type={dns_type}&name={full_name}"
            response = requests.get(query_url, headers=headers)
            response.raise_for_status()
            records = response.json().get("result", [])
            if not records:
                break
            for record in records:
                delete_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record['id']}"
                requests.delete(delete_url, headers=headers)
                print(f"删除 {subdomain} {dns_type} 记录: {record['id']}")

    elif operation == "add" and ip_list:
        ip_list = ip_list[:MAX_IPS_PER_SUBDOMAIN]  # 限制 IP 数量
        for ip in ip_list:
            payload = {"type": dns_type, "name": full_name, "content": ip, "ttl": 1, "proxied": False}
            resp = requests.post(f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
                                 headers=headers, json=payload)
            if resp.status_code in (200, 201):
                print(f"添加 {subdomain} {dns_type} 记录: {ip}")
            else:
                print(f"添加 {dns_type} 记录失败: {subdomain} IP {ip} 错误 {resp.status_code} {resp.text}")

# ------------------------- 主函数 -------------------------
def main():
    try:
        configs, ip_counts, total_ips, log_entries = fetch_subdomain_configs(IP_LIST_URL)

        # 写日志文件
        log_file_name = f"proxyip_sync_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(log_file_name, "w") as f:
            f.write("\n".join(log_entries))

        # Telegram 上传日志文件并附带国家统计
        send_telegram_file(log_file_name, ip_counts, total_ips)

        # DNS 更新
        for idx, token in enumerate(api_tokens, start=1):
            print("="*50)
            print(f"开始处理 API Token #{idx}")
            zone_id, domain = fetch_zone_info(token)
            print(f"域区 ID: {zone_id} | 域名: {domain}")

            for subdomain, version_ips in configs.items():
                for dns_type, ip_list in version_ips.items():
                    update_dns_record(token, zone_id, subdomain, domain, "A", "delete")
                    update_dns_record(token, zone_id, subdomain, domain, "A", "add", ip_list)

            print(f"结束处理 API Token #{idx}")
            print("="*50 + "\n")

    except Exception as e:
        print(f"错误: {e}")
        send_telegram_message(f"错误: {e}")

if __name__ == "__main__":
    main()
