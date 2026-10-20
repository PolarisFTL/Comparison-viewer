# Comparison Viewer

Technical and User Report - English Edition 2.2.1

Release 2.2.1 adopts the general name Comparison Viewer, adds bilingual README navigation, refreshes artwork/screenshots, and fixes Windows Chinese CLI encoding. It adds no analysis feature. Historical 2.1 / 2.2 baselines remain below.

Authors: PolarisFTL and GPT 6 Astra. A local workspace for comparing sample-aligned detection, segmentation, generation, enhancement, and other image outputs. RGB-T is one use case. Review and select images together on a trusted LAN.

[PolarisFTL on GitHub](https://github.com/PolarisFTL)

GPT 6 Astra is credited for AI coding collaboration. OpenAI is its provider; the link below identifies the provider, not a personal GitHub account for the model.

[OpenAI](https://openai.com/)

### Configure first, then compare

The host opens a setup page before the viewer. Name the dataset, choose 2-24 image folders and a reference method, and edit the display name of each column. Display names do not rename the source folders. Inspect the matching audit before entering the viewer.

![Figure 1. Setup with synthetic data. No private experimental images are included.](screenshots/setup.png)

> Windows has a portable EXE and source entry points. The current macOS delivery is source code with .command launchers, not a Mac .app that has been tested on hardware. Latin text uses embedded Times New Roman subsets; Chinese text uses embedded SimSun subsets. System font files are not distributed.

## 01  Opening the project on macOS

Use the source route available today. A Windows .exe cannot run directly on macOS. Extract the complete source ZIP into a writable folder, such as a project folder under Documents. Do not download only index.html or run from a read-only disk image.

### Prepare Python and launch

1. If needed, install a supported Python 3 release from the official macOS downloads page, with version 3.9 or newer. The viewer uses the standard library at runtime: no npm setup or pip runtime packages are required. The official installer includes Tk for tkinter.

2. Double-click Start-macOS.command. It prefers a neighboring portable .app if one is actually supplied in a future release; otherwise it locates Python 3.9+, starts the local service, and opens /setup. Keep its Terminal window open. Closing the browser does not stop the service.

3. If execution permission prevents double-clicking, open Terminal in the extracted project folder and run:

```sh
chmod +x Start-macOS.command Start-LAN-macOS.command
```

Then double-click again, or run bash Start-macOS.command from that folder. Quote paths containing spaces; dragging the folder into Terminal can help enter its location.

### Folder picking, Tk, and system prompts

4. Choose folders through the host-side dialog, or paste absolute folder paths into the setup fields. If tkinter or _tkinter is missing, run python3 -m tkinter to check the selected interpreter. Use an official Python installation or the manual path fields; pip install tkinter is not a fix for a missing standard-library component.

5. If macOS blocks downloaded content, verify its origin and follow the system Privacy & Security approval flow for that item. Do not disable Gatekeeper, delete the system Python, or recursively remove quarantine attributes.

Future .app bundles must be built on macOS and state their Intel or Apple Silicon architecture, signing, and test status. A single-architecture build is not Universal. Mac hardware and native-picker GUI remain unvalidated; CI status follows actual repository records. See docs/MACOS.md for troubleshooting.

[Official Python on macOS guide](https://docs.python.org/3/using/mac.html)

## 02  Dataset consistency and safe matching

The reference folder defines the sample set. One row means one sample across methods. Keep the same sample identifiers and comparable scene content in each method folder. Method count and display names are configurable.

| Folder | Corresponding file | Result |
| --- | --- | --- |
| Input (reference) | sample_001.jpg | Defines the sample row |
| Baseline | sample_001.jpg | Exact filename first |
| Ours | sample_001.png | Unique stem fallback |
| GT | No corresponding file | Missing, never substituted |

### Never infer correspondence from sorted position

Exact filenames take priority. A different extension is acceptable when the stem match is unique. Review nested folders, duplicate stems, and extra files in the audit. Ambiguity is rejected: the tool does not pick an arbitrary candidate, pair the Nth file with the Nth file, or invent prefix/suffix rules.

Extra files in non-reference folders do not become new reference samples. Missing results are explicit placeholders and can help reveal incomplete predictions. Complete paper comparisons should use a common sample set.

### Same name or size does not establish registration

RGB and thermal views, different crops, or different canvas borders may use different geometry. Ensure comparable fields of view and orientation during result generation. The viewer preserves aspect ratio and does not register images, alter boxes or confidence values, or enhance images and present them as original predictions.

> Original images remain read-only. Configuration, indexes, audits, credentials, databases, and exports live under local/ or an explicit workspace and stay out of public source packages. Header sampling is not a full corruption check. PNG and JPEG are recommended; TIFF decoding depends on the browser.

## 03  Scale, lazy loading, and limits

The objective is to bound simultaneously decoded pixels, not to make the file count smaller. Scanning builds a lightweight index. It does not Base64-encode the library, create every ImageBitmap, or decode all source pixels at startup.

| Mechanism | Cost it controls |
| --- | --- |
| Current-page DOM | Only this page exists; paging does not append history |
| IntersectionObserver | Visible and near-edge loads; offscreen images lose src |
| Four-task queue | Bounds reading and decoding per browser |
| Cancellation and disposal | Drops stale work and revokes Blob URLs |
| Canvas checks | Estimates exports and handles selected images only |

### Measured index baseline on real data

The previous completed round indexed 8,980 samples, 10 methods, and 89,800 images, with zero missing or ambiguous matches. Scanning/matching took 8.386 s, or 9.628 s including workspace commit. The manifest was 7,261,083 bytes. It sampled 357 headers; hashes of 10 representative originals were unchanged. This is not a full pixel-integrity proof.

Twenty page changes kept 40 image nodes and 40 cells for 10 methods, with zero errors and peak concurrency four. Internal render diagnostics of 6.0-9.4 ms measure DOM construction only. The 293-456 ms automation round trips are also not full original-image loading times.

> Costs depend on visible pixels. Four rows with 24 methods create 96 cells, not 40. Twelve 840 × 712 RGBA images require roughly 27.4 MiB for pixels alone, before indexes, cache, GPU storage, and encoding. Stable node counts do not prove zero process-memory growth or guarantee that the browser can never stall.

## 04  Comparison, review, and figure workflow

The default page has four sample rows with methods in columns. Filename search, complete/missing/favorite filters, random jumps, and remembered position help navigate. Columns can be hidden, reordered, or viewed alone; headers remain aligned during horizontal scrolling.

![Figure 2. Synthetic native-pixel montage preview. This output is 1400 × 444.](screenshots/export.png)

| Action | Purpose and boundary |
| --- | --- |
| Ctrl + wheel / drag | Pointer-centered zoom / pan; normal wheel still scrolls |
| Double-click / 1:1 | Fit container / native pixel scale |
| Row or page sync | Normalized view state, not automatic registration |
| ROI / pair view | Draw, move, redraw; side-by-side or same-size wipe |
| Favorites and annotations | Personal notes, tags, reviewed status; no model ranking |

Shortcuts: / focuses search; left/right arrows page outside input fields; + / - zoom and 0 fits a focused viewport; Esc closes dialogs. Details use original images. Only the host can open its native file manager; visitors cannot operate the host file system.

## 05  Native-pixel export and preview

The new default is Native pixels 1:1 (recommended); Custom total width (resizes images) is an explicit alternative. Native layout uses the largest original width per column and height per row. Smaller images are not enlarged; remaining space stays white. ROI bounds round outward to original pixel boundaries and are copied at 1:1.

### Why ten 840 × 712 images cannot fit into 3200 px unchanged

Ten image contents alone require 840 × 10 = 8400 px horizontally, before gaps and margins. A 3200 px ten-column montage must reduce pixels per image. PNG compression is lossless, but it cannot restore information discarded by resizing. DPI metadata, display scaling, and a high device-pixel ratio do not create extra source pixels.

With current defaults, four samples and ten methods at 840 × 712 produce an 8592 × 3116 canvas: 26,772,672 pixels. The RGBA canvas alone is about 102.13 MiB; source decoding, encoding, and preview require additional memory.

| Setting | New export contract |
| --- | --- |
| Horizontal / vertical gap | 16 px defaults; independently adjustable from 0-256 px |
| Outer margin | 24 px default; adjustable from 0-512 px |
| Method header / font | 44 px / 24 px defaults; outside image content |
| Sample label / font | 32 px / 18 px defaults; can be hidden |
| Preview | Fit or 100%; never changes PNG pixel dimensions |
| Size guard | Desktop cap 48 MP; stricter on weak devices; side 16384 |

Bounded header reads inspect only selected images, avoiding a second full decode just to plan dimensions. JPEG EXIF orientations 1-8 are considered; unexpected decoded dimensions are rejected, never stretched. Weak devices use 24 MP or 12 MP budgets, including individual-source checks. Split oversized native selections; no silent downsampling.

> Native geometry, real PNG, and browser checks were completed for 2.1; that historical baseline is shown on the validation page. The earlier 3200 × 1260 montage is a resized-export baseline, not native-pixel evidence. Originals are never enhanced or overwritten.

## 06  Trusted LAN collaboration and access

The default service listens only on 127.0.0.1, port 8770. LAN sharing is explicit. It uses the real private IPv4 address and netmask to limit access; allowed subnets may be specified. It does not assume the entire campus network is a single /24.

| Role | Capabilities and records |
| --- | --- |
| Host administrator | Configure folders and index, invite, rotate code, reveal files, stop service |
| Visitor | Access-code login; nickname plus recovery code claims identity |
| Independent review | Per-person favorites, notes, tags, and reviewed status |
| Central summary | Host SQLite, per-reviewer and shared recommendations, JSON backup |

Use Start-LAN-macOS.command or Start-LAN-Windows.bat. The host copies the actual invitation URL and code. Visitors need only a browser, not Python or access to the original drive letters. The host must stay awake, powered on, and running the service.

### Reachability still requires a second-device check

Windows inbound firewall changes normally require UAC. On macOS, approve inbound access only for a trusted application when prompted. Restrict the actual port to required private ranges. Wireless client isolation, VLANs, guest networks, and routing policies can prevent same-campus devices from reaching each other.

> HTTP is not encrypted; an access code does not replace TLS. This is not a public-Internet or untrusted-Wi-Fi service. Host, Origin, session, change-token, and index-allowlist checks reduce risk but are not a security audit. Authorized visitors can save or screenshot images, so invite only people permitted to view the data.

Remote users cannot configure host folders or run host administration. Back up SQLite using the supplied flow or stop the service before copying, including any WAL state. Keep local/, credentials, and research data out of GitHub.

## 07  Validation, delivery, and references

| Item | Completed 2.1 Windows / Chromium baseline |
| --- | --- |
| Complete Python run | 95 tests: 94 passed, one Windows symlink-permission skip; 25.309 s |
| JavaScript checks | 40: 36 dependency-free Node checks and four real Skia Canvas / PNG round trips |
| Windows 2.1 portable EXE | 13,680,469 bytes, GUI subsystem; ran with Windows-only PATH, without Python/Node; native 4×4 PNG saved |
| Mixed-size PNGs | 865 × 621; all 16 RGB regions exactly match their originals |
| Mouse-drawn ROI | 426 × 90; four integer, 1:1 crops with zero pixel differences |
| Real four rows, ten methods | 8592 × 3116 saved; 40 regions at 840 × 712, scale 1, no missing/errors |
| Real-data pixel verification | All 40/40 regions exactly match their originals decoded to RGB by PIL |
| Guard and splitting | 52.89 MP rejected without a canvas; seven-row and one-row PNGs saved |
| Mac / CI / native picker | No Mac hardware or remote CI run; picker GUI not interactively accepted |

Fit preview was about 1149.95 × 417.05 while the PNG remained 8592 × 3116. Pixel checks apply to this batch and browser, not every ICC, alpha, or EXIF case or compressed-file bytes. HTTP roles are simulated, not a second-campus-device test. The old 86-test / 17-JS figures are historical. Details: TESTING.md.

### Public package and licensing

The 2.2.1 local Windows Python run completed 127 tests: 126 passed, one symlink-permission skip, 49.001 s, including Chinese CLI output under CP1252. CI requires an actual run record. The table above remains the 2.1 historical baseline.

The public allowlist excludes local/, originals, credentials, databases, real paths, and private screenshots. Code and documentation use MIT. Los Pollos Hermanos artwork and trademarks are third-party material excluded from MIT; no official affiliation, sponsorship, or authorization is claimed. See assets/README.md.

Rebuilding these reports requires reportlab and legally available SimSun and Times New Roman files. The builder discovers system or explicitly supplied fonts and fails if they are absent; it does not substitute STSong. PDFs embed used-glyph subsets only. Font files are not included in source or release ZIPs.

[Project initiator: PolarisFTL](https://github.com/PolarisFTL)

[Official Python macOS / Tk guidance](https://www.python.org/download/mac/tcltk/)

[Apple: opening an app from an unknown developer](https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac)

Companion documents: README.md / README_EN.md; docs/MACOS.md, QUICKSTART.md, ARCHITECTURE_PERFORMANCE.md, LAN_COLLABORATION.md, TESTING.md, and PUBLISHING.md.

## 08  2.2: a small library for MulimgViewer

Workflow: lazily review the large library, collect independent annotations, apply threshold N, confirm samples and methods, copy a method-organized small library, prepare local paths, then lay out figures in MulimgViewer. This exports original files, not a PNG montage.

| Filter | Exact meaning |
| --- | --- |
| Any favorite / threshold N | At least one favorite / favorite count >= N |
| Notes or tags | Any reviewer has a note or tags |
| Team unreviewed / all | Nobody reviewed / entire dataset; filename query applies |

Open Batch export originals and preview first. The summary displays at most 200 rows; export includes every match. All methods, including hidden columns, are selected by default. Choose a subset explicitly. Counts identify reviewers, not model quality.

The host chooses an existing writable parent; a new batch avoids overwriting originals. Visitors download ZIPs to their own computer. Display names map to cross-platform-safe folders. Image bytes are not re-encoded; reports record Missing and failed copies. Cancellation retains completed files and an incomplete report.

### ZIP paths must belong to the recipient

Extract everything, then enter the batch folder itself in the success dialog: its direct children are method folders. Download the MulimgViewer import CSV and copy one or all local method paths. A host drive path cannot be reused on another computer; regenerate after moving a batch.

The compatible CSV is headerless: sample rows, method columns, existing absolute image paths on this device, and complete copied rows only. Headered manifest.csv is an audit, not an image list. Keep real extensions. paths.txt contains relative folders to join with the actual batch root; report.json records status and mapping.

[Official MulimgViewer parser checked for format](https://github.com/nachifur/MulimgViewer/blob/master/src/mulimgviewer/src/data.py)

> 2.2 checks: 310 synthetic samples, four methods, favorites 310/240/205. N=3 exported 205 samples, 819 matching-hash files, one Missing; compatible CSV 204×4. ZIP integrity and absence of host paths passed. An isolated 1503×10 real-data review selected 20 samples: all 200 hashes matched, 5.516 s including verification for this batch only. Twenty real page changes kept 40 images without console errors; search, N4=0 persistence, and four clipboard paths passed. 65 pure-JS plus four real-Canvas checks passed. Final Python counts: TESTING.md. Mac and external GUI remain untested.
