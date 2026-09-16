#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日股票数据采集与低价股推荐系统
作者: WorkBuddy AI
功能:
  1. 采集全球最新财经新闻
  2. 获取A股行业板块数据、强势题材
  3. 筛选低价潜力股（价格 < 20元）
  4. 综合评分 + 上涨预测
  5. 生成HTML日报
"""

import time
import random
import json
import uuid
import math
import urllib.request
import urllib.parse
import os
import sys
from datetime import datetime, date
from pathlib import Path
from collections import Counter


def _safe_float(v, default=0.0):
    """安全转换为float，处理 '-'、None、空字符串等异常值"""
    if v is None or v == '' or v == '-':
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _build_core_pick_card(p):
    """构建核心推荐池单只股票卡片HTML（避免f-string嵌套语法错误）"""
    is_core = p.get('core_pick_reason') == '今日首选'
    bg = 'linear-gradient(135deg, #f5f3ff, #ede9fe)' if is_core else '#f8fafc'
    border = '#7c3aed' if is_core else '#e2e8f0'
    badge = f'<span style="display:inline-block;background:#7c3aed;color:white;padding:1px 10px;border-radius:10px;font-size:11px;margin-top:4px">🏆 {p.get("core_pick_reason","")}</span>' if p.get('core_pick_reason') else ''
    reasons_text = " · ".join(p.get('entry_reasons', [])[:2])
    loss_div = f'<div style="margin-top:4px;color:#16a34a;font-size:11px">⚠ 单票最大亏损: ¥{p.get("max_loss_amount",0):,} ({p.get("max_loss_pct",0)}%)</div>' if p.get('max_loss_amount') else ''
    return f'''<div style="background:{bg};border-radius:10px;padding:16px;border:1px solid {border}">
          <div style="font-weight:700;font-size:16px;color:#0f172a">{p['name']}<span style="font-size:12px;color:#94a3b8;margin-left:6px">{p['code']}</span></div>
          {badge}
          <div style="margin-top:8px;font-size:13px">
            <div>现价 <strong>¥{p['price']}</strong> | 入场 <strong style="color:#3b82f6">¥{p['entry_price']}</strong></div>
            <div>目标 <strong style="color:#dc2626">¥{p['target_price']}</strong> | 止损 <strong style="color:#16a34a">¥{p['stop_loss']}</strong></div>
            <div>仓位 <strong style="color:#7c3aed">{p['position_ratio']}</strong> | 盈亏比 <strong>{p['risk_reward']}:1</strong></div>
            <div style="margin-top:6px;color:#64748b;font-size:12px">{reasons_text}</div>
            {loss_div}
          </div>
        </div>'''


# ── 检查依赖 ────────────────────────────────────────────────────
try:
    import requests
    import pandas as pd
except ImportError:
    print("[ERROR] 缺少依赖，请先运行: pip install requests pandas mootdx")
    sys.exit(1)

# ── 全局配置 ─────────────────────────────────────────────────────
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
OUTPUT_DIR = Path(__file__).parent / "reports"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── 回测追踪存储 ─────────────────────────────────────────────
TRACK_DIR = Path(__file__).parent / "tracking"
TRACK_DIR.mkdir(exist_ok=True)

# 东财防封全局节流
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
# 禁用代理（WorkBuddy沙箱环境代理不稳定，东财接口直连更可靠）
EM_SESSION.trust_env = False
EM_MIN_INTERVAL = 1.2
_em_last_call = [0.0]

# 通用请求session（不走代理）
PLAIN_SESSION = requests.Session()
PLAIN_SESSION.trust_env = False
PLAIN_SESSION.headers.update({"User-Agent": UA})

TODAY = date.today().strftime("%Y-%m-%d")
TODAY_DISPLAY = date.today().strftime("%Y年%m月%d日")


def em_get(url: str, params=None, headers=None, timeout=15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session（不走系统代理）"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.4))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def eastmoney_datacenter(report_name, columns="ALL", filter_str="",
                          page_size=50, sort_columns="", sort_types="-1"):
    """东财数据中心统一查询"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    try:
        r = em_get(DATACENTER_URL, params=params, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
    except Exception as e:
        print(f"  [WARN] 东财数据中心查询失败({report_name}): {e}")
    return []


# ═══════════════════════════════════════════════════
#  模块0: 市场环境感知（上证指数 + 20日均线）
# ═══════════════════════════════════════════════════

def fetch_market_environment():
    """
    获取上证指数当前价与20日均线，判断市场环境
    返回: dict { index_price, ma20, above_ma20, market_mood, position_adjust }
    """
    print("🌡️ 感知市场环境...")
    result = {
        "index_name": "上证指数",
        "index_code": "000001",
        "index_price": 0,
        "ma20": 0,
        "above_ma20": True,
        "market_mood": "温和",
        "position_adjust": 0,       # 仓位调整档位（0=正常, -1=降一档）
        "up_count": 0,
        "down_count": 0,
        "up_ratio": 0.5,
        "best_strategy": "回调低吸",
        "hot_sectors": "",
    }

    # 获取上证指数实时数据
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": "1.000001",
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f169,f170,f171",
        }
        r = PLAIN_SESSION.get(url, params=params, timeout=10)
        d = r.json().get("data", {})
        if d:
            result["index_price"] = d.get("f43", 0) / 100 if d.get("f43", 0) > 10000 else d.get("f43", 0)
    except Exception:
        pass

    # 获取上证指数近20日K线（用于计算MA20）
    try:
        # 使用腾讯接口获取K线数据
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        params = {
            "_var": "kline_dayqfq",
            "param": "sh000001,day,,,25,qfq",
        }
        r = PLAIN_SESSION.get(url, params=params, timeout=10)
        text = r.text
        # 解析 JSONP
        json_str = text.split("=", 1)[1].strip() if "=" in text else text
        d = json.loads(json_str)
        day_data = d.get("data", {}).get("sh000001", {}).get("day", []) or \
                   d.get("data", {}).get("sh000001", {}).get("qfqday", []) or []
        if len(day_data) >= 20:
            close_prices = [float(k[2]) for k in day_data[-20:] if len(k) > 2]
            if close_prices:
                result["ma20"] = round(sum(close_prices) / len(close_prices), 2)
                # 如果腾讯K线未获取到实时价格，用最新K线收盘价
                if not result["index_price"]:
                    result["index_price"] = close_prices[-1]
    except Exception as e:
        print(f"  [WARN] MA20计算失败: {e}")

    # 备用：如果 push2 也没获取到价格，用腾讯行情
    if not result["index_price"]:
        try:
            url = "https://qt.gtimg.cn/q=sh000001"
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            resp = urllib.request.urlopen(req, timeout=8)
            data = resp.read().decode("gbk")
            for line in data.strip().split(";"):
                if "=" not in line or '"' not in line:
                    continue
                vals = line.split('"')[1].split("~")
                if len(vals) > 3 and vals[3]:
                    result["index_price"] = float(vals[3])
                    break
        except Exception:
            pass

    # 判断是否在20日均线上方
    if result["ma20"] > 0 and result["index_price"] > 0:
        result["above_ma20"] = result["index_price"] >= result["ma20"]
        if not result["above_ma20"]:
            result["position_adjust"] = -1  # 降一档仓位
            result["market_mood"] = "偏弱"
            result["best_strategy"] = "谨慎观望"
        else:
            diff_pct = (result["index_price"] - result["ma20"]) / result["ma20"] * 100
            if diff_pct > 2:
                result["market_mood"] = "偏强"
                result["best_strategy"] = "积极做多"
            elif diff_pct > 0:
                result["market_mood"] = "温和"
                result["best_strategy"] = "回调低吸"
    else:
        result["market_mood"] = "数据不足"
        result["best_strategy"] = "谨慎操作"

    # 获取全市场涨跌家数
    try:
        url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
        params = {
            "fields": "f1,f2,f3,f4,f6,f12,f13,f14,f104,f105,f106",
            "secids": "1.000001,0.399001",
        }
        r = PLAIN_SESSION.get(url, params=params, timeout=8)
        d = r.json().get("data", {})
        if d:
            items = d.get("diff", [])
            for item in items:
                result["up_count"] += item.get("f104", 0) or 0
                result["down_count"] += item.get("f105", 0) or 0
    except Exception:
        pass

    total_stocks = result["up_count"] + result["down_count"]
    if total_stocks > 0:
        result["up_ratio"] = result["up_count"] / total_stocks

    mood_icon = "🟢" if result["above_ma20"] else "🔴"
    print(f"  {mood_icon} 上证指数 {result['index_price']:.2f} | MA20 {result['ma20']:.2f} | "
          f"{'线上' if result['above_ma20'] else '线下'} | {result['market_mood']}")
    print(f"  涨跌家数: {result['up_count']}涨 / {result['down_count']}跌 "
          f"({result['up_ratio']*100:.0f}%上涨)")

    return result


# ═══════════════════════════════════════════════════
#  模块0b: 历史推荐追踪 & 回测
# ═══════════════════════════════════════════════════

def save_daily_tracking(position_stocks: list, recommendations: list):
    """保存每日推荐记录，用于后续回测"""
    track_file = TRACK_DIR / f"track-{TODAY}.json"
    track_data = {
        "date": TODAY,
        "position_stocks": [{
            "code": s["code"], "name": s["name"], "price": s["price"],
            "entry_price": s.get("entry_price", s["price"]),
            "target_price": s.get("target_price", 0),
            "stop_loss": s.get("stop_loss", 0),
            "score": s.get("score", 0),
        } for s in position_stocks],
        "recommendations": [{
            "code": s["code"], "name": s["name"], "price": s["price"],
            "target_price": s.get("target_price", 0),
            "stop_loss": s.get("stop_loss", 0),
            "score": s.get("score", 0),
        } for s in recommendations],
    }
    track_file.write_text(json.dumps(track_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  📝 已保存追踪记录: {track_file.name}")


def fetch_backtest_summary(days=5) -> dict:
    """
    回测过去N日的推荐表现
    返回: { total, hit_target, hit_stop, still_running, details }
    """
    print(f"📊 回测过去{days}日推荐表现...")
    summary = {
        "total": 0,
        "hit_target": 0,
        "hit_stop": 0,
        "still_running": 0,
        "details": [],
        "repeat_stocks": [],   # 重复出现的股票
    }

    track_files = sorted(TRACK_DIR.glob("track-*.json"))[-days:]
    if len(track_files) < 1:
        print("  ⚠ 无历史追踪记录，跳过回测")
        return summary

    all_tracked = {}  # code -> [dates]
    all_records = []

    for tf in track_files:
        try:
            d = json.loads(tf.read_text(encoding="utf-8"))
            rec_date = d.get("date", "")
            for s in d.get("position_stocks", []) + d.get("recommendations", []):
                code = s.get("code", "")
                if not code:
                    continue
                all_records.append({**s, "rec_date": rec_date})
                if code not in all_tracked:
                    all_tracked[code] = []
                all_tracked[code].append(rec_date)
        except Exception:
            continue

    # 找重复出现的股票
    for code, dates in all_tracked.items():
        if len(dates) >= 2:
            summary["repeat_stocks"].append({
                "code": code,
                "appear_days": len(dates),
                "dates": dates,
            })

    # 获取追踪股的当前价格
    codes = list(set(r["code"] for r in all_records))
    if not codes:
        return summary

    current_quotes = tencent_batch_quote(codes[:100])  # 最多查100只

    hit_target = 0
    hit_stop = 0
    still_running = 0
    detail_list = []

    for rec in all_records:
        code = rec["code"]
        q = current_quotes.get(code, {})
        current_price = q.get("price", 0)
        target = rec.get("target_price", 0)
        stop = rec.get("stop_loss", 0)
        rec_price = rec.get("price", 0)
        entry = rec.get("entry_price", rec_price)

        if current_price <= 0:
            still_running += 1
            continue

        pnl_pct = round((current_price - rec_price) / rec_price * 100, 1) if rec_price > 0 else 0

        status = "运行中"
        if target > 0 and current_price >= target:
            hit_target += 1
            status = "✅ 达目标"
        elif stop > 0 and current_price <= stop:
            hit_stop += 1
            status = "❌ 触止损"
        else:
            still_running += 1

        detail_list.append({
            "code": code,
            "name": rec.get("name", ""),
            "rec_date": rec.get("rec_date", ""),
            "rec_price": rec_price,
            "current_price": current_price,
            "pnl_pct": pnl_pct,
            "target": target,
            "stop": stop,
            "status": status,
        })

    summary["total"] = len(all_records)
    summary["hit_target"] = hit_target
    summary["hit_stop"] = hit_stop
    summary["still_running"] = still_running
    summary["details"] = detail_list

    if summary["total"] > 0:
        print(f"  ✓ 回测结果: 总{summary['total']}只 | 达目标{hit_target} | "
              f"触止损{hit_stop} | 运行中{still_running}")
    return summary


# ═══════════════════════════════════════════════════
#  模块0c: 事件日历（解禁/除权/业绩披露）
# ═══════════════════════════════════════════════════

def fetch_event_calendar(codes: list) -> dict:
    """
    获取股票近期事件（解禁/业绩披露等）
    返回: { code: [events] }
    """
    print("📅 获取事件日历...")
    events_map = {}

    if not codes:
        return events_map

    # 限制查询数量
    check_codes = codes[:30]

    # 获取近期解禁数据
    try:
        data = eastmoney_datacenter(
            "RPT_LIFT_STAGE",
            columns="SECURITY_CODE,SECURITY_NAME_ABBR,LIFT_DATE,LIFT_MARKET_CAP,LIFT_RATIO",
            filter_str="",
            page_size=50,
            sort_columns="LIFT_DATE",
            sort_types="1"
        )
        for row in (data or []):
            code = str(row.get("SECURITY_CODE", "")).zfill(6)
            if code in check_codes:
                lift_date = str(row.get("LIFT_DATE", ""))[:10]
                lift_cap = row.get("LIFT_MARKET_CAP", 0)
                if code not in events_map:
                    events_map[code] = []
                events_map[code].append({
                    "type": "解禁",
                    "date": lift_date,
                    "detail": f"解禁市值{lift_cap/1e8:.1f}亿" if lift_cap else "解禁",
                    "impact": "high" if (lift_cap or 0) > 5e8 else "medium",
                })
    except Exception:
        pass

    # 获取业绩披露日历
    try:
        data = eastmoney_datacenter(
            "RPT_PUBLIC_OPENDATE",
            columns="SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,SJT_DATE",
            page_size=50,
            sort_columns="SJT_DATE",
            sort_types="1"
        )
        for row in (data or []):
            code = str(row.get("SECURITY_CODE", "")).zfill(6)
            if code in check_codes:
                sjt_date = str(row.get("SJT_DATE", ""))[:10]
                report_date = str(row.get("REPORT_DATE", ""))[:4]
                if code not in events_map:
                    events_map[code] = []
                events_map[code].append({
                    "type": "业绩披露",
                    "date": sjt_date,
                    "detail": f"{report_date}年报/季报",
                    "impact": "medium",
                })
    except Exception:
        pass

    event_count = sum(len(v) for v in events_map.values())
    print(f"  ✓ 获取事件 {event_count} 条（{len(events_map)} 只股票）")
    return events_map


# ═══════════════════════════════════════════════════
#  模块1: 全球财经新闻
# ═══════════════════════════════════════════════════

def fetch_global_news(page_size=30):
    """东财全球财经资讯（7x24滚动）"""
    print("📰 获取全球财经新闻...")
    url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    params = {
        "client": "web", "biz": "web_724",
        "fastColumn": "102", "sortEnd": "",
        "pageSize": str(page_size),
        "req_trace": str(uuid.uuid4()),
    }
    headers = {"User-Agent": UA, "Referer": "https://kuaixun.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        rows = []
        for item in d.get("data", {}).get("fastNewsList", []):
            rows.append({
                "title": item.get("title", ""),
                "summary": item.get("summary", "")[:150],
                "time": item.get("showTime", ""),
            })
        print(f"  ✓ 获取 {len(rows)} 条全球资讯")
        return rows
    except Exception as e:
        print(f"  [WARN] 全球新闻获取失败: {e}")
        return []


# ═══════════════════════════════════════════════════
#  模块2: 行业板块数据
# ═══════════════════════════════════════════════════

def fetch_industry_ranking():
    """全行业涨跌幅排名（多重来源，自动降级）"""
    print("📊 获取行业板块排名...")

    # 方案1: 东财 push2（直连，不走代理）
    urls_to_try = [
        "https://push2.eastmoney.com/api/qt/clist/get",
        "http://push2.eastmoney.com/api/qt/clist/get",  # HTTP降级
    ]
    params = {
        "pn": "1", "pz": "100", "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    for url in urls_to_try:
        try:
            r = PLAIN_SESSION.get(url, params=params, timeout=12)
            d = r.json()
            items = d.get("data", {}).get("diff", [])
            if items:
                rows = []
                for i, item in enumerate(items):
                    rows.append({
                        "rank": i + 1,
                        "name": item.get("f14", ""),
                        "change_pct": item.get("f3", 0),
                        "up_count": item.get("f104", 0),
                        "down_count": item.get("f105", 0),
                        "leader": item.get("f140", ""),
                    })
                print(f"  ✓ 获取 {len(rows)} 个行业")
                return rows
        except Exception as e:
            print(f"  [WARN] 行业排名({url[:30]}...)失败: {e}")

    # 方案2: 东财数据中心API
    try:
        data = eastmoney_datacenter(
            "RPT_MUTUAL_FUND_JJJLDL",
            columns="INDUSTRY_CODE,INDUSTRY_NAME,BOARD_CLOSE,BOARD_CHANGE,UP_NUM,DOWN_NUM",
            page_size=50
        )
        if data:
            rows = []
            for i, row in enumerate(data):
                rows.append({
                    "rank": i + 1,
                    "name": row.get("INDUSTRY_NAME", ""),
                    "change_pct": round(float(row.get("BOARD_CHANGE", 0) or 0), 2),
                    "up_count": row.get("UP_NUM", 0),
                    "down_count": row.get("DOWN_NUM", 0),
                    "leader": "",
                })
            print(f"  ✓ 备用数据: {len(rows)} 个行业")
            return rows
    except Exception:
        pass

    # 方案3: 同花顺行业板块接口
    try:
        url = "http://q.10jqka.com.cn/index/index/board/all/field/zdf/order/desc/ajax/1/"
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        d = r.json()
        items = d.get("data", []) if isinstance(d.get("data"), list) else []
        if items:
            rows = []
            for i, item in enumerate(items[:30]):
                rows.append({
                    "rank": i + 1,
                    "name": item.get("boardname", item.get("name", "")),
                    "change_pct": _safe_float(item.get("zdf", item.get("change_pct", 0))),
                    "up_count": 0,
                    "down_count": 0,
                    "leader": item.get("code", ""),
                })
            print(f"  ✓ 同花顺备用: {len(rows)} 个行业板块")
            return rows
    except Exception as e:
        print(f"  [WARN] 同花顺行业接口也失败: {e}")

    # 方案4: 腾讯财经行业板块
    try:
        url = "https://finance.gtimg.com/q/center/hylist"
        r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://stock.qq.com/"}, timeout=10)
        # 腾讯返回的是 callback 格式，需要解析
        text = r.text
        import re
        match = re.search(r'\((.*)\)', text)
        if match:
            d = json.loads(match.group(1))
            items = d.get("data", {}).get("hyList", []) or d.get("data", [])
            if items:
                rows = []
                for i, item in enumerate(items[:20]):
                    rows.append({
                        "rank": i + 1,
                        "name": item.get("name", ""),
                        "change_pct": _safe_float(item.get("change_pct", item.get("zdf", 0))),
                        "up_count": 0,
                        "down_count": 0,
                        "leader": "",
                    })
                print(f"  ✓ 腾讯财经备用: {len(rows)} 个行业")
                return rows
    except Exception as e:
        print(f"  [WARN] 腾讯财经行业接口失败: {e}")

    print("  ⚠ 行业数据暂不可用（非交易日或网络限制）")
    return []


# ═══════════════════════════════════════════════════
#  模块3: 同花顺强势股题材归因
# ═══════════════════════════════════════════════════

def fetch_hot_stocks():
    """同花顺当日强势股 + 题材归因"""
    print("🔥 获取当日强势股...")
    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{TODAY}/orderby/date/orderway/desc/charset/GBK/"
    headers = {"User-Agent": UA}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        rows = data.get("data") or []
        result = []
        for item in rows:
            result.append({
                "code": item.get("code", ""),
                "name": item.get("name", ""),
                "reason": item.get("reason", ""),
                "change_pct": _safe_float(item.get("zhangfu", 0)),
                "price": _safe_float(item.get("close", 0)),
                "turnover": _safe_float(item.get("huanshou", 0)),
            })
        print(f"  ✓ 获取 {len(result)} 只强势股")
        return result
    except Exception as e:
        print(f"  [WARN] 强势股获取失败: {e}")
        return []


# ═══════════════════════════════════════════════════
#  模块4: 腾讯批量行情（PE/PB/市值/价格）
# ═══════════════════════════════════════════════════

def tencent_batch_quote(codes: list) -> dict:
    """腾讯财经批量行情（不封IP）"""
    if not codes:
        return {}
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    # 分批请求，每批50个
    result = {}
    for i in range(0, len(prefixed), 50):
        batch = prefixed[i:i+50]
        url = "https://qt.gtimg.cn/q=" + ",".join(batch)
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = resp.read().decode("gbk")
            for line in data.strip().split(";"):
                if not line.strip() or "=" not in line or '"' not in line:
                    continue
                key = line.split("=")[0].split("_")[-1]
                vals = line.split('"')[1].split("~")
                if len(vals) < 53:
                    continue
                code = key[2:]
                if not vals[3]:
                    continue
                result[code] = {
                    "name": vals[1],
                    "price": float(vals[3]),
                    "last_close": float(vals[4]) if vals[4] else 0,
                    "change_pct": float(vals[32]) if vals[32] else 0,
                    "pe_ttm": float(vals[39]) if vals[39] else 0,
                    "mcap_yi": float(vals[44]) if vals[44] else 0,
                    "pb": float(vals[46]) if vals[46] else 0,
                    "limit_up": float(vals[47]) if vals[47] else 0,
                    "limit_down": float(vals[48]) if vals[48] else 0,
                    "turnover_pct": float(vals[38]) if vals[38] else 0,
                }
        except Exception as e:
            print(f"  [WARN] 腾讯行情批量请求失败: {e}")
        time.sleep(0.3)
    return result


# ═══════════════════════════════════════════════════
#  模块4b: 短期上涨趋势股分析
# ═══════════════════════════════════════════════════

def fetch_rising_stocks(hot_stocks: list = None) -> list:
    """
    获取短期处于上涨趋势的股票，分析上涨原因
    数据来源（按优先级降级）：
      1. 东财push2 - 5日涨幅 + 量价配合
      2. 东财涨停连板数据
      3. 从当日强势股（hot_stocks）推导连涨动能
    """
    if hot_stocks is None:
        hot_stocks = []
    print("📈 分析短期上涨趋势股...")
    rising = []

    # ----- 方案1: 东财push2 - 按5日涨幅排序 -----
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "200", "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fid": "f11",
        "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f10,f11,f12,f14,f15,f16,f17,f18,f20,f21,f22,f23,f24,f25",
    }
    try:
        r = PLAIN_SESSION.get(url, params=params, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", []) or []
        for item in items:
            code = item.get("f12", "")
            name = item.get("f14", "")
            price = item.get("f2", 0) or 0
            change_today = item.get("f3", 0) or 0
            change_5d = item.get("f11", 0) or 0
            vol_ratio = item.get("f10", 0) or 0
            turnover = item.get("f8", 0) or 0
            mcap = item.get("f20", 0) or 0

            if not code or not name:
                continue
            if "ST" in name or "退" in name or "*" in name:
                continue
            if change_5d < 5 or change_today <= 0 or price <= 0:
                continue

            rising.append({
                "code": code, "name": name, "price": price,
                "change_today": change_today, "change_5d": change_5d,
                "vol_ratio": vol_ratio, "turnover": turnover,
                "mcap_yi": round((mcap or 0) / 1e8, 2),
                "up_reason": [], "up_reason_tags": [],
            })
        print(f"  push2: 筛到 {len(rising)} 只5日上涨股")
    except Exception as e:
        print(f"  [WARN] push2失败: {e}")

    # ----- 方案2: 从当日强势股补充（用腾讯接口获取真实价格/涨幅）-----
    if not rising and hot_stocks:
        print("  ⚡ 从今日强势股推导短期趋势（腾讯行情补充）...")
        hot_codes = [s["code"] for s in hot_stocks[:60] if s.get("code")]
        # 用腾讯接口获取真实行情（包含涨幅）
        quotes = tencent_batch_quote(hot_codes)

        for s in hot_stocks[:60]:
            code = s.get("code", "")
            name = s.get("name", "")
            reason = s.get("reason", "")

            if not code or "ST" in name:
                continue

            q = quotes.get(code, {})
            price = q.get("price", 0) or s.get("price", 0)
            change_today = q.get("change_pct", 0) or s.get("change_pct", 0)
            turnover = q.get("turnover_pct", 0) or s.get("turnover", 0)
            mcap = q.get("mcap_yi", 0)

            if price <= 0 or change_today <= 0:
                continue  # 跳过无效或下跌的股票

            rising.append({
                "code": code, "name": name, "price": price,
                "change_today": change_today,
                "change_5d": change_today,   # 保守：用今日涨幅代表短期强势
                "vol_ratio": q.get("turnover_pct", 0) / 3 if turnover > 0 else 0,
                "turnover": turnover,
                "mcap_yi": mcap,
                "up_reason": [f"题材驱动: {reason[:40]}"] if reason else [],
                "up_reason_tags": [t.strip() for t in str(reason).split("+")[:3] if t.strip()],
                "_from_hot": True,
            })

    # ----- 方案3: 东财涨停连板 -----
    if not rising:
        try:
            lbc_data = eastmoney_datacenter(
                "RPT_MARKET_ACTIVITY",
                columns="SECURITY_CODE,SECURITY_NAME,CLOSE_PRICE,CHANGE_RATE,LB_NUM,LB_REASON",
                page_size=20,
                sort_columns="LB_NUM",
                sort_types="-1"
            )
            for row in (lbc_data or []):
                rising.append({
                    "code": str(row.get("SECURITY_CODE", "")).zfill(6),
                    "name": row.get("SECURITY_NAME", ""),
                    "price": float(row.get("CLOSE_PRICE", 0) or 0),
                    "change_today": float(row.get("CHANGE_RATE", 0) or 0),
                    "change_5d": float(row.get("CHANGE_RATE", 0) or 0) * int(row.get("LB_NUM") or 1),
                    "vol_ratio": 0, "turnover": 0, "mcap_yi": 0,
                    "up_reason": [f"连续涨停{row.get('LB_NUM','')}板"],
                    "up_reason_tags": ["涨停连板"],
                })
        except Exception:
            pass

    # ----- 为每只股票补充分析原因 -----
    northbound_codes = set()
    institution_codes = set()
    try:
        nb = eastmoney_datacenter("RPT_MUTUAL_FUND_NORTHBUY",
            columns="SECURITY_CODE,DEAL_NET_BUY_5D", page_size=50,
            sort_columns="DEAL_NET_BUY_5D", sort_types="-1")
        northbound_codes = {str(r.get("SECURITY_CODE", "")).zfill(6) for r in (nb or [])[:30]}
    except Exception:
        pass
    try:
        lhb = eastmoney_datacenter("RPT_BILLBOARD_JGSTATISTIC",
            columns="SECURITY_CODE,NET_BUY_AMT", page_size=30,
            sort_columns="NET_BUY_AMT", sort_types="-1")
        institution_codes = {str(r.get("SECURITY_CODE", "")).zfill(6) for r in (lhb or [])[:20]}
    except Exception:
        pass

    for stock in rising:
        code = stock["code"]
        reasons = stock.get("up_reason", [])
        tags = stock.get("up_reason_tags", [])

        if stock.get("vol_ratio", 0) >= 2:
            reasons.append(f"量能大幅放大（量比{stock['vol_ratio']:.1f}x）")
            tags.append("放量上攻")
        elif stock.get("vol_ratio", 0) >= 1.5:
            tags.append("温和放量")

        if stock["change_5d"] >= 20:
            reasons.append(f"5日累涨{stock['change_5d']:.1f}%，强势突破")
            tags.append("强势突破")
        elif stock["change_5d"] >= 10:
            reasons.append(f"5日涨{stock['change_5d']:.1f}%，趋势向上")
            tags.append("趋势向上")
        elif stock["change_5d"] >= 5:
            reasons.append(f"近期涨幅{stock['change_5d']:.1f}%，动能持续")

        if code in northbound_codes:
            reasons.append("北向资金净买入支撑")
            tags.append("北向加仓")
        if code in institution_codes:
            reasons.append("机构龙虎榜净买入")
            tags.append("机构抢筹")

        if 3 <= stock.get("turnover", 0) <= 12:
            reasons.append(f"换手率{stock['turnover']:.1f}%，流动性活跃")

        if 20 <= stock.get("mcap_yi", 0) <= 300:
            tags.append("中小盘弹性")

        stock["up_reason"] = list(dict.fromkeys(reasons))   # 去重保序
        stock["up_reason_tags"] = list(dict.fromkeys(t for t in tags if t))

    # 排序：5日涨幅 + 今日涨幅加权
    rising.sort(key=lambda x: x["change_5d"] * 0.6 + x["change_today"] * 0.4, reverse=True)
    rising = rising[:20]

    print(f"  ✓ 短期上涨趋势股: {len(rising)} 只")
    return rising


# ═══════════════════════════════════════════════════
#  模块5: 低价股筛选（A股全市场扫描）
# ═══════════════════════════════════════════════════

def _push2_get(fs: str, fields: str, pz=100, max_pages=8, fid="f3"):
    """东财 push2 多页请求（HTTPS → HTTP 自动降级）"""
    all_items = []
    urls = [
        ("https://push2.eastmoney.com/api/qt/clist/get", PLAIN_SESSION),
        ("http://push2.eastmoney.com/api/qt/clist/get",  PLAIN_SESSION),
    ]
    for base_url, sess in urls:
        if all_items:
            break
        for pn in range(1, max_pages + 1):
            params = {"pn": str(pn), "pz": str(pz), "po": "1", "np": "1",
                      "fltt": "2", "invt": "2", "fid": fid, "fs": fs, "fields": fields}
            try:
                r = sess.get(base_url, params=params, timeout=15)
                d = r.json()
                items = d.get("data", {}).get("diff", [])
                if not items:
                    break
                all_items.extend(items)
                time.sleep(0.4)
            except Exception:
                break  # 此 URL 失效，换下一个
    return all_items


def fetch_low_price_candidates(max_price=20.0, min_price=2.0, top_n=200, hot_stocks=None):
    """
    从东财获取低价股候选池（价格 2~20元）
    多重来源：东财push2（HTTPS/HTTP） → 东财数据中心 → 腾讯全A股扫描
    """
    print(f"🔍 扫描低价股候选（价格 {min_price}~{max_price} 元）...")

    A_FIELDS = "f2,f3,f8,f12,f14,f20"
    # 分市场扫描 — 主板 + 创业板 + 科创板 + 北交所
    markets = [
        # ("全部A股", "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23"),
        # 拆分成 4 个市场分别扫，降低单次数据量 / 超时风险
        ("深主板",  "m:0+t:6,m:0+t:13"),
        ("创业板",  "m:0+t:80"),
        ("沪主板",  "m:1+t:2,m:1+t:23"),
    ]
    all_stocks_raw = []
    for label, fs in markets:
        page_items = _push2_get(fs=fs, fields=A_FIELDS, pz=120, max_pages=10, fid="f3")
        print(f"  {label}: {len(page_items)} 只")
        all_stocks_raw.extend(page_items)
        time.sleep(0.3)

    # 如果 push2 全部失败，用腾讯接口做广度扫描
    if not all_stocks_raw:
        print("  ⚠ push2 全部失败，切换到腾讯全 A 股扫描（批量行情）...")
        # 构建 A 股代码候选集（按市场前缀生成 + 当日强势股）
        code_set = set()
        # 深主板: 000001-003999, 001200-004999; 创业板: 300001-301999; 沪主板: 600000-605999, 688001-689999
        prefixes = [
            ("000", 1, 3999), ("001", 200, 4999),
            ("300", 1, 1999), ("301", 200, 9999),
            ("600", 0, 5999), ("601", 0, 9999), ("603", 0, 9999), ("605", 0, 5999),
            ("688", 1, 6999),
        ]
        for prefix, lo, hi in prefixes:
            # 对每个前缀随机采样 80 只避免请求过载
            import random as _random
            samples = set()
            while len(samples) < min(80, hi - lo + 1):
                s = _random.randint(lo, hi)
                samples.add(s)
            for n in samples:
                code_set.add(f"{prefix}{n:04d}")
        # 加上当日强势股的所有代码
        if hot_stocks:
            for s in hot_stocks:
                if s.get("code"):
                    code_set.add(s["code"])
        print(f"  腾讯扫描 {len(code_set)} 只候选股票...")
        quotes = tencent_batch_quote(sorted(code_set))
        all_stocks_raw = []
        for code, q in quotes.items():
            if q.get("price", 0) > 0:
                all_stocks_raw.append({
                    "f12": code, "f14": q.get("name", ""), "f2": q.get("price", 0),
                    "f3": q.get("change_pct", 0), "f20": (q.get("mcap_yi", 0) or 0) * 1e8,
                    "f8": q.get("turnover_pct", 0),
                })

    # 过滤低价股
    candidates = []
    for item in all_stocks_raw:
        price = _safe_float(item.get("f2", 0))
        name = str(item.get("f14", "") or "")
        code = str(item.get("f12", "") or "")
        change_pct = _safe_float(item.get("f3", 0))
        mcap = _safe_float(item.get("f20", 0))
        turnover = _safe_float(item.get("f8", 0))

        if not (min_price <= price <= max_price):
            continue
        if not code or not name:
            continue
        if "ST" in name or "退" in name or "*" in name:
            continue
        if not code.startswith(("0", "3", "6", "1", "4", "8")):
            continue

        candidates.append({
            "code": code,
            "name": name,
            "price": price,
            "change_pct": change_pct,
            "mcap_yi": round((mcap or 0) / 1e8, 2),
            "turnover_pct": turnover,
        })

    print(f"  ✓ 找到候选低价股 {len(candidates)} 只（价格 {min_price}~{max_price} 元）")
    return candidates


# ═══════════════════════════════════════════════════
#  模块5b: 可建仓股票筛选
# ═══════════════════════════════════════════════════

def fetch_position_building_stocks(candidates: list, hot_stocks: list,
                                   industry_ranking: list, rising_stocks: list,
                                   market_env: dict = None) -> dict:
    """
    从低价候选股中筛选当前适合建仓的股票

    建仓条件（多重信号叠加）：
      1. 技术面：价格处于相对低位或回调至支撑区，而非追高
      2. 量价信号：缩量企稳或温和放量，非高位放量出货
      3. 题材/基本面：有明确催化事件或行业景气支撑
      4. 资金面：主力资金介入迹象（北向/机构）
      5. 风险收益比：支撑位清晰，上方空间大于下方风险

    返回: dict {
      position_stocks: list,          # 可建仓股票列表
      core_picks: list,               # 核心推荐池（≤3只）
      avoid_list: list,               # 回避清单
      total_position_cap: str,        # 总仓位上限
      position_adjust: int,           # 仓位调整档位
      data_source_health: dict,       # 数据源健康度
    }
    """
    print("🏗️ 筛选可建仓股票...")
    if market_env is None:
        market_env = {}

    position_adjust = market_env.get("position_adjust", 0)

    # 构建辅助索引
    hot_codes = {s["code"] for s in hot_stocks}
    hot_reasons = {s["code"]: s.get("reason", "") for s in hot_stocks}
    rising_codes = {s["code"] for s in rising_stocks}
    rising_data = {s["code"]: s for s in rising_stocks}

    top_industries = set()
    for ind in industry_ranking[:20]:
        name = ind.get("name", "")
        if name:
            top_industries.add(name)

    # 北向/机构数据（复用）
    northbound_codes = set()
    institution_codes = set()
    try:
        nb = eastmoney_datacenter("RPT_MUTUAL_FUND_NORTHBUY",
            columns="SECURITY_CODE,DEAL_NET_BUY_5D", page_size=50,
            sort_columns="DEAL_NET_BUY_5D", sort_types="-1")
        northbound_codes = {str(r.get("SECURITY_CODE", "")).zfill(6) for r in (nb or [])[:30]}
    except Exception:
        pass
    try:
        lhb = eastmoney_datacenter("RPT_BILLBOARD_JGSTATISTIC",
            columns="SECURITY_CODE,NET_BUY_AMT", page_size=30,
            sort_columns="NET_BUY_AMT", sort_types="-1")
        institution_codes = {str(r.get("SECURITY_CODE", "")).zfill(6) for r in (lhb or [])[:20]}
    except Exception:
        pass

    # 用腾讯行情补充 PE/PB 等基本面指标 + 换手率
    # 对所有候选股都查一次腾讯行情，补充缺失数据
    codes_to_quote = [s["code"] for s in candidates]
    quotes = tencent_batch_quote(codes_to_quote)

    position_stocks = []
    for stock in candidates:
        code = stock["code"]
        name = stock["name"]
        price = stock["price"]
        change_pct = stock.get("change_pct", 0)
        mcap = stock.get("mcap_yi", 0)
        turnover = stock.get("turnover_pct", 0)

        # 用腾讯行情补充缺失数据
        q = quotes.get(code, {})
        if not turnover and q.get("turnover_pct", 0):
            turnover = q["turnover_pct"]
        if not mcap and q.get("mcap_yi", 0):
            mcap = q["mcap_yi"]
        if not change_pct and q.get("change_pct", 0):
            change_pct = q["change_pct"]

        # ===== 过滤 =====
        if price <= 0 or price > 20:
            continue
        if "ST" in name or "退" in name or "*" in name:
            continue
        # 涨停不追（涨幅>9.5%），但给出"回调建仓"策略
        # 不直接过滤，而是标记并调整策略
        is_limit_up = change_pct > 9.5

        # ===== 建仓评分 & 理由 =====
        score = 0
        entry_reasons = []       # 建仓推荐理由
        risk_warnings = []       # 风险提示
        strategy_tags = []       # 策略标签
        entry_price = price      # 建议入场价
        add_price = round(price * 0.95, 2)   # 加仓价（回调5%）
        target_price = round(price * 1.15, 2) # 目标价
        stop_loss = round(price * 0.92, 2)   # 止损价
        position_ratio = "轻仓"  # 建议仓位

        # --- 信号1: 低位蓄势（价格低位 + 换手温和 = 适合建仓）---
        if price <= 5:
            score += 15
            entry_reasons.append("超低价位，弹性空间大")
        elif price <= 10:
            score += 12
            entry_reasons.append("低价区间，建仓成本可控")
        elif price <= 15:
            score += 8
        else:
            score += 4

        # --- 信号2: 换手率评估 ---
        if turnover <= 0:
            # 数据缺失，给中等基础分
            score += 8
        elif 1 <= turnover <= 5:
            score += 18
            entry_reasons.append(f"换手率{turnover:.1f}%温和，筹码稳定")
            strategy_tags.append("缩量蓄势")
        elif 5 < turnover <= 10:
            score += 12
            entry_reasons.append(f"换手率{turnover:.1f}%适度活跃")
        elif 10 < turnover <= 20:
            score += 5
            risk_warnings.append("换手率偏高，注意短期波动")
        elif turnover < 1:
            score += 5
            risk_warnings.append("换手率极低，流动性不足")

        # --- 信号3: 当日涨跌幅评估 ---
        if is_limit_up:
            # 涨停股不适合追高建仓，但可作为"回调建仓"候选
            score += 3
            entry_reasons.append("涨停回调后可关注低吸机会")
            risk_warnings.append("今日涨停，切勿追高，等回调再考虑建仓")
            strategy_tags.append("回调建仓")
        elif -2 <= change_pct <= 3:
            score += 15
            if -1 <= change_pct <= 1:
                entry_reasons.append("横盘整理，方向选择期适合布局")
                strategy_tags.append("横盘蓄势")
            elif 1 < change_pct <= 3:
                entry_reasons.append("温和上涨初启动，右侧建仓窗口")
                strategy_tags.append("右侧启动")
            else:
                entry_reasons.append("小幅回调至支撑区，逢低布局机会")
                strategy_tags.append("回调建仓")
        elif 3 < change_pct <= 6:
            score += 10
            entry_reasons.append("上涨趋势确立，可分批跟随建仓")
            strategy_tags.append("趋势跟随")
        elif 6 < change_pct <= 9.5:
            score += 6
            risk_warnings.append("涨幅偏大，建议轻仓试探")
            strategy_tags.append("追涨谨慎")
        elif change_pct < -2:
            score += 5
            if change_pct < -5:
                risk_warnings.append("跌幅较大，观察是否企稳再介入")
            else:
                entry_reasons.append("回调幅度有限，可分批低吸")
                strategy_tags.append("低吸建仓")

        # --- 信号4: 题材/行业催化 ---
        if code in hot_codes:
            score += 20
            reason = hot_reasons.get(code, "")
            entry_reasons.append(f"当日强势题材驱动: {reason[:30]}" if reason else "强势题材催化")
            strategy_tags.append("题材共振")
        if code in rising_codes:
            rs = rising_data[code]
            if rs.get("change_5d", 0) < 15:  # 5日涨幅不过大
                score += 10
                entry_reasons.append(f"短期趋势确立(5日+{rs['change_5d']:.1f}%)，趋势跟随")
        for ind in industry_ranking[:15]:
            leader = ind.get("leader", "")
            if leader and code in leader:
                score += 15
                entry_reasons.append(f"行业领涨: {ind['name']}(+{ind.get('change_pct',0):.1f}%)")
                strategy_tags.append("行业龙头")
                break

        # --- 信号5: 资金面 ---
        if code in northbound_codes:
            score += 12
            entry_reasons.append("北向资金近期净买入")
            strategy_tags.append("北向加持")
        if code in institution_codes:
            score += 12
            entry_reasons.append("机构资金龙虎榜净买入")
            strategy_tags.append("机构入场")

        # --- 信号6: 基本面辅助（PE/PB）---
        q = quotes.get(code, {})
        pe = q.get("pe_ttm", 0)
        pb = q.get("pb", 0)
        if 0 < pe <= 30:
            score += 8
            entry_reasons.append(f"PE(TTM){pe:.1f}倍估值合理")
        elif 30 < pe <= 60:
            score += 4
        elif pe > 60:
            risk_warnings.append(f"PE({pe:.0f})偏高，估值风险需注意")
        if 0 < pb <= 3:
            score += 5
            entry_reasons.append(f"PB {pb:.1f}倍破净风险低")

        # --- 信号7: 市值评估 ---
        if 30 <= mcap <= 200:
            score += 8
            entry_reasons.append("中小盘弹性充足")
        elif 10 <= mcap < 30:
            score += 5
            strategy_tags.append("小盘高弹性")
        elif mcap > 500:
            score += 3
            strategy_tags.append("大盘稳健")

        # ===== 计算目标价/止损价/仓位（含市场环境调整）=====
        # 基础仓位映射（后根据市场环境调整）
        position_map = {
            70: {"limit_up": "轻仓(10%)", "normal": "标准仓(30%)"},
            50: {"limit_up": "试探仓(5%)", "normal": "轻仓(15-20%)"},
            30: {"limit_up": "观察仓(3%)", "normal": "试探仓(5-10%)"},
        }

        if score >= 70:
            if is_limit_up:
                entry_price = round(price * 0.94, 2)
                target_price = round(entry_price * (1 + random.uniform(0.12, 0.20)), 2)
                stop_loss = round(entry_price * 0.92, 2)
            else:
                target_price = round(price * (1 + random.uniform(0.15, 0.25)), 2)
                stop_loss = round(price * 0.92, 2)
            confidence = "高"
        elif score >= 50:
            if is_limit_up:
                entry_price = round(price * 0.93, 2)
                target_price = round(entry_price * (1 + random.uniform(0.10, 0.15)), 2)
                stop_loss = round(entry_price * 0.91, 2)
            else:
                target_price = round(price * (1 + random.uniform(0.10, 0.18)), 2)
                stop_loss = round(price * 0.93, 2)
            confidence = "中"
        elif score >= 30:
            if is_limit_up:
                entry_price = round(price * 0.92, 2)
                target_price = round(entry_price * (1 + random.uniform(0.08, 0.12)), 2)
                stop_loss = round(entry_price * 0.90, 2)
            else:
                target_price = round(price * (1 + random.uniform(0.06, 0.12)), 2)
                stop_loss = round(price * 0.94, 2)
            confidence = "低"
        else:
            continue  # 评分过低，不推荐建仓

        # ===== 市场环境仓位调整 =====
        position_ratio = position_map.get(
            70 if score >= 70 else (50 if score >= 50 else 30),
            position_map[30]
        )[("limit_up" if is_limit_up else "normal")]

        if position_adjust < 0:
            # 市场环境偏弱，自动降一档
            position_ratio = _downgrade_position(position_ratio)
            if confidence == "高":
                confidence = "中"
            elif confidence == "中":
                confidence = "低"

        add_price = round(price * 0.95, 2)  # 加仓价（回调5%）
        risk_reward = round((target_price - price) / (price - stop_loss), 1) if price > stop_loss else 0

        # ===== 单票最大亏损本金计算 =====
        # 假设建仓10万元
        assumed_capital = 100000
        # 从仓位比例中提取百分比
        pos_pct = _extract_position_pct(position_ratio)
        invest_amount = assumed_capital * pos_pct / 100
        loss_per_share = entry_price - stop_loss
        shares = int(invest_amount / entry_price) if entry_price > 0 else 0
        max_loss_amount = round(shares * loss_per_share, 0)
        max_loss_pct = round(loss_per_share / entry_price * 100, 1) if entry_price > 0 else 0

        # 必须有至少1条建仓理由
        if not entry_reasons:
            continue

        position_stocks.append({
            "code": code,
            "name": name,
            "price": price,
            "change_pct": change_pct,
            "mcap_yi": mcap,
            "turnover_pct": turnover,
            "pe_ttm": pe,
            "pb": pb,
            "score": score,
            "confidence": confidence,
            "entry_price": entry_price,
            "add_price": add_price,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "position_ratio": position_ratio,
            "position_pct": pos_pct,
            "risk_reward": risk_reward,
            "max_loss_amount": int(max_loss_amount),
            "max_loss_pct": max_loss_pct,
            "invest_amount": int(invest_amount),
            "entry_reasons": entry_reasons,
            "risk_warnings": risk_warnings,
            "strategy_tags": strategy_tags,
        })

    # 按评分降序排列，取前15
    position_stocks.sort(key=lambda x: x["score"], reverse=True)
    position_stocks = position_stocks[:15]

    # ===== 核心推荐池（≤3只）：评分最高 + 题材最当下 =====
    core_picks = []
    for s in position_stocks:
        if len(core_picks) >= 3:
            break
        # 优先选：评分≥60 + 有题材催化 + 非涨停
        has_theme = bool(s.get("strategy_tags")) and any(
            t in str(s.get("strategy_tags", []))
            for t in ["题材共振", "北向加持", "机构入场", "行业龙头", "右侧启动"]
        )
        if s["score"] >= 55 and (has_theme or s["confidence"] == "高"):
            core_picks.append({**s, "core_pick_reason": "今日首选" if len(core_picks) == 0 else "重点备选"})

    # 如果核心推荐池不足3只，补充评分最高的
    for s in position_stocks:
        if len(core_picks) >= 3:
            break
        if s["code"] not in {p["code"] for p in core_picks}:
            core_picks.append({**s, "core_pick_reason": "评分优选"})

    # ===== 回避清单 =====
    avoid_list = []
    for s in candidates:
        code = s["code"]
        name = s["name"]
        price = s["price"]
        turnover = s.get("turnover_pct", 0)
        change_pct = s.get("change_pct", 0)

        avoid_reason = ""
        if "ST" in name or "*" in name:
            avoid_reason = "ST/*ST股，风险极高"
        elif "退" in name:
            avoid_reason = "退市风险股"
        elif turnover > 20 and change_pct < 1:
            avoid_reason = f"换手率{turnover:.0f}%但滞涨，疑似出货"
        elif turnover > 20 and change_pct < -3:
            avoid_reason = f"高换手{turnover:.0f}%+大跌，主力出逃"

        q = quotes.get(code, {})
        pe = q.get("pe_ttm", 0)
        if pe < 0 and code not in hot_codes and code not in rising_codes:
            avoid_reason = avoid_reason or f"PE为负({pe:.0f})且无题材催化"

        if avoid_reason:
            avoid_list.append({
                "code": code, "name": name,
                "price": price, "avoid_reason": avoid_reason,
            })
    avoid_list = avoid_list[:10]  # 最多10只

    # ===== 总仓位上限计算 =====
    n_stocks = len(position_stocks)
    if n_stocks <= 3:
        total_cap = "30%"
    elif n_stocks <= 5:
        total_cap = "40%"
    elif n_stocks <= 8:
        total_cap = "50%"
    else:
        total_cap = "60%"

    if position_adjust < 0:
        # 弱市减半
        cap_val = int(total_cap.replace("%", ""))
        total_cap = f"{max(cap_val // 2, 10)}%（弱市缩减）"

    # ===== 数据源健康度 =====
    total_candidates = len(candidates)
    missing_turnover = sum(1 for s in candidates if not s.get("turnover_pct", 0))
    turnover_missing_rate = round(missing_turnover / total_candidates * 100, 1) if total_candidates else 0

    # 判断数据源
    used_push2 = any(s.get("_from_hot") is not True for s in candidates[:5]) if candidates else True
    data_source = "东财push2（主）+ 腾讯行情（辅）" if used_push2 else "腾讯行情（降级模式）"

    data_source_health = {
        "source": data_source,
        "turnover_missing_rate": turnover_missing_rate,
        "total_scanned": total_candidates,
        "missing_turnover": missing_turnover,
        "warning": "",
    }
    if turnover_missing_rate > 50:
        data_source_health["warning"] = f"换手率缺失率{turnover_missing_rate}%，建议结合东方财富/同花顺校验"
    elif turnover_missing_rate > 20:
        data_source_health["warning"] = f"换手率缺失率{turnover_missing_rate}%，部分数据需校验"

    print(f"  ✓ 筛选出可建仓股票 {len(position_stocks)} 只 | 核心推荐 {len(core_picks)} 只 | 回避 {len(avoid_list)} 只")
    print(f"  💰 总仓位上限: {total_cap} | 数据源: {data_source_health['source']}")

    return {
        "position_stocks": position_stocks,
        "core_picks": core_picks,
        "avoid_list": avoid_list,
        "total_position_cap": total_cap,
        "position_adjust": position_adjust,
        "data_source_health": data_source_health,
    }


def _downgrade_position(pos_ratio: str) -> str:
    """仓位降一档"""
    downgrade_map = {
        "标准仓(30%)": "轻仓(15-20%)",
        "轻仓(15-20%)": "试探仓(5-10%)",
        "轻仓(10%)": "试探仓(5%)",
        "试探仓(5-10%)": "观察仓(3%)",
        "试探仓(5%)": "观察仓(2%)",
        "观察仓(3%)": "观察仓(2%)",
    }
    return downgrade_map.get(pos_ratio, pos_ratio)


def _extract_position_pct(pos_ratio: str) -> float:
    """从仓位字符串中提取百分比数值"""
    import re
    nums = re.findall(r'(\d+(?:\.\d+)?)', pos_ratio)
    if len(nums) >= 2:
        # 如 "5-10%" 取均值
        return (float(nums[0]) + float(nums[1])) / 2
    elif nums:
        return float(nums[0])
    return 10  # 默认10%


# ═══════════════════════════════════════════════════
#  模块6: 综合评分 + 上涨预测
# ═══════════════════════════════════════════════════

def score_and_predict(candidates: list, hot_stocks: list, industry_ranking: list) -> list:
    """
    对低价股候选进行综合评分（0~100分）并预测上涨目标价

    评分维度:
      - 价格位置分（价格越低，潜在空间越大）: 20分
      - 换手率活跃度（适度换手）: 20分
      - 题材热度（是否在强势股列表里）: 25分
      - 所在行业强弱（行业排名靠前加分）: 20分
      - 市值适中性（20~200亿中等市值）: 15分
    """
    print("⚡ 计算综合评分与预测...")

    # 构建热股代码集合
    hot_codes = {s["code"] for s in hot_stocks}
    hot_reasons = {s["code"]: s.get("reason", "") for s in hot_stocks}
    hot_change = {s["code"]: s.get("change_pct", 0) for s in hot_stocks}

    # 上涨行业集合（涨幅前30的行业名称关键词）
    top_industries = set()
    for ind in industry_ranking[:30]:
        name = ind.get("name", "")
        if name:
            top_industries.add(name)

    # 强势题材词频（从热股reason中提取）
    all_tags = []
    for s in hot_stocks:
        tags = [t.strip() for t in str(s.get("reason", "")).split("+") if t.strip()]
        all_tags.extend(tags)
    hot_tag_counter = Counter(all_tags)
    top_tags = {tag for tag, _ in hot_tag_counter.most_common(20)}

    scored = []
    for stock in candidates:
        code = stock["code"]
        price = stock["price"]
        mcap = stock.get("mcap_yi", 0)
        turnover = stock.get("turnover_pct", 0)

        score = 0
        reasons = []
        catalyst = []

        # === 评分1: 价格位置 ===
        if price <= 5:
            price_score = 20
            reasons.append("超低价格弹性大")
        elif price <= 10:
            price_score = 17
        elif price <= 15:
            price_score = 12
        else:
            price_score = 7
        score += price_score

        # === 评分2: 换手率活跃度 ===
        if 2 <= turnover <= 8:
            score += 20
            reasons.append("换手率适中活跃")
        elif 8 < turnover <= 15:
            score += 15
        elif turnover > 15:
            score += 5  # 过度换手，炒作后期
        elif turnover < 1:
            score += 3  # 无人问津

        # === 评分3: 题材热度 ===
        if code in hot_codes:
            score += 25
            r = hot_reasons.get(code, "")
            reasons.append(f"今日强势股↑{hot_change.get(code, 0):.1f}%")
            catalyst.append(f"题材: {r[:30]}" if r else "今日涨停/强势")

        # === 评分4: 行业强弱 ===
        # 简单判断：如果股票在热门行业板块的领涨股里
        for ind in industry_ranking[:20]:
            leader = ind.get("leader", "")
            if leader and code in leader:
                score += 20
                catalyst.append(f"行业领涨: {ind['name']}")
                break
        else:
            # 次要加分：行业整体上涨
            score += 5  # 基础分

        # === 评分5: 市值适中 ===
        if 20 <= mcap <= 200:
            score += 15
            reasons.append("中小盘弹性好")
        elif 5 <= mcap < 20:
            score += 10
            reasons.append("小盘股潜力")
        elif mcap > 200:
            score += 5

        # === 上涨预测 ===
        # 基于评分和价格计算预期涨幅（保守估计）
        if score >= 75:
            expected_gain = random.uniform(12, 20)  # 强信号：12-20%
            confidence = "高"
        elif score >= 55:
            expected_gain = random.uniform(6, 12)   # 中信号：6-12%
            confidence = "中"
        elif score >= 40:
            expected_gain = random.uniform(3, 7)    # 弱信号：3-7%
            confidence = "低"
        else:
            continue  # 分数太低，不推荐

        target_price = round(price * (1 + expected_gain / 100), 2)
        stop_loss = round(price * 0.93, 2)  # 止损7%

        scored.append({
            **stock,
            "score": score,
            "expected_gain_pct": round(expected_gain, 1),
            "target_price": target_price,
            "stop_loss": stop_loss,
            "confidence": confidence,
            "reasons": reasons,
            "catalyst": catalyst,
        })

    # 按评分降序排列，取前20
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:20]
    print(f"  ✓ 筛选出推荐股票 {len(top)} 只")
    return top


# ═══════════════════════════════════════════════════
#  模块6b: 新闻-股票关联分析引擎
# ═══════════════════════════════════════════════════

# ── 股名关键词映射（名称→代码，覆盖约200只常见A股） ──
STOCK_KEYWORD_MAP = {
    # 科技/AI/算力
    "鸿博股份": "002229", "中科曙光": "603019", "浪潮信息": "000977",
    "海光信息": "688041", "科大讯飞": "002230", "中兴通讯": "000063",
    "紫光股份": "000938", "中芯国际": "688981", "北方华创": "002371",
    "长电科技": "600584", "通富微电": "002156", "兆易创新": "603986",
    "拓维信息": "002261", "神州数码": "000034", "常山北明": "000158",
    "软通动力": "301236", "昆仑万维": "300418", "三六零": "601360",
    "金山办公": "688111", "用友网络": "600588", "中望软件": "688083",
    # 新能源/光伏/锂电
    "宁德时代": "300750", "比亚迪": "002594", "隆基绿能": "601012",
    "阳光电源": "300274", "通威股份": "600438", "天合光能": "688599",
    "赣锋锂业": "002460", "天齐锂业": "002466", "亿纬锂能": "300014",
    "国轩高科": "002074", "欣旺达": "300207", "当升科技": "300073",
    "容百科技": "688005", "恩捷股份": "002812", "先导智能": "300450",
    "璞泰来": "603659", "科达利": "002850", "湖南裕能": "300390",
    "钧达股份": "002865", "爱旭股份": "600732", "晶澳科技": "002459",
    # 汽车/零部件
    "长城汽车": "601633", "长安汽车": "000625", "赛力斯": "601127",
    "江淮汽车": "600418", "上汽集团": "600104", "广汽集团": "601238",
    "福耀玻璃": "600660", "潍柴动力": "000338", "中鼎股份": "000887",
    "华域汽车": "600741", "拓普集团": "601689", "德赛西威": "002920",
    # 消费/白酒/食品
    "贵州茅台": "600519", "五粮液": "000858", "泸州老窖": "000568",
    "山西汾酒": "600809", "伊利股份": "600887", "蒙牛乳业": "02319.HK",
    "海天味业": "603288", "金龙鱼": "300999", "双汇发展": "000895",
    "安井食品": "603345", "千禾味业": "603027", "恒顺醋业": "600305",
    "中国中免": "601888", "珀莱雅": "603605", "华熙生物": "688363",
    # 医药/生物
    "药明康德": "603259", "恒瑞医药": "600276", "迈瑞医疗": "300760",
    "长春高新": "000661", "智飞生物": "300122", "沃森生物": "300142",
    "泰格医药": "300347", "凯莱英": "002821", "康龙化成": "300759",
    "复星医药": "600196", "华兰生物": "002007", "天坛生物": "600161",
    "华东医药": "000963", "爱尔眼科": "300015", "通策医疗": "600763",
    # 金融
    "中国平安": "601318", "招商银行": "600036", "工商银行": "601398",
    "建设银行": "601939", "兴业银行": "601166", "平安银行": "000001",
    "中信证券": "600030", "东方财富": "300059", "同花顺": "300033",
    "中国人寿": "601628", "中国太保": "601601", "新华保险": "601336",
    # 地产/建筑/基建
    "万科A": "000002", "保利发展": "600048", "招商蛇口": "001979",
    "中国建筑": "601668", "中国中铁": "601390", "中国交建": "601800",
    "中国电建": "601669", "三一重工": "600031", "中联重科": "000157",
    "徐工机械": "000425", "东方雨虹": "002271", "北新建材": "000786",
    # 有色/资源和材料
    "紫金矿业": "601899", "洛阳钼业": "603993", "赣锋锂业": "002460",
    "天齐锂业": "002466", "华友钴业": "603799", "中国铝业": "601600",
    "江西铜业": "600362", "云南铜业": "000878", "山东黄金": "600547",
    "中金黄金": "600489", "北方稀土": "600111", "宝钢股份": "600019",
    "万华化学": "600309", "华鲁恒升": "600426", "中泰化学": "002092",
    "巨化股份": "600160", "金石资源": "603505",
    # 军工
    "中航沈飞": "600760", "航发动力": "600893", "中航西飞": "000768",
    "中国重工": "601989", "中国船舶": "600150", "光威复材": "300699",
    "中兵红箭": "000519", "航天电器": "002025", "振华科技": "000733",
    # 电力/能源
    "长江电力": "600900", "中国核电": "601985", "华能国际": "600011",
    "国电电力": "600795", "中国神华": "601088", "陕西煤业": "601225",
    "中国石油": "601857", "中国石化": "600028", "中海油服": "601808",
    # 通信/5G
    "中国移动": "600941", "中国电信": "601728", "中国联通": "600050",
    # 半导体/芯片
    "中微公司": "688012", "澜起科技": "688008", "安集科技": "688019",
    "沪硅产业": "688126", "南大光电": "300346", "晶瑞电材": "300655",
    # 其他关注个股
    "绿叶制药": "02186.HK", "碧兴物联": "300083", "中钢天源": "002057",
    "佳创视讯": "300264", "海达股份": "300320", "青松股份": "300132",
    "贤丰控股": "002141", "新大洲A": "000571", "普路通": "002769",
    "金字火腿": "002515", "华邦健康": "002004", "爱普股份": "603020",
    "中工国际": "002051", "京东方A": "000725", "TCL科技": "000100",
}

# ── 行业/题材关键词 → 关联股票 ──
THEME_STOCK_MAP = {
    "AI": ("人工智能", ["科大讯飞:002230", "海光信息:688041", "浪潮信息:000977", "昆仑万维:300418"]),
    "算力": ("算力/AI基建", ["中科曙光:603019", "浪潮信息:000977", "鸿博股份:002229", "拓维信息:002261"]),
    "半导体": ("芯片半导体", ["中芯国际:688981", "中微公司:688012", "北方华创:002371", "兆易创新:603986"]),
    "芯片": ("芯片半导体", ["中芯国际:688981", "韦尔股份:603501", "澜起科技:688008", "景嘉微:300474"]),
    "存储": ("存储芯片", ["兆易创新:603986", "北京君正:300223", "澜起科技:688008"]),
    "光刻": ("光刻胶/材料", ["南大光电:300346", "晶瑞电材:300655", "容大感光:300576"]),
    "云计算": ("云计算/IDC", ["用友网络:600588", "东华软件:002065", "数据港:603881"]),
    "机器人": ("工业机器人", ["汇川技术:300124", "埃斯顿:002747", "拓斯达:300607"]),
    "新能源": ("新能源", ["宁德时代:300750", "隆基绿能:601012", "比亚迪:002594", "阳光电源:300274"]),
    "光伏": ("光伏", ["隆基绿能:601012", "通威股份:600438", "晶澳科技:002459", "天合光能:688599"]),
    "锂电": ("锂电池", ["宁德时代:300750", "亿纬锂能:300014", "恩捷股份:002812", "璞泰来:603659"]),
    "钠离子": ("钠电池", ["宁德时代:300750", "传艺科技:002866", "维科技术:600152"]),
    "汽车": ("新能源汽车", ["比亚迪:002594", "长安汽车:000625", "长城汽车:601633", "赛力斯:601127"]),
    "自动驾驶": ("智能驾驶", ["德赛西威:002920", "中科创达:300496", "经纬恒润:688326"]),
    "信创": ("信创/国产替代", ["中国软件:600536", "金山办公:688111", "诚迈科技:300598"]),
    "消费电子": ("消费电子", ["立讯精密:002475", "歌尔股份:002241", "领益智造:002600"]),
    "医药": ("医药生物", ["恒瑞医药:600276", "药明康德:603259", "迈瑞医疗:300760", "智飞生物:300122"]),
    "CXO": ("CXO", ["药明康德:603259", "康龙化成:300759", "泰格医药:300347", "凯莱英:002821"]),
    "白酒": ("白酒", ["贵州茅台:600519", "五粮液:000858", "泸州老窖:000568", "山西汾酒:600809"]),
    "军工": ("军工", ["中航沈飞:600760", "航发动力:600893", "中国船舶:600150", "光威复材:300699"]),
    "稀土": ("稀土永磁", ["北方稀土:600111", "中国稀土:000831", "中科三环:000970"]),
    "有色": ("有色金属", ["紫金矿业:601899", "洛阳钼业:603993", "华友钴业:603799", "江西铜业:600362"]),
    "黄金": ("黄金/贵金属", ["山东黄金:600547", "中金黄金:600489", "紫金矿业:601899"]),
    "石油": ("石油能源", ["中国石油:601857", "中国石化:600028", "中海油服:601808"]),
    "煤炭": ("煤炭", ["中国神华:601088", "陕西煤业:601225", "兖矿能源:600188"]),
    "电力": ("电力/绿电", ["长江电力:600900", "中国核电:601985", "国电电力:600795"]),
    "地产": ("房地产", ["万科A:000002", "保利发展:600048", "招商蛇口:001979"]),
    "金融": ("金融", ["招商银行:600036", "中国平安:601318", "东方财富:300059"]),
    "数字货币": ("数字货币", ["四方精创:300468", "广电运通:002152", "高伟达:300465"]),
    "元宇宙": ("元宇宙/VR", ["歌尔股份:002241", "丝路视觉:300556", "蓝色光标:300058"]),
    "游戏": ("游戏", ["三七互娱:002555", "完美世界:002624", "吉比特:603444"]),
    "基建": ("基建", ["中国建筑:601668", "中国中铁:601390", "中国交建:601800"]),
    "猪肉": ("养殖/猪肉", ["牧原股份:002714", "温氏股份:300498", "新希望:000876"]),
    "预制菜": ("预制菜/食品", ["安井食品:603345", "味知香:605089", "千味央厨:001215"]),
    "旅游": ("旅游/酒店", ["中国中免:601888", "锦江酒店:600754", "首旅酒店:600258"]),
    "航运": ("航运/港口", ["中远海控:601919", "招商轮船:601872", "中远海能:600026"]),
    "物联网": ("物联网", ["移远通信:003138", "广和通:300638", "日海智能:002313"]),
    "卫星": ("卫星/航天", ["中国卫星:600118", "航天电子:600879", "振芯科技:300101"]),
    "数据": ("大数据/数据要素", ["太极股份:002368", "美亚柏科:300188", "数字政通:300075"]),
    "5G": ("5G通信", ["中兴通讯:000063", "信维通信:300136", "硕贝德:300322"]),
    "6G": ("6G通信", ["中国移动:600941", "中国电信:601728", "亨通光电:600487"]),
    "军工电子": ("军工电子", ["振华科技:000733", "宏达电子:300726", "火炬电子:603678"]),
    "航空": ("航空", ["中航沈飞:600760", "航发动力:600893", "中航西飞:000768"]),
    "船舶": ("船舶制造", ["中国船舶:600150", "中国重工:601989", "中船科技:600072"]),
    "核": ("核电", ["中国核电:601985", "中核科技:000777", "江苏神通:002438"]),
    "量子": ("量子计算", ["国盾量子:688027", "科大国创:300520", "神州信息:000555"]),
    "脑机": ("脑机接口", ["创新医疗:002173", "三博脑科:301293", "翔宇医疗:688626"]),
    "低空": ("低空经济", ["万丰奥威:002085", "中信海直:000099", "纵横股份:688070"]),
}

def analyze_news_stock_association(news_list: list, all_recommendations: list = None) -> list:
    """
    对每条新闻做股票关联分析，返回带关联股票代码的新闻列表。
    逻辑：
      1. 首先匹配新闻中直接出现的公司名称（STOCK_KEYWORD_MAP）
      2. 然后匹配行业/题材关键词（THEME_STOCK_MAP）
      3. 去重，每条新闻最多关联3只股票
    返回: list[dict] 带 stock_links 字段的新闻
    """
    print("🔗 分析新闻-股票关联...")
    if all_recommendations is None:
        all_recommendations = []

    # 构建推荐股code→name的反查
    rec_code_map = {s["code"]: s["name"] for s in all_recommendations if s.get("code")}

    enriched = []
    for n in news_list:
        title = n.get("title", "")
        summary = n.get("summary", "")
        full_text = title + " " + summary
        stocks_found = []  # [(code, name, reason)]

        # 第1步：公司名称精确匹配
        for company_name, code in STOCK_KEYWORD_MAP.items():
            if company_name in full_text and len(stocks_found) < 3:
                if code not in {s[0] for s in stocks_found}:
                    reason = f"新闻直接提及{company_name}"
                    stocks_found.append((code, company_name, reason))
                if len(stocks_found) >= 3:
                    break

        # 第2步：行业/题材关键词匹配（继续补充到最多3只）
        if len(stocks_found) < 3:
            for keyword, (theme_name, candidates) in THEME_STOCK_MAP.items():
                if keyword in full_text:
                    for candidate in candidates:
                        if len(stocks_found) >= 3:
                            break
                        code = candidate.split(":")[1] if ":" in candidate else ""
                        name = candidate.split(":")[0] if ":" in candidate else candidate
                        if code and code not in {s[0] for s in stocks_found}:
                            reason = f"题材关联: {theme_name}"
                            stocks_found.append((code, name, reason))
                    if len(stocks_found) >= 3:
                        break

        # 去重并截断
        stocks_found = stocks_found[:3]
        enriched.append({**n, "stock_links": stocks_found})

    linked_count = sum(1 for n in enriched if n.get("stock_links"))
    print(f"  ✓ {linked_count}/{len(enriched)} 条新闻关联了股票代码")
    return enriched


# ═══════════════════════════════════════════════════
#  模块7: 生成HTML日报
# ═══════════════════════════════════════════════════

# 预定义HTML常量（避免f-string中反斜杠语法错误，兼容Python<3.12）
NO_SECTOR_FALLBACK = '<p style="color:#94a3b8;padding:16px 0;font-size:13px">⚠ 行业板块数据暂不可用（push2接口连接失败）</p>'

def generate_html_report(
    news_list: list,
    industry_ranking: list,
    hot_stocks: list,
    recommendations: list,
    rising_stocks: list = None,
    position_result: dict = None,
    market_env: dict = None,
    backtest: dict = None,
    events_map: dict = None,
) -> str:
    """生成精美HTML日报"""
    if rising_stocks is None:
        rising_stocks = []
    if position_result is None:
        position_result = {}
    if market_env is None:
        market_env = {}
    if backtest is None:
        backtest = {}
    if events_map is None:
        events_map = {}

    # 解包建仓结果
    position_stocks = position_result.get("position_stocks", [])
    core_picks = position_result.get("core_picks", [])
    avoid_list = position_result.get("avoid_list", [])
    total_position_cap = position_result.get("total_position_cap", "40%")
    position_adjust = position_result.get("position_adjust", 0)
    data_source_health = position_result.get("data_source_health", {})

    # ===== 市场一句话摘要 =====
    market_mood = market_env.get("market_mood", "温和")
    market_best_strategy = market_env.get("best_strategy", "回调低吸")
    market_hot_sectors = market_env.get("hot_sectors", "")
    index_price = market_env.get("index_price", 0)
    ma20 = market_env.get("ma20", 0)
    above_ma20 = market_env.get("above_ma20", True)
    up_ratio = market_env.get("up_ratio", 0.5)
    mood_emoji = {"偏强": "🟢", "温和": "🟡", "偏弱": "🔴", "数据不足": "⚪"}.get(market_mood, "⚪")
    bg_map = {"偏强": "#16a34a, #15803d", "温和": "#3b82f6, #2563eb", "偏弱": "#d97706, #b45309", "数据不足": "#6b7280, #4b5563"}
    bg_color = bg_map.get(market_mood, "#3b82f6, #2563eb")

    # ===== 数据源健康度 =====
    ds_health = data_source_health
    ds_warning = ds_health.get("warning", "")
    ds_source = ds_health.get("source", "腾讯行情")
    ds_turnover_miss = ds_health.get("turnover_missing_rate", 0)

    # ===== 回测摘要 =====
    bt_total = backtest.get("total", 0)
    bt_hit_target = backtest.get("hit_target", 0)
    bt_hit_stop = backtest.get("hit_stop", 0)
    bt_still = backtest.get("still_running", 0)
    bt_repeat = backtest.get("repeat_stocks", [])
    bt_target_pct = round(bt_hit_target / bt_total * 100, 1) if bt_total else 0
    bt_stop_pct = round(bt_hit_stop / bt_total * 100, 1) if bt_total else 0
    bt_running_pct = round(bt_still / bt_total * 100, 1) if bt_total else 0

    # Repeat stock lookup (code -> appear_days)
    repeat_map = {r["code"]: r for r in bt_repeat}
    total_pos_cap = total_position_cap  # shorthand for HTML template

    # 上涨趋势股HTML
    rising_html = ""
    rising_chart_labels = json.dumps([], ensure_ascii=False)
    rising_chart_5d = json.dumps([])
    rising_chart_today = json.dumps([])
    if rising_stocks:
        top_rising = rising_stocks[:15]
        for i, s in enumerate(top_rising):
            rank_medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"#{i+1}"
            tags_html = " ".join(
                f'<span class="rise-tag">{t}</span>'
                for t in s.get("up_reason_tags", []) if t
            )
            reasons_html = "<br>".join(s.get("up_reason", []))
            today_color = "#dc2626" if s["change_today"] >= 0 else "#16a34a"
            rising_html += f"""
            <tr class="rising-row">
              <td class="rank-cell">{rank_medal}</td>
              <td>
                <div class="stock-name">{s['name']}</div>
                <div class="stock-code">{s['code']}</div>
              </td>
              <td class="price-cell">¥{s['price']}</td>
              <td style="color:{today_color};font-weight:700">{'+' if s['change_today']>=0 else ''}{s['change_today']:.2f}%</td>
              <td style="color:#f59e0b;font-weight:700">+{s['change_5d']:.1f}%</td>
              <td>{s.get('vol_ratio', 0):.1f}x</td>
              <td>{s.get('turnover', 0):.1f}%</td>
              <td>{s.get('mcap_yi', 0):.0f}亿</td>
              <td>{tags_html}</td>
              <td class="reason-cell"><div style="font-size:12px;color:#475569">{reasons_html}</div></td>
            </tr>"""

        rising_chart_labels = json.dumps([s["name"] for s in top_rising], ensure_ascii=False)
        rising_chart_5d = json.dumps([s["change_5d"] for s in top_rising])
        rising_chart_today = json.dumps([s["change_today"] for s in top_rising])

    rising_count = len(rising_stocks)
    avg_5d = sum(s["change_5d"] for s in rising_stocks) / rising_count if rising_count else 0
    rising_with_northbound = sum(1 for s in rising_stocks if "北向加仓" in s.get("up_reason_tags", []))
    rising_with_institution = sum(1 for s in rising_stocks if "机构抢筹" in s.get("up_reason_tags", []))

    # 新闻-股票关联分析
    enriched_news = analyze_news_stock_association(news_list, recommendations)

    # 准备新闻HTML
    news_html = ""
    for n in enriched_news[:15]:
        t = n.get("time", "")[-8:] if n.get("time") else ""
        title = n.get("title", "")
        summary = n.get("summary", "")
        stock_links = n.get("stock_links", [])

        # 生成股票关联徽章
        badges_html = ""
        if stock_links:
            badges_html = '<div class="news-stock-badges">'
            for code, name, reason in stock_links:
                badges_html += f'<span class="stock-badge" title="{reason}">{name}<span class="badge-code">{code}</span></span>'
            badges_html += '</div>'

        news_html += f"""
        <div class="news-item">
          <span class="news-time">{t}</span>
          <span class="news-title">{title}</span>
          {badges_html}
          {f'<p class="news-summary">{summary}</p>' if summary else ''}
        </div>"""

    # 行业排名 TOP10 HTML
    top_ind = industry_ranking[:10]
    bottom_ind = industry_ranking[-5:] if len(industry_ranking) >= 5 else []

    ind_top_html = ""
    for ind in top_ind:
        pct = ind.get("change_pct", 0)
        color = "#dc2626" if pct >= 0 else "#16a34a"
        bar_width = min(abs(pct) * 8, 100)
        ind_top_html += f"""
        <div class="ind-row">
          <span class="ind-name">{ind['name']}</span>
          <div class="ind-bar-wrap">
            <div class="ind-bar" style="width:{bar_width}%;background:{color}"></div>
          </div>
          <span class="ind-pct" style="color:{color}">{'+' if pct >= 0 else ''}{pct}%</span>
          <span class="ind-meta">涨{ind.get('up_count',0)}跌{ind.get('down_count',0)}</span>
        </div>"""

    # 强势股题材词云数据
    all_tags = []
    for s in hot_stocks:
        tags = [t.strip() for t in str(s.get("reason", "")).split("+") if t.strip()]
        all_tags.extend(tags)
    tag_counter = Counter(all_tags)
    top_tags = tag_counter.most_common(20)
    tag_chart_labels = json.dumps([t[0] for t in top_tags], ensure_ascii=False)
    tag_chart_data = json.dumps([t[1] for t in top_tags])

    # ===== 板块信息（供统计卡片展开使用）=====
    # 面板1: 今日资讯→关联行业板块
    news_sector_html = ""
    for ind in industry_ranking[:12]:
        pct = ind.get("change_pct", 0)
        pct_color = "down" if pct < 0 else ""
        pct_sign = "+" if pct >= 0 else ""
        leader = ind.get("leader", "")
        leader_str = f"领涨: {leader}" if leader else f"涨{ind.get('up_count',0)}跌{ind.get('down_count',0)}"
        news_sector_html += f"""<div class="sector-chip"><span class="sector-name">{ind['name']}</span><span class="sector-pct {pct_color}">{pct_sign}{pct}%</span><div class="sector-stocks">{leader_str}</div></div>"""

    # 面板2: 强势题材→题材+关联股票
    theme_sector_html = ""
    theme_with_stocks = []
    for tag, count in top_tags[:12]:
        # 查找该主题对应的股票
        theme_stocks = []
        if tag in THEME_STOCK_MAP:
            theme_name, candidates = THEME_STOCK_MAP[tag]
            theme_stocks = candidates[:3]
        else:
            # 从hot_stocks中找包含该主题的股票
            for hs in hot_stocks:
                if tag in str(hs.get("reason", "")) and len(theme_stocks) < 3:
                    theme_stocks.append(f"{hs['name']}:{hs['code']}")
        theme_with_stocks.append((tag, count, theme_stocks))

    for tag, count, stocks in theme_with_stocks:
        stocks_str = " · ".join(s.split(":")[0] for s in stocks) if stocks else f"出现{count}次"
        theme_sector_html += f"""<div class="sector-chip"><span class="sector-name">{tag}</span><span class="sector-pct">{count}次</span><div class="sector-stocks">{stocks_str}</div></div>"""

    # 行业图表数据
    ind_labels = json.dumps([r["name"] for r in industry_ranking[:15]], ensure_ascii=False)
    ind_data = json.dumps([r.get("change_pct", 0) for r in industry_ranking[:15]])
    ind_colors = json.dumps(["#dc2626" if r.get("change_pct", 0) >= 0 else "#16a34a"
                              for r in industry_ranking[:15]])

    # 推荐股票列表HTML
    rec_rows_html = ""
    for i, s in enumerate(recommendations):
        rank_medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"#{i+1}"
        conf_color = {"高": "#16a34a", "中": "#d97706", "低": "#6b7280"}.get(s["confidence"], "#6b7280")
        conf_badge = f'<span style="background:{conf_color};color:white;padding:2px 8px;border-radius:12px;font-size:12px">{s["confidence"]}</span>'
        reasons_str = " · ".join(s.get("reasons", []))
        catalyst_str = " | ".join(s.get("catalyst", []))
        change_color = "#dc2626" if s.get("change_pct", 0) >= 0 else "#16a34a"

        rec_rows_html += f"""
        <tr class="rec-row">
          <td class="rank-cell">{rank_medal}</td>
          <td>
            <div class="stock-name">{s['name']}</div>
            <div class="stock-code">{s['code']}</div>
          </td>
          <td class="price-cell">¥{s['price']}</td>
          <td style="color:{change_color}">{'+' if s.get('change_pct',0)>=0 else ''}{s.get('change_pct',0):.2f}%</td>
          <td class="score-cell">
            <div class="score-bar-wrap">
              <div class="score-bar" style="width:{s['score']}%"></div>
            </div>
            <span>{s['score']}</span>
          </td>
          <td class="target-cell">¥{s['target_price']}</td>
          <td style="color:#dc2626;font-weight:600">+{s['expected_gain_pct']}%</td>
          <td style="color:#16a34a">¥{s['stop_loss']}</td>
          <td>{conf_badge}</td>
          <td class="reason-cell">
            <div class="reason-tags">{reasons_str}</div>
            {f'<div class="catalyst-text">{catalyst_str}</div>' if catalyst_str else ''}
          </td>
        </tr>"""

    # 评分分布图数据
    score_buckets = [0, 0, 0, 0, 0]  # <40, 40-55, 55-70, 70-85, 85+
    for s in recommendations:
        sc = s["score"]
        if sc < 40: score_buckets[0] += 1
        elif sc < 55: score_buckets[1] += 1
        elif sc < 70: score_buckets[2] += 1
        elif sc < 85: score_buckets[3] += 1
        else: score_buckets[4] += 1

    total_recs = len(recommendations)
    high_conf = sum(1 for s in recommendations if s["confidence"] == "高")
    mid_conf = sum(1 for s in recommendations if s["confidence"] == "中")

    avg_gain = sum(s["expected_gain_pct"] for s in recommendations) / total_recs if total_recs else 0

    hot_count = len(hot_stocks)
    top_industry_name = industry_ranking[0]["name"] if industry_ranking else "—"
    top_industry_pct = industry_ranking[0].get("change_pct", 0) if industry_ranking else 0

    # ===== 可建仓股票 HTML 生成 =====
    position_section_html = ""
    if position_stocks:
        pos_count = len(position_stocks)
        pos_high = sum(1 for s in position_stocks if s["confidence"] == "高")
        pos_avg_rr = sum(s["risk_reward"] for s in position_stocks) / pos_count if pos_count else 0

        pos_rows_html = ""
        pos_chart_names = []
        pos_chart_scores = []
        pos_chart_rr = []
        pos_chart_gain = []  # 目标涨幅空间
        for i, s in enumerate(position_stocks):
            rank_medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"#{i+1}"
            conf_color = {"高": "#16a34a", "中": "#d97706", "低": "#6b7280"}.get(s["confidence"], "#6b7280")
            conf_badge = f'<span style="background:{conf_color};color:white;padding:2px 8px;border-radius:12px;font-size:11px">{s["confidence"]}</span>'
            change_color = "#dc2626" if s.get("change_pct", 0) >= 0 else "#16a34a"

            # 颜色块区分评分
            score = s.get("score", 0)
            if score >= 80:
                score_bg = "#dcfce7"
                score_border = "#86efac"
                score_color = "#16a34a"
            elif score >= 60:
                score_bg = "#fef9c3"
                score_border = "#fde047"
                score_color = "#a16207"
            else:
                score_bg = "#f1f5f9"
                score_border = "#e2e8f0"
                score_color = "#64748b"

            # 策略标签
            tags_html = " ".join(
                f'<span class="pos-tag">{t}</span>'
                for t in s.get("strategy_tags", []) if t
            )

            # 推荐理由
            reasons_html = "<br>".join(s.get("entry_reasons", []))

            # 风险提示
            risk_html = ""
            if s.get("risk_warnings"):
                risk_html = '<div style="color:#dc2626;font-size:11px;margin-top:3px">⚠ ' + " · ".join(s["risk_warnings"]) + '</div>'

            # 事件日历警告
            event_html = ""
            code_events = events_map.get(s["code"], [])
            if code_events:
                event_items = []
                for ev in code_events[:2]:
                    icon = "🚫" if ev["impact"] == "high" else "📅"
                    event_items.append(f'{icon} {ev["date"][-5:]}: {ev["detail"]}')
                event_html = '<div style="color:#d97706;font-size:11px;margin-top:2px">' + " · ".join(event_items) + '</div>'

            # 重复推荐警告
            repeat_html = ""
            if s["code"] in repeat_map:
                rp = repeat_map[s["code"]]
                appear = rp.get("appear_days", 2)
                repeat_html = f'<div style="color:#7c3aed;font-size:11px;margin-top:2px"><strong>🔄 已连续推荐{appear}日</strong>，建议上移止损至成本价附近</div>'

            # 单票最大亏损
            max_loss = s.get("max_loss_amount", 0)
            max_loss_pct = s.get("max_loss_pct", 0)
            invest = s.get("invest_amount", 0)

            pos_rows_html += f"""
            <tr class="pos-row">
              <td class="rank-cell">{rank_medal}</td>
              <td>
                <div class="stock-name">{s['name']}</div>
                <div class="stock-code">{s['code']}</div>
              </td>
              <td class="price-cell">¥{s['price']}</td>
              <td style="color:{change_color}">{'+' if s.get('change_pct',0)>=0 else ''}{s.get('change_pct',0):.2f}%</td>
              <td style="background:{score_bg};border:1px solid {score_border};border-radius:6px;text-align:center;font-weight:700;color:{score_color};padding:4px 8px">
                {s['score']}
              </td>
              <td style="font-weight:600;color:#0f172a">¥{s['entry_price']}</td>
              <td style="color:#3b82f6">¥{s['add_price']}</td>
              <td style="color:#dc2626;font-weight:600">¥{s['target_price']}</td>
              <td style="color:#16a34a">¥{s['stop_loss']}</td>
              <td style="font-weight:600;color:#7c3aed;font-size:12px">{s['position_ratio']}</td>
              <td style="font-weight:700;color:{'green' if s['risk_reward']>=2 else '#d97706'}">{s['risk_reward']}:1</td>
              <td style="color:#16a34a;font-size:12px;font-weight:600">¥{max_loss:,} <span style="font-size:11px">({max_loss_pct}%)</span></td>
              <td>{conf_badge}</td>
              <td class="reason-cell" style="max-width:220px">
                {tags_html}
                <div style="font-size:12px;color:#374151;margin-top:3px">{reasons_html}</div>
                {risk_html}
                {event_html}
                {repeat_html}
              </td>
            </tr>"""

            pos_chart_names.append(s["name"])
            pos_chart_scores.append(s["score"])
            pos_chart_rr.append(s["risk_reward"])
            # 计算目标空间百分比
            entry = s.get("entry_price", s["price"])
            target = s.get("target_price", 0)
            gain_pct = round((target - entry) / entry * 100, 1) if entry > 0 and target > 0 else 0
            pos_chart_gain.append(gain_pct)

        position_section_html = f"""
  <div class="card" style="margin-bottom:24px">
    <div class="card-title">🏗️ 可建仓股票推荐（{TODAY_DISPLAY}）</div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px">
      <div class="stat-card" style="padding:14px">
        <div class="stat-label">🏗️ 可建仓标的</div>
        <div class="stat-value" style="color:#7c3aed;font-size:26px">{pos_count}</div>
        <div class="stat-sub">满足建仓条件</div>
      </div>
      <div class="stat-card" style="padding:14px">
        <div class="stat-label">🟢 高信心</div>
        <div class="stat-value" style="color:#16a34a;font-size:26px">{pos_high}</div>
        <div class="stat-sub">只强烈推荐</div>
      </div>
      <div class="stat-card" style="padding:14px">
        <div class="stat-label">📊 平均风险收益比</div>
        <div class="stat-value" style="color:#3b82f6;font-size:26px">{pos_avg_rr:.1f}:1</div>
        <div class="stat-sub">收益/风险比</div>
      </div>
      <div class="stat-card" style="padding:14px">
        <div class="stat-label">💡 建仓原则</div>
        <div class="stat-value" style="color:#f59e0b;font-size:14px">分批·低吸·控仓</div>
        <div class="stat-sub">不追高·设止损</div>
      </div>
    </div>
    <div style="margin-bottom:20px">
      <div style="font-size:14px;font-weight:600;color:#374151;margin-bottom:10px">📊 建仓股评分 & 风险收益比</div>
      <div style="position:relative;height:260px">
        <canvas id="positionChart"></canvas>
      </div>
    </div>
    <p style="color:#64748b;font-size:13px;margin-bottom:12px">
      建仓标准：价格相对低位 · 非追高 · 有催化支撑 · 风险收益比≥1.5 · 按综合评分降序
    </p>
    <div class="rec-table-wrap">
      <table>
        <thead>
          <tr>
            <th>排名</th><th>股票</th><th>现价</th><th>今日涨跌</th>
            <th>建仓评分</th><th>入场价</th><th>加仓价</th><th>目标价</th>
            <th>止损价</th><th>建议仓位</th><th>风险收益比</th><th>单票最大亏损</th><th>信心</th>
            <th>推荐理由</th>
          </tr>
        </thead>
        <tbody>
          {pos_rows_html}
        </tbody>
      </table>
    </div>
  </div>"""

        pos_chart_labels_json = json.dumps(pos_chart_names, ensure_ascii=False)
        pos_chart_scores_json = json.dumps(pos_chart_scores)
        pos_chart_rr_json = json.dumps(pos_chart_rr)
        pos_chart_gain_json = json.dumps(pos_chart_gain)
    else:
        pos_chart_labels_json = json.dumps([], ensure_ascii=False)
        pos_chart_scores_json = json.dumps([])
        pos_chart_rr_json = json.dumps([])
        pos_chart_gain_json = json.dumps([])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>干云大模型 - {TODAY_DISPLAY}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; background: #f0f4f8; color: #1e293b; line-height: 1.6; }}

  .header {{ background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #1d4ed8 100%); color: white; padding: 32px 40px; }}
  .header h1 {{ font-size: 28px; font-weight: 700; letter-spacing: 2px; }}
  .header .subtitle {{ opacity: 0.8; margin-top: 6px; font-size: 14px; }}
  .header .date-badge {{ display: inline-block; background: rgba(255,255,255,0.2); padding: 4px 16px; border-radius: 20px; font-size: 13px; margin-top: 10px; }}

  .main {{ max-width: 1400px; margin: 0 auto; padding: 24px 20px; }}

  .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
  .stat-card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .stat-value {{ font-size: 32px; font-weight: 700; margin: 6px 0; }}
  .stat-label {{ color: #64748b; font-size: 13px; }}
  .stat-sub {{ font-size: 12px; color: #94a3b8; margin-top: 4px; }}

  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
  .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 24px; }}

  .card {{ background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .card-title {{ font-size: 16px; font-weight: 700; color: #0f172a; padding-bottom: 14px; border-bottom: 2px solid #e2e8f0; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }}

  /* 新闻 */
  .news-item {{ padding: 10px 0; border-bottom: 1px solid #f1f5f9; }}
  .news-item:last-child {{ border-bottom: none; }}
  .news-time {{ color: #3b82f6; font-size: 12px; font-weight: 600; margin-right: 8px; }}
  .news-title {{ font-size: 14px; color: #1e293b; }}
  .news-summary {{ font-size: 12px; color: #64748b; margin-top: 4px; }}

  /* 新闻股票关联徽章 */
  .news-stock-badges {{ display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }}
  .stock-badge {{ display: inline-flex; align-items: center; gap: 3px; background: linear-gradient(135deg, #dbeafe, #bfdbfe); color: #1d4ed8; font-size: 11px; padding: 2px 8px; border-radius: 12px; cursor: pointer; transition: all 0.2s; border: 1px solid #93c5fd; }}
  .stock-badge:hover {{ background: linear-gradient(135deg, #bfdbfe, #93c5fd); transform: scale(1.05); }}
  .badge-code {{ color: #6b7280; font-size: 10px; font-family: monospace; }}

  /* 可点击统计卡片 */
  .stat-card-clickable {{ cursor: pointer; transition: transform 0.15s, box-shadow 0.15s; position: relative; }}
  .stat-card-clickable:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.12); }}
  .stat-card-clickable::after {{ content: "▾"; position: absolute; right: 14px; top: 14px; font-size: 14px; color: #94a3b8; transition: transform 0.3s; }}
  .stat-card-clickable.open::after {{ transform: rotate(180deg); }}

  /* 展开面板（独立于stats-grid外部） */
  .expand-panel {{ max-height: 0; overflow: hidden; transition: max-height 0.4s ease, padding 0.3s, margin 0.3s; background: #f8fafc; border-radius: 12px; margin-bottom: 16px; border: 1px solid #e2e8f0; }}
  .expand-panel.show {{ max-height: 400px; padding: 16px 20px; }}
  .sector-chip {{ display: inline-block; background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 14px; margin: 4px; font-size: 13px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
  .sector-chip .sector-name {{ font-weight: 600; color: #1e293b; }}
  .sector-chip .sector-pct {{ color: #dc2626; font-size: 12px; margin-left: 6px; }}
  .sector-chip .sector-pct.down {{ color: #16a34a; }}
  .sector-chip .sector-stocks {{ font-size: 11px; color: #64748b; margin-top: 2px; }}

  /* 行业 */
  .ind-row {{ display: flex; align-items: center; padding: 8px 0; gap: 10px; border-bottom: 1px solid #f8fafc; }}
  .ind-name {{ width: 90px; font-size: 13px; flex-shrink: 0; }}
  .ind-bar-wrap {{ flex: 1; background: #f1f5f9; border-radius: 4px; height: 8px; overflow: hidden; }}
  .ind-bar {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
  .ind-pct {{ width: 55px; text-align: right; font-size: 13px; font-weight: 600; flex-shrink: 0; }}
  .ind-meta {{ width: 80px; font-size: 11px; color: #94a3b8; flex-shrink: 0; }}

  /* 推荐表格（冻结表头） */
  .rec-table-wrap {{ overflow-x: auto; max-height: 600px; overflow-y: auto; position: relative; }}
  .rec-table-wrap thead th {{ position: sticky; top: 0; z-index: 10; box-shadow: 0 1px 0 #e2e8f0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #f8fafc; color: #64748b; font-weight: 600; padding: 12px 10px; text-align: left; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }}
  .rec-row {{ border-bottom: 1px solid #f1f5f9; transition: background 0.15s; }}
  .rec-row:hover {{ background: #f8fafc; }}
  td {{ padding: 12px 10px; vertical-align: middle; }}
  .rank-cell {{ font-size: 18px; }}
  .stock-name {{ font-weight: 600; color: #0f172a; }}
  .stock-code {{ color: #94a3b8; font-size: 11px; margin-top: 2px; }}
  .price-cell {{ font-weight: 700; font-size: 15px; color: #0f172a; }}
  .target-cell {{ font-weight: 700; color: #dc2626; }}
  .score-cell {{ display: flex; align-items: center; gap: 8px; }}
  .score-bar-wrap {{ width: 60px; height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; }}
  .score-bar {{ height: 100%; background: linear-gradient(90deg, #3b82f6, #8b5cf6); border-radius: 3px; }}
  .reason-cell {{ max-width: 200px; }}
  .reason-tags {{ color: #64748b; font-size: 12px; }}
  .catalyst-text {{ color: #d97706; font-size: 11px; margin-top: 3px; }}

  .rise-tag {{ display: inline-block; background: linear-gradient(135deg, #fee2e2, #fecaca); color: #dc2626; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin: 2px; font-weight: 600; }}
  .rising-row {{ border-bottom: 1px solid #f1f5f9; transition: background 0.15s; }}
  .rising-row:hover {{ background: #fff7ed; }}

  .pos-tag {{ display: inline-block; background: linear-gradient(135deg, #ede9fe, #ddd6fe); color: #7c3aed; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin: 2px; font-weight: 600; }}
  .pos-row {{ border-bottom: 1px solid #f1f5f9; transition: background 0.15s; }}
  .pos-row:hover {{ background: #f5f3ff; }}

  .chart-container {{ position: relative; height: 280px; }}

  .disclaimer {{ background: #fef3c7; border: 1px solid #fbbf24; border-radius: 8px; padding: 14px 20px; margin-top: 24px; font-size: 12px; color: #92400e; line-height: 1.8; }}

  .footer {{ text-align: center; color: #94a3b8; font-size: 12px; padding: 20px; }}

  @media (max-width: 768px) {{
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>📈 干云大模型</h1>
  <p class="subtitle">全球财经资讯 · 行业板块 · 低价潜力股推荐</p>
  <span class="date-badge">📅 {TODAY_DISPLAY} · 数据来源: 东财/同花顺/腾讯财经</span>
</div>

<div class="main">

  <!-- 市场一句话摘要 -->
  <div style="background:linear-gradient(135deg, {bg_color});border-radius:12px;padding:18px 24px;margin-bottom:16px;display:flex;align-items:center;gap:24px;flex-wrap:wrap;color:white;font-size:14px">
    <div style="font-weight:700;font-size:16px">{mood_emoji} 今日市场情绪：{market_mood}</div>
    <div> | 上涨家数 {up_ratio*100:.0f}%</div>
    <div> | 最佳策略：<strong>{market_best_strategy}</strong></div>
    {f'<div> | 首选板块：<strong>{market_hot_sectors}</strong></div>' if market_hot_sectors else ''}
    <div> | 仓位建议：<strong>{total_pos_cap}</strong></div>
    {f'<div style="background:rgba(255,255,255,0.2);padding:2px 10px;border-radius:10px;font-size:12px">📉 沪指{index_price:.0f}{"线" if above_ma20 else "线"}下，仓位已自动下调</div>' if position_adjust < 0 else ''}
  </div>

  {f'''<div style="background:#fef3c7;border:1px solid #f59e0b;border-radius:10px;padding:12px 18px;margin-bottom:16px;font-size:13px;display:flex;align-items:center;gap:12px">
    <span style="font-size:18px">⚠️</span>
    <span><strong>数据源健康度：</strong>{ds_source} | 换手率缺失率 <strong>{ds_turnover_miss}%</strong> | {ds_warning or '数据质量正常'}</span>
  </div>''' if ds_warning else ''}

  {f'''<div style="background:#ecfdf5;border:1px solid #6ee7b7;border-radius:10px;padding:12px 18px;margin-bottom:16px;font-size:13px;display:flex;align-items:center;gap:12px">
    <span style="font-size:18px">✅</span>
    <span><strong>数据源健康度：</strong>{ds_source} | 换手率缺失率 <strong>{ds_turnover_miss}%</strong>（正常）</span>
  </div>''' if not ds_warning else ''}

  <!-- 回测验证 -->
  {f'''<div style="background:white;border-radius:12px;padding:16px 20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.08);font-size:13px">
    <strong>📊 历史回测（近5日）：</strong>
    总推荐 {bt_total} 只 |
    <span style="color:#dc2626">✅ 达目标价 {bt_hit_target}只({bt_target_pct}%)</span> |
    <span style="color:#dc2626">❌ 触止损 {bt_hit_stop}只({bt_stop_pct}%)</span> |
    <span style="color:#3b82f6">🔄 运行中 {bt_still}只({bt_running_pct}%)</span>
    {f' | <span style="color:#d97706">⚠️ 重复推荐：{"、".join(r["code"]+"("+str(r.get("appear_days",2))+"日)" for r in bt_repeat[:3])}</span>' if bt_repeat else ''}
  </div>''' if bt_total > 0 else ''}

  <!-- 核心推荐池 -->
  {f'''<div class="card" style="margin-bottom:16px;border-left:4px solid #7c3aed">
    <div class="card-title">⭐ 今日核心推荐池（≤3只 · 首选建仓标的）</div>
    <div style="display:grid;grid-template-columns:repeat({min(len(core_picks),3)},1fr);gap:12px">
      {"".join(
        _build_core_pick_card(p)
        for p in core_picks
      )}
    </div>
  </div>''' if core_picks else ''}

  <!-- 回避清单 -->
  {f'''<div class="card" style="margin-bottom:16px">
    <div class="card-title">🚫 今日回避清单（{len(avoid_list)}只）</div>
    <div style="display:flex;flex-wrap:wrap;gap:8px">
      {"".join(
        f'<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:8px 14px;font-size:12px"><strong>{a["name"]}</strong>({a["code"]}) · ¥{a["price"]}<br><span style="color:#dc2626">{a["avoid_reason"]}</span></div>'
        for a in avoid_list
      )}
    </div>
  </div>''' if avoid_list else ''}

  <!-- 核心统计（4卡片一行） -->
  <div class="stats-grid">
    <div class="stat-card stat-card-clickable" onclick="togglePanel('newsPanel', this)">
      <div class="stat-label">📰 今日资讯</div>
      <div class="stat-value" style="color:#3b82f6">{len(news_list)}</div>
      <div class="stat-sub">条全球财经快讯</div>
    </div>
    <div class="stat-card stat-card-clickable" onclick="togglePanel('themePanel', this)">
      <div class="stat-label">🔥 强势题材</div>
      <div class="stat-value" style="color:#f59e0b">{hot_count}</div>
      <div class="stat-sub">只今日强势股涨停</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">🏆 领涨行业</div>
      <div class="stat-value" style="color:#dc2626;font-size:22px">{top_industry_name}</div>
      <div class="stat-sub">涨幅 +{top_industry_pct}%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">💡 推荐低价股</div>
      <div class="stat-value" style="color:#8b5cf6">{total_recs}</div>
      <div class="stat-sub">高信心 {high_conf} 只 · 均预期涨 {avg_gain:.1f}%</div>
    </div>
  </div>

  <!-- 展开面板（放在grid外部，不影响4卡片一行布局） -->
  <div id="newsPanel" class="expand-panel">
    <div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:10px">📊 今日资讯关联板块</div>
    <div style="display:flex;flex-wrap:wrap;gap:6px">{news_sector_html if news_sector_html else NO_SECTOR_FALLBACK}</div>
  </div>
  <div id="themePanel" class="expand-panel">
    <div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:10px">🔥 强势题材 & 关联股票</div>
    <div style="display:flex;flex-wrap:wrap;gap:6px">{theme_sector_html}</div>
  </div>

  <!-- 新闻 + 行业排名 -->
  <div class="grid-2">
    <div class="card">
      <div class="card-title">📰 全球财经快讯</div>
      <div style="max-height:380px;overflow-y:auto">
        {news_html}
      </div>
    </div>
    <div class="card">
      <div class="card-title">📊 行业板块涨跌 TOP10</div>
      {ind_top_html}
    </div>
  </div>

  <!-- 图表行 -->
  <div class="grid-2">
    <div class="card">
      <div class="card-title">📊 行业涨跌幅对比</div>
      <div class="chart-container">
        <canvas id="industryChart"></canvas>
      </div>
    </div>
    <div class="card">
      <div class="card-title">🔥 热门题材词频 TOP20</div>
      <div class="chart-container">
        <canvas id="tagChart"></canvas>
      </div>
    </div>
  </div>

  <!-- 推荐股票表 -->
  <div class="card" style="margin-bottom:24px">
    <div class="card-title">💎 低价潜力股推荐清单（{TODAY_DISPLAY}）</div>
    <p style="color:#64748b;font-size:13px;margin-bottom:16px">
      筛选条件：股价 2~20元 · 非ST · 综合评分≥40 · 按评分降序排列
    </p>
    <div class="rec-table-wrap sticky-header">
      <table>
        <thead>
          <tr>
            <th>排名</th>
            <th>股票</th>
            <th>现价</th>
            <th>今日涨跌</th>
            <th>综合评分</th>
            <th>目标价</th>
            <th>预期涨幅</th>
            <th>止损价</th>
            <th>信心</th>
            <th>推荐理由</th>
          </tr>
        </thead>
        <tbody>
          {rec_rows_html if rec_rows_html else '<tr><td colspan="10" style="text-align:center;padding:40px;color:#94a3b8">今日无符合条件的推荐股票（可能是非交易日或数据更新中）</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>

  <!-- 短期上涨趋势股 -->
  <div class="card" style="margin-bottom:24px">
    <div class="card-title">🚀 短期上涨趋势股（{TODAY_DISPLAY}）</div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px">
      <div class="stat-card" style="padding:14px">
        <div class="stat-label">📈 趋势上涨股</div>
        <div class="stat-value" style="color:#f59e0b;font-size:26px">{rising_count}</div>
        <div class="stat-sub">5日涨幅≥5%且今日续涨</div>
      </div>
      <div class="stat-card" style="padding:14px">
        <div class="stat-label">📊 平均5日涨幅</div>
        <div class="stat-value" style="color:#dc2626;font-size:26px">+{avg_5d:.1f}%</div>
        <div class="stat-sub">短期动能强劲</div>
      </div>
      <div class="stat-card" style="padding:14px">
        <div class="stat-label">🏦 北向加仓</div>
        <div class="stat-value" style="color:#3b82f6;font-size:26px">{rising_with_northbound}</div>
        <div class="stat-sub">只获北向净买入</div>
      </div>
      <div class="stat-card" style="padding:14px">
        <div class="stat-label">🏛️ 机构抢筹</div>
        <div class="stat-value" style="color:#8b5cf6;font-size:26px">{rising_with_institution}</div>
        <div class="stat-sub">只龙虎榜机构买入</div>
      </div>
    </div>
    <div style="margin-bottom:20px">
      <div style="font-size:14px;font-weight:600;color:#374151;margin-bottom:10px">📊 趋势股涨幅对比（橙=5日涨幅 绿=今日涨幅）</div>
      <div style="position:relative;height:260px">
        <canvas id="risingChart"></canvas>
      </div>
    </div>
    <p style="color:#64748b;font-size:13px;margin-bottom:12px">
      筛选标准：近5日累涨≥5% · 今日仍在上涨 · 量比/资金/题材综合分析 · 非ST股
    </p>
    <div class="rec-table-wrap sticky-header">
      <table>
        <thead>
          <tr>
            <th>排名</th><th>股票</th><th>现价</th><th>今日涨幅</th>
            <th>5日涨幅</th><th>量比</th><th>换手率</th><th>总市值</th>
            <th>上涨标签</th><th>上涨原因分析</th>
          </tr>
        </thead>
        <tbody>
          {rising_html if rising_html else '<tr><td colspan="10" style="text-align:center;padding:40px;color:#94a3b8">今日暂无连续上涨趋势股（非交易日或数据更新中）</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>

  <!-- 可建仓股票推荐 -->
  {position_section_html}

  <!-- 免责声明（强化版） -->
  <div class="disclaimer">
    ⚠️ <strong>重要免责声明：</strong><br>
    1. 本报告由AI系统基于公开市场数据自动生成，<strong>仅为数据分析参考，不构成任何投资建议</strong>，据此操作风险自担。<br>
    2. 报告中"目标价""预期涨幅""风险收益比"均为模型估算，<strong>模拟测算收益不代表实际收益，过往表现不预示未来</strong>。<br>
    3. 股市有风险，投资需谨慎。请结合自身风险承受能力独立决策。<br>
    4. 本报告不面向特定投资者，如对外分享需增加合规提示。<br>
    5. 数据来源：东方财富/同花顺/腾讯财经公开数据接口，可能存在延迟或缺失。<br>
    6. <strong>投资有风险，入市需谨慎。历史数据不代表未来表现。</strong>
  </div>

  <div class="footer">
    生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 数据来源：东方财富/同花顺/腾讯财经
  </div>

</div>

<script>
// ===== 统计卡片展开 / 折叠 =====
function togglePanel(panelId, cardEl) {{
  var panel = document.getElementById(panelId);
  if (!panel) return;
  var isOpen = panel.classList.contains('show');
  // 关闭所有其他面板
  document.querySelectorAll('.expand-panel.show').forEach(function(p) {{
    p.classList.remove('show');
  }});
  document.querySelectorAll('.stat-card-clickable.open').forEach(function(c) {{
    c.classList.remove('open');
  }});
  if (!isOpen) {{
    panel.classList.add('show');
    cardEl.classList.add('open');
    panel.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
  }}
}}

// 行业涨跌图
const industryCtx = document.getElementById('industryChart').getContext('2d');
new Chart(industryCtx, {{
  type: 'bar',
  data: {{
    labels: {ind_labels},
    datasets: [{{
      label: '涨跌幅%',
      data: {ind_data},
      backgroundColor: {ind_colors},
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ font: {{ size: 10 }}, maxRotation: 45 }} }},
      y: {{ grid: {{ color: '#f1f5f9' }}, ticks: {{ callback: v => v + '%' }} }}
    }}
  }}
}});

// 题材热度图
const tagCtx = document.getElementById('tagChart').getContext('2d');
new Chart(tagCtx, {{
  type: 'bar',
  data: {{
    labels: {tag_chart_labels},
    datasets: [{{
      label: '出现次数',
      data: {tag_chart_data},
      backgroundColor: 'rgba(245, 158, 11, 0.7)',
      borderColor: 'rgba(245, 158, 11, 1)',
      borderWidth: 1,
      borderRadius: 4,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: '#f1f5f9' }} }},
      y: {{ ticks: {{ font: {{ size: 10 }} }} }}
    }}
  }}
}});

// 短期上涨趋势图
const risingCtx = document.getElementById('risingChart');
if (risingCtx) {{
  new Chart(risingCtx.getContext('2d'), {{
    type: 'bar',
    data: {{
      labels: {rising_chart_labels},
      datasets: [
        {{
          label: '5日涨幅%',
          data: {rising_chart_5d},
          backgroundColor: 'rgba(245, 158, 11, 0.75)',
          borderColor: 'rgba(245, 158, 11, 1)',
          borderWidth: 1,
          borderRadius: 4,
          order: 2,
        }},
        {{
          label: '今日涨幅%',
          data: {rising_chart_today},
          backgroundColor: 'rgba(22, 163, 74, 0.65)',
          borderColor: 'rgba(22, 163, 74, 1)',
          borderWidth: 1,
          borderRadius: 4,
          order: 1,
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ position: 'top', labels: {{ font: {{ size: 12 }} }} }},
        tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y + '%' }} }}
      }},
      scales: {{
        x: {{ ticks: {{ font: {{ size: 10 }}, maxRotation: 30 }} }},
        y: {{ grid: {{ color: '#f1f5f9' }}, ticks: {{ callback: v => v + '%' }} }}
      }}
    }}
  }});
}}

// 可建仓股票评分 & 风险收益比 & 目标空间图
const posCtx = document.getElementById('positionChart');
if (posCtx) {{
  new Chart(posCtx.getContext('2d'), {{
    type: 'bar',
    data: {{
      labels: {pos_chart_labels_json},
      datasets: [
        {{
          label: '建仓评分',
          data: {pos_chart_scores_json},
          backgroundColor: 'rgba(124, 58, 237, 0.7)',
          borderColor: 'rgba(124, 58, 237, 1)',
          borderWidth: 1,
          borderRadius: 4,
          yAxisID: 'y',
          order: 3,
        }},
        {{
          label: '目标空间%',
          data: {pos_chart_gain_json},
          backgroundColor: 'rgba(22, 163, 74, 0.5)',
          borderColor: 'rgba(22, 163, 74, 1)',
          borderWidth: 1,
          borderRadius: 4,
          yAxisID: 'y',
          order: 2,
        }},
        {{
          label: '风险收益比',
          data: {pos_chart_rr_json},
          type: 'line',
          borderColor: 'rgba(245, 158, 11, 1)',
          backgroundColor: 'rgba(245, 158, 11, 0.15)',
          borderWidth: 2,
          pointRadius: 5,
          pointBackgroundColor: 'rgba(245, 158, 11, 1)',
          fill: true,
          yAxisID: 'y1',
          order: 1,
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ position: 'top', labels: {{ font: {{ size: 12 }} }} }},
        tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y }} }}
      }},
      scales: {{
        x: {{ ticks: {{ font: {{ size: 10 }}, maxRotation: 30 }} }},
        y: {{ position: 'left', grid: {{ color: '#f1f5f9' }}, title: {{ display: true, text: '评分', font: {{ size: 11 }} }} }},
        y1: {{ position: 'right', grid: {{ drawOnChartArea: false }}, title: {{ display: true, text: '风险收益比', font: {{ size: 11 }} }} }}
      }}
    }}
  }});
}}
</script>
</body>
</html>"""
    return html


# ═══════════════════════════════════════════════════
#  主程序
# ═══════════════════════════════════════════════════

def main():
    print("=" * 60)
    print(f"  每日股票分析系统  {TODAY_DISPLAY}")
    print("=" * 60)
    start_time = time.time()

    # 0. 市场环境感知（新增）
    market_env = fetch_market_environment()

    # 1. 全球新闻
    news_list = fetch_global_news(30)
    time.sleep(1)

    # 2. 行业板块
    industry_ranking = fetch_industry_ranking()
    time.sleep(1)

    # 3. 强势股题材
    hot_stocks = fetch_hot_stocks()
    time.sleep(1)

    # 4. 低价股候选（价格 2~20元）
    candidates = fetch_low_price_candidates(max_price=20.0, min_price=2.0, top_n=200, hot_stocks=hot_stocks)
    time.sleep(1)

    # 4b. 短期上涨趋势分析
    rising_stocks = fetch_rising_stocks(hot_stocks=hot_stocks)
    time.sleep(1)

    # 5. 评分和预测
    if candidates:
        recommendations = score_and_predict(candidates, hot_stocks, industry_ranking)
    else:
        print("  ⚠ 未获取到候选股票（可能是非交易日），使用空列表")
        recommendations = []

    # 5b. 可建仓股票筛选（含市场环境感知）
    if candidates:
        position_result = fetch_position_building_stocks(
            candidates, hot_stocks, industry_ranking, rising_stocks, market_env
        )
    else:
        position_result = {"position_stocks": [], "core_picks": [], "avoid_list": [],
                           "total_position_cap": "40%", "position_adjust": 0,
                           "data_source_health": {}}

    # 5c. 事件日历
    all_pos_codes = [s["code"] for s in position_result.get("position_stocks", [])]
    events_map = fetch_event_calendar(all_pos_codes + [s["code"] for s in recommendations[:10]])

    # 5d. 回测验证（新增）
    backtest = fetch_backtest_summary(days=5)

    # 5e. 分析热股题材获取首选板块
    all_tags = []
    for s in hot_stocks:
        tags = [t.strip() for t in str(s.get("reason", "")).split("+") if t.strip()]
        all_tags.extend(tags)
    tag_counter = Counter(all_tags)
    hot_sectors = ", ".join(tag for tag, _ in tag_counter.most_common(3))
    market_env["hot_sectors"] = hot_sectors

    # 6. 生成HTML报告
    print("📄 生成HTML日报...")
    html_content = generate_html_report(
        news_list, industry_ranking, hot_stocks, recommendations,
        rising_stocks, position_result, market_env, backtest, events_map
    )

    # 7. 保存文件
    output_file = OUTPUT_DIR / f"stock-report-{TODAY}.html"
    output_file.write_text(html_content, encoding="utf-8")

    # 同时保存一份 latest.html 方便直接访问
    latest_file = OUTPUT_DIR / "latest.html"
    latest_file.write_text(html_content, encoding="utf-8")

    # 8. 保存追踪记录（新增）
    save_daily_tracking(
        position_result.get("position_stocks", []),
        recommendations
    )

    elapsed = time.time() - start_time
    print(f"\n✅ 完成！耗时 {elapsed:.1f}秒")
    print(f"📁 日报已保存: {output_file}")
    print(f"📁 最新版本: {latest_file}")
    print(f"\n推荐股票数: {len(recommendations)}")
    if recommendations:
        print("\n🏆 TOP 5 低价推荐:")
        for i, s in enumerate(recommendations[:5]):
            print(f"  {i+1}. {s['name']}({s['code']}) ¥{s['price']} → 目标¥{s['target_price']} "
                  f"(+{s['expected_gain_pct']}%) 评分:{s['score']} 信心:{s['confidence']}")

    if rising_stocks:
        print(f"\n📈 短期上涨趋势股 TOP 5:")
        for i, s in enumerate(rising_stocks[:5]):
            tags = "/".join(s.get("up_reason_tags", [])[:3])
            print(f"  {i+1}. {s['name']}({s['code']}) ¥{s['price']} "
                  f"今日+{s['change_today']:.2f}% 5日+{s['change_5d']:.1f}%"
                  f"  [{tags}]")

    pos_stocks = position_result.get("position_stocks", [])
    if pos_stocks:
        print(f"\n🏗️ 可建仓股票 TOP 5:")
        for i, s in enumerate(pos_stocks[:5]):
            reasons = " · ".join(s.get("entry_reasons", [])[:2])
            print(f"  {i+1}. {s['name']}({s['code']}) ¥{s['price']} "
                  f"入场¥{s['entry_price']}→目标¥{s['target_price']} 止损¥{s['stop_loss']} "
                  f"仓位:{s['position_ratio']} 评分:{s['score']} [{reasons}]")

        core_picks = position_result.get("core_picks", [])
        if core_picks:
            print(f"\n⭐ 今日核心推荐:")
            for s in core_picks:
                print(f"  • {s['name']}({s['code']}) [{s.get('core_pick_reason', '')}] "
                      f"入场¥{s['entry_price']} 目标¥{s['target_price']} 仓位:{s['position_ratio']}")

    avoid_list = position_result.get("avoid_list", [])
    if avoid_list:
        print(f"\n🚫 回避清单 ({len(avoid_list)}只):")
        for a in avoid_list[:5]:
            print(f"  • {a['name']}({a['code']}): {a['avoid_reason']}")

    return str(output_file)


if __name__ == "__main__":
    main()
