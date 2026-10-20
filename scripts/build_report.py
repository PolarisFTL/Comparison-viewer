#!/usr/bin/env python3
"""Build bilingual reports with actual SimSun and Times New Roman subset fonts.

Build dependency: reportlab. System font files are read, never redistributed.
On a Mac without licensed SimSun, set the font arguments to licensed files;
missing required fonts cause an explicit error instead of silent substitution.
"""
import argparse
import itertools
import os
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Image, Spacer, PageBreak

ROOT = Path(__file__).resolve().parents[1]
PAGE_W, PAGE_H = A4
WIDTH = PAGE_W - 104
INK = colors.HexColor('#18283D')
BLUE = colors.HexColor('#344BA8')
MUTED = colors.HexColor('#536277')
LINE = colors.HexColor('#D8E1ED')
PALE = colors.HexColor('#F2F5FC')
AUTHORS = 'PolarisFTL and GPT 6 Astra'
VERSION_DATE = '2026-10-20'


def find_font(explicit, env_name, names):
    supplied = explicit or os.environ.get(env_name)
    if supplied:
        path = Path(supplied).expanduser()
        if not path.is_file():
            raise FileNotFoundError('Required licensed font file not found: ' + str(path))
        return path
    folders = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts',
               Path('/Library/Fonts'), Path('/System/Library/Fonts/Supplemental'),
               Path.home() / 'Library' / 'Fonts']
    for folder in folders:
        for name in names:
            path = folder / name
            if path.is_file():
                return path
    raise FileNotFoundError('Required font unavailable: {}. Supply an authorized font file with {}. '
                            'No substitute font is used.'.format(names[0], env_name))


def register_fonts(args):
    paths = {
        'SimSun': find_font(args.simsun, 'RGBT_REPORT_SIMSUN', ('simsun.ttc', 'SimSun.ttf')),
        'TNR': find_font(args.times, 'RGBT_REPORT_TIMES', ('times.ttf', 'Times New Roman.ttf')),
        'TNRBold': find_font(args.times_bold, 'RGBT_REPORT_TIMES_BOLD', ('timesbd.ttf', 'Times New Roman Bold.ttf')),
        'TNRItalic': find_font(args.times_italic, 'RGBT_REPORT_TIMES_ITALIC', ('timesi.ttf', 'Times New Roman Italic.ttf')),
    }
    for name, path in paths.items():
        pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=0))
    pdfmetrics.registerFontFamily('TNR', normal='TNR', bold='TNRBold', italic='TNRItalic', boldItalic='TNRBold')
    return paths


def mixed(text, bold=False, italic=False):
    """Chinese runs use SimSun; Latin, digits and ASCII punctuation use TNR."""
    result = []
    text = str(text)
    for chinese, group in itertools.groupby(text, key=lambda char: ord(char) > 0x024F):
        value = ''.join(group)
        font = 'SimSun' if chinese else ('TNRBold' if bold else ('TNRItalic' if italic else 'TNR'))
        result.append('<font name="{}">{}</font>'.format(font, escape(value).replace('\n', '<br/>')))
    return ''.join(result)


def styles(language):
    base = 'SimSun' if language == 'zh' else 'TNR'
    return {
        'title': ParagraphStyle('Title', fontName=base, fontSize=26, leading=33,
                                 textColor=INK, spaceAfter=11, wordWrap='CJK' if language == 'zh' else None),
        'h1': ParagraphStyle('H1', fontName=base, fontSize=20, leading=27,
                              textColor=INK, spaceAfter=12),
        'h2': ParagraphStyle('H2', fontName=base, fontSize=12.4, leading=18,
                              textColor=BLUE, spaceBefore=11, spaceAfter=6),
        'p': ParagraphStyle('Body', fontName=base, fontSize=10.6 if language == 'zh' else 11.1,
                             leading=16.6 if language == 'zh' else 15.9, textColor=INK,
                             spaceAfter=8, wordWrap='CJK' if language == 'zh' else None),
        'small': ParagraphStyle('Small', fontName=base, fontSize=9.2, leading=13.8,
                                 textColor=MUTED, spaceAfter=7, wordWrap='CJK' if language == 'zh' else None),
        'cell': ParagraphStyle('Cell', fontName=base, fontSize=9.5, leading=14,
                                textColor=INK, wordWrap='CJK' if language == 'zh' else None),
        'th': ParagraphStyle('TH', fontName=base, fontSize=9.5, leading=14, textColor=BLUE),
        'code': ParagraphStyle('Code', fontName='TNR', fontSize=10, leading=14.5,
                                textColor=BLUE, spaceAfter=7, leftIndent=11),
    }


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        kwargs['initialFontName'] = 'TNR'
        super().__init__(*args, **kwargs)
        self.saved = []

    def showPage(self):
        self.saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        for state in self.saved:
            self.__dict__.update(state)
            self.setStrokeColor(LINE)
            self.line(52, PAGE_H - 39, PAGE_W - 52, PAGE_H - 39)
            self.setFillColor(MUTED)
            self.setFont('TNR', 8.2)
            self.drawString(52, PAGE_H - 29, 'RGBT COMPARISON VIEWER  |  TECHNICAL AND USER REPORT')
            self.drawString(52, 28, AUTHORS + '  |  ' + VERSION_DATE)
            self.drawRightString(PAGE_W - 52, 28, '{} / {}'.format(self._pageNumber, len(self.saved)))
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)


def build_table(rows, ratios, paragraph_styles):
    total = sum(ratios)
    data = [[Paragraph(mixed(value, index == 0), paragraph_styles['th' if index == 0 else 'cell'])
             for value in row] for index, row in enumerate(rows)]
    table = Table(data, colWidths=[WIDTH * ratio / total for ratio in ratios], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'TNR'),
        ('BACKGROUND', (0, 0), (-1, 0), PALE),
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    return table


def blocks_zh():
    return [
        ('RGBT Detection\nComparison Viewer', [
            ('p', '技术与使用报告 - 中文版 2.2.1'),
            ('small', '2.2.1 发布整理：加入中英文 README 切换，更新界面标识及公开合成截图；未增加分析功能。下文保留 2.1 / 2.2 实测基线，发布附加检查见 TESTING.md。'),
            ('p', '作者：PolarisFTL 与 GPT 6 Astra。以本地目录为起点，进行多方法图像比较、典型样本筛选与可信内网协作。'),
            ('url', 'PolarisFTL GitHub', 'https://github.com/PolarisFTL'),
            ('small', 'GPT 6 Astra 为 AI 编程协作署名，提供方为 OpenAI。下方为提供方网站，不是模型个人 GitHub 主页。'),
            ('url', 'OpenAI', 'https://openai.com/'),
            ('h', '先配置，再分析'),
            ('p', '主机启动后首先进入目录配置页：填写数据集名称，选择 2-24 个方法目录和基准目录，给每列设置便于阅读的显示名。修改显示名不会重命名源文件夹。检查对应关系后，再进入查看器。'),
            ('figure', 'setup.png', '图 1  使用合成数据的配置页。原始实验图片不进入公开报告。', 205),
            ('note', 'Windows 提供便携 EXE 与源码入口；当前 macOS 交付为源码与 .command 启动器，不包含已经实机验收的 Mac .app。本报告中文使用宋体，拉丁文字使用 Times New Roman，PDF 内嵌字体子集；不发布系统字体文件。'),
        ]),
        ('01  macOS：从下载到打开', [
            ('p', '当前可用路径是源码启动。Windows 的 .exe 不能在 macOS 直接运行。将完整源码 ZIP 解压到你可写的目录，例如“文稿”中的一个项目文件夹；不要只下载 index.html，也不要从只读磁盘映像内运行。'),
            ('h', '准备 Python，并启动'),
            ('p', '1. 若未安装合适的 Python，从 python.org 的 macOS 下载页安装仍受支持的 Python 3.x，版本至少 3.9；本工具运行时只用标准库，不需要 npm 或 pip 安装运行依赖。官方安装程序包含可供 tkinter 使用的 Tk。'),
            ('p', '2. 双击 Start-macOS.command。它优先检测旁边的便携 .app（将来实际提供时），否则查找 Python 3.9+，启动服务并打开 /setup。保留终端窗口，关闭网页并不自动停止服务。'),
            ('p', '3. 如果只因为脚本执行权限无法双击，在“终端”中进入解压后的项目目录，对本项目的两份启动脚本执行：'),
            ('code', 'chmod +x Start-macOS.command Start-LAN-macOS.command'),
            ('p', '然后重新双击；也可在该项目目录执行 bash Start-macOS.command。路径包含空格时使用引号，或将项目文件夹拖入终端辅助填入路径。'),
            ('h', '目录选择、Tk 与安全提示'),
            ('p', '4. 在配置页点击选择目录，在主机的系统对话框中选文件夹；或使用页面路径输入框粘贴目录绝对路径。若选择器报 tkinter / _tkinter 错误，可先运行 python3 -m tkinter 检查当前解释器，再使用官方 Python 安装程序或直接手填路径。不要用 pip install tkinter 修复标准库组件。'),
            ('p', '5. 如 macOS 拦截下载内容，先核实来源，再按系统“隐私与安全性”中的受控允许流程处理；不关闭 Gatekeeper，不删除系统 Python，不批量移除下载隔离标记。'),
            ('small', '未来的 .app 须在真实 macOS 或 macOS CI 构建，并分别说明 Intel / Apple Silicon 架构、签名和测试状态；单架构不能称为 Universal。目前 Mac 实机、原生目录对话框 GUI 和远程 CI 尚未执行。详细排障见 docs/MACOS.md。'),
            ('url', 'Python macOS 安装说明', 'https://docs.python.org/3/using/mac.html'),
        ]),
        ('02  数据一致性与安全匹配', [
            ('p', '基准目录定义样本集合，每一行对应同一样本的不同方法输出。建议所有目录保留相同样本 ID 和相同场景内容；方法数量和显示名称可自由配置。'),
            ('table', [['目录', '对应文件', '结果'], ['Input（基准）', 'sample_001.jpg', '建立样本行'], ['Baseline', 'sample_001.jpg', '完整文件名优先'], ['Ours', 'sample_001.png', '主文件名唯一时匹配'], ['GT', '缺少对应文件', 'Missing，不替代']], [1, 1.4, 1.7]),
            ('h', '不通过排序推断同一样本'),
            ('p', '优先完整文件名精确对应；扩展名不同且主文件名唯一时允许安全匹配。嵌套目录、重复主名和额外文件需看审计。歧义拒绝，不随机挑选，不把第 N 张配给第 N 张，也不擅自猜测前后缀。'),
            ('p', '以基准目录为全集，其他目录的额外文件不自动变成新样本。缺失会明确占位，可用于检查预测不完整；若要进行完整论文比较，应让各方法包含相同样本集合。'),
            ('h', '同名、同尺寸并不证明配准'),
            ('p', 'RGB、红外、不同裁剪和不同画布边框可能具有不同几何关系。请在结果生成阶段保证视野和方向可比。查看器保持纵横比，不自动配准、不改变检测框、不修改预测置信度、不增强图片后冒充原始结果。'),
            ('note', '源图保持只读。配置、索引、审计、数据库、口令和导出写入 local/ 或显式 workspace，不放入公开源码包。文件头抽样不等于全量损坏检测，TIFF 等格式能否解码受浏览器支持限制，推荐 PNG / JPEG。'),
        ]),
        ('03  规模、按需加载与性能边界', [
            ('p', '关键是限制同时解码的像素，而不是让文件总数变少。目录扫描产生轻量索引，不把整库转为 Base64，不预创建全部 ImageBitmap，也不在启动时全量读取像素。'),
            ('table', [['机制', '控制的成本'], ['当前页 DOM', '只创建这一页，换页不追加旧节点'], ['IntersectionObserver', '可见与边缘范围加载，横向离屏图移除 src'], ['4 任务队列', '限制每个浏览器同时读取与解码任务'], ['取消与引用释放', '换页丢弃旧任务，撤销 Blob URL'], ['画布规模检查', '导出前估算，只处理选定图像']], [1.1, 2.3]),
            ('h', '真实数据索引基线'),
            ('p', '上一轮已实测 8,980 样本、10 方法、89,800 图片，缺失与歧义均为 0。索引扫描匹配 8.386 秒，包含工作区提交 9.628 秒，manifest 7,261,083 字节。抽样检查 357 个文件头，10 个代表原图前后哈希一致；没有逐文件全量像素完整性证明。'),
            ('p', '连续翻页 20 次，10 方法场景始终为 40 图像节点与 40 单元，错误 0，峰值并发 4。内部 render 6.0-9.4 ms 仅是 DOM 构建诊断；293-456 ms 含自动化 UI 调用，也不是整页原图加载时间。'),
            ('note', '资源成本随可见像素增长。默认 4 行、24 方法有 96 个单元，不能继续声称固定 40。12 张 840 × 712 RGBA 像素约 27.4 MiB，还不含索引、缓存、GPU 和编码。节点不累计不代表浏览器进程零增长，也不能承诺永不卡顿。'),
        ]),
        ('04  比较、筛选与制图工作流', [
            ('p', '默认每页 4 行，方法按列。搜索文件名、完整／缺失／收藏筛选、随机跳转和位置记忆帮助定位样本。列可以隐藏、排序、单列查看；表头与列一同横向滚动。'),
            ('figure', 'export.png', '图 2  合成示例的原像素拼图预览；本例输出为 1400 × 444。', 230),
            ('table', [['操作', '用途与边界'], ['Ctrl + 滚轮 / 拖动', '以指针缩放 / 平移；普通滚轮仍滚动页面'], ['双击 / 1:1', '适应容器 / 原始像素比例'], ['同步：同一行或当前页', '归一化视野；不是自动空间配准'], ['ROI / 双方法', '框选、移动、重画；并排与同尺寸分割线'], ['收藏 / 备注 / 标签 / 已审', '保存人工判断，系统不自动评价算法优劣']], [1.2, 2.3]),
            ('small', '快捷键：/ 聚焦搜索；输入框外左右方向键翻页；视口焦点下 + / - 缩放、0 适应；Esc 关闭弹窗。详情读取原图。系统文件定位只由主机执行，访问者不操作主机文件管理器。'),
        ]),
        ('05  原始像素导出与预览', [
            ('p', '新导出默认使用“原始像素 1:1（推荐）”；“自定义总宽（会缩放）”是明确的另一模式。原像素模式按每列最大原图宽、每行最大原图高安排单元，小图不放大，空余部分留白。ROI 向外取整到原图像素边界再以 1:1 取出。'),
            ('h', '840 × 712 的十列为什么不能塞进 3200px 而不缩小'),
            ('p', '仅十幅图像内容的总宽就需要 840 × 10 = 8400px，实际还要加列距和外边距。总宽 3200px 的十列拼图必然降低每幅图的像素数量。PNG 是无损编码，但不能恢复缩小前丢掉的信息；DPI 标签、显示缩放或高 DPR 也不会增加源像素。'),
            ('small', '当前默认布局中，4 样本 × 10 方法、每幅 840 × 712 的画布为 8592 × 3116，即 26,772,672 像素。仅 RGBA 画布约 102.13 MiB；读取原图、编码和预览还会额外占用内存。'),
            ('table', [['参数', '新导出约定'], ['水平 / 垂直间距', '默认各 16px；各自可调 0-256px'], ['外边距', '默认 24px；可调 0-512px'], ['方法标题区 / 字号', '默认 44px / 24px，文字不覆盖图像'], ['样本编号区 / 字号', '默认 32px / 18px，可隐藏'], ['预览', '适应视口或 100%；不改变最终 PNG 像素'], ['规模保护', '桌面最多 48MP，弱设备更严格；单边 16384']], [1.25, 2.35]),
            ('p', '先选定样本和方法再预览，只对所选图读取有限文件头以估算布局，避免为尺寸解码两遍。JPEG EXIF 方向 1-8 纳入解释；实际解码尺寸不符则拒绝，不强拉伸。弱设备预算降至 24MP 或 12MP，单图也受约束；原像素超限应拆分，不偷偷降采样。'),
            ('note', '原像素几何、真实 PNG 与浏览器检查在 2.1 已完成，历史基线见验收页和 TESTING.md。此前 3200 × 1260 真图属于旧缩放基线，不是原像素结果。原图始终不修改、不增强。'),
        ]),
        ('06  可信内网协作与权限', [
            ('p', '默认只监听 127.0.0.1，端口 8770。需要分享时明确使用 LAN 启动器，依据真实私有 IPv4 和掩码限制网段；可以显式指定允许子网，不能假定整个校园网是同一个 /24。'),
            ('table', [['角色', '权限与记录'], ['主机管理员', '配置目录、索引、邀请与口令、系统定位、退出服务'], ['访问者', '口令登录；昵称 + 恢复码认领个人身份'], ['独立标记', '个人收藏、备注、标签和已审，不互相覆盖'], ['集中汇总', '主机 SQLite；按人、共同推荐和进度查看；JSON 备份']], [1, 2.8]),
            ('p', '运行 Start-LAN-macOS.command 或 Start-LAN-Windows.bat，由主机复制实际邀请 URL 和口令。其他人只需浏览器，不需要 Python 或原目录盘符；但主机需开机、不休眠且持续运行服务。'),
            ('h', '网络能否互通需要现场检查'),
            ('p', 'Windows 防火墙入站规则通常需 UAC；macOS 只在可信情况下按系统提示允许入站连接。仅放行实际端口与所需私有范围。无线客户端隔离、跨 VLAN、访客网和路由策略会阻止同校设备互通，不能仅凭同一校园网就承诺可达。'),
            ('note', 'HTTP 不加密。口令不是 TLS，不适合公网或不可信公共网络。Host、Origin、会话、变更令牌与索引白名单只是风险控制，不是安全审计。登录者可截图或下载授权图片，只向有数据访问权的人分享。'),
            ('small', '远程角色不得选择主机目录或执行主机管理。导出只处理授权样本。复制 SQLite 前停止服务或使用备份流程，避免遗漏 WAL；local/、凭据和实验数据不进入 GitHub。'),
        ]),
        ('07  验证状态、交付与参考', [
            ('table', [['项目', '2.1 Windows / Chromium 已完成基线'], ['Python 完整测试', '95 项：94 通过、1 跳过（Windows 符号链接权限）；25.309 秒'], ['JavaScript 检查', '40 项：36 项无依赖 Node 检查 + 4 项真实 Skia Canvas / PNG 回读'], ['Windows 2.1 便携 EXE', '13,680,469 字节，GUI 子系统\n仅 Windows PATH 无 Python / Node；启动和原生 4×4 PNG 保存成功'], ['混合尺寸 PNG', '865 × 621；16 单元逐像素与原图 RGB 相同，差异 0'], ['鼠标框选 ROI', '426 × 90；4 单元坐标与尺寸均为整数、1:1，像素差异 0'], ['真实 4 样本 × 10 方法', '8592 × 3116 已保存；40 单元 840 × 712、scale 1、缺失失败 0'], ['真实图像像素核验', '本批 40/40 区域与原图经 PIL 解码后的 RGB 像素完全一致'], ['超限与拆分', '52.89MP 拒绝且无画布；拆为 7 行与 1 行，两份 PNG 均保存'], ['macOS / CI / 选择器 GUI', '未 Mac 实机、未远程 CI，原生对话框未操作验收']], [1.2, 2.7]),
            ('p', 'CSS 适应预览约 1149.95 × 417.05，但 PNG 仍为 8592 × 3116。像素核验只针对本批图像与该浏览器，不泛化为所有 ICC、透明度、EXIF 场景或压缩字节相同。HTTP 模拟身份不证明第二台校园网设备可达；旧 86 项／17 JS 属上一轮。详见 TESTING.md。'),
            ('h', '公开内容与许可'),
            ('p', '公开包使用白名单，排除 local/、原图、口令、数据库、真实路径和私有截图。代码与文档 MIT；Los Pollos Hermanos 图像与商标属于第三方材料，不包含在 MIT 中，不声明官方关联、赞助或授权。详见 assets/README.md。'),
            ('small', '报告重建需 reportlab，以及合法可用的宋体和 Times New Roman。构建脚本从环境或系统字体目录查找，缺失时明确报错，不替换成 STSong。PDF 只嵌入所用字形子集，不将系统字体文件加入源码或发布 ZIP。'),
            ('url', '项目发起者 PolarisFTL', 'https://github.com/PolarisFTL'),
            ('url', 'Python 官方 macOS / Tk 说明', 'https://www.python.org/download/mac/tcltk/'),
            ('url', 'Apple：打开未知开发者应用', 'https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac'),
            ('small', '配套文档：README.md / README_EN.md、docs/MACOS.md、QUICKSTART.md、ARCHITECTURE_PERFORMANCE.md、LAN_COLLABORATION.md、TESTING.md 和 PUBLISHING.md。'),
        ]),
    ]


def blocks_en():
    return [
        ('RGBT Detection\nComparison Viewer', [
            ('p', 'Technical and User Report - English Edition 2.2.1'),
            ('small', 'Release 2.2.1 adds Chinese/English README switching, refreshed interface artwork, and public synthetic screenshots. It adds no analysis feature. The 2.1 / 2.2 test baselines remain below; release checks are in TESTING.md.'),
            ('p', 'Authors: PolarisFTL and GPT 6 Astra. A local workspace for comparing method outputs, selecting representative samples, and reviewing images together on a trusted LAN.'),
            ('url', 'PolarisFTL on GitHub', 'https://github.com/PolarisFTL'),
            ('small', 'GPT 6 Astra is credited for AI coding collaboration. OpenAI is its provider; the link below identifies the provider, not a personal GitHub account for the model.'),
            ('url', 'OpenAI', 'https://openai.com/'),
            ('h', 'Configure first, then compare'),
            ('p', 'The host opens a setup page before the viewer. Name the dataset, choose 2-24 image folders and a reference method, and edit the display name of each column. Display names do not rename the source folders. Inspect the matching audit before entering the viewer.'),
            ('figure', 'setup.png', 'Figure 1. Setup with synthetic data. No private experimental images are included.', 205),
            ('note', 'Windows has a portable EXE and source entry points. The current macOS delivery is source code with .command launchers, not a Mac .app that has been tested on hardware. Latin text uses embedded Times New Roman subsets; Chinese text uses embedded SimSun subsets. System font files are not distributed.'),
        ]),
        ('01  Opening the project on macOS', [
            ('p', 'Use the source route available today. A Windows .exe cannot run directly on macOS. Extract the complete source ZIP into a writable folder, such as a project folder under Documents. Do not download only index.html or run from a read-only disk image.'),
            ('h', 'Prepare Python and launch'),
            ('p', '1. If needed, install a supported Python 3 release from the official macOS downloads page, with version 3.9 or newer. The viewer uses the standard library at runtime: no npm setup or pip runtime packages are required. The official installer includes Tk for tkinter.'),
            ('p', '2. Double-click Start-macOS.command. It prefers a neighboring portable .app if one is actually supplied in a future release; otherwise it locates Python 3.9+, starts the local service, and opens /setup. Keep its Terminal window open. Closing the browser does not stop the service.'),
            ('p', '3. If execution permission prevents double-clicking, open Terminal in the extracted project folder and run:'),
            ('code', 'chmod +x Start-macOS.command Start-LAN-macOS.command'),
            ('p', 'Then double-click again, or run bash Start-macOS.command from that folder. Quote paths containing spaces; dragging the folder into Terminal can help enter its location.'),
            ('h', 'Folder picking, Tk, and system prompts'),
            ('p', '4. Choose folders through the host-side dialog, or paste absolute folder paths into the setup fields. If tkinter or _tkinter is missing, run python3 -m tkinter to check the selected interpreter. Use an official Python installation or the manual path fields; pip install tkinter is not a fix for a missing standard-library component.'),
            ('p', '5. If macOS blocks downloaded content, verify its origin and follow the system Privacy & Security approval flow for that item. Do not disable Gatekeeper, delete the system Python, or recursively remove quarantine attributes.'),
            ('small', 'Future .app bundles must be built on macOS and state their Intel or Apple Silicon architecture, signing, and test status. A single-architecture build is not Universal. Mac hardware, native-picker GUI, and remote CI have not been validated here. See docs/MACOS.md for troubleshooting.'),
            ('url', 'Official Python on macOS guide', 'https://docs.python.org/3/using/mac.html'),
        ]),
        ('02  Dataset consistency and safe matching', [
            ('p', 'The reference folder defines the sample set. One row means one sample across methods. Keep the same sample identifiers and comparable scene content in each method folder. Method count and display names are configurable.'),
            ('table', [['Folder', 'Corresponding file', 'Result'], ['Input (reference)', 'sample_001.jpg', 'Defines the sample row'], ['Baseline', 'sample_001.jpg', 'Exact filename first'], ['Ours', 'sample_001.png', 'Unique stem fallback'], ['GT', 'No corresponding file', 'Missing, never substituted']], [1.05, 1.4, 1.7]),
            ('h', 'Never infer correspondence from sorted position'),
            ('p', 'Exact filenames take priority. A different extension is acceptable when the stem match is unique. Review nested folders, duplicate stems, and extra files in the audit. Ambiguity is rejected: the tool does not pick an arbitrary candidate, pair the Nth file with the Nth file, or invent prefix/suffix rules.'),
            ('p', 'Extra files in non-reference folders do not become new reference samples. Missing results are explicit placeholders and can help reveal incomplete predictions. Complete paper comparisons should use a common sample set.'),
            ('h', 'Same name or size does not establish registration'),
            ('p', 'RGB and thermal views, different crops, or different canvas borders may use different geometry. Ensure comparable fields of view and orientation during result generation. The viewer preserves aspect ratio and does not register images, alter boxes or confidence values, or enhance images and present them as original predictions.'),
            ('note', 'Original images remain read-only. Configuration, indexes, audits, credentials, databases, and exports live under local/ or an explicit workspace and stay out of public source packages. Header sampling is not a full corruption check. PNG and JPEG are recommended; TIFF decoding depends on the browser.'),
        ]),
        ('03  Scale, lazy loading, and limits', [
            ('p', 'The objective is to bound simultaneously decoded pixels, not to make the file count smaller. Scanning builds a lightweight index. It does not Base64-encode the library, create every ImageBitmap, or decode all source pixels at startup.'),
            ('table', [['Mechanism', 'Cost it controls'], ['Current-page DOM', 'Only this page exists; paging does not append history'], ['IntersectionObserver', 'Visible and near-edge loads; offscreen images lose src'], ['Four-task queue', 'Bounds reading and decoding per browser'], ['Cancellation and disposal', 'Drops stale work and revokes Blob URLs'], ['Canvas checks', 'Estimates exports and handles selected images only']], [1.2, 2.4]),
            ('h', 'Measured index baseline on real data'),
            ('p', 'The previous completed round indexed 8,980 samples, 10 methods, and 89,800 images, with zero missing or ambiguous matches. Scanning/matching took 8.386 s, or 9.628 s including workspace commit. The manifest was 7,261,083 bytes. It sampled 357 headers; hashes of 10 representative originals were unchanged. This is not a full pixel-integrity proof.'),
            ('p', 'Twenty page changes kept 40 image nodes and 40 cells for 10 methods, with zero errors and peak concurrency four. Internal render diagnostics of 6.0-9.4 ms measure DOM construction only. The 293-456 ms automation round trips are also not full original-image loading times.'),
            ('note', 'Costs depend on visible pixels. Four rows with 24 methods create 96 cells, not 40. Twelve 840 × 712 RGBA images require roughly 27.4 MiB for pixels alone, before indexes, cache, GPU storage, and encoding. Stable node counts do not prove zero process-memory growth or guarantee that the browser can never stall.'),
        ]),
        ('04  Comparison, review, and figure workflow', [
            ('p', 'The default page has four sample rows with methods in columns. Filename search, complete/missing/favorite filters, random jumps, and remembered position help navigate. Columns can be hidden, reordered, or viewed alone; headers remain aligned during horizontal scrolling.'),
            ('figure', 'export.png', 'Figure 2. Synthetic native-pixel montage preview. This output is 1400 × 444.', 230),
            ('table', [['Action', 'Purpose and boundary'], ['Ctrl + wheel / drag', 'Pointer-centered zoom / pan; normal wheel still scrolls'], ['Double-click / 1:1', 'Fit container / native pixel scale'], ['Row or page sync', 'Normalized view state, not automatic registration'], ['ROI / pair view', 'Draw, move, redraw; side-by-side or same-size wipe'], ['Favorites and annotations', 'Personal notes, tags, reviewed status; no model ranking']], [1.3, 2.5]),
            ('small', 'Shortcuts: / focuses search; left/right arrows page outside input fields; + / - zoom and 0 fits a focused viewport; Esc closes dialogs. Details use original images. Only the host can open its native file manager; visitors cannot operate the host file system.'),
        ]),
        ('05  Native-pixel export and preview', [
            ('p', 'The new default is Native pixels 1:1 (recommended); Custom total width (resizes images) is an explicit alternative. Native layout uses the largest original width per column and height per row. Smaller images are not enlarged; remaining space stays white. ROI bounds round outward to original pixel boundaries and are copied at 1:1.'),
            ('h', 'Why ten 840 × 712 images cannot fit into 3200 px unchanged'),
            ('p', 'Ten image contents alone require 840 × 10 = 8400 px horizontally, before gaps and margins. A 3200 px ten-column montage must reduce pixels per image. PNG compression is lossless, but it cannot restore information discarded by resizing. DPI metadata, display scaling, and a high device-pixel ratio do not create extra source pixels.'),
            ('small', 'With current defaults, four samples and ten methods at 840 × 712 produce an 8592 × 3116 canvas: 26,772,672 pixels. The RGBA canvas alone is about 102.13 MiB; source decoding, encoding, and preview require additional memory.'),
            ('table', [['Setting', 'New export contract'], ['Horizontal / vertical gap', '16 px defaults; independently adjustable from 0-256 px'], ['Outer margin', '24 px default; adjustable from 0-512 px'], ['Method header / font', '44 px / 24 px defaults; outside image content'], ['Sample label / font', '32 px / 18 px defaults; can be hidden'], ['Preview', 'Fit or 100%; never changes PNG pixel dimensions'], ['Size guard', 'Desktop cap 48 MP; stricter on weak devices; side 16384']], [1.3, 2.5]),
            ('p', 'Bounded header reads inspect only selected images, avoiding a second full decode just to plan dimensions. JPEG EXIF orientations 1-8 are considered; unexpected decoded dimensions are rejected, never stretched. Weak devices use 24 MP or 12 MP budgets, including individual-source checks. Split oversized native selections; no silent downsampling.'),
            ('note', 'Native geometry, real PNG, and browser checks were completed for 2.1; that historical baseline is shown on the validation page. The earlier 3200 × 1260 montage is a resized-export baseline, not native-pixel evidence. Originals are never enhanced or overwritten.'),
        ]),
        ('06  Trusted LAN collaboration and access', [
            ('p', 'The default service listens only on 127.0.0.1, port 8770. LAN sharing is explicit. It uses the real private IPv4 address and netmask to limit access; allowed subnets may be specified. It does not assume the entire campus network is a single /24.'),
            ('table', [['Role', 'Capabilities and records'], ['Host administrator', 'Configure folders and index, invite, rotate code, reveal files, stop service'], ['Visitor', 'Access-code login; nickname plus recovery code claims identity'], ['Independent review', 'Per-person favorites, notes, tags, and reviewed status'], ['Central summary', 'Host SQLite, per-reviewer and shared recommendations, JSON backup']], [1.1, 2.9]),
            ('p', 'Use Start-LAN-macOS.command or Start-LAN-Windows.bat. The host copies the actual invitation URL and code. Visitors need only a browser, not Python or access to the original drive letters. The host must stay awake, powered on, and running the service.'),
            ('h', 'Reachability still requires a second-device check'),
            ('p', 'Windows inbound firewall changes normally require UAC. On macOS, approve inbound access only for a trusted application when prompted. Restrict the actual port to required private ranges. Wireless client isolation, VLANs, guest networks, and routing policies can prevent same-campus devices from reaching each other.'),
            ('note', 'HTTP is not encrypted; an access code does not replace TLS. This is not a public-Internet or untrusted-Wi-Fi service. Host, Origin, session, change-token, and index-allowlist checks reduce risk but are not a security audit. Authorized visitors can save or screenshot images, so invite only people permitted to view the data.'),
            ('small', 'Remote users cannot configure host folders or run host administration. Back up SQLite using the supplied flow or stop the service before copying, including any WAL state. Keep local/, credentials, and research data out of GitHub.'),
        ]),
        ('07  Validation, delivery, and references', [
            ('table', [['Item', 'Completed 2.1 Windows / Chromium baseline'], ['Complete Python run', '95 tests: 94 passed, one Windows symlink-permission skip; 25.309 s'], ['JavaScript checks', '40: 36 dependency-free Node checks and four real Skia Canvas / PNG round trips'], ['Windows 2.1 portable EXE', '13,680,469 bytes, GUI subsystem; ran with Windows-only PATH, without Python/Node; native 4×4 PNG saved'], ['Mixed-size PNGs', '865 × 621; all 16 RGB regions exactly match their originals'], ['Mouse-drawn ROI', '426 × 90; four integer, 1:1 crops with zero pixel differences'], ['Real four rows, ten methods', '8592 × 3116 saved; 40 regions at 840 × 712, scale 1, no missing/errors'], ['Real-data pixel verification', 'All 40/40 regions exactly match their originals decoded to RGB by PIL'], ['Guard and splitting', '52.89 MP rejected without a canvas; seven-row and one-row PNGs saved'], ['Mac / CI / native picker', 'No Mac hardware or remote CI run; picker GUI not interactively accepted']], [1.2, 2.7]),
            ('p', 'Fit preview was about 1149.95 × 417.05 while the PNG remained 8592 × 3116. Pixel checks apply to this batch and browser, not every ICC, alpha, or EXIF case or compressed-file bytes. HTTP roles are simulated, not a second-campus-device test. The old 86-test / 17-JS figures are historical. Details: TESTING.md.'),
            ('h', 'Public package and licensing'),
            ('p', 'The public allowlist excludes local/, originals, credentials, databases, real paths, and private screenshots. Code and documentation use MIT. Los Pollos Hermanos artwork and trademarks are third-party material excluded from MIT; no official affiliation, sponsorship, or authorization is claimed. See assets/README.md.'),
            ('small', 'Rebuilding these reports requires reportlab and legally available SimSun and Times New Roman files. The builder discovers system or explicitly supplied fonts and fails if they are absent; it does not substitute STSong. PDFs embed used-glyph subsets only. Font files are not included in source or release ZIPs.'),
            ('url', 'Project initiator: PolarisFTL', 'https://github.com/PolarisFTL'),
            ('url', 'Official Python macOS / Tk guidance', 'https://www.python.org/download/mac/tcltk/'),
            ('url', 'Apple: opening an app from an unknown developer', 'https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac'),
            ('small', 'Companion documents: README.md / README_EN.md; docs/MACOS.md, QUICKSTART.md, ARCHITECTURE_PERFORMANCE.md, LAN_COLLABORATION.md, TESTING.md, and PUBLISHING.md.'),
        ]),
    ]


def batch_page(language):
    if language == 'zh':
        return ('08  2.2：从大库到 MulimgViewer 小库', [
            ('p', '推荐流程：大库按需浏览 → 多人独立标记 → 推荐人数阈值 N → 确认样本与方法 → 按方法复制原图小库 → 复制本机路径 → MulimgViewer 排版。小库导出保留独立原文件，不是 PNG 拼图。'),
            ('table', [['筛选', '确切含义'], ['任意人收藏 / 至少 N 人', '至少 1 人收藏 / 收藏人数 ≥ N'], ['有备注或标签', '任意人填写 note 或 tags'], ['全队未审 / 全部', '无人标已审 / 全部样本；均可叠加文件名查询']], [1.25, 2.65]),
            ('p', '团队汇总点击“批量导出原图”，先“预览导出范围”再确认。汇总仅展示前 200 行，批量导出处理全部匹配样本；默认全部方法，包含隐藏列，可主动选子集。推荐人数按身份计数，不自动判断模型优劣。'),
            ('p', '主机选已有可写输出目录，程序创建全新批次而不覆盖原图。访问者只能下载 ZIP 到自己电脑。方法显示名映射为跨系统安全目录名；原文件字节不重新编码，Missing 与失败写入报告。取消保留已完成副本及不完整报告，不自动删除。'),
            ('h', 'ZIP 路径要属于接收者电脑'),
            ('p', '完整解压后，在成功弹窗填“你电脑上已解压的批次目录”：该目录下面直接是方法文件夹。再下载 MulimgViewer 导入 CSV，可复制单个或全部方法路径。主机盘符不能在 Mac／另一台电脑使用；移动后重新准备路径。'),
            ('p', '专用 CSV 无表头，每行样本、每列方法，每格为当前电脑图片绝对路径；只含完整复制行。带表头 manifest.csv 是审计表，不能作图片列表；扩展名不同不假改后缀。paths.txt 仅含相对方法名，需与批次绝对路径拼接；report.json 保存状态和映射。'),
            ('url', 'MulimgViewer 官方读取代码（已核对格式）', 'https://github.com/nachifur/MulimgViewer/blob/master/src/mulimgviewer/src/data.py'),
            ('note', '2.2 实测：310 合成样本、4 方法，三人收藏 310／240／205；N=3 导出 205 样本、819 文件、1 Missing，819 哈希均同源；兼容 CSV 为 204×4，ZIP 完整且无主机路径。现用 1503×10 数据隔离标记副本筛出 20 样本，200 原图 SHA256 全同，含验证 5.516 秒，仅此小批次。真实翻 20 页始终 40 img、无控制台错误；搜索与 N4=0 刷新恢复通过，4 路径剪贴板通过。2.2 纯 JS 65＋真实 Canvas 4 项通过，最终 Python 计数见 TESTING.md。Mac 与外部 GUI 未实机。'),
        ])
    return ('08  2.2: a small library for MulimgViewer', [
        ('p', 'Workflow: lazily review the large library, collect independent annotations, apply threshold N, confirm samples and methods, copy a method-organized small library, prepare local paths, then lay out figures in MulimgViewer. This exports original files, not a PNG montage.'),
        ('table', [['Filter', 'Exact meaning'], ['Any favorite / threshold N', 'At least one favorite / favorite count >= N'], ['Notes or tags', 'Any reviewer has a note or tags'], ['Team unreviewed / all', 'Nobody reviewed / entire dataset; filename query applies']], [1.3, 2.6]),
        ('p', 'Open Batch export originals and preview first. The summary displays at most 200 rows; export includes every match. All methods, including hidden columns, are selected by default. Choose a subset explicitly. Counts identify reviewers, not model quality.'),
        ('p', 'The host chooses an existing writable parent; a new batch avoids overwriting originals. Visitors download ZIPs to their own computer. Display names map to cross-platform-safe folders. Image bytes are not re-encoded; reports record Missing and failed copies. Cancellation retains completed files and an incomplete report.'),
        ('h', 'ZIP paths must belong to the recipient'),
        ('p', 'Extract everything, then enter the batch folder itself in the success dialog: its direct children are method folders. Download the MulimgViewer import CSV and copy one or all local method paths. A host drive path cannot be reused on another computer; regenerate after moving a batch.'),
        ('p', 'The compatible CSV is headerless: sample rows, method columns, existing absolute image paths on this device, and complete copied rows only. Headered manifest.csv is an audit, not an image list. Keep real extensions. paths.txt contains relative folders to join with the actual batch root; report.json records status and mapping.'),
        ('url', 'Official MulimgViewer parser checked for format', 'https://github.com/nachifur/MulimgViewer/blob/master/src/mulimgviewer/src/data.py'),
        ('note', '2.2 checks: 310 synthetic samples, four methods, favorites 310/240/205. N=3 exported 205 samples, 819 matching-hash files, one Missing; compatible CSV 204×4. ZIP integrity and absence of host paths passed. An isolated 1503×10 real-data review selected 20 samples: all 200 hashes matched, 5.516 s including verification for this batch only. Twenty real page changes kept 40 images without console errors; search, N4=0 persistence, and four clipboard paths passed. 65 pure-JS plus four real-Canvas checks passed. Final Python counts: TESTING.md. Mac and external GUI remain untested.'),
    ])


def render_blocks(pages, language):
    s = styles(language)
    story = []
    for page_index, (title, blocks) in enumerate(pages):
        if page_index:
            story.append(PageBreak())
        story.append(Paragraph(mixed(title, language == 'en'), s['title' if page_index == 0 else 'h1']))
        for block in blocks:
            kind = block[0]
            if kind in ('p', 'small', 'h', 'code'):
                style = 'h2' if kind == 'h' else kind
                story.append(Paragraph(mixed(block[1], kind == 'h'), s[style]))
            elif kind == 'note':
                item = Table([[Paragraph(mixed(block[1]), s['small'])]], colWidths=[WIDTH])
                item.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, -1), 'TNR'),
                                          ('BACKGROUND', (0, 0), (-1, -1), PALE),
                                          ('BOX', (0, 0), (-1, -1), 0.4, LINE),
                                          ('LEFTPADDING', (0, 0), (-1, -1), 11),
                                          ('RIGHTPADDING', (0, 0), (-1, -1), 11),
                                          ('TOPPADDING', (0, 0), (-1, -1), 9),
                                          ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
                story.extend([Spacer(1, 3), item, Spacer(1, 6)])
            elif kind == 'table':
                story.extend([Spacer(1, 3), build_table(block[1], block[2], s), Spacer(1, 7)])
            elif kind == 'figure':
                path = ROOT / 'docs' / 'screenshots' / block[1]
                if path.is_file():
                    w, h = ImageReader(str(path)).getSize()
                    scale = min(WIDTH / w, block[3] / h)
                    image = Image(str(path), width=w * scale, height=h * scale)
                    image.hAlign = 'LEFT'
                    story.extend([Spacer(1, 6), image, Spacer(1, 5), Paragraph(mixed(block[2], italic=language == 'en'), s['small'])])
            elif kind == 'url':
                label, url = block[1:]
                html = mixed(label + ': ') + '<link href="{}" color="#344BA8">{}</link>'.format(escape(url), mixed(url))
                story.append(Paragraph(html, s['small']))
            else:
                raise ValueError('Unknown report block: ' + kind)
    return story


def markdown(pages):
    lines = []
    for page_index, (title, blocks) in enumerate(pages):
        lines.extend([('# ' if page_index == 0 else '## ') + title.replace('\n', ' '), ''])
        for block in blocks:
            kind = block[0]
            if kind in ('p', 'small'):
                lines.extend([block[1], ''])
            elif kind == 'h':
                lines.extend(['### ' + block[1], ''])
            elif kind == 'note':
                lines.extend(['> ' + block[1], ''])
            elif kind == 'code':
                lines.extend(['```sh', block[1], '```', ''])
            elif kind == 'url':
                lines.extend(['[{}]({})'.format(block[1], block[2]), ''])
            elif kind == 'figure':
                lines.extend(['![{}](screenshots/{})'.format(block[2], block[1]), ''])
            elif kind == 'table':
                for index, row in enumerate(block[1]):
                    lines.append('| ' + ' | '.join(str(value).replace('|', '\\|').replace('\n', '<br>') for value in row) + ' |')
                    if index == 0:
                        lines.append('| ' + ' | '.join('---' for _ in row) + ' |')
                lines.append('')
    return '\n'.join(lines)


def build(language, output_dir):
    pages = blocks_zh() if language == 'zh' else blocks_en()
    pages.append(batch_page(language))
    name = '技术与使用报告-中文' if language == 'zh' else 'Technical-and-User-Report-English'
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / (name + '.pdf')
    md = output_dir / (name + '.md')
    md.write_text(markdown(pages), encoding='utf-8')
    document = SimpleDocTemplate(str(destination), pagesize=A4, leftMargin=52, rightMargin=52,
                                 topMargin=57, bottomMargin=49,
                                 title='RGBT Comparison Viewer - ' + ('技术与使用报告' if language == 'zh' else 'Technical and User Report'),
                                 author=AUTHORS, subject='Local comparison, native-pixel export, macOS use, and trusted LAN review')
    document.build(render_blocks(pages, language), canvasmaker=NumberedCanvas)
    print('Created ' + str(destination))
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=('both', 'zh', 'en'), default='both')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'docs')
    parser.add_argument('--simsun', type=Path)
    parser.add_argument('--times', type=Path)
    parser.add_argument('--times-bold', type=Path)
    parser.add_argument('--times-italic', type=Path)
    args = parser.parse_args()
    paths = register_fonts(args)
    # Report only font families here; absolute user paths never enter the PDF.
    print('Using actual SimSun and Times New Roman font files; embedding glyph subsets only.')
    for language in ('zh', 'en') if args.language == 'both' else (args.language,):
        build(language, args.output_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
