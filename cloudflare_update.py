import os
import requests

# ------------------------- 配置区 -------------------------
# 从环境变量中获取 Cloudflare API Token，可以是单个或多个（逗号分割）
cf_tokens_str = os.getenv("CF_TOKENS", "").strip()
if not cf_tokens_str:
    raise Exception("环境变量 CF_TOKENS 未设置或为空")
api_tokens = [token.strip() for token in cf_tokens_str.split(",") if token.strip()]

# 从环境变量中获取 Telegram Bot Token 和 Chat ID
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()
if not BOT_TOKEN or not CHAT_ID:
    raise Exception("Telegram Bot Token 或 Chat ID 未设置")

# 远程 IP 文件 URL
IP_LIST_URL = "https://raw.githubusercontent.com/fangovo/ip-fandai/refs/heads/main/proxyip_443_sorted.txt"

def send_telegram_message(text: str) -> None:
    """发送消息到 Telegram"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"  # 使用 HTML 格式
    }
    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"Telegram 推送失败: {response.status_code} {response.text}")
    else:
        print("Telegram 推送成功")

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
    return configs

# 获取最新子域名配置
subdomain_configs = fetch_subdomain_configs(IP_LIST_URL)
# -----------------------------------------------------------

# DNS 类型映射
dns_record_map = {
    "v4": "A",
    "v6": "AAAA"
}

# 获取 Cloudflare 第一个域区信息
def fetch_zone_info(api_token: str) -> tuple:
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
    response = requests.get("https://api.cloudflare.com/client/v4/zones", headers=headers)
    response.raise_for_status()
    zones = response.json().get("result", [])
    if not zones:
        raise Exception("未找到域区信息")
    return zones[0]["id"], zones[0]["name"]

# 更新 DNS 记录（删除或添加）
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
                send_telegram_message(f"成功添加 {subdomain} {dns_type} 记录: {ip}")  # 推送到 Telegram
            else:
                error_message = f"添加 {dns_type} 记录失败: {subdomain} IP {ip} 错误 {response.status_code} {response.text}"
                print(error_message)
                send_telegram_message(error_message)  # 错误信息推送到 Telegram

def main():
    try:
        for idx, token in enumerate(api_tokens, start=1):
            print("=" * 50)
            print(f"开始处理 API Token #{idx}")
            zone_id, domain = fetch_zone_info(token)
            print(f"域区 ID: {zone_id} | 域名: {domain}")
            
            for subdomain, version_ips in subdomain_configs.items():
                for version_key, ip_list in version_ips.items():
                    dns_type = dns_record_map.get(version_key)
                    if not dns_type:
                        continue
                    # 删除旧记录
                    update_dns_record(token, zone_id, subdomain, domain, dns_type, "delete")
                    # 添加新记录
                    if ip_list:
                        update_dns_record(token, zone_id, subdomain, domain, dns_type, "add", ip_list)
                    else:
                        print(f"{subdomain} ({dns_type}) 未获取到 IP")
            print(f"结束处理 API Token #{idx}")
            print("=" * 50 + "\n")
            send_telegram_message(f"API Token #{idx} 更新完毕！")  # 推送结束通知
    except Exception as err:
        error_message = f"错误: {err}"
        print(error_message)
        send_telegram_message(error_message)  # 错误信息推送到 Telegram

if __name__ == "__main__":
    main()
