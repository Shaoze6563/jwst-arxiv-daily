# JWST × Galaxy arXiv Daily

每天从 arXiv API 收集与 JWST 和星系科学相关的新论文，按相关度排序，输出 Markdown 和 CSV，并由 GitHub Actions 自动提交结果。

## 功能

- 查询 `astro-ph.GA`、`astro-ph.CO`、`astro-ph.EP` 和 `astro-ph.IM`
- 识别 JWST、NIRCam、NIRSpec、MIRI、JADES、CEERS 等关键词
- 识别 galaxy、high-redshift、reionization、SED fitting、AGN 等科学主题
- 用 arXiv ID 去重
- 每天生成 HTML、Markdown 和 CSV
- 每月自动生成每日 HTML 目录，每年自动生成月份目录
- 生成 `reports/index.html` 作为所有年份的总入口
- 无第三方 Python 依赖

## 上传到 GitHub

1. 在 GitHub 新建一个空仓库，例如 `jwst-arxiv-daily`。
2. 在本目录运行：

   ```bash
   git init
   git add .
   git commit -m "Initial JWST arXiv collector"
   git branch -M main
   git remote add origin <你的仓库地址>
   git push -u origin main
   ```

3. 打开仓库的 **Actions** 页面，启用工作流。
4. 选择 **Daily JWST galaxy arXiv digest**，点击 **Run workflow** 做首次测试。

工作流每天 `02:00 UTC` 触发，即新加坡时间 `10:00`。这个时间给 arXiv 当天的更新留出了余量；GitHub 定时任务也可能比设定时间稍晚启动。

## 首次配置

编辑 `config.json`：

- 将 `contact_email` 换成你的邮箱，用于 arXiv API 的 User-Agent 标识；
- 调整关键词、分类和 `minimum_score`；
- `lookback_days` 控制程序回看多少天，默认 14 天；
- `max_results` 控制每次最多获取多少个候选结果，默认 300。

首次运行会按论文首次提交日期收集回看窗口内符合条件的论文；旧论文上传新版时不会再次推送。以后由 `data/seen.json` 进一步去重。

## HTML 目录结构

```text
reports/
├── index.html                 # 所有年份入口
└── 2026/
    ├── index.html             # 2026 年的月份目录
    └── 07/
        ├── index.html         # 2026 年 7 月的每日日报目录
        ├── 2026-07-11.html    # 当日日报
        ├── 2026-07-11.md
        └── 2026-07-11.csv
```

GitHub 仓库可以直接打开这些文件查看。若之后启用 GitHub Pages，`reports/` 也可以作为静态网站来源。

## 本地测试

```bash
python3 -m unittest discover -s tests -v
python3 collector.py --dry-run
python3 collector.py
```

`--dry-run` 会访问 arXiv 并把报告打印到终端，但不会修改报告和去重状态。

## 调整筛选宽严程度

- 更严格：把 `minimum_score` 从 `5` 提高到 `7` 或 `8`；
- 更宽松：增加 `related_terms`，或者把 `minimum_score` 降到 `4`；
- 只要星系论文：删除不需要的 `related_terms`，保留 `galaxy_terms`。

查询遵循 [arXiv API 文档](https://info.arxiv.org/help/api/user-manual.html)。同一查询每天只运行一次，并缓存已经推送的 arXiv ID。
