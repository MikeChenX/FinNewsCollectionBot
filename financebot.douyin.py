# 福生无量天尊
from openai import OpenAI
import feedparser
import requests
from newspaper import Article
from datetime import datetime
import time
import pytz
import os
from typing import Dict, Tuple, List

# OpenAI API Key
openai_api_key = os.getenv("OPENAI_API_KEY")
# 从环境变量获取 Server酱 SendKeys
server_chan_keys_env = os.getenv("SERVER_CHAN_KEYS")
if not server_chan_keys_env:
    raise ValueError("环境变量 SERVER_CHAN_KEYS 未设置，请在Github Actions中设置此变量！")
server_chan_keys = server_chan_keys_env.split(",")

openai_client = OpenAI(api_key=openai_api_key, base_url="https://api.deepseek.com/v1")

# 扩展RSS源：新增民生/综合热点源，适配每日热点速览
rss_feeds = {
    "🔥 每日综合热点": {
        "央视新闻":"https://news.cctv.com/rss/news.shtml",
        "人民日报":"https://www.people.com.cn/rss/201905/17/c1008-40359834.html",
        "新华社":"http://www.xinhuanet.com/rss.xml"
    },
    "💲 财经热点":{
        "华尔街见闻":"https://dedicated.wallstreetcn.com/rss.xml",
        "东方财富":"http://rss.eastmoney.com/rss_partener.xml",
    },
    "🏠 民生政策": {
        "中国政府网":"http://www.gov.cn/fuwu/bmfw/rss.htm",
        "中新网民生":"https://www.chinanews.com.cn/rss/minsheng.xml",
    }
}

# 获取北京时间
def today_date():
    return datetime.now(pytz.timezone("Asia/Shanghai")).date()

# 爬取网页正文 (用于 AI 分析，但不展示)
def fetch_article_text(url):
    try:
        print(f"📰 正在爬取文章内容: {url}")
        article = Article(url)
        article.download()
        article.parse()
        text = article.text[:800]  # 热点速览只需核心信息，缩短文本长度
        if not text:
            print(f"⚠️ 文章内容为空: {url}")
        return text
    except Exception as e:
        print(f"❌ 文章爬取失败: {url}，错误: {e}")
        return "（未能获取文章正文）"

# 添加 User-Agent 头
def fetch_feed_with_headers(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    return feedparser.parse(url, request_headers=headers)

# 自动重试获取 RSS
def fetch_feed_with_retry(url, retries=3, delay=5):
    for i in range(retries):
        try:
            feed = fetch_feed_with_headers(url)
            if feed and hasattr(feed, 'entries') and len(feed.entries) > 0:
                return feed
        except Exception as e:
            print(f"⚠️ 第 {i+1} 次请求 {url} 失败: {e}")
            time.sleep(delay)
    print(f"❌ 跳过 {url}, 尝试 {retries} 次后仍失败。")
    return None

# 获取RSS内容（爬取正文但不展示）
def fetch_rss_articles(rss_feeds, max_articles=10) -> Tuple[Dict[str, str], str]:
    news_data = {}
    analysis_text = ""  # 用于AI分析的正文内容

    for category, sources in rss_feeds.items():
        category_content = ""
        for source, url in sources.items():
            print(f"📡 正在获取 {source} 的 RSS 源: {url}")
            feed = fetch_feed_with_retry(url)
            if not feed:
                print(f"⚠️ 无法获取 {source} 的 RSS 数据")
                continue
            print(f"✅ {source} RSS 获取成功，共 {len(feed.entries)} 条新闻")

            articles = []  # 每个source都需要重新初始化列表
            for entry in feed.entries[:5]:
                title = entry.get('title', '无标题')
                link = entry.get('link', '') or entry.get('guid', '')
                if not link:
                    print(f"⚠️ {source} 的新闻 '{title}' 没有链接，跳过")
                    continue

                # 爬取正文用于分析（不展示）
                article_text = fetch_article_text(link)
                analysis_text += f"【{title}】\n{article_text}\n\n"

                print(f"🔹 {source} - {title} 获取成功")
                articles.append(f"- [{title}]({link})")

            if articles:
                category_content += f"### {source}\n" + "\n".join(articles) + "\n\n"

        news_data[category] = category_content

    return news_data, analysis_text

# 优化：合规校验函数（适配每日热点速览）
def compliance_check(content: str) -> Tuple[bool, str]:
    """
    每日热点速览内容合规校验（适配抖音监管要求）
    """
    # 禁止关键词：时政敏感/引导性/违规词汇
    forbidden_keywords = [
        "个股涨停", "龙头个股", "推荐", "买入", "卖出", "必涨", "必跌",
        "精准预测", "稳赚", "抄底", "逃顶", "敏感时政关键词", "煽动性表述",
        "绝对化表述", "虚假承诺"
    ]
    
    # 检查禁止关键词
    found_keywords = [kw for kw in forbidden_keywords if kw in content]
    if found_keywords:
        return False, f"存在违规关键词：{','.join(found_keywords)}，请删除或修改。"
    
    # 检查是否包含合规声明
    if "本内容仅为信息整理，不构成任何建议" not in content:
        return False, "缺少合规声明，需添加'本内容仅为信息整理，不构成任何建议'。"
    
    return True, "内容合规"

# 核心修改：生成每日热点速览摘要（适配30-60秒口播+文字闪烁）
def summarize(text: str) -> str:
    completion = openai_client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": """
             你是专业的新闻速览编辑，需生成适配抖音30-60秒口播的每日热点速览内容，要求：
             1. 精选3-5条当日核心热点（优先民生/财经/政策类，避开敏感时政）；
             2. 每条热点控制在1-2句话，语言通俗口语化，适配口播节奏；
             3. 为每条热点标注【闪烁关键词】（3-5字，用于视频文字闪烁）；
             4. 整体结构：开场语+3-5条热点+合规声明；
             5. 总字数控制在200字以内，避免专业术语，无绝对化表述；
             6. 合规声明必须包含：本内容仅为信息整理，不构成任何建议。
             示例格式：
             大家好！今天的热点速览来了👇
             1. 医保新政落地【门诊报销提至60%】：全国门诊报销比例统一提高至60%，覆盖所有参保人群。
             2. 人民币升值破7.0【造纸板块受益】：离岸人民币兑美元升破7.0，造纸行业原材料成本降低。
             本内容仅为信息整理，不构成任何建议。
             """},
            {"role": "user", "content": text}
        ]
    )
    return completion.choices[0].message.content.strip()

# 核心修改：生成每日热点速览脚本（适配文字闪烁视频）
def generate_hotspot_scripts(summary: str) -> List[str]:
    """
    生成每日热点速览的抖音文字闪烁视频脚本
    输出：完整口播脚本+文字闪烁标注
    """
    # 拆分热点内容
    lines = [line.strip() for line in summary.split("\n") if line.strip()]
    
    # 提取开场、热点、声明
    opening = ""
    hotspots = []
    declaration = ""
    for line in lines:
        if "大家好" in line or "今天的热点" in line:
            opening = line
        elif line.startswith("1.") or line.startswith("2.") or line.startswith("3.") or line.startswith("4.") or line.startswith("5."):
            hotspots.append(line)
        elif "本内容仅为信息整理" in line:
            declaration = line
    
    # 生成完整脚本
    script = f"""【每日热点速览-抖音口播脚本（30-60秒）】
▶️ 口播开场：{opening}
▶️ 口播内容：
"""
    flash_keywords = []  # 提取所有闪烁关键词
    for idx, hotspot in enumerate(hotspots):
        # 提取闪烁关键词（【】内的内容）
        if "【" in hotspot and "】" in hotspot:
            keyword = hotspot.split("【")[1].split("】")[0]
            flash_keywords.append(keyword)
            # 移除关键词标记，保留口播内容
            broadcast_content = hotspot.replace(f"【{keyword}】", "").strip()
            script += f"  {idx+1}. {broadcast_content}\n"
        else:
            script += f"  {idx+1}. {hotspot}\n"
    
    script += f"""▶️ 口播结尾：{declaration}

🎯 文字闪烁标注（适配视频制作）：
"""
    for idx, keyword in enumerate(flash_keywords):
        script += f"  第{idx+1}条热点闪烁词：{keyword}（闪烁频率0.5秒/次，高对比度显示）\n"
    
    # 视频制作备注
    script += """
📌 视频制作注意：
1. 背景：简约纯色背景（黑/白），避免干扰；
2. 字体：白色字体+黑色描边，字号24-30号；
3. 节奏：口播说完1条热点，对应关键词闪烁2次；
4. 时长：整体控制在30-60秒，语速180-200字/分钟。
"""
    return [script]

# 发送微信推送
def send_to_wechat(title, content):
    for key in server_chan_keys:
        url = f"https://sctapi.ftqq.com/{key}.send"
        data = {"title": title, "desp": content}
        response = requests.post(url, data=data, timeout=10)
        if response.ok:
            print(f"✅ 推送成功: {key}")
        else:
            print(f"❌ 推送失败: {key}, 响应：{response.text}")

# 主流程
def main():
    today_str = today_date().strftime("%Y-%m-%d")

    # 获取RSS新闻数据
    articles_data, analysis_text = fetch_rss_articles(rss_feeds, max_articles=5)
    
    # 生成每日热点速览摘要
    hotspot_summary = summarize(analysis_text)
    print(f"\n📝 生成每日热点速览摘要：\n{hotspot_summary}")
    
    # 合规校验
    is_compliant, compliance_result = compliance_check(hotspot_summary)
    if not is_compliant:
        print(f"❌ 内容不合规：{compliance_result}")
        return
    print("✅ 内容合规校验通过")
    
    # 生成抖音文字闪烁脚本
    douyin_scripts = generate_hotspot_scripts(hotspot_summary)
    print(f"\n🎬 生成抖音视频脚本：")
    for script in douyin_scripts:
        print(script + "\n")
    
    # 生成最终推送内容
    final_summary = f"📅 **{today_str} 每日热点速览（抖音适配版）**\n\n"
    final_summary += "📝 核心摘要：\n" + hotspot_summary + "\n\n"
    final_summary += "🎬 抖音文字闪烁脚本：\n" + "\n\n".join(douyin_scripts) + "\n\n"
    
    # 补充新闻来源
    final_summary += "---\n📡 新闻来源：\n"
    for category, content in articles_data.items():
        if content.strip():
            final_summary += f"## {category}\n{content}\n\n"

    # 推送到微信
    send_to_wechat(title=f"📌 {today_str} 每日热点速览（抖音脚本）", content=final_summary)

if __name__ == "__main__":
    main()