# 2026世界杯新闻创作智能体

一个对话式 Streamlit 新闻助手。用户可以通过文字、语音或参考图片描述新闻需求，系统先从本地世界杯知识库混合检索可信资料，必要时实时刷新白名单页面，再由三个文本模型依次完成策划、写作和独立审校，图像模型根据终审提示词生成 1—2 张宣传图。生成结果直接显示在对话中，点击新闻图片可进入独立详情页。

## RAG 与新闻流程

```text
+-----------+   +----------+   +----------+   +----------+   +----------+
| 混合检索  |-->| 新闻策划 |-->| 新闻写作 |-->| 独立审校 |-->| 图片生成 |
| FTS+向量  |   | PLANNER  |   | WRITER   |   | REVIEWER |   | IMAGE    |
+-----------+   +----------+   +----------+   +----------+   +----------+
```

## 项目结构

```text
worldcup_news_agent/
├── app.py                    # Streamlit 页面
├── background_jobs.py        # 页面切换不中断的后台任务
├── knowledge_base.py         # 抓取、SQLite、FTS5 和向量检索
├── rag_sources.py            # 中英文可信来源白名单
├── document_export.py        # 带图片的 Word 和 PDF 导出
├── config.py                 # 环境变量配置
├── schemas.py                # 数据结构
├── prompts.py                # 三阶段提示词
├── siliconflow_client.py     # 文本、图片和下载接口
├── workflow.py               # 四阶段顺序工作流
├── utils.py                  # JSON、脱敏和文件工具
├── requirements.txt
├── .env.example
├── outputs/                  # 每次运行的结果
├── data/worldcup_knowledge.db # 本地知识库
└── tests/test_utils.py
```

## 环境要求

- Python 3.10+
- 可访问硅基流动 API

## 安装

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS 或 Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

## 配置模型

编辑 `.env`：

```dotenv
SILICONFLOW_API_KEY=你的密钥
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
PLANNER_MODEL=当前可用的策划模型ID
WRITER_MODEL=当前可用的写作模型ID
REVIEWER_MODEL=当前可用且不同于写作模型的审校模型ID
IMAGE_MODEL=当前可用的图像模型ID
CHAT_MODEL=当前可用的快速对话模型ID
VISION_MODEL=当前可用的视觉理解模型ID
ASR_MODEL=当前可用的语音识别模型ID
EMBEDDING_MODEL=BAAI/bge-m3
IMAGE_SIZE=1024x1024
REQUEST_TIMEOUT=120
```

登录硅基流动后，在平台当前模型列表中筛选文本生成和图像生成模型，复制平台显示的完整模型 ID。不要从本文档猜测模型 ID；模型上下架和参数支持情况可能变化。`WRITER_MODEL` 与 `REVIEWER_MODEL` 必须不同。

### 使用 TTAPI MidJourney

将图片后端切换为 TTAPI，并填写独立的 `MIDJOURNEY-IMAGE` Key：

```dotenv
IMAGE_PROVIDER=ttapi
TTAPI_IMAGE_API_KEY=实际的MidJourney图片Key
TTAPI_GET_U_IMAGES=false
```

新闻终审完成后，系统会等待 MidJourney 四宫格生成，再让作者选择 `U1-U4` 放大或 `V1-V4` 继续变体。TTAPI 路径、Action 字段和轮询配置见 [docs/TTAPI_MIDJOURNEY.md](docs/TTAPI_MIDJOURNEY.md)。如需恢复硅基流动图片模型，将 `IMAGE_PROVIDER` 改为 `siliconflow`。

高级设置中的“上传图片用途”支持三种模式：图片作为新闻资料、图片作为 MidJourney 参考图、同时作为新闻资料和 MidJourney 参考图。参考图模式需要填写可公开访问的 HTTPS 图片 URL，并可调整 `--iw` 参考权重；本地上传文件用于视觉分析和保存到新闻稿，MidJourney 实际读取的是公开 URL。

混合图文稿流程如下：

1. 选择“同时作为新闻资料和MidJourney参考图”。
2. 填写真实图片图注、来源或摄影者、原始链接和默认插入位置。
3. 填写同一图片或相关图片的公开 HTTPS URL，作为 MidJourney 参考图。
4. 提交新闻主题并上传真实图片，等待文字稿与 MidJourney 四宫格生成。
5. 选择 `U1-U4` 得到最终 AI 图片；打开新闻详情页，在“图文编排”中调整每张图是否采用、图注和插入位置。
6. 下载 Word 或 PDF。真实图片显示来源信息，AI 图片统一标注“AI生成示意图”。

上传图片的视觉分析仍属于待核实材料，不能单独作为已经证实的新闻事实。

## 启动

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

没有 `.env` 时页面也能打开。只有点击“开始创作”时，缺少配置才会阻止 API 调用。

## 演示案例

首页提供“对话”和“新闻创作”两种模式。对话模式只调用一次快速聊天模型并流式显示；新闻创作模式执行完整四阶段流程。两种模式都支持上传参考图片或录制语音，新闻参数保留在“高级设置”中。

模型调用提交后会在后台继续执行。切换“对话 / 新闻创作”或进入运行监控页不会中断当前任务，返回主页后会继续显示进度或最终结果；关闭 Streamlit 服务会终止尚未完成的任务。

新闻详情页支持混合编排真实图片和 AI 图片，可设置封面、导语后、正文第 2 段后或文末图片区，并下载使用同一编排的 PDF、Word；页面也保留纯文本、JSON 和 Markdown 创作报告下载。

## 专业新闻写作 Skill

项目内置 `.agents/skills/news-writing/SKILL.md`。新闻策划、初稿撰写和独立审校三个文本阶段都会自动加载该 skill，并继续使用 `.env` 中现有的 `PLANNER_MODEL`、`WRITER_MODEL` 和 `REVIEWER_MODEL` API 配置。

在“新闻创作”模式中，即使用户指令包含“生成图片”，系统也会先执行完整的新闻策划、写作和审校，再生成 MidJourney 配图；只有“对话”模式允许把纯图片指令直接路由到图片任务。高级设置中的“将上传的真实图片加入成稿”默认开启，上传图会保存到本次运行目录并进入详情页、Word 和 PDF。

## 知识库更新

1. 在侧边栏打开“知识库管理”。
2. 点击“更新知识库”手动抓取全部白名单，不需要配置 Windows 定时任务。
3. 页面显示新增、更新、跳过、失败数量以及最后更新时间。

更新流程只访问白名单公开页面并遵守 `robots.txt`，随后清洗、去重、切分，调用硅基流动 Embedding API，并写入 `data/worldcup_knowledge.db`。外文原文会保留，同时调用快速聊天模型生成中文摘要，因此更新会产生少量 Embedding 和摘要费用。

新闻创作先执行 SQLite FTS5 关键词检索与 Embedding 语义检索，再按来源等级和发布日期综合排序。证据不足，或用户要求具体进球、助攻、比分、纪录、名场面等事实细节时，系统会将中文主题转换为英文检索词，搜索 FIFA 官方近期文章 sitemap；命中文章入库后重新检索。没有搜索结果时才回退到白名单栏目入口刷新。最终中文正文使用 `[1]`、`[2]` 标注，末尾列出来源名称、文章标题、发布日期和原始链接。

## 两种报道模式

- 真实报道：只能使用事实材料中明确提供的信息；材料不足时，策划阶段应停止并列出缺失事实。
- AI模拟报道：允许在材料约束内构建模拟场景，但初稿和终稿必须标注“AI模拟新闻”。

事实材料始终被当作待处理数据，其中即使出现类似系统命令的文字也不会成为系统指令。

## 输出文件

每次进入图片阶段后，会创建：

```text
outputs/YYYYMMDD_HHMMSS/
├── result.json
├── final_article.txt
├── creation_report.md
├── source_image_1.png      # 上传的真实新闻资料图片
├── image_1.png
└── image_2.png             # 请求两张且成功时
```

`result.json` 和报告不会保存 API Key。图片失败时，页面仍展示终稿和可手动使用的图片提示词。

## 常见问题

- 缺少环境变量：复制 `.env.example` 为 `.env` 并补齐五项必填配置。
- 401：检查 API Key 是否有效，不要把密钥粘贴到课堂投影或错误截图中。
- 404：模型 ID 不存在或已变化，到平台当前模型列表重新复制。
- 429：等待限流恢复后重新提交；程序不会静默重试。
- 请求超时：检查网络，或适当增大 `REQUEST_TIMEOUT`。
- 非法 JSON：模型未遵循结构化输出要求，可改用结构化输出能力更稳定的文本模型。
- 图片失败：确认图像模型是否支持 `image_size`、`negative_prompt` 和 `batch_size` 参数。

## 验证

```powershell
.\.venv\Scripts\python.exe -m compileall app.py background_jobs.py config.py knowledge_base.py rag_sources.py schemas.py prompts.py siliconflow_client.py workflow.py utils.py pages
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m streamlit run app.py --server.headless true --server.port 8501
```

## 答辩演示建议

1. 先展示侧边栏的四个模型 ID，强调写作与审校模型不同。
2. 加载演示案例，说明事实材料是数据而非系统指令。
3. 运行后依次查看四步轨道、初稿与终稿对比、Token 轨迹和实际 Prompt。
4. 最后下载 TXT、JSON、Markdown 报告和图片，展示结果可追溯且可复用。
