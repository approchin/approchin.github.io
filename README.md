# PM01 运动控制项目文章

SuperMimic-PM01 和 SONIC-PM01 各用一篇中文长文、一个页面。正文分别在 `article.md` 和 `sonic-article.md`，视频清单分别在 `clips.json` 和 `sonic-clips.json`。两页共用 `page.html`、`assets/article.css` 和 `assets/article.js`。

用 Python 3.12 构建：

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python restore_assets.py
.venv/bin/python build.py
.venv/bin/python -m http.server 8790 --bind 127.0.0.1 --directory dist
```

首页是 `dist/index.html`（项目目录），两篇长文分别位于 `dist/supermimic-pm01/index.html` 和 `dist/sonic-pm01/index.html`。目录条目来自 `projects.json`；各页的资产引用是相对路径。

Pages 工作流已放入 `.github/workflows/pages.yml`。把源码放入要使用的 GitHub 仓库并在 Pages 中选择 GitHub Actions，工作流会构建并部署 `dist/`。同一构建结果也支持个人站根目录或个人站中的子目录，因为站内资源用相对路径。

SuperMimic 使用 02–09 号 MP4，SONIC 使用七组匹配参考的 A28k／B28k 回放。每个画面左参考、右策略。配图来自已核对的导出版本，原始动作和模型权重留在各自的发布流程中。动捕署名为 [Motion Data by Bones Studio](https://bones.studio/)，使用条件见 [BONES-SEED 条款](https://bones.studio/info/seed-license)。EngineAI 视觉资产声明、KaTeX 和 IBM Plex 的许可随资源保留。

这个仓库的媒体按体积拆成数个资产包；`restore_assets.py` 校验并恢复图、回放视频与文档字体。
