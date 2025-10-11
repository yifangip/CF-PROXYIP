import os
import requests
from datetime import datetime

# ------------------------- 配置区 -------------------------
# 从环境变量中获取 Cloudflare API Token
cf_tokens_str = os.getenv("CF_TOKENS", "").strip()
if not cf_tokens_str:
    raise Exception("环境变量 CF_TOKENS 未设置或为空")
api_tokens = [token.strip() for token in cf_tokens_str.split(",") if token.strip()]

# Telegram Bot 配置
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()
if not BOT_TOKEN or not CHAT_ID:
    raise Exception("Telegram BOT_TOKEN 或 CHAT_ID 未设置")

# 远程 IP 文件 URL
IP_LIST_URL = "https://raw.githubusercontent.com/fangovo/ip-fandai/refs/heads/main/proxyip_443_sorted.txt"

# ------------------------- Telegram 推送函数 -------------------------
def send_telegram_message(text: str, log_file_url: str = None) -> None:
    """发送消息到 Telegram"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    message = f"<b>📢 Cloudflare DNS 同步汇总</b>\n\n🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{text}"
    if log_file_url:
        message += f"\n\n📄 <a href='{log_file_url}'>日志文件已上传</a>"
    
    params = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"Telegram 推送失败: {response.status_code} {response.text}")
    else:
        print("Telegram 推送成功")

# ------------------------- 生成 IP 配置 -------------------------
def fetch_subdomain_configs(url: str) -> dict:
    """
    从远程文件生成子域名配置
    文件格式: 每行 ip#country（可能带端口）
    返回格式: { 'proxyip_国家': {"v4": [ip1, ip2, ...]} }
    """
    response = requests.get(url)
    response.raise_for_status()
    lines = response.text.strip().split('\n')
    configs = {}
    ip_counts = {}  # 国家 IP 数量统计
    total_ips = 0  # 获取到的总 IP 数量
    log_entries = []  # 日志条目列表

    for line in lines:
        if not line.strip() or "#" not in line:
            continue
        ip_raw, country = line.strip().split("#", 1)
        ip = ip_raw.split(":")[0].strip()  # 去掉端口，只保留 IP
        country = country.strip().lower()  # 小写化

        if not ip or not country:
            continue

        subdomain_name = f"proxyip_{country}"
        if subdomain_name not in configs:
            configs[subdomain_name] = {"v4": []}
        configs[subdomain_name]["v4"].append(ip)

        # 更新国家的 IP 数量统计
        if country not in ip_counts:
            ip_counts[country] = 0
        ip_counts[country] += 1
        total_ips += 1
        log_entries.append(f"{subdomain_name} → {ip}")

    return configs, ip_counts, total_ips, log_entries

# ------------------------- 更新 DNS 记录 -------------------------
def update_dns_record(api_token: str, zone_id: str, subdomain: str, domain: str, dns_type: str, operation: str, ip_list: list = None) -> None:
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
    full_record_name = domain if subdomain == "@" else f"{subdomain}.{domain}"

    if operation == "delete":
        while True:
            query_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type={dns_type}&name={full_record_name}"
            response = requests.get(query_url, headers=headers)
            response.raise_for_status()
            records = response.json().get("result", [])
            if not records:
                break
            for record in records:
                delete_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record['id']}"
                del_resp = requests.delete(delete_url, headers=headers)
                del_resp.raise_for_status()
                print(f"删除 {subdomain} {dns_type} 记录: {record['id']}")
    elif operation == "add" and ip_list is not None:
        for ip in ip_list:
            payload = {
                "type": dns_type,
                "name": full_record_name,
                "content": ip,
                "ttl": 1,
                "proxied": False
            }
            response = requests.post(f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
                                     json=payload, headers=headers)
            if response.status_code == 200 or response.status_code == 201:
                print(f"添加 {subdomain} {dns_type} 记录: {ip}")
            else:
                print(f"添加 {dns_type} 记录失败: {subdomain} IP {ip} 错误 {response.status_code} {response.text}")

# ------------------------- 主函数 -------------------------
def main():
    try:
        configs, ip_counts, total_ips, log_entries = fetch_subdomain_configs(IP_LIST_URL)
        log_file_name = f"proxyip_sync_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        # 将日志写入文件
        with open(log_file_name, "w") as log_file:
            log_file.write("\n".join(log_entries))

        # 上传日志文件到 Telegram
        send_telegram_message(
            text=f"总共获取 IP：{total_ips}\n\n*🌎 各国家 IP 数量统计:*\n" + 
            "\n".join([f"• {country.upper()}: `{count}` 条" for country, count in ip_counts.items()]),
            log_file_url=None  # 可将日志文件上传到云存储并传递链接，这里留空
        )

        # 进行 DNS 更新操作
        for idx, token in enumerate(api_tokens, start=1):
            print("=" * 50)
            print(f"开始处理 API Token #{idx}")
            zone_id, domain = fetch_zone_info(token)
            print(f"域区 ID: {zone_id} | 域名: {domain}")

            for subdomain, version_ips in configs.items():
                for version_key, ip_list in version_ips.items():
                    dns_type = "A"  # 目前只处理 A 记录
                    # 删除旧记录
                    update_dns_record(token, zone_id, subdomain, domain, dns_type, "delete")
                    # 添加新记录
                    if ip_list:
                        update_dns_record(token, zone_id, subdomain, domain, dns_type, "add", ip_list)
                    else:
                        print(f"{subdomain} ({dns_type}) 未获取到 IP")
            print(f"结束处理 API Token #{idx}")
            print("=" * 50 + "\n")

    except Exception as err:
        error_message = f"错误: {err}"
        print(error_message)
        send_telegram_message(error_message)  # 错误信息推送到 Telegram

if __name__ == "__main__":
    main()
