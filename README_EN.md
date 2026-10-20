[简体中文](README.md) | **English**

<p align="center"><img src="assets/brand.png" width="140" alt="Project interface artwork"></p>

# RGBT Detection Comparison Viewer

A local tool for comparing image results, reviewing samples together, and preparing paper figures. Built for RGB-T detection experiments and other sample-aligned image outputs. **Original images remain read-only. Runtime has no CDN, npm, or online API dependency.**

Authors: [PolarisFTL](https://github.com/PolarisFTL) and GPT 6 Astra (AI coding collaboration, provided by [OpenAI](https://openai.com/)).

**Review the large library → annotate independently → select at least N recommendations → export method-organized originals → continue layout in MulimgViewer.** Native-pixel PNG montages can also be previewed and exported here.

## Download and start

**[v2.2.1 downloads and checksums](https://github.com/PolarisFTL/rgbt-comparison-viewer/releases/tag/v2.2.1)**

| Option | Download | Requirements |
|---|---|---|
| Windows x64 portable bundle, recommended | [Portable ZIP](https://github.com/PolarisFTL/rgbt-comparison-viewer/releases/download/v2.2.1/RGBT-Comparison-Viewer-windows-amd64-portable.zip) | Extract and double-click `RGBTViewer.exe`; no Python, Node, or .NET installation |
| Windows single executable | [RGBTViewer.exe](https://github.com/PolarisFTL/rgbt-comparison-viewer/releases/download/v2.2.1/RGBTViewer.exe) | Includes its runtime; place it in a writable location |
| Windows / macOS source | [Source ZIP](https://github.com/PolarisFTL/rgbt-comparison-viewer/releases/download/v2.2.1/RGBT-Comparison-Viewer-source.zip) | Host Python 3.9+, standard library only; collaborators need just a browser |

1. **Start.** Use the Windows portable EXE. For source, extract the complete project into a writable directory, then run `Start-Windows.bat` or `Start-macOS.command`.
2. **Configure.** Name the dataset, select **2-24 image folders**, choose a reference method, and edit method display names.
3. **Audit and browse.** Inspect the filename-matching audit before opening the viewer. The default is four sample rows with methods in columns; configuration can be reused.

macOS currently uses source and `.command` launchers. **A Windows EXE cannot run directly on a Mac; no hardware-validated Mac `.app` is supplied.** Install Python 3.9+ if needed. In the extracted project folder, execution permission can be set with `chmod +x Start-macOS.command Start-LAN-macOS.command`, or use `bash Start-macOS.command`. The [Mac guide](docs/MACOS.md) covers Python, Tk, paths, and system prompts; the [English report](docs/Technical-and-User-Report-English.pdf) also explains the source route. Double-clicking `index.html` is not a replacement for the local-service launcher.

## Dataset requirements

The reference folder defines the sample set. Each row must represent the same sample across methods:

```text
Input/       sample_001.jpg  sample_002.jpg
Baseline/    sample_001.png  sample_002.png
Ours/        sample_001.png  sample_002.png
GT/          sample_001.png  sample_002.png
```

- Exact filenames take priority; different extensions are accepted when the stem match is unique.
- Files are never paired by sorted position, and prefix/suffix rules are not guessed. Missing files show `Missing`; ambiguous matches are rejected.
- Display names are editable; **source folders and images are not renamed**. The audit reports nesting, duplicate stems, extras, and missing files.
- Outputs need comparable scenes, fields of view, and orientation. Identical names or dimensions do not prove registration. Boxes and confidence values are not changed.
- PNG/JPEG are recommended. Other formats depend on browser decoding; header checks are not full-library image-integrity validation.

## Comparison and paper figures

- Pagination, filename search, complete/missing/favorite filters, random navigation, and remembered position.
- Hide, reorder, or isolate columns; adjust widths, gaps, and light/dark theme.
- Pointer-centered `Ctrl + wheel` zoom, drag to pan, double-click to fit; normalized row/page synchronization. Normal wheel still scrolls the page.
- Original-image details, ROI, arbitrary side-by-side pairs, and same-size wipe comparison without automatic registration.
- Favorites, notes, tags, and reviewed status. `/` focuses search; left/right arrows page outside input fields.
- PNG export defaults to **native pixels 1:1**, with configurable gaps, margins, titles, and labels. Custom total width explicitly resizes images. A smaller CSS preview does not reduce the downloaded PNG.

Ten 840px-wide images already need 8400px for image content alone. A 3200px montage cannot retain those native pixels. Lossless PNG or higher DPI cannot restore information discarded by resizing. Canvas budgets are checked before allocation; oversized selections can be split without silently downsampling native mode. See [QUICKSTART](docs/QUICKSTART.md).

## Team review and selected libraries

By default, the service listens only on `127.0.0.1`, port `8770`. For a trusted LAN, use `Start-LAN-Windows.bat` or `Start-LAN-macOS.command`; the host shares its actual invitation URL and access code. Reviewers claim independent identities with nicknames and recovery codes; annotations are stored in host-side SQLite.

Team filters include any favorite, at least N favorites, notes/tags, nobody reviewed, and all samples, with filename queries. **The summary displays at most 200 rows; batch export processes every matching sample beyond that display limit.**

Open “批量导出原图” (Batch export originals) in the team summary and preview first. All methods, including hidden viewer columns, are selected by default; choose a subset explicitly:

- **Host copy:** choose an existing writable parent. A fresh batch receives method-organized originals, without overwriting sources or old batches.
- **Visitor ZIP:** download to your computer, extract everything, then enter the batch folder itself to generate device-local absolute paths. Host drive paths are not your local paths.
- **Continue layout:** copy one or all method paths. For different extensions, download the MulimgViewer CSV: headerless, no BOM, sample rows and method columns, complete copied rows only. Headered `manifest.csv` is an audit, not an image list. Extensions are never disguised.
- **Reuse later:** batches contain `report.json`, `paths.txt`, and correspondence lists. `paths.txt` has relative method names to join with the actual batch root. Cancellation retains completed copies and a partial report; an unfinished ZIP is not downloadable.

Detailed instructions: [English batch workflow](docs/BATCH_EXPORT_EN.md) / [中文](docs/BATCH_EXPORT.md). CSV compatibility was checked against official MulimgViewer source; external GUI import is not claimed as interactively tested.

The host must stay awake and running. VLANs, wireless isolation, and firewalls can prevent campus connectivity. LAN mode uses **HTTP without TLS**, for trusted private networks and authorized collaborators, not direct public-Internet exposure. Only the host configures folders or runs host-system actions. See [LAN guidance](docs/LAN_COLLABORATION.md).

## Why the whole image library need not be decoded at once

The index stores filenames and correspondence. Pagination, IntersectionObserver, and a **four-task image queue** load pixels on demand. Page changes cancel stale requests, remove old nodes, and release image references. Four rows and ten methods create 40 image cells; a different method count changes that number.

| Executed scenario | Evidence and scope |
|---|---|
| Historical large-library audit | 8,980 samples, ten methods, 89,800 files; scanning/matching 8.386 s, without full-library pixel decoding |
| 2.2 real-data browsing | Twenty page changes on a 1,503 × 10 copy kept 40 image nodes, without console errors |
| Beyond 200 summary rows | Synthetic 310 × 4, N=3 selected 205 samples; 819 copied originals matched source SHA256, with one Missing |
| Real selected batch | N=2 selected 20 × 10; all 200 hashes matched, 5.516 s including verification for that batch only |
| 2.2 regression baseline | Python: 123 tests, 122 passed and one permission skip; 65 JS checks plus four real Canvas/PNG checks passed |

These are local Windows functional baselines; release-specific checks are in [TESTING.md](docs/TESTING.md). Stable node counts do not prove constant process memory. Huge images, concurrent visitors, and exports still consume disk, network, and memory; stall-free operation on every device is not promised.

## Synthetic screenshots

All screenshots use generated OBB examples, not private research images.

<details>
<summary>Expand setup, comparison, team review, and batch-export screenshots</summary>

![Setup](docs/screenshots/setup.png)
![Synchronized comparison](docs/screenshots/viewer.png)
![Team summary](docs/screenshots/collaboration.png)
![Batch preview](docs/screenshots/batch-export.png)
![ZIP and CSV result](docs/screenshots/batch-result.png)

</details>

## Documentation, development, and limits

| Document | Coverage |
|---|---|
| [QUICKSTART](docs/QUICKSTART.md) / [MACOS](docs/MACOS.md) | Startup, configuration, shortcuts, and Mac troubleshooting |
| [BATCH_EXPORT_EN](docs/BATCH_EXPORT_EN.md) / [中文](docs/BATCH_EXPORT.md) | Large-library review to MulimgViewer handoff |
| [Architecture](docs/ARCHITECTURE_PERFORMANCE.md) / [LAN](docs/LAN_COLLABORATION.md) | Lazy loading, resource limits, and permissions |
| [English report](docs/Technical-and-User-Report-English.pdf) / [中文报告](docs/技术与使用报告-中文.pdf) | Technical/user PDFs with embedded Times New Roman / SimSun subsets |
| [TESTING](docs/TESTING.md) / [PUBLISHING](docs/PUBLISHING.md) | Executed checks, untested areas, and clean packaging |

Node is not a runtime requirement. Run Python development tests with `python -m unittest discover -s tests -p "test_*.py"`. Windows/macOS [CI workflows](https://github.com/PolarisFTL/rgbt-comparison-viewer/actions) are supplied; see Actions for actual run status. CI is not native-GUI acceptance.

Physical macOS, native folder-picker GUI, external MulimgViewer GUI, a second campus-network device, and long-running process-memory behavior have not been accepted on hardware. Default `local/` is ignored; put custom workspaces outside the repository or add explicit ignore rules. Keep configuration, indexes, credentials, SQLite, annotations, exports, and research images out of GitHub. Publish the allowlisted source package.

Code and documentation use [MIT](LICENSE). **Los Pollos Hermanos artwork/trademarks are third-party material excluded from the MIT code license.** Rights remain with their respective holders; no official affiliation or sponsorship is claimed. See [asset notices](assets/README.md).
