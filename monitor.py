"""
B站 UP 主动态监控 -> Server酱3 推送
GitHub Actions 定时运行，免服务器
"""

import json
import os
import time
import hashlib
import urllib.request
import urllib.parse
import urllib.error

# ==================== 配置 ====================
UID_LIST = [u.strip() for u in os.getenv("BILI_UID", "").split(",") if u.strip()]
NAME_LIST = [n.strip() for n in os.getenv("BILI_UP_NAME", "").split(",") if n.strip()]
SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "")
BILI_COOKIE = os.getenv("BILI_COOKIE", "buvid3=infoc;")  # 填写你的 B站 Cookie 能提高成功率
REQUEST_INTERVAL = 2
STATE_FILE = "data/state.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

MIXIN_TABLE = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
               27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
               37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
               22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]

_WBI_MIXIN = None
# ==============================================


def fetch_wbi_mixin():
    """获取 WBI 混淆密钥（仅获取一次）"""
    global _WBI_MIXIN
    if _WBI_MIXIN:
        return _WBI_MIXIN
    url = "https://api.bilibili.com/x/web-interface/nav"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Cookie": BILI_COOKIE,
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        wbi = data["data"]["wbi_img"]
        raw = wbi["img_url"].split("/")[-1].split(".")[0] + wbi["sub_url"].split("/")[-1].split(".")[0]
        _WBI_MIXIN = "".join(raw[MIXIN_TABLE[i]] for i in range(32))
        print(f"WBI 密钥获取成功")
        return _WBI_MIXIN
    except Exception as e:
        print(f"获取 WBI 密钥失败: {e}")
        return None


def sign_params(params, mixin):
    """对参数做 WBI 签名"""
    sorted_keys = sorted(params.keys())
    query = "&".join(f"{k}={params[k]}" for k in sorted_keys)
    params["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    params["wts"] = int(time.time())
    return params


def http_get(url, extra_headers=None):
    """统一的 HTTP GET 请求"""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.bilibili.com/",
        "Cookie": BILI_COOKIE,
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"请求失败: {e}")
        return None


def get_user_info(uid):
    """获取 UP 主名称"""
    mixin = fetch_wbi_mixin()
    if not mixin:
        return {"name": f"UID:{uid}"}
    params = sign_params({"mid": uid}, mixin)
    url = "https://api.bilibili.com/x/space/wbi/acc/info?" + urllib.parse.urlencode(params)
    data = http_get(url, {"Referer": f"https://space.bilibili.com/{uid}/"})
    if data and data.get("code") == 0:
        return {"name": data["data"]["name"]}
    return {"name": f"UID:{uid}"}


def get_user_dynamics(uid):
    """获取 UP 主最新动态（polymer feed API，需 Cookie + WBI）"""
    mixin = fetch_wbi_mixin()
    if not mixin:
        print("无法获取 WBI 密钥，跳过")
        return []

    params = sign_params({
        "host_mid": uid,
        "platform": "web",
        "web_location": "333.1387",
        "features": "itemOpusStyle,listOnlyfans,opusBigCover,forwardListHidden",
    }, mixin)

    url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?" + urllib.parse.urlencode(params)
    data = http_get(url, {"Referer": f"https://space.bilibili.com/{uid}/dynamic"})

    if not data:
        return []
    if data.get("code") != 0:
        print(f"API code={data.get('code')}, msg={data.get('message')}")
        return []

    return data.get("data", {}).get("items", [])


def extract_dynamic_info(item):
    """从 polymer feed item 中提取动态信息"""
    id_str = item.get("id_str", "")
    modules = item.get("modules", {})
    author = modules.get("module_author", {})
    author_name = author.get("name", "未知")
    pub_ts = author.get("pub_ts", 0)

    dyn = modules.get("module_dynamic", {})
    major = dyn.get("major", {})
    dyn_type = major.get("type", "")
    text = dyn.get("desc", {}).get("text", "")

    parts = [text] if text else []
    pic_urls = []

    if dyn_type == "MAJOR_TYPE_ARCHIVE":
        a = major.get("archive", {})
        t = a.get("title", "")
        if t:
            parts.append(f"\n[视频] {t}")
    elif dyn_type == "MAJOR_TYPE_DRAW":
        for it in major.get("draw", {}).get("items", []):
            s = it.get("src", "")
            if s:
                pic_urls.append(s)
    elif dyn_type == "MAJOR_TYPE_ARTICLE":
        a = major.get("article", {})
        t = a.get("title", "")
        if t:
            parts.append(f"\n[专栏] {t}")
    elif dyn_type == "MAJOR_TYPE_OPUS":
        opus = major.get("opus", {})
        s = opus.get("summary", {}).get("text", "")
        if s:
            parts.append(s)
        for p in opus.get("pics", []):
            u = p.get("url", "")
            if u:
                pic_urls.append(u)
    elif dyn_type == "MAJOR_TYPE_LIVE_RCMD":
        parts.append("\n[直播] UP 主正在直播!")
    elif dyn_type == "MAJOR_TYPE_NONE":
        topic = modules.get("module_topic", {}).get("name", "")
        if topic:
            parts.append(f"\n[话题] {topic}")

    pub_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(pub_ts)) if pub_ts else ""

    return {
        "id": id_str,
        "author": author_name,
        "text": "\n".join(parts) if parts.strip() else "(无内容)",
        "time": pub_time,
        "timestamp": pub_ts,
        "type": dyn_type.replace("MAJOR_TYPE_", ""),
        "pics": pic_urls,
    }


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"last_dynamic_ids": {}, "last_check_time": 0}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_serverchan(title, content):
    if not SENDKEY:
        print("未设置 SERVERCHAN_SENDKEY")
        return False
    import re
    m = re.match(r"^sctp(\d+)t", SENDKEY)
    if not m:
        print("SendKey 格式不正确 (应为 sctp...t...)")
        return False
    url = f"https://{m.group(1)}.push.ft07.com/send/{SENDKEY}.send?" + urllib.parse.urlencode({"title": title, "desp": content})
    data = http_get(url)
    if data:
        if data.get("code") == 0:
            print(f"Server酱3 推送成功: {title}")
            return True
        print(f"Server酱3 推送失败: {data.get('message')}")
    return False


def format_push_content(dyn):
    link = f"https://t.bilibili.com/{dyn['id']}"
    pics = "".join(f"\n![图片]({u})" for u in dyn.get("pics", []))
    return f"""### {dyn['author']} 发布了新动态

**时间**: {dyn['time']}
**类型**: {dyn['type']}

---

{dyn['text']}
{pics}

---

[查看原动态]({link})
"""


def main():
    print("=== B站动态监控 (Server酱3) ===")
    if not UID_LIST:
        print("未设置 BILI_UID")
        return

    print(f"Cookie: {'已设置' if BILI_COOKIE != 'buvid3=infoc;' else '仅 buvid3（部分 API 可能受限）'}")
    print(f"监控 {len(UID_LIST)} 个 UP 主: {', '.join(UID_LIST)}")

    # 预加载 WBI 密钥
    fetch_wbi_mixin()
    state = load_state()

    for idx, uid in enumerate(UID_LIST):
        print(f"\n--- [{idx+1}/{len(UID_LIST)}] UID: {uid} ---")

        name = NAME_LIST[idx] if idx < len(NAME_LIST) and NAME_LIST[idx] else get_user_info(uid).get("name", f"UID:{uid}")
        print(f"UP 主: {name}")

        last_id = state["last_dynamic_ids"].get(uid, "")
        time.sleep(REQUEST_INTERVAL)

        items = get_user_dynamics(uid)
        if not items:
            print("未获取到动态数据（可能需要有效的 BILI_COOKIE）")
            continue

        print(f"获取到 {len(items)} 条动态")
        new_dynamics = []
        latest_id = last_id

        for item in items:
            info = extract_dynamic_info(item)
            if not info["id"]:
                continue
            if info["id"] > latest_id:
                latest_id = info["id"]
            if last_id and info["id"] > last_id:
                new_dynamics.append(info)

        if not last_id:
            print(f"首次运行，记录最新 ID: {latest_id}（不推送）")
        elif new_dynamics:
            print(f"发现 {len(new_dynamics)} 条新动态!")
            for dyn in new_dynamics:
                send_serverchan(f"{dyn['author']} 有新动态!", format_push_content(dyn))
                time.sleep(1)
        else:
            print("没有新动态")

        state["last_dynamic_ids"][uid] = latest_id

    state["last_check_time"] = int(time.time())
    save_state(state)
    print(f"\n=== 本轮完成 ===")


if __name__ == "__main__":
    main()
