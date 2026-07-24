# TTAPI MidJourney 配置与作者选图流程

## 1. 创建独立图片 Key

TTAPI 控制台中应创建一把只授权 `MIDJOURNEY-IMAGE` 产品的 Key。现有硅基流动 Key 继续负责新闻策划、写作、审校、视觉理解和知识库，不与 MidJourney Key 混用。

项目 `.env` 配置如下：

```dotenv
IMAGE_PROVIDER=ttapi
TTAPI_IMAGE_API_KEY=实际的MidJourney图片Key
TTAPI_IMAGE_BASE_URL=https://api.ttapi.io
TTAPI_IMAGE_API_KEY_HEADER=TT-API-KEY
TTAPI_GET_U_IMAGES=false
TTAPI_IMAGINE_PATH=/midjourney/v1/imagine
TTAPI_FETCH_PATH=/midjourney/v1/fetch
TTAPI_ACTION_PATH=/midjourney/v1/action
TTAPI_FETCH_METHOD=GET
TTAPI_ACTION_FIELD=action
TTAPI_POLL_INTERVAL_SECONDS=5
TTAPI_POLL_TIMEOUT_SECONDS=600
```

`TTAPI_GET_U_IMAGES=false` 用于优先取得 MidJourney 原始四宫格和编号操作。若设为 `true`，部分 TTAPI 账户会返回四张独立图片，但可能不返回 U1-U4/V1-V4 的 Action ID，此时页面只能直接采用其中一张，不能继续生成编号变体。

## 2. 指定参考图片

新闻创作的高级设置提供两种图片用途：

- `图片作为新闻资料`：视觉模型提取图片中的人物、场景和文字线索，并加入新闻事实材料；
- `图片作为MidJourney参考图`：视觉分析只用于完善画面描述，不写入新闻事实，公开图片 URL 会放在 MidJourney Prompt 开头。

MidJourney 无法访问浏览器本地文件路径，因此参考图模式必须填写可公开访问的 HTTPS 图片 URL。参考权重会转换成 `--iw` 参数：

```text
https://example.com/reference.jpg editorial World Cup photography --iw 1.5 --ar 16:9 --style raw
```

上传文件可供视觉模型分析，但真正发送给 MidJourney 的图像像素来自该 HTTPS URL。

## 3. Imagine 请求

项目默认发送：

```http
POST https://api.ttapi.io/midjourney/v1/imagine
Content-Type: application/json
TT-API-KEY: 图片Key

{
  "prompt": "新闻图片提示词 --ar 1:1 --style raw --no text watermark logo",
  "getUImages": false
}
```

新闻审校模型输出的 `final_image_prompts` 会自动成为 MidJourney Prompt。系统根据 `IMAGE_SIZE` 补充 `--ar`，并把负面提示词转换成 `--no` 参数。

## 4. Fetch 轮询

```http
GET https://api.ttapi.io/midjourney/v1/fetch?jobId=任务ID
TT-API-KEY: 图片Key
```

后台任务每 5 秒查询一次，最多等待 600 秒。完成后系统立即把临时 CDN 图片下载到 `outputs/<运行目录>/`，避免 TTAPI URL 过期。

## 5. 作者选择 U/V

页面显示四宫格后提供：

- `U1-U4`：放大对应象限，完成后作为新闻最终图片；
- `V1-V4`：围绕对应象限生成下一组四宫格，可继续选择；
- `采用此候选`：仅在 TTAPI 已直接返回四张独立图片但没有 U/V Action 时显示。

系统从 Fetch 响应的 `actions`、`buttons` 或 `components` 中读取真实 `customId`/`actionId`，不会根据按钮文本猜测 Action ID。

Action 请求默认格式：

```http
POST https://api.ttapi.io/midjourney/v1/action
Content-Type: application/json
TT-API-KEY: 图片Key

{
  "jobId": "任务ID",
  "action": "Fetch响应中的真实Action ID"
}
```

若 TTAPI 控制台 Quick Start 使用 `customId` 字段，应将配置改为：

```dotenv
TTAPI_ACTION_FIELD=customId
```

若 Fetch 文档要求 POST，应改为：

```dotenv
TTAPI_FETCH_METHOD=POST
```

## 6. 联调检查

首次真实调用应检查三类脱敏响应：

1. Imagine 创建任务响应是否包含 `jobId`；
2. Fetch 完成响应是否包含四宫格 URL 和 U1-U4/V1-V4 Action；
3. U1 或 V1 Action 响应是否返回新 `jobId`，以及后续 Fetch 是否返回图片。

如果页面提示没有 U/V Action ID，应优先检查 TTAPI 原始 Fetch 响应和 `TTAPI_GET_U_IMAGES`，不要手工构造 Action ID。
