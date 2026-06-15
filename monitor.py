"""
B站 UP 主动态监控 -> Server酱3 推送 (BiliDingBot 方案)
GitHub Actions 定时运行，免服务器
"""

import json, os, time, hashlib, urllib.parse, logging, sys
import http.cookiejar, urllib.request, urllib.error

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ==================== 配置 ====================
UID_LIST = [u.strip() for u in os.getenv("BILI_UID", "").split(",") if u.strip()]
NAME_LIST = [n.strip() for n in os.getenv("BILI_UP_NAME", "").split(",") if n.strip()]
SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "")
BILI_COOKIE = os.getenv("BILI_COOKIE", "")
REQUEST_INTERVAL = 2
STATE_FILE = "data/state.json"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

BILI_HOME = "https://www.bilibili.com/"
BILI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"
BILI_DYNAMIC_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
BILI_USER_API = "https://api.bilibili.com/x/space/wbi/acc/info"

MIXIN_TABLE = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52]
FALLBACK_MIXIN = "ea1db124af3c7062474693fa704f4ff8"

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
opener.addheaders = [("User-Agent", USER_AGENT)]
urllib.request.install_opener(opener)
# ==============================================


def fetch(url, referer=None, timeout=15):
    """HTTP GET，带 Cookie 和 Referer"""
    headers = {}
    if referer:
        headers["Referer"] = referer
    if BILI_COOKIE:
        headers["Cookie"] = BILI_COOKIE
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        log.error(f"HTTP {e.code}: {e.reason}")
        return None
    except Exception as e:
        log.error(f"请求失败: {e}")
        return None


def init_session():
    """初始化（不需要访问首页，直接用用户 Cookie）"""
    if BILI_COOKIE:
        log.info("使用用户 Cookie（包含 %d 个字段）", len(BILI_COOKIE.split(";")))
    else:
        log.warning("未设置 BILI_COOKIE，API 可能返回 412")


_wbi_mixin = None


def get_mixin_key():
    """获取 WBI mixin key（带缓存和降级）"""
    global _wbi_mixin
    if _wbi_mixin:
        return _wbi_mixin

    data = fetch(BILI_NAV_API, referer=BILI_HOME)
    if not data:
        log.warning("获取 WBI 密钥失败，使用降级 key")
        _wbi_mixin = FALLBACK_MIXIN
        return _wbi_mixin

    wbi = data.get("data", {}).get("wbi_img", {})
    img = wbi.get("img_url", "")
    sub = wbi.get("sub_url", "")
    if not img or not sub:
        _wbi_mixin = FALLBACK_MIXIN
        return _wbi_mixin

    raw = img.rsplit("/", 1)[-1].split(".")[0] + sub.rsplit("/", 1)[-1].split(".")[0]
    _wbi_mixin = "".join(raw[MIXIN_TABLE[i]] for i in range(64))[:32]
    log.info(f"WBI mixin key 已就绪")
    return _wbi_mixin


def sign_params(params):
    """WBI 签名（v2）- 值需 URL 编码"""
    mixin = get_mixin_key()
    params["wts"] = str(int(time.time()))
    sorted_keys = sorted(params.keys())
    query = "&".join(f"{k}={urllib.parse.quote(str(params[k]), safe='')}" for k in sorted_keys)
    params["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return params


def get_user_dynamics(uid, max_retries=2):
    """获取 UP 主最新动态"""
    global _wbi_mixin
    for attempt in range(max_retries):
        params = sign_params({"host_mid": uid})
        url = BILI_DYNAMIC_API + "?" + urllib.parse.urlencode(params)
        data = fetch(url, referer=f"https://space.bilibili.com/{uid}/dynamic")

        if data is None:
            time.sleep(3)
            continue

        code = data.get("code")
        if code == 0:
            return data.get("data", {}).get("items", [])

        if code == -352:  # WBI 签名过期
            log.warning("WBI 签名失效，刷新后重试")
            _wbi_mixin = None
            continue

        log.error(f"API code={code}, msg={data.get('message')}")
        return []

    log.error("重试耗尽，获取动态失败")
    return []


def get_user_name(uid):
    """获取 UP 主名称"""
    global _wbi_mixin
    params = sign_params({"mid": uid})
    url = BILI_USER_API + "?" + urllib.parse.urlencode(params)
    data = fetch(url, referer=f"https://space.bilibili.com/{uid}/")
    if data and data.get("code") == 0:
        return data["data"]["name"]
    return f"UID:{uid}"


def extract_dynamic(item):
    """从 polymer feed item 提取信息"""
    mid = item.get("id_str", "")
    modules = item.get("modules", {})
    author = modules.get("module_author", {})
    name = author.get("name", "未知")

    dyn = modules.get("module_dynamic") or {}
    major = dyn.get("major") or {}
    desc = dyn.get("desc") or {}
    text = desc.get("text", "")
    dyn_type = item.get("type", "")

    # WORD 类型 desc.text 可能为空，从 opus.summary.text 补充
    if not text:
        opus = major.get("opus") or {}
        text = (opus.get("summary") or {}).get("text", "")

    pics = []
    if dyn_type == "DYNAMIC_TYPE_DRAW":
        for it in (major.get("draw") or {}).get("items", []):
            s = it.get("src", "")
            if s:
                pics.append(s)
    elif dyn_type == "DYNAMIC_TYPE_WORD":
        for p in (major.get("opus") or {}).get("pics", []):
            u = p.get("url", "")
            if u:
                pics.append(u)

    pub_ts = author.get("pub_ts", 0)
    if pub_ts and isinstance(pub_ts, str):
        pub_ts = int(pub_ts)
    pub_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(pub_ts)) if pub_ts else ""

    return {
        "id": mid,
        "author": name,
        "text": text or "(无内容)",
        "time": pub_time,
        "type": dyn_type,
        "pics": pics,
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
        return False
    import re
    m = re.match(r"^sctp(\d+)t", SENDKEY)
    if not m:
        log.error("SendKey 格式不正确")
        return False
    url = f"https://{m.group(1)}.push.ft07.com/send/{SENDKEY}.send?" + urllib.parse.urlencode({"title": title, "desp": content})
    data = fetch(url)
    if data and data.get("code") == 0:
        log.info(f"推送成功: {title}")
        return True
    log.error(f"推送失败")
    return False


def main():
    log.info("=== B站动态监控 / Server酱3 ===")
    if not UID_LIST:
        log.error("未设置 BILI_UID")
        sys.exit(1)

    # 1. 初始化 Session（访问首页拿 Cookie）
    init_session()

    # 2. 预获取 WBI 密钥
    get_mixin_key()

    state = load_state()
    log.info(f"监控 {len(UID_LIST)} 个 UP 主")

    for idx, uid in enumerate(UID_LIST):
        log.info(f"[{idx+1}/{len(UID_LIST)}] UID: {uid}")

        name = NAME_LIST[idx] if idx < len(NAME_LIST) and NAME_LIST[idx] else get_user_name(uid)
        log.info(f"  UP 主: {name}")

        last_id = state["last_dynamic_ids"].get(uid, "")
        time.sleep(REQUEST_INTERVAL)

        items = get_user_dynamics(uid)
        if not items:
            log.info("  未获取到动态")
            continue

        log.info(f"  获取到 {len(items)} 条动态")
        new_dynamics = []
        latest_id = last_id

        for item in items:
            info = extract_dynamic(item)
            if not info["id"]:
                continue
            if info["id"] > latest_id:
                latest_id = info["id"]
            if last_id and info["id"] > last_id:
                new_dynamics.append(info)

        if not last_id:
            log.info(f"  首次运行，记录 ID: {latest_id}（不推送）")
        elif new_dynamics:
            log.info(f"  发现 {len(new_dynamics)} 条新动态!")
            for dyn in new_dynamics:
                link = f"https://t.bilibili.com/{dyn['id']}"
                pics = "".join(f"\n![图片]({u})" for u in dyn["pics"])
                content = f"### {dyn['author']} 发布了新动态\n\n**时间**: {dyn['time']}\n**类型**: {dyn['type']}\n\n---\n\n{dyn['text']}{pics}\n\n---\n\n[查看原动态]({link})"
                send_serverchan(f"{dyn['author']} 有新动态!", content)
                time.sleep(1)
        else:
            log.info("  没有新动态")

        state["last_dynamic_ids"][uid] = latest_id

    state["last_check_time"] = int(time.time())
    save_state(state)
    log.info("=== 本轮完成 ===")


if __name__ == "__main__":
    main()
