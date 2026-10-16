# Application image color pipeline

## What image or preview is actually displayed?

### Takeaway

The application has multiple image sources and resolutions, and the source depends on whether a path is Lightroom-managed and which view is rendering it. For managed photos the inspector/rows request Lightroom previews, but the focus viewer independently reads a large Lightroom proxy and may instead decode the RAW’s embedded JPEG when the proxy would need enlargement; for unmanaged photos the inspector can show the original directly while its row and focus routes use reduced or separately decoded copies.

### Cited Findings

- `previews.file_image_pixmap` routes managed files through `lightroom_bridge.preview_pixmap`; the bridge prefers Lightroom’s catalog/SDK preview but can generate an application fallback by decoding the source. Unmanaged images use a 640-pixel maximum decode and may be cached in memory and on disk. The on-disk cache is a PNG, keyed by source path and modification time. [previews.py:L454-L474](../../previews.py#L454), [previews.py:L4212-L4223](../../previews.py#L4212), [previews.py:L4275-L4303](../../previews.py#L4275), [lightroom_bridge.py:L465-L478](../../lightroom_bridge.py#L465)
- In the inspector, managed images use that asynchronous bridge path. For unmanaged image files, `DetailPanel.show_path` first loads the source with `QPixmap(str(path))` unless it is serving a stale cached preview; it separately requests `file_image_pixmap` to prepare/cache its reduced rendition. [detail_panel.py:L2331-L2357](../../detail_panel.py#L2331)
- `row_delegates` obtains the row image through `file_image_pixmap(..., asynchronous=True)`. That path first uses its 80-pixel row cache or an existing inspector cache; otherwise it schedules a background decode. [row_delegates.py:L121](../../row_delegates.py#L121), [previews.py:L426-L440](../../previews.py#L426), [previews.py:L4224-L4252](../../previews.py#L4224)
- Lightroom preview lookup queries the catalog’s `Previews.lrdata/previews.db` pyramid. A requested maximum dimension selects the largest available level at or below that limit when possible; without a maximum it searches levels largest-first. The Lightroom SDK plug-in requests a JPEG thumbnail up to 2560 × 2560. [lightroom_bridge.py:L311-L358](../../lightroom_bridge.py#L311), [plugins/PipelineLightroom.lrplugin/Start.lua:L111-L120](../../plugins/PipelineLightroom.lrplugin/Start.lua#L111)
- A Lightroom preview already in the pyramid is loaded directly. If absent, the app can show a local fallback created from `_decode_2d_image`, save it as JPEG quality 92, and later replace it when the Lightroom preview appears. `preview_origin` distinguishes `lightroom` from `application`; the inspector exposes that origin badge. [lightroom_bridge.py:L465-L478](../../lightroom_bridge.py#L465), [lightroom_bridge.py:L481-L510](../../lightroom_bridge.py#L481), [lightroom_bridge.py:L767-L845](../../lightroom_bridge.py#L767), [detail_panel.py:L1531-L1555](../../detail_panel.py#L1531)
- Focus loading is a separate decode path. For managed images `_DecodeTask` asks for the largest proxy; if that proxy would be enlarged to fit the viewer, a RAW may use its embedded JPEG instead. Otherwise it reads the chosen proxy (or source), applies orientation, and stores a full image capped at 8192 pixels plus a fit-to-screen copy. [focus.py:L78-L120](../../focus.py#L78), [focus.py:L121-L149](../../focus.py#L121), [focus.py:L154-L180](../../focus.py#L154)
- Filmstrip and gallery thumbnails have further routes: the filmstrip uses a 300-pixel disk thumbnail or cached preview and can decode from the Lightroom proxy; gallery tiles use the 640-pixel preview if sufficient or request a scaled decode from the proxy. [focus.py:L345-L385](../../focus.py#L345), [focus.py:L444-L505](../../focus.py#L444), [focus.py:L568-L590](../../focus.py#L568), [focus.py:L3204-L3245](../../focus.py#L3204)
- When Lightroom stores a rotated/mirrored preview, `_oriented_preview_path` reads it and writes a new JPEG at quality 95. That creates a second pixel-generation/cache route and has no explicit ICC-profile transfer in the code. Unrotated orientation `AB` returns the original preview path. [lightroom_bridge.py:L361-L389](../../lightroom_bridge.py#L361)
- The provided screenshots appear to show the same photograph with different crop/scale and a visible color/contrast difference. They are screenshots, not the source image or Lightroom preview file, so they do not identify which app route or profile was active. The code includes origin badges that could disambiguate the app’s active source, but the supplied comparison alone does not show that evidence. [detail_panel.py:L1531-L1555](../../detail_panel.py#L1531), [pipeline_browser.py:L5881-L5917](../../pipeline_browser.py#L5881)

### Inferences

- A screenshot comparison can conflate rendition differences with display color management: the inspector, focus viewer, filmstrip, and gallery are not guaranteed to show the same encoded image bytes or the same resolution.
- For a managed RAW, focus may visibly diverge from the Lightroom proxy when the proxy is smaller than the available focus area, because the viewer can switch to the camera’s embedded JPEG. The app labels the focus source as Lightroom, application preview, original, or unknown, which should be recorded during any reproduction.

### Gaps

- The screenshots do not identify the source photo, its embedded profile, the proxy bytes, Lightroom’s current develop-preview state, or which application view/origin badge produced the app image. Therefore the screenshots cannot establish a single cause for the observed color difference.
- The repository does not establish whether the Lightroom SDK JPEG thumbnail uses the exact same quality, preview freshness, or display pipeline as the Lightroom window shown in the comparison.

## ICC profiles, pixel encoding, resize, caches, and LUTs

### Takeaway

The app reads an embedded ICC profile only to display its description in image information; no application code explicitly converts pixels between color spaces or establishes a display/output profile. Ordinary Qt decodes keep their format source-dependent until later format conversions; the focus loader normalizes to 8-bit `RGB32` or premultiplied `ARGB32`, while selected specialized decoders explicitly create 8-bit RGB images with bespoke transforms. The `.cube` LUT machinery is an image-of-a-LUT preview feature, not a LUT applied to ordinary photos.

### Cited Findings

- A repository-wide search finds no call to `QImage.colorSpace()`, `convertToColorSpace`, `setColorSpace`, `iccProfile`, or equivalent profile transform in the image display paths. The only ICC-related code is `focus.image_info`: Pillow reads `im.info['icc_profile']` and `ImageCms.getProfileDescription` to show a profile name. It does not transform image pixels. [focus.py:L3419-L3422](../../focus.py#L3419), [focus.py:L3482-L3492](../../focus.py#L3482)
- The ordinary 2D decoder uses `QImageReader`, enables EXIF/metadata orientation, asks the reader to scale to a maximum dimension when applicable, reads the image, and applies a smooth Qt resize only if it is still too large. It does not specify a color space or output transfer curve. [previews.py:L4141-L4184](../../previews.py#L4141)
- Focus uses `QImageReader` with auto-transform and scaled decode above 8192 pixels. Before caching it converts alpha images to `Format_ARGB32_Premultiplied` and opaque images to `Format_RGB32`; the separate display copy is scaled with `Qt.SmoothTransformation`. This is a pixel-layout conversion, not an explicit ICC-to-sRGB conversion. [focus.py:L87-L117](../../focus.py#L87), [focus.py:L135-L145](../../focus.py#L135)
- Lightroom previews are read as QImages and become QPixmaps. The general preview cache writes PNGs; local Lightroom fallbacks are written as JPEG quality 92; rotated Lightroom previews are re-encoded at JPEG quality 95. No explicit profile metadata is copied, normalized, or removed in these save calls. Therefore the code does not prove that a particular Qt image plugin preserves or strips an embedded profile during decode/encode. [lightroom_bridge.py:L373-L389](../../lightroom_bridge.py#L373), [lightroom_bridge.py:L465-L478](../../lightroom_bridge.py#L465), [lightroom_bridge.py:L866-L873](../../lightroom_bridge.py#L866), [previews.py:L4285-L4302](../../previews.py#L4285)
- `DetailPanel._update_preview` scales the held pixmap with `Qt.SmoothTransformation` to fit the panel (bounded by panel width and preview height). Focus scales at decode time and uses its fitted copy; filmstrip/gallery then scale to their cell size. Repeated routes can therefore resize at different stages and from different source resolutions. [detail_panel.py:L1217-L1258](../../detail_panel.py#L1217), [focus.py:L141-L145](../../focus.py#L141), [focus.py:L479-L505](../../focus.py#L479), [focus.py:L3235-L3245](../../focus.py#L3235)
- The RAW normal decode uses `rawpy.postprocess` with camera white balance and 8-bit output, then wraps the resulting bytes as `Format_RGB888`; fallback is the largest embedded JPEG. The focus RAW fallback uses the same embedded JPEG extractor with orientation auto-transform and a max dimension. [previews.py:L3407-L3423](../../previews.py#L3407), [previews.py:L3426-L3460](../../previews.py#L3426)
- EXR previews explicitly clamp negative values, apply Reinhard tone mapping and an approximate gamma 2.2 encoding, then quantize to 8-bit RGB888. This is an explicit special-case transform, not a general ICC color-management path. [previews.py:L3069-L3114](../../previews.py#L3069)
- `.cube` preview generation applies a parsed LUT to the selected/default test image. Comments and dispatch identify it as the preview of a LUT file; ordinary 2D photo decoding does not call this path. [previews.py:L3117-L3127](../../previews.py#L3117), [previews.py:L3347-L3404](../../previews.py#L3347), [previews.py:L4141-L4169](../../previews.py#L4141)
- Qt documents `QImage.convertToColorSpace` as an explicit operation (and says it does nothing if the image has no valid color space); `QImageReader`’s documented `setAutoTransform` concerns transformation metadata such as orientation. These APIs are available, but the app’s normal image routes do not invoke the color-space conversion operation. [Qt QImage documentation](https://doc.qt.io/qt-6/qimage.html), [Qt QImageReader documentation](https://doc.qt.io/qt-6/qimagereader.html)

### Inferences

- The most concrete color-management defect is not that the code explicitly assigns a wrong profile; it is that the code has no explicit, consistent profile interpretation and display conversion. If source pixels are in Adobe RGB, Display P3, camera RGB, or another tagged space and the decoder/painter path treats those channel values as ordinary RGB without the matching transform, appearance can differ from Lightroom. This is especially plausible for unmanaged original paths and the RAW embedded-JPEG fallback.
- No explicit ICC strip operation exists. However, profile retention through `QImageReader`, QPixmap conversion, image resizing, PNG/JPEG encoding, and Qt’s platform paint backend is not established by the repository. The rotated-preview JPEG save and fallback JPEG save are specific points where profile loss must be tested against the installed Qt image plugins.
- The reduced 640-pixel image cache and 300-pixel filmstrip cache are derived artifacts; their cache keys are based on file path/date (and Lightroom proxy identities/revisions for bridge output), not on profile-conversion policy. A future profile policy change would need cache versioning/invalidation to prevent old pixels from surviving.

### Gaps

- Runtime evidence is missing for the installed Qt/PySide6 version and its JPEG/PNG handlers: whether `QImageReader.read()` attaches an ICC-derived QColorSpace, whether `convertToFormat`/`QPixmap.fromImage` retain it, whether `QPixmap` painting applies display transforms, and whether Qt writers retain ICC metadata.
- No original image or Lightroom preview was supplied for byte-level inspection of ICC chunks, decoded pixel values, dimensions, and source-vs-cache comparisons. The screenshot images do not substitute for those artifacts.

## Concrete causes and a path to exact Lightroom parity

### Takeaway

The leading code-supported causes are divergent source selection (Lightroom preview versus original/embedded JPEG), the absence of an explicit ICC-to-display transform, and different resize/cache/re-encode stages. Lightroom support does exist, but it is not yet a single, color-managed rendering path shared by every view. Exact parity requires controlling both the rendered pixels and the display transform, then verifying the full route with the same source and preview.

### Cited Findings

- The inspector for managed photos is intentionally routed through Lightroom’s preview bridge, but focus separately chooses a large proxy and can choose an embedded RAW JPEG when the proxy would be enlarged. Unmanaged inspector images may load the original directly. These branch points are concrete, code-level sources of different pixels. [detail_panel.py:L2341-L2357](../../detail_panel.py#L2341), [focus.py:L82-L118](../../focus.py#L82), [previews.py:L4212-L4223](../../previews.py#L4212)
- The bridge obtains existing catalog pyramid files or asks the Lightroom SDK for a JPEG thumbnail (2560 maximum). It does not expose a Lightroom export job with an explicit output profile or export color-space setting in the reviewed code. [lightroom_bridge.py:L311-L358](../../lightroom_bridge.py#L311), [plugins/PipelineLightroom.lrplugin/Start.lua:L111-L120](../../plugins/PipelineLightroom.lrplugin/Start.lua#L111)
- The app profile-information panel only reports an ICC profile name. There is no explicit color-space conversion in decode, cache, or display; Qt provides such conversion APIs. [focus.py:L3482-L3492](../../focus.py#L3482), [Qt QImage documentation](https://doc.qt.io/qt-6/qimage.html)
- The report comparison is visually consistent with a color/rendering mismatch, but its screenshots alone do not distinguish color-space mismatch from different source renditions, cached/stale previews, JPEG re-encoding, or display/capture behavior.

### Inferences

- Recommended path to parity:
  1. Use a single declared reference rendition for the same catalog photo and develop state. For parity with Lightroom’s on-screen preview, obtain that Lightroom-rendered JPEG/proxy and ensure it is current; do not let one view switch to an original or embedded RAW JPEG. If parity must match a particular Lightroom export, add a controlled Lightroom export route with the same export profile, bit depth, and size rather than assuming a catalog thumbnail is equivalent.
  2. At decode, inspect `QImage.colorSpace()` and embedded ICC data; explicitly convert tagged pixels to the chosen output space, normally sRGB for a standard desktop preview, or to the same display/monitor space used for Lightroom. Define a policy for untagged sources and unsupported profiles. Preserve the color-space metadata or re-tag every cache output correctly; avoid opaque QPixmap/JPEG re-encodes that silently change interpretation.
  3. Route inspector, row, focus, filmstrip, and gallery through the same canonical rendition and transform. Keep lower-resolution derivatives generated only after that transform and key/invalidate caches by source revision, preview revision, and color-policy version.
  4. Verify using the exact source image, Lightroom proxy/export file, the app origin labels, decoded pixel/profile inspection, and the same monitor/display setup. Compare pixels before display and then compare controlled screenshots; otherwise display ICC differences remain confounded with image-processing differences.
- The viewer’s `APERÇU LIGHTROOM` badge is useful but does not by itself prove pixel parity: focus may be showing a separate pyramid level, may have re-encoded an orientation variant, or may have used the RAW embedded JPEG fallback. Record actual proxy path, selected level, profile description, dimensions, and origin during comparison.

### Gaps

- The exact Lightroom window rendering path and current preview freshness are not represented in this repository. The Lightroom SDK bridge requests a JPEG thumbnail but does not document or configure all Lightroom display/export color settings here.
- To claim exact parity, runtime validation is still needed on the user’s installed Lightroom Classic, PySide6/Qt build, Windows display profile, and the original comparison photo. Repository inspection alone cannot prove the color transform performed by platform-specific Qt plugins or the monitor pipeline.
