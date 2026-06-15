"""
B站 UP 主动态监控 → Server酱³ 推送
GitHub Actions 定时运行，免服务器
"""

import json
import os
import time
import hashlib
import urllib.request
import urllib.parse

# ==================== 配置 ====================
# UP 主 UID，多个用英文逗号分隔（从 GitHub Secrets 读取）
# 示例：BILI_UID = "123,456,789"
UID_LIST = [u.strip() for u in os.getenv("BILI_UID", "").split(",") if u.strip()]

# UP 主名称，多个用英文逗号分隔（可选，留空自动获取）
NAME_LIST = [n.strip() for n in os.getenv("BILI_UP_NAME", "").split(",") if n.strip()]

# Server酱³ SendKey（从 GitHub Secrets 读取，形如 sctp12345t...）
SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "")

# 请求间隔（秒），防止被 B 站限流
REQUEST_INTERVAL = 2

# 状态文件路径
STATE_FILE = "data/state.json"

# B站 API 基础配置
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
# ==============================================


def get_wbi_keys():
    """获取 B 站 WBI 签名密钥"""
    url = "https://api.bilibili.com/x/web-interface/nav"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        img_url = data["data"]["wbi_img"]["img_url"]
        sub_url = data["data"]["wbi_img"]["sub_url"]
        img_key = img_url.split("/")[-1].split(".")[0]
        sub_key = sub_url.split("/")[-1].split(".")[0]
        return img_key + sub_key
    except Exception as e:
        print(f"获取 WBI 密钥失败: {e}")
        return None


def mixin_key_table():
    """WBI 混淆映射表"""
    return [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
            27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
            37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
            22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]


def wbi_sign(params, mixin_key):
    """对请求参数进行 WBI 签名"""
    # 对 key 排序
    sorted_keys = sorted(params.keys())
    # 拼成 query string
    query = "&".join(f"{k}={params[k]}" for k in sorted_keys)
    # 计算 md5
    sign_str = query + mixin_key
    w_rid = hashlib.md5(sign_str.encode()).hexdigest()
    params["w_rid"] = w_rid
    params["wts"] = int(time.time())
    return params


def get_user_info(uid):
    """获取 UP 主基本信息（名称）"""
    mixin_key_raw = get_wbi_keys()
    if not mixin_key_raw:
        print("未获取到 WBI 密钥，跳过签名")
        return {"name": f"UID:{uid}"}

    mixin_key = "".join(mixin_key_table()[i] for i in range(len(mixin_key_raw)) 
                        if i < len(mixin_key_raw)) if len(mixin_key_raw) >= 64 else mixin_key_raw

    # 重新实现正确的 WBI 混淆
    key_len = len(mixin_key_raw)
    mixin = ""
    table = mixin_key_table()
    for i in range(32):
        if table[i] < key_len:
            mixin += mixin_key_raw[table[i]]
    for i in range(32, 64):
        if table[i] < key_len:
            mixin += mixin_key_raw[table[i]]

    params = {"mid": uid}
    params = wbi_sign(params, mixin)

    url = "https://api.bilibili.com/x/space/wbi/acc/info?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Referer": f"https://space.bilibili.com/{uid}/",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") == 0:
            return {"name": data["data"]["name"]}
    except Exception as e:
        print(f"获取用户信息失败: {e}")

    return {"name": f"UID:{uid}"}


def get_user_dynamics(uid):
    """获取 UP 主的最新动态（使用旧版 API，无需 WBI 签名）"""
    url = f"https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/space_history?host_uid={uid}&offset_dynamic_id=0"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Referer": f"https://space.bilibili.com/{uid}/dynamic",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") == 0:
            cards = data.get("data", {}).get("cards", [])
            return cards
        else:
            print(f"API 返回异常: code={data.get('code')}, msg={data.get('message')}")
            return []
    except Exception as e:
        print(f"获取动态失败: {e}")
        return []


def extract_dynamic_info(card):
    """从动态 card 中提取信息（space_history 格式）"""
    desc = card.get("desc", {})
    dynamic_id = str(desc.get("dynamic_id_str") or desc.get("dynamic_id", ""))
    timestamp = desc.get("timestamp", 0)
    uname = "未知"
    user_profile = desc.get("user_profile", {})
    if user_profile:
        uname = user_profile.get("info", {}).get("uname", "未知")

    # 解析动态类型
    card_type = desc.get("type", 0)
    type_names = {
        1: "转发", 2: "图文", 4: "纯文字", 8: "视频投稿",
        16: "小视频", 64: "专栏", 256: "音频",
        512: "直播", 2048: "直播", 4200: "直播预约",
    }
    dynamic_type = type_names.get(card_type, f"未知类型({card_type})")

    # 解析 card JSON 内容
    text_content = ""
    pic_urls = []
    try:
        card_json = json.loads(card.get("card", "{}"))
        item = card_json.get("item", {})

        # 文字内容
        text_content = item.get("description", "") or item.get("content", "") or ""
        if not text_content:
            # 转发动态取 origin 的内容
            origin = card_json.get("origin", "")
            if origin:
                try:
                    origin_json = json.loads(origin) if isinstance(origin, str) else origin
                    text_content = origin_json.get("item", {}).get("description", "") or "（转发动态）"
                except:
                    text_content = "（转发动态）"

        # 图片
        pictures = item.get("pictures", [])
        for p in pictures:
            src = p.get("img_src", "")
            if src:
                pic_urls.append(src)

        # 视频标题
        title = item.get("title", "") or card_json.get("title", "")
        if title and card_type in (8, 16):
            text_content = f"[视频] {title}\n{text_content}"

        # 专栏标题
        if title and card_type == 64:
            text_content = f"[专栏] {title}\n{text_content}"

    except Exception as e:
        text_content = f"(解析失败: {e})"

    pub_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)) if timestamp else ""

    return {
        "id": dynamic_id,
        "author": uname,
        "text": text_content or "(无内容)",
        "time": pub_time,
        "timestamp": timestamp,
        "type": dynamic_type,
        "pics": pic_urls,
    }


def load_state():
    """读取持久化状态"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"last_dynamic_ids": {}, "last_check_time": 0}


def save_state(state):
    """保存持久化状态"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_serverchan(title, content):
    """通过 Server酱³ 推送消息"""
    if not SENDKEY:
        print("未设置 SERVERCHAN_SENDKEY，跳过推送")
        return False

    # Server酱³ SendKey 格式: sctp<uid>t... ，自动提取 uid
    import re
    match = re.match(r"^sctp(\d+)t", SENDKEY)
    if not match:
        print("SendKey 格式不正确，应为 Server酱³ 的 SendKey（形如 sctp...t...）")
        return False

    uid = match.group(1)
    url = f"https://{uid}.push.ft07.com/send/{SENDKEY}.send"

    # GET 方式，参数放 query string
    params = urllib.parse.urlencode({
        "title": title,
        "desp": content,
    })
    url = url + "?" + params

    req = urllib.request.Request(url, headers={
        "User-Agent": "BiliServerChan/1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("code") == 0:
            print(f"✅ Server酱³ 推送成功: {title}")
            return True
        else:
            print(f"❌ Server酱³ 推送失败: {result.get('message', '未知错误')}")
            return False
    except Exception as e:
        print(f"❌ Server酱³ 推送异常: {e}")
        return False


def format_push_content(dynamic_info):
    """格式化推送内容为 Markdown"""
    link = f"https://t.bilibili.com/{dynamic_info['id']}"

    # 图片
    pics_md = ""
    for url in dynamic_info.get("pics", []):
        pics_md += f"\n![图片]({url})"

    content = f"""### {dynamic_info['author']} 发布了新动态

**时间**: {dynamic_info['time']}
**类型**: {dynamic_info['type']}

---

{dynamic_info['text']}
{pics_md}

---

[🔗 查看原动态]({link})
"""
    return content


def get_user_name_cache(uid, idx):
    """获取 UP 主名称，优先用配置的 NAME_LIST，其次调 API"""
    if idx < len(NAME_LIST) and NAME_LIST[idx]:
        return NAME_LIST[idx]
    try:
        info = get_user_info(uid)
        return info.get("name", f"UID:{uid}")
    except:
        return f"UID:{uid}"


def main():
    print(f"=== B站动态监控 (Server酱³) ===")

    if not UID_LIST:
        print("❌ 未设置 BILI_UID，请在 GitHub Secrets 中配置（多个用英文逗号分隔）")
        print("   示例: BILI_UID = 123,456,789")
        return

    print(f"监控 {len(UID_LIST)} 个 UP 主: {', '.join(UID_LIST)}")

    # 加载状态
    state = load_state()

    for idx, uid in enumerate(UID_LIST):
        print(f"\n--- [{idx+1}/{len(UID_LIST)}] UID: {uid} ---")

        # 获取 UP 主名称
        up_name = get_user_name_cache(uid, idx)
        print(f"UP 主: {up_name}")

        last_id = state["last_dynamic_ids"].get(uid, "")
        print(f"上次记录动态 ID: {last_id}")

        # 获取最新动态（旧版 API，稳定无需 WBI）
        time.sleep(REQUEST_INTERVAL)
        cards = get_user_dynamics(uid)

        if not cards:
            print("未获取到动态数据，可能被限流或接口异常")
            continue

        print(f"获取到 {len(cards)} 条动态")

        # 找出新动态
        new_dynamics = []
        latest_id = last_id

        for card in cards:
            info = extract_dynamic_info(card)
            if not info["id"]:
                continue

            if info["id"] > latest_id:
                latest_id = info["id"]

            if not last_id:
                continue

            if info["id"] > last_id:
                new_dynamics.append(info)

        # 推送新动态
        if not last_id:
            print(f"首次运行，记录最新动态 ID: {latest_id}（不推送）")
        elif new_dynamics:
            print(f"发现 {len(new_dynamics)} 条新动态！")
            for dyn in new_dynamics:
                title = f"{dyn['author']} 有新动态！"
                content = format_push_content(dyn)
                success = send_serverchan(title, content)
                if not success:
                    print(f"推送失败: {dyn['id']}")
                time.sleep(1)
        else:
            print("没有新动态")

        # 更新状态
        state["last_dynamic_ids"][uid] = latest_id

    state["last_check_time"] = int(time.time())
    save_state(state)
    print(f"\n=== 本轮检查完成 ===")


if __name__ == "__main__":
    main()
