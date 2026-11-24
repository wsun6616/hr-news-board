# HR实务资讯在线看板（免费版）

这是一个零现金成本的静态网站项目，适合 HR 日常查看社保医保、劳动争议、政策法规、招聘市场等实务内容。

## 一、当前实现

- 固定展示最新 **100 条**实务资讯
- 按发布时间倒序排列
- 每小时由 GitHub Actions 自动抓取并更新
- 页面每 5 分钟自动检查一次数据文件
- 数据保存在仓库内，不依赖付费数据库
- 支持关键词搜索、分类筛选、已读、收藏、原文跳转
- 不需要服务器，不需要后端账号
- 主数据源为湖北省人社厅工作动态，备用数据源为人力资源和社会保障部 RSS
- 本地电脑优先双击 `双击打开-100条.html`，该文件已内嵌100条数据，不依赖外部数据文件
- 部署到 GitHub 时使用 `index.html`，在线模式会优先读取最新数据

## 二、目录说明

```text
HR资讯免费在线版/
├── index.html                  # 在线部署用前端页面
├── 双击打开-100条.html          # 完全自包含的本地版，优先双击这个
├── fetch_news.py               # 抓取、筛选、分类脚本
├── .nojekyll                   # GitHub Pages 静态发布配置
├── data/
│   ├── latest.json             # 在线模式读取的最新100条
│   ├── archive.json            # 最近500条历史库
│   └── inline-data.js          # 本地双击打开时的内置数据
└── .github/workflows/
    └── update-news.yml         # 每小时自动更新任务
```

## 三、免费部署步骤

### 1. 注册 GitHub

打开 GitHub 官网，注册一个免费账号。如果已有账号，直接登录即可。

### 2. 新建仓库

点击右上角“New repository”：

- Repository name 可填写：`hr-news-board`
- 选择 **Public（公开仓库）**
- 不需要勾选 README
- 点击 Create repository

### 3. 上传项目文件

进入新建仓库，点击“uploading an existing file”，把本文件夹内的全部内容拖进去，包括：

- `.github`
- `data`
- `index.html`
- `fetch_news.py`
- `.nojekyll`
- `README.md`

然后点击 Commit changes。

### 4. 开启 GitHub Pages

进入仓库：

1. 点击 Settings
2. 左侧点击 Pages
3. Source 选择 **Deploy from a branch**
4. Branch 选择 **main**，目录选择 **/root**
5. 点击 Save

等待 1—3 分钟，页面会显示访问地址，格式通常为：

```text
https://你的用户名.github.io/hr-news-board/
```

### 5. 确认自动更新

进入仓库顶部的 Actions：

- 能看到 `Update HR news`
- 点击进入后可手动运行 Run workflow
- 之后系统会每小时自动执行一次

## 四、如何增加或减少功能

### 增加资讯来源

打开 `fetch_news.py`，仿照 `parse_hubei_work` 或 `parse_mohrss_rss` 增加一个解析函数，再把函数加入 `main()` 中的 parser 列表。

### 修改分类

在 `fetch_news.py` 中修改 `classify()` 函数；在 `index.html` 中修改 `channels` 数组。

### 修改更新频率

打开 `.github/workflows/update-news.yml`，修改：

```yaml
schedule:
  - cron: '0 * * * *'
```

例如每 30 分钟运行一次：

```yaml
schedule:
  - cron: '*/30 * * * *'
```

### 只保留指定板块

在 `index.html` 的 `channels` 数组中删除对应板块，也可以在 `fetch_news.py` 的筛选规则中直接排除。

## 五、免费方案的客观边界

1. **不收费不等于付费服务器级别的稳定性。** GitHub 免费服务可能出现任务延迟、平台规则调整或额度变化。
2. 定时任务计划为每小时一次，但 GitHub Actions 实际执行时间可能延后。
3. 页面展示的是可核验的真实来源，不编造资讯；如果来源网站临时不可用，会继续保留历史数据。
4. `latest.json` 始终保留最新100条，`archive.json` 保留最近500条；更早内容可通过 Git 提交历史查看。
5. 已读和收藏保存在当前浏览器，清除浏览器数据后会丢失。
6. 若以后需要精确到分钟级实时、后台账号、多人协同、全文检索或付费 SLA，才需要升级服务器或数据库服务。

## 六、建议的日常使用方式

- 上班后打开固定网址，先看“劳动争议案例”和“社保医保实务”
- 处理员工问题时，用关键词搜索同类政策或案例
- 涉及制度修订、工伤、试用期、竞业限制、欠薪时，优先点击原文核对
- 每周可手动运行一次 Actions，确认自动任务正常
