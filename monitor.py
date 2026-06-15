"""
B站 UP 主动态监控 → Server酱 Turbo 推送
GitHub Actions 定时运行，免服务器
"""

import json
import os
import time
import hashlib
import urllib.request
import urllib.parse

# ==================== 配置 ====================
# UP 主 UID（修改这里）
UID = "3546768189622669"

# UP 主名称（可选，仅用于推送标题）
UP_NAME = ""

# Server酱 Turbo SendKey（从 GitHub Secrets 读取）
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


def get_user_dynamics(uid, offset_dynamic_id="0"):
    """获取 UP 主的空间动态列表（最新一页）"""
    mixin_key_raw = get_wbi_keys()
    if not mixin_key_raw:
        print("未获取到 WBI 密钥，尝试无签名请求")

    if mixin_key_raw:
        key_len = len(mixin_key_raw)
        mixin = ""
        table = mixin_key_table()
        for i in range(32):
            if table[i] < key_len:
                mixin += mixin_key_raw[table[i]]

        params = {
            "host_mid": uid,
            "offset_dynamic_id": offset_dynamic_id,
        }
        params = wbi_sign(params, mixin)
        url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?" + urllib.parse.urlencode(params)
    else:
        url = f"https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid={uid}&offset_dynamic_id={offset_dynamic_id}"

    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Referer": f"https://space.bilibili.com/{uid}/dynamic",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") == 0:
            items = data.get("data", {}).get("items", [])
            has_more = data.get("data", {}).get("has_more", False)
            return items, has_more
        else:
            print(f"API 返回异常: {data}")
            return [], False
    except Exception as e:
        print(f"获取动态失败: {e}")
        return [], False


def extract_dynamic_info(item):
    """从动态 item 中提取信息"""
    id_str = item.get("id_str", "")
    modules = item.get("modules", {})
    
    # 作者信息
    author = modules.get("module_author", {})
    author_name = author.get("name", "未知")
    
    # 动态内容
    dynamic = modules.get("module_dynamic", {})
    major = dynamic.get("major", {})
    desc = dynamic.get("desc", {})
    text = desc.get("text", "")
    
    dynamic_type = major.get("type", "")
    
    # 根据类型提取内容
    content_parts = [text] if text else []
    
    if dynamic_type == "MAJOR_TYPE_ARCHIVE":
        archive = major.get("archive", {})
        title = archive.get("title", "")
        cover = archive.get("cover", "")
        if title:
            content_parts.append(f"\n[视频] {title}")
        if cover:
            content_parts.append(f"\n![封面]({cover})")

    elif dynamic_type == "MAJOR_TYPE_ARTICLE":
        article = major.get("article", {})
        article_title = article.get("title", "")
        covers = article.get("covers", [])
        if article_title:
            content_parts.append(f"\n[专栏] {article_title}")
        for c in covers:
            content_parts.append(f"\n![图片]({c})")

    elif dynamic_type == "MAJOR_TYPE_DRAW":
        draw = major.get("draw", {})
        items_list = draw.get("items", [])
        for it in items_list:
            src = it.get("src", "")
            if src:
                content_parts.append(f"\n![图片]({src})")

    elif dynamic_type == "MAJOR_TYPE_LIVE_RCMD":
        content_parts.append("\n[直播] UP 主正在直播！")

    elif dynamic_type == "MAJOR_TYPE_OPUS":
        opus = major.get("opus", {})
        summary = opus.get("summary", {}).get("text", "")
        pics = opus.get("pics", [])
        if summary:
            content_parts.append(summary)
        for p in pics:
            src = p.get("url", "")
            if src:
                content_parts.append(f"\n![图片]({src})")

    # 转发中的原始动态
    if dynamic_type == "MAJOR_TYPE_NONE":
        topic = modules.get("module_topic")
        if topic:
            topic_name = topic.get("name", "")
            if topic_name:
                content_parts.append(f"\n[话题] {topic_name}")

    # 发布时间
    pub_ts = author.get("pub_ts", 0)
    pub_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(pub_ts)) if pub_ts else ""

    return {
        "id": id_str,
        "author": author_name,
        "text": "\n".join(content_parts) if content_parts else "(无内容)",
        "time": pub_time,
        "timestamp": pub_ts,
        "type": dynamic_type,
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
    """通过 Server酱 Turbo 推送消息"""
    if not SENDKEY:
        print("未设置 SERVERCHAN_SENDKEY，跳过推送")
        return False

    url = f"https://sctapi.ftqq.com/{SENDKEY}.send"
    data = json.dumps({
        "title": title,
        "desp": content,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("code") == 0:
            print(f"✅ Server酱推送成功: {title}")
            return True
        else:
            print(f"❌ Server酱推送失败: {result.get('message', '未知错误')}")
            return False
    except Exception as e:
        print(f"❌ Server酱推送异常: {e}")
        return False


def format_push_content(dynamic_info):
    """格式化推送内容为 Markdown"""
    link = f"https://t.bilibili.com/{dynamic_info['id']}"
    
    content = f"""### {dynamic_info['author']} 发布了新动态

**时间**: {dynamic_info['time']}
**类型**: {dynamic_info['type']}

---

{dynamic_info['text']}

---

[🔗 查看原动态]({link})
"""
    return content


def main():
    print(f"=== B站动态监控 (Server酱 Turbo) ===")
    print(f"目标 UID: {UID}")

    # 获取 UP 主名称
    user_info = get_user_info(UID)
    up_name = UP_NAME or user_info.get("name", f"UID:{UID}")
    print(f"UP 主: {up_name}")

    # 加载状态
    state = load_state()
    last_id = state["last_dynamic_ids"].get(UID, "")
    print(f"上次记录动态 ID: {last_id}")

    # 获取最新动态
    time.sleep(REQUEST_INTERVAL)
    items, has_more = get_user_dynamics(UID)

    if not items:
        print("未获取到动态数据，可能被限流或接口异常")
        return

    print(f"获取到 {len(items)} 条动态")

    # 找出新动态（ID 大于上次记录的）
    new_dynamics = []
    latest_id = last_id

    for item in items:
        info = extract_dynamic_info(item)
        if not info["id"]:
            continue

        # 更新最新 ID
        if info["id"] > latest_id:
            latest_id = info["id"]

        # 如果是第一次运行（没有历史记录），只记录不推送
        if not last_id:
            continue

        # 动态 ID 大于上次记录的，视为新动态
        if info["id"] > last_id:
            new_dynamics.append(info)

    # 推送新动态
    if not last_id:
        print(f"首次运行，记录最新动态 ID: {latest_id}（不推送，避免刷屏）")
    elif new_dynamics:
        print(f"\n发现 {len(new_dynamics)} 条新动态！")
        for dyn in new_dynamics:
            title = f"{dyn['author']} 有新动态！"
            content = format_push_content(dyn)
            success = send_serverchan(title, content)
            if not success:
                print(f"推送失败: {dyn['id']}")
            time.sleep(1)  # 推送间隔
    else:
        print("没有新动态")

    # 更新状态
    state["last_dynamic_ids"][UID] = latest_id
    state["last_check_time"] = int(time.time())
    save_state(state)
    print(f"状态已更新: last_dynamic_id = {latest_id}")


if __name__ == "__main__":
    main()
