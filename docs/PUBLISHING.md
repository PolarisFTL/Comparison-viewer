# Comparison Viewer：GitHub 发布与便携打包

项目仓库为 `https://github.com/PolarisFTL/comparison-viewer`。正式产物统一为 `ComparisonViewer.exe`、`Comparison-Viewer-windows-amd64-portable.zip` 与 `Comparison-Viewer-source.zip`；源码 ZIP 顶层目录为 `Comparison-Viewer/`。RGB-T / DroneVehicle 保留为历史使用案例与实测数据，不作为工具的任务限制。

## 公开代码与本机数据分离

可公开：源码、启动器、中文文档、通用测试、合成 demo、示例配置和获授权的品牌资源。

不公开：`local/`、真实路径、口令／恢复码、SQLite／WAL／SHM、实验图、团队备注、私有截图、索引、真实审计及旧项目私有副本。`.gitignore` 不能移除已跟踪文件，首次提交仍需检查暂存区。

公开截图只使用合成示例；项目不自动上传数据或发布 GitHub。

## 干净源码包

```sh
python scripts/package_public.py
```

脚本采用明确清单，只收录源码、文档、资源、合成 demo、测试和启动器；拒绝符号链接、运行数据、数据库及可识别的私有路径／凭据。输出位于忽略的 `dist/`。扫描不能形式化证明没有秘密，需人工复核报告截图和 Logo 授权。

## GitHub Actions 与便携构建

`ci.yml` 提供 Windows / macOS、Python 3.9 / 3.12 标准库测试；手动触发还可构建便携程序。PyInstaller 只在构建阶段需要，不是运行时联网依赖。工作流实际成功前不能声称 CI 已通过。

Windows 不能直接生成经过验证的 macOS 应用。macOS 在对应 runner 构建，Intel／Apple Silicon、签名、公证和 Gatekeeper 仍需确认，单架构不得标为 Universal。未签名包不能伪装为 Apple 已公证应用。

源码版无需 Node.js、npm 或第三方 Python 包。便携包包含 Python 环境，体积较大；发布注明平台、架构、版本与校验和。

中英报告由 `scripts/build_report.py` 同时生成 PDF 与 Markdown：`技术与使用报告-中文` 和 `Technical-and-User-Report-English`。每份报告都介绍原像素导出、性能边界、Mac 从源码启动以及内网协作。默认执行 `python scripts/build_report.py` 生成两种语言，也可用 `--language zh` 或 `--language en`。

重建需要构建阶段依赖 `reportlab` 以及合法可用的宋体与 Times New Roman，不影响查看器运行时。脚本读取系统目录或显式字体参数：`--simsun`、`--times`、`--times-bold`、`--times-italic`；对应环境变量为 `COMPARISON_REPORT_SIMSUN`、`COMPARISON_REPORT_TIMES`、`COMPARISON_REPORT_TIMES_BOLD`、`COMPARISON_REPORT_TIMES_ITALIC`。Mac 未提供宋体时必须取得合法字体并显式指定，否则构建明确失败，不使用 STSong 等字体替代。PDF 仅嵌入所用字形的子集，不在源码 ZIP 或便携包中分发系统字体文件。

报告截图只使用 `docs/screenshots/` 下的合成示例，不放真实实验截图。报告区分实测值和设计机制；修改实现或测试后同步更新，不把旧版基线当作新版。Mac 用户详细启动步骤见 [MACOS.md](MACOS.md)，源码运行与未来 `.app` 构建必须分开描述。

## 建议 Release 内容

1. 功能、平台及依赖说明。
2. 干净源码包与实际构建验证的平台便携包。
3. 合成截图、教程和已知限制。
4. 校验和、测试和变更。
5. 代码 MIT 与品牌图独立权属声明。

不要发布个人 IP、口令、论文路径或未公开结果；真实数据遵守数据集许可和论文披露范围。

## 2.2 批量小库功能的发布边界

公开源码包含团队筛选和精选小库导出实现，以及中英 [BATCH_EXPORT.md](BATCH_EXPORT.md) / [BATCH_EXPORT_EN.md](BATCH_EXPORT_EN.md)。运行时生成的批次、ZIP、paths.txt、report.json、匹配清单和重绑定路径结果属于用户数据，不应放进公开包；真实路径与真实图像只保留在用户明确选择的位置或私有 workspace。

MulimgViewer CSV 适配依据其官方开源读取逻辑核对，文档给出来源和适用边界；这不等于将 MulimgViewer 捆绑发布，也不等于外部 GUI 各版本已经实测。扩展名不同不转换格式、不伪装后缀；专用兼容 CSV 与带表头审计清单用途分开。

2.1 的 95 项 Python／40 项 JS、原像素导出和 Windows EXE 结果是保留的历史基线。2.2 新增筛选、批量复制、ZIP 和跨系统路径测试应按本轮实际结果单独记录，不把历史测试数字改名为新版本已通过。最终以 `TESTING.md` 为准。
