# Reference Workflow Analysis

> Current standalone UI note: the public workflow uses `CSRModelLoader -> CSRVideoCrop -> CSRMediaAssets -> CSRSegmentReplace -> CSRMerge -> SaveVideo` with one output socket per processing node. The old combined `CSRMediaLibrary` remains registered only as a compatibility node.

Source inspected read-only:

```text
15.AICG3D_分段人物场景动作迁移替换.json
```

The inspected source SHA-256 was `BF04AB61684D2B6AF7E0DF5BB285870B2B8795171EBDEB7D404A531FFA46B4B8`. The local absolute path is intentionally omitted from the public package.

The source contains eight nodes and eight links:

```text
AICG3D_H3Loader
AICG3D_H3SelectedVideoContext
AICG3D_H3SegmentSampler
AICG3D_H3SegmentDecode
AICG3D_H3MediaLoader
AICG3D_H3WhiteModelRig
SaveVideo (white-model preview)
SaveVideo (final output)
```

## Responsibility Mapping

| Reference node | CSR replacement |
|---|---|
| `AICG3D_H3Loader` | `MiniMax H3 Aicg 加载器 · CSR独立版` |
| `AICG3D_H3MediaLoader` | Image uploads inside `MiniMax H3 Aicg资源库 · CSR独立版` |
| `AICG3D_H3WhiteModelRig` | Optional action-preview route only; the CSR default uses the source video directly as the motion master |
| `AICG3D_H3SelectedVideoContext` | Video upload and free segment planning inside `MiniMax H3 Aicg 视频裁剪 · CSR独立版` |
| `AICG3D_H3SegmentSampler` | Sampling half of `CSR ③ 逐段替换` |
| `AICG3D_H3SegmentDecode` | `CSR ④ 无缝合并` |
| Final `SaveVideo` | Final `SaveVideo` |

## Behavioral Differences

- The original groups video loading, cuts and generation into AICG3D nodes with fixed segment settings.
- CSR exposes a dedicated upload area and a persistent, editable segment table.
- CSR treats the user-entered start/end ranges as the exact output timeline.
- Context frames are read internally from previous output and never duplicated in final duration.
- Each generated segment has its own MP4, marker JSON and hash.
- The source soundtrack is extracted once into a standalone WAV, while every segment is encoded video-only.
- H3 sampling keeps one structural audio placeholder token but never receives the real soundtrack.
- The final pass re-encodes one continuous CFR timeline and verifies exact frame count.
- Audio is muxed only after the complete silent video timeline has passed frame-count verification.
- CSR adds boundary locking and optional short boundary blending on top of context inheritance.
- The original workflow JSON is not modified by this plugin.
